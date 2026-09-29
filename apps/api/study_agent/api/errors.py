from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from study_agent.domain.errors import DomainError


def _error_body(
    request: Request,
    *,
    code: str,
    message: str,
    details: Any,
) -> dict[str, object]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": jsonable_encoder(details),
            "request_id": getattr(request.state, "request_id", None),
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(
                request,
                code=exc.code,
                message=exc.message,
                details=exc.details,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error_body(
                request,
                code="VALIDATION_ERROR",
                message="请求参数校验失败",
                details=exc.errors(),
            ),
        )
