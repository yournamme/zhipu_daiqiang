"""Application-level error types and FastAPI handlers."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.runtime_logging import get_runtime_log_service

logger = logging.getLogger(__name__)


class AegisFlowError(Exception):
    """Base application error."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        code: str = "aegisflow_error",
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


class BadRequestError(AegisFlowError):
    """Raised when user input is incomplete or invalid."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message,
            status_code=400,
            code="bad_request",
            details=details,
        )


class NotFoundError(AegisFlowError):
    """Raised when a requested resource does not exist."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message,
            status_code=404,
            code="not_found",
            details=details,
        )


class UpstreamRequestError(AegisFlowError):
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

    @app.exception_handler(AegisFlowError)
    async def handle_aegisflow_error(request: Request, exc: AegisFlowError) -> JSONResponse:
        logger.warning("application error on %s: %s", request.url.path, exc.message)
        account_id = str(request.path_params.get("account_id") or "").strip()
        runtime_logs = get_runtime_log_service()
        if account_id:
            runtime_logs.log_account_event(
                account_id=account_id,
                action="request",
                stage="http_error",
                status="failed",
                message=exc.message,
                details={"path": request.url.path, "code": exc.code, "details": exc.details},
                level=logging.WARNING,
            )
        else:
            runtime_logs.log_system_event(
                stage="http_error",
                status="failed",
                message=exc.message,
                details={"path": request.url.path, "code": exc.code, "details": exc.details},
                level=logging.WARNING,
            )
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unexpected error on %s: %s", request.url.path, exc)
        account_id = str(request.path_params.get("account_id") or "").strip()
        runtime_logs = get_runtime_log_service()
        details = {"path": request.url.path, "type": exc.__class__.__name__}
        if account_id:
            runtime_logs.log_account_event(
                account_id=account_id,
                action="request",
                stage="http_error",
                status="failed",
                message="服务内部异常",
                details=details,
                level=logging.ERROR,
            )
        else:
            runtime_logs.log_system_event(
                stage="http_error",
                status="failed",
                message="服务内部异常",
                details=details,
                level=logging.ERROR,
            )
        payload = AegisFlowError(
            "服务内部异常",
            status_code=500,
            code="internal_error",
            details={"type": exc.__class__.__name__},
        ).to_payload()
        return JSONResponse(status_code=500, content=payload)
