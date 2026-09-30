import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from study_agent.config import get_settings
from study_agent.infrastructure.readiness import Probe, get_readiness_probes

router = APIRouter(tags=["健康检查"])


class LiveResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadyResponse(BaseModel):
    status: Literal["ok", "not_ready"]
    dependencies: dict[str, str]


@router.get("/health/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    return LiveResponse()


@router.get("/health/ready", response_model=ReadyResponse)
async def ready(
    response: Response,
    probes: Annotated[dict[str, Probe], Depends(get_readiness_probes)],
) -> ReadyResponse:
    async def check(name: str, probe: Probe) -> tuple[str, str]:
        try:
            await asyncio.wait_for(probe(), timeout=get_settings().readiness_timeout_seconds)
        except Exception:
            # Errors may contain credentials or internal URLs.
            return name, "down"
        return name, "up"

    dependencies = dict(
        await asyncio.gather(*(check(name, probe) for name, probe in probes.items()))
    )
    healthy = bool(dependencies) and all(value == "up" for value in dependencies.values())
    response.status_code = 200 if healthy else 503
    return ReadyResponse(status="ok" if healthy else "not_ready", dependencies=dependencies)
