from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from secrets import compare_digest
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from study_agent.api.errors import register_exception_handlers
from study_agent.api.router import api_router
from study_agent.config import get_settings
from study_agent.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("application_started", environment=settings.app_env)
    yield
    logger.info("application_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url="/redoc" if settings.app_env != "production" else None,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)

    @app.middleware("http")
    async def access_control(request: Request, call_next):  # type: ignore[no-untyped-def]
        public_health = {
            f"{settings.api_prefix}/health/live",
            f"{settings.api_prefix}/health/ready",
        }
        protected = request.url.path.startswith(settings.api_prefix + "/")
        if (
            settings.api_access_token
            and protected
            and request.method != "OPTIONS"
            and request.url.path not in public_health
        ):
            authorization = request.headers.get("Authorization", "")
            expected = "Bearer " + settings.api_access_token
            if not compare_digest(authorization.encode(), expected.encode()):
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": {
                            "code": "UNAUTHORIZED",
                            "message": "请设置有效访问令牌",
                            "request_id": getattr(request.state, "request_id", None),
                        }
                    },
                    headers={"WWW-Authenticate": "Bearer"},
                )
        return await call_next(request)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
