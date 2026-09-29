from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["健康检查"])


class LiveResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadyResponse(BaseModel):
    status: Literal["ok"] = "ok"
    dependencies: dict[str, str]


@router.get("/health/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    return LiveResponse()


@router.get("/health/ready", response_model=ReadyResponse)
async def ready() -> ReadyResponse:
    # 基础骨架阶段只验证应用进程；接入基础设施后替换为真实依赖探针。
    return ReadyResponse(status="ok", dependencies={"application": "up"})
