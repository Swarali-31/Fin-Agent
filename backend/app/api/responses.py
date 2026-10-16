"""Uniform response and exception handling for the HTTP API."""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.repositories.base import PersistenceNotConfigured
from backend.app.schemas.common import ApiError, ResponseEnvelope
from backend.app.services.api import APIServiceError


def success(
    request: Request,
    data: Any,
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    envelope = ResponseEnvelope(
        request_id=request.state.request_id,
        status="ok",
        data=data,
    )
    return JSONResponse(
        status_code=status_code,
        content=envelope.model_dump(mode="json"),
        headers=headers,
    )


def install_exception_handlers(app: Any) -> None:
    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
        return _error_response(request, 409, "record_conflict", "This record already exists or conflicts with saved data.", None)

    @app.exception_handler(OperationalError)
    @app.exception_handler(ProgrammingError)
    async def database_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return _error_response(request, 503, "database_unavailable", "Your workspace database is unavailable. Please contact the workspace owner.", None)

    @app.exception_handler(PersistenceNotConfigured)
    async def persistence_not_configured_handler(
        request: Request,
        exc: PersistenceNotConfigured,
    ) -> JSONResponse:
        return _error_response(
            request,
            503,
            "persistence_not_configured",
            str(exc),
            None,
        )

    @app.exception_handler(APIServiceError)
    async def service_error_handler(request: Request, exc: APIServiceError) -> JSONResponse:
        return _error_response(
            request,
            exc.status_code,
            exc.code,
            str(exc),
            exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            request,
            422,
            "validation_error",
            "Request validation failed.",
            {
                "errors": [
                    {
                        "location": ".".join(str(part) for part in error["loc"]),
                        "message": error["msg"],
                        "type": error["type"],
                    }
                    for error in exc.errors()
                ]
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        status_code = exc.status_code if exc.status_code in {400, 404, 409, 422, 503} else 500
        return _error_response(
            request,
            status_code,
            "http_error",
            str(exc.detail),
            None,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return _error_response(
            request,
            500,
            "internal_error",
            "An unexpected server error occurred.",
            {"exception_type": type(exc).__name__},
        )


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None,
) -> JSONResponse:
    envelope = ResponseEnvelope(
        request_id=getattr(request.state, "request_id", "unknown"),
        status="error",
        error=ApiError(code=code, message=message, details=details),
    )
    return JSONResponse(
        status_code=status_code,
        content=envelope.model_dump(mode="json"),
    )
