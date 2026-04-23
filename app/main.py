"""FastAPI application entrypoint."""

from __future__ import annotations

from fastapi import FastAPI

from app.errors import install_exception_handlers
from app.services.account_state import get_account_state_service
from app.services.scheduler_service import get_scheduler_service
from app.web.routes import router


def create_app() -> FastAPI:
    """Build the FastAPI app."""
    app = FastAPI(
        title="GLM Desk",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    install_exception_handlers(app)
    app.include_router(router)

    @app.on_event("startup")
    def start_scheduler() -> None:
        get_account_state_service().clear_payment_cache()
        get_scheduler_service().start()

    @app.on_event("shutdown")
    def stop_scheduler() -> None:
        get_scheduler_service().stop()

    return app


app = create_app()
