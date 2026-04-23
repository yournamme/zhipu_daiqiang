"""Application-level error types and FastAPI handlers."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class GlmDeskError(Exception):
    """Base application error."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        code: str = "glm_desk_error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            },
        }


class BadRequestError(GlmDeskError):
    """Raised when user input is incomplete or invalid."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message,
            status_code=400,
            code="bad_request",
            details=details,
        )


class NotFoundError(GlmDeskError):
    """Raised when a requested resource does not exist."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message,
            status_code=404,
            code="not_found",
            details=details,
        )


class UpstreamRequestError(GlmDeskError):
    """Raised when BigModel returns an error or invalid payload."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message,
            status_code=502,
            code="upstream_request_failed",
            details=details,
        )


def install_exception_handlers(app: FastAPI) -> None:
    """Register shared exception handlers."""

    @app.exception_handler(GlmDeskError)
    async def handle_glm_desk_error(_: Request, exc: GlmDeskError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        payload = GlmDeskError(
            "服务内部异常",
            status_code=500,
            code="internal_error",
            details={"type": exc.__class__.__name__},
        ).to_payload()
        return JSONResponse(status_code=500, content=payload)
