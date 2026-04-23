"""FastAPI routes and page rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.models import (
    AccountPreferencesRequest,
    AccountImportRequest,
    CaptchaVerifyPayloadRequest,
    CreateQrRequest,
    ManualCaptchaRequest,
    PreviewPaymentRequest,
    PreviewSeedRequest,
)
from app.services.payment_service import get_payment_service

router = APIRouter()
payment_service = get_payment_service()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


@router.get("/", response_class=HTMLResponse)
def index(request: Request, ic: str = Query(default="")):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "default_invitation_code": ic,
            "transport_name": payment_service.health_payload()["transport"],
        },
    )


@router.get("/healthz")
def healthz():
    return success(payment_service.health_payload())


@router.get("/api/accounts")
def list_accounts():
    return success(payment_service.list_accounts())


@router.post("/api/accounts/import")
def import_account(payload: AccountImportRequest):
    return success(payment_service.import_account(payload))


@router.get("/api/accounts/{account_id}")
def get_account(account_id: str):
    return success(payment_service.get_account_detail(account_id))


@router.delete("/api/accounts/{account_id}")
def delete_account(account_id: str):
    return success(payment_service.delete_account(account_id))


@router.patch("/api/accounts/{account_id}")
def update_account_preferences(account_id: str, payload: AccountPreferencesRequest):
    return success(payment_service.update_preferences(account_id, payload))


@router.post("/api/accounts/{account_id}/bootstrap")
def bootstrap_account(account_id: str, refresh_fingerprint: bool = Query(default=False)):
    return success(payment_service.bootstrap_account(account_id, refresh_fingerprint=refresh_fingerprint))


@router.get("/api/accounts/{account_id}/products")
def get_products(account_id: str):
    return success(payment_service.load_products(account_id))


@router.post("/api/accounts/{account_id}/captcha")
def save_captcha(account_id: str, payload: ManualCaptchaRequest):
    return success(payment_service.save_manual_captcha(account_id, payload))


@router.get("/api/accounts/{account_id}/captcha/challenge")
def get_captcha_challenge(account_id: str, analyze: bool = Query(default=True)):
    return success(payment_service.fetch_captcha_challenge(account_id, analyze=analyze))


@router.get("/api/accounts/{account_id}/captcha/tdc")
def collect_captcha_tdc(account_id: str):
    return success(payment_service.collect_captcha_tdc(account_id))


@router.post("/api/accounts/{account_id}/captcha/verify-payload")
def build_captcha_verify_payload(account_id: str, payload: CaptchaVerifyPayloadRequest):
    return success(payment_service.build_captcha_verify_payload(account_id, payload))


@router.post("/api/accounts/{account_id}/captcha/verify")
def submit_captcha_verify(account_id: str, payload: CaptchaVerifyPayloadRequest):
    return success(payment_service.submit_captcha_verify(account_id, payload))


@router.post("/api/accounts/{account_id}/captcha/solve")
def solve_captcha(account_id: str):
    return success(payment_service.solve_captcha(account_id))


@router.post("/api/accounts/{account_id}/payments/preview")
def preview_payment(account_id: str, payload: PreviewPaymentRequest):
    return success(payment_service.preview_payment(account_id, payload))


@router.post("/api/accounts/{account_id}/payments/preview/seed")
def seed_preview_payment(account_id: str, payload: PreviewSeedRequest):
    return success(payment_service.seed_preview(account_id, payload))


@router.post("/api/accounts/{account_id}/payments/qr")
def create_qr(account_id: str, payload: CreateQrRequest):
    return success(payment_service.create_qr(account_id, payload))


@router.post("/api/accounts/{account_id}/run")
def run_payment_flow(account_id: str):
    return success(payment_service.run_payment_flow(account_id))


@router.get("/api/accounts/{account_id}/payments/check/{biz_id}")
def check_payment(account_id: str, biz_id: str):
    return success(payment_service.check_payment(account_id, biz_id))


@router.get("/api/accounts/{account_id}/tasks")
def list_tasks(account_id: str):
    return success(payment_service.list_tasks(account_id))


def success(data: Any) -> dict[str, Any]:
    """Wrap success payloads consistently."""
    return {"ok": True, "data": data}
