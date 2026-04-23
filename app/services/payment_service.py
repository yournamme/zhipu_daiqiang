"""Business orchestration for BigModel payment flow."""

from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
from functools import lru_cache
from io import BytesIO
from typing import Any

import qrcode

from app.clients.bigmodel_client import BigModelClient, get_bigmodel_client
from app.clients.tencent_captcha_client import TencentCaptchaClient, get_tencent_captcha_client
from app.errors import BadRequestError, GlmDeskError, UpstreamRequestError
from app.models import (
    AccountDetailResponse,
    AccountRecord,
    AccountSessionState,
    AccountPreferencesRequest,
    CaptchaVerifyPayloadRequest,
    CreateQrRequest,
    ManualCaptchaRequest,
    PaymentCheckResult,
    PaymentTaskRecord,
    PreviewPaymentRequest,
    PreviewResult,
    PreviewSeedRequest,
    ProductOffer,
)
from app.services.account_state import (
    AccountStateService,
    get_account_state_service,
    make_id,
    utc_now_iso,
)
from app.services.captcha_service import CaptchaService, get_captcha_service
from app.services.ocr_service import OcrService, get_ocr_service
from app.services.tdc_service import TencentTdcService, get_tdc_service


@dataclass(frozen=True)
class StaticProduct:
    product_id: str
    product_name: str
    unit: str
    sale_price: str
    plan_type: str
    version: str = "v2"


STATIC_PRODUCTS: tuple[StaticProduct, ...] = (
    StaticProduct("product-02434c", "Lite", "month", "49", "lite"),
    StaticProduct("product-1df3e1", "Pro", "month", "149", "pro"),
    StaticProduct("product-2fc421", "Max", "month", "469", "max"),
    StaticProduct("product-b8ea38", "Lite", "quarter", "132.3", "lite"),
    StaticProduct("product-fef82f", "Pro", "quarter", "402.3", "pro"),
    StaticProduct("product-5d3a03", "Max", "quarter", "1266.3", "max"),
    StaticProduct("product-70a804", "Lite", "year", "470.4", "lite"),
    StaticProduct("product-5643e6", "Pro", "year", "1430.4", "pro"),
    StaticProduct("product-d46f8b", "Max", "year", "4502.4", "max"),
)

DEFAULT_PRODUCT_ID = "product-5643e6"


class PaymentService:
    """Coordinate account bootstrap, preview, QR creation, and polling."""

    def __init__(
        self,
        *,
        state_service: AccountStateService | None = None,
        captcha_service: CaptchaService | None = None,
        bigmodel_client: BigModelClient | None = None,
        tencent_captcha_client: TencentCaptchaClient | None = None,
        ocr_service: OcrService | None = None,
        tdc_service: TencentTdcService | None = None,
    ) -> None:
        self.state_service = state_service or get_account_state_service()
        self.captcha_service = captcha_service or get_captcha_service()
        self.bigmodel_client = bigmodel_client or get_bigmodel_client()
        self.tencent_captcha_client = tencent_captcha_client or get_tencent_captcha_client()
        self.ocr_service = ocr_service or get_ocr_service()
        self.tdc_service = tdc_service or get_tdc_service()

    def health_payload(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "transport": self.bigmodel_client.transport_name,
            "ocr": self.ocr_service.status_payload(),
            "tdc": self.tdc_service.status_payload(),
        }

    def list_accounts(self):
        return self.state_service.list_accounts()

    def get_account_detail(self, account_id: str) -> AccountDetailResponse:
        return self.state_service.get_account_detail(account_id)

    def import_account(self, request):
        return self.state_service.import_account(request)

    def update_preferences(self, account_id: str, request: AccountPreferencesRequest) -> AccountDetailResponse:
        return self.state_service.update_preferences(account_id, request)

    def delete_account(self, account_id: str) -> dict[str, Any]:
        self.state_service.delete_account(account_id)
        return {"account_id": account_id, "deleted": True}

    def bootstrap_account(self, account_id: str, *, refresh_fingerprint: bool = False) -> AccountDetailResponse:
        if refresh_fingerprint:
            self.state_service.rotate_browser_impersonate(account_id)
        account = self.state_service.get_account(account_id)
        session = self.state_service.load_session(account_id)

        user_info_result = self.bigmodel_client.get_customer_info(account, session)
        user_info = self._ensure_dict(user_info_result.data, label="getCustomerInfo.data")
        organizations = self._extract_organizations(user_info)
        org_id, project_id = self._choose_org_and_project(
            organizations=organizations,
            preferred_org_id=account.org_id or session.org_id,
            preferred_project_id=account.project_id or session.project_id,
        )

        session.org_id = org_id
        session.project_id = project_id
        session.customer_number = str(user_info.get("customerNumber") or "")
        session.customer_name = str(user_info.get("customerName") or "")
        session.user_info = user_info
        session.organizations = organizations

        if not session.customer_number:
            raise UpstreamRequestError(
                "getCustomerInfo 没返回 customerNumber，后面 create-sign 根本没法拼。",
                details={"payload": user_info_result.raw},
            )

        account.org_id = org_id
        account.project_id = project_id
        account.last_bootstrap_at = utc_now_iso()
        self.state_service.update_account(account)

        try:
            products = self.load_products(account_id, invitation_code=account.invitation_code, account=account, session=session)
            session.products = products
            if not session.selected_product_id:
                session.selected_product_id = DEFAULT_PRODUCT_ID
            self.state_service.save_session(session)
            account = self.state_service.get_account(account_id)
            account.account_status = "valid"
            account.account_status_message = "同步上下文和套餐成功"
            account.account_checked_at = utc_now_iso()
            self.state_service.update_account(account)
            return self.state_service.get_account_detail(account_id)
        except Exception as exc:
            account = self.state_service.get_account(account_id)
            account.account_status = "error"
            account.account_status_message = str(exc)
            account.account_checked_at = utc_now_iso()
            self.state_service.update_account(account)
            raise

    def load_products(
        self,
        account_id: str,
        *,
        invitation_code: str | None = None,
        account: AccountRecord | None = None,
        session: AccountSessionState | None = None,
    ) -> list[ProductOffer]:
        account = account or self.state_service.get_account(account_id)
        session = session or self.state_service.load_session(account_id)
        if not session.customer_number:
            detail = self.bootstrap_account(account_id)
            return detail.session.products

        invitation = invitation_code if invitation_code is not None else account.invitation_code
        result = self.bigmodel_client.batch_preview(account, session, invitation or "")
        payload = self._ensure_dict(result.data, label="batchPreview.data")
        session.is_subscribed = bool(payload.get("isSubscribed"))
        session.purchase_mode = "upgrade" if session.is_subscribed else "new_purchase"
        products = self._merge_products(payload, purchase_mode=session.purchase_mode)
        session.products = products
        if not session.selected_product_id:
            session.selected_product_id = DEFAULT_PRODUCT_ID
        self.state_service.save_session(session)
        return products

    def save_manual_captcha(self, account_id: str, request: ManualCaptchaRequest) -> AccountSessionState:
        session = self.state_service.load_session(account_id)
        session = self.captcha_service.store_manual_ticket(session, request)
        return self.state_service.save_session(session)

    def fetch_captcha_challenge(self, account_id: str, *, analyze: bool = True) -> dict[str, Any]:
        account = self.state_service.get_account(account_id)
        challenge = self.tencent_captcha_client.prehandle(account)
        image_bytes = self.tencent_captcha_client.fetch_image_bytes(account, challenge)
        payload: dict[str, Any] = {
            "instruction": challenge.instruction,
            "sess": challenge.sess,
            "sid": challenge.sid,
            "image_url": challenge.image_url,
            "image_path": challenge.image_path,
            "image_size": len(image_bytes),
            "image_base64": "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii"),
            "raw": challenge.raw,
        }
        if analyze:
            payload["ocr"] = self.ocr_service.analyze_captcha_image(
                image_bytes,
                prompt_text=challenge.instruction,
            )
        session = self.state_service.load_session(account_id)
        self.captcha_service.store_challenge_snapshot(
            session,
            sess=challenge.sess,
            sid=challenge.sid,
            instruction=challenge.instruction,
            raw=challenge.raw,
            ocr=payload.get("ocr") if isinstance(payload.get("ocr"), dict) else None,
        )
        self.state_service.save_session(session)
        return payload

    def build_captcha_verify_payload(
        self,
        account_id: str,
        request: CaptchaVerifyPayloadRequest,
    ) -> dict[str, Any]:
        account = self.state_service.get_account(account_id)
        session = self.state_service.load_session(account_id)
        request, tdc_result = self._hydrate_tdc_if_needed(account, session, request)
        payload = self.captcha_service.build_verify_payload(session, request)
        payload["challenge"] = {
            "sess": session.captcha_challenge_sess,
            "sid": session.captcha_challenge_sid,
            "instruction": session.captcha_challenge_instruction,
            "updated_at": session.captcha_challenge_updated_at,
        }
        if tdc_result:
            payload["tdc"] = tdc_result
        self._attach_pow_if_needed(session, request, payload)
        return payload

    def submit_captcha_verify(
        self,
        account_id: str,
        request: CaptchaVerifyPayloadRequest,
    ) -> dict[str, Any]:
        account = self.state_service.get_account(account_id)
        session = self.state_service.load_session(account_id)
        request, tdc_result = self._hydrate_tdc_if_needed(account, session, request)
        bundle = self.captcha_service.build_verify_payload(session, request)
        bundle["challenge"] = {
            "sess": session.captcha_challenge_sess,
            "sid": session.captcha_challenge_sid,
            "instruction": session.captcha_challenge_instruction,
            "updated_at": session.captcha_challenge_updated_at,
        }
        if tdc_result:
            bundle["tdc"] = tdc_result
        self._attach_pow_if_needed(session, request, bundle)
        verify_result = self.tencent_captcha_client.verify(account, bundle["payload"])

        if verify_result.sess:
            session.captcha_challenge_sess = verify_result.sess
        if verify_result.ticket and verify_result.randstr:
            session.captcha_ticket = verify_result.ticket
            session.captcha_randstr = verify_result.randstr
            session.captcha_updated_at = utc_now_iso()
        else:
            session.captcha_ticket = ""
            session.captcha_randstr = ""
            session.captcha_updated_at = None
        self.state_service.save_session(session)

        return {
            "request": bundle,
            "response": verify_result.raw,
            "ticket": verify_result.ticket,
            "randstr": verify_result.randstr,
            "ret": verify_result.ret,
            "error_code": verify_result.error_code,
            "error_message": verify_result.error_message,
        }

    def solve_captcha(self, account_id: str) -> dict[str, Any]:
        attempts: list[dict[str, Any]] = []
        last_result: dict[str, Any] = {}
        attempt = 0
        while True:
            attempt += 1
            try:
                challenge = self.fetch_captcha_challenge(account_id, analyze=True)
            except GlmDeskError as exc:
                result = {
                    "attempt": attempt,
                    "challenge": None,
                    "verify": {
                        "skipped": True,
                        "error_code": "OCR_EXCEPTION",
                        "error_message": exc.message,
                        "details": exc.details,
                    },
                    "ticket": "",
                    "randstr": "",
                    "status": "ocr_exception",
                }
                attempts.append(result)
                last_result = result
                continue
            ocr_gate = self._captcha_ocr_gate(challenge)
            if not ocr_gate["usable"]:
                result = {
                    "attempt": attempt,
                    "challenge": challenge,
                    "verify": {
                        "skipped": True,
                        "error_code": "OCR_INCOMPLETE",
                        "error_message": "OCR 点位少于 3 个或置信度不达标，跳过 verify 并刷新重试。",
                        "ocr_gate": ocr_gate,
                    },
                    "ticket": "",
                    "randstr": "",
                    "status": "ocr_rejected",
                }
                attempts.append(result)
                last_result = result
                continue

            verify = self.submit_captcha_verify(account_id, CaptchaVerifyPayloadRequest())
            error_code = str(verify.get("error_code") or "")
            result = {
                "attempt": attempt,
                "challenge": challenge,
                "verify": verify,
                "ticket": verify.get("ticket") or "",
                "randstr": verify.get("randstr") or "",
                "status": "verified" if not error_code or error_code == "0" else "verify_failed",
            }
            if error_code == "50":
                result["ticket"] = ""
                result["randstr"] = ""
                result["status"] = "recognition_failed"
                attempts.append(result)
                last_result = result
                continue
            if (error_code and error_code != "0") or not result["ticket"] or not result["randstr"]:
                result["ticket"] = ""
                result["randstr"] = ""
                attempts.append(result)
                last_result = result
                continue
            attempts.append(result)
            last_result = result
            return {
                **result,
                "attempts": attempts,
            }

    def collect_captcha_tdc(self, account_id: str) -> dict[str, Any]:
        account = self.state_service.get_account(account_id)
        session = self.state_service.load_session(account_id)
        result = self.tdc_service.collect_for_challenge(account, session.captcha_challenge_raw or {})
        return result.to_payload()

    def preview_payment(self, account_id: str, request: PreviewPaymentRequest) -> PreviewResult:
        account, session = self._ensure_context(account_id)
        invitation = (request.invitation_code or account.invitation_code).strip()
        preview_attempts: list[dict[str, Any]] = []
        preview_round = 0

        while True:
            preview_round += 1
            # 1. Solve a fresh captcha chain each round after the first failed preview.
            captcha_request = request if preview_round == 1 else request.model_copy(update={"ticket": None, "randstr": None})
            ticket, randstr = self._resolve_or_solve_preview_captcha(account_id, session, captcha_request)

            # 2. call preview API
            try:
                result = self.bigmodel_client.preview_payment(
                    account,
                    session,
                    request,
                    invitation_code=invitation,
                    ticket=ticket,
                    randstr=randstr,
                )
            except UpstreamRequestError as exc:
                preview_attempts.append(
                    {
                        "round": preview_round,
                        "code": None,
                        "biz_id": None,
                        "sold_out": None,
                        "msg": exc.message,
                        "ticket": ticket[:30] + "..." if ticket else "",
                    }
                )
                if len(preview_attempts) > 100:
                    preview_attempts.pop(0)
                session = self.state_service.load_session(account_id)
                continue
            raw = result.raw
            code = raw.get("code")
            data = result.data if isinstance(result.data, dict) else {}

            biz_id = str(data.get("bizId") or "").strip()
            attempt_info = {
                "round": preview_round,
                "code": code,
                "biz_id": biz_id or None,
                "sold_out": bool(data.get("soldOut")),
                "msg": raw.get("msg") or "",
                "ticket": ticket[:30] + "..." if ticket else "",
            }
            preview_attempts.append(attempt_info)
            if len(preview_attempts) > 100:
                preview_attempts.pop(0)

            preview = PreviewResult(
                biz_id=biz_id,
                third_party_amount=self._string_value(data, "thirdPartyAmount"),
                sold_out=bool(data.get("soldOut")),
                original_amount=self._string_value(data, "originalAmount"),
                pay_amount=self._string_value(data, "payAmount"),
                residual_amount=self._string_value(data, "residualAmount"),
                give_amount=self._string_value(data, "giveAmount"),
                cash_amount=self._string_value(data, "cashAmount"),
                renew_amount=self._string_value(data, "renewAmount"),
                campaign_discount_details=list(data.get("campaignDiscountDetails") or []),
                last_subscription_summary=self._ensure_dict(
                    data.get("lastSubscriptionSummary") or {},
                    label="preview.lastSubscriptionSummary",
                ),
                raw=raw,
            )

            # 3. Only a successful business id can move the flow forward.
            if code == 200 and biz_id:
                session.selected_product_id = request.product_id
                session.preview = preview
                session.captcha_ticket = ticket
                session.captcha_randstr = randstr
                self.state_service.save_session(session)
                return preview

            # 4. code=200 with bizId=null, captcha errors, or other failures restart the full chain.
            session = self.state_service.load_session(account_id)
            # reload session to get fresh state

    def seed_preview(self, account_id: str, request: PreviewSeedRequest) -> PreviewResult:
        session = self.state_service.load_session(account_id)
        preview = self._preview_from_upstream_payload(request.preview)
        session.preview = preview
        product_id = str((preview.raw.get("data") or {}).get("productId") or "").strip()
        if product_id:
            session.selected_product_id = product_id
        self.state_service.save_session(session)
        return preview

    def create_qr(self, account_id: str, request: CreateQrRequest) -> PaymentTaskRecord:
        account, session = self._ensure_context(account_id)
        product_id = request.product_id.strip() or session.selected_product_id
        if not product_id:
            raise BadRequestError("缺少 product_id，二维码没法生成")
        invitation = (request.invitation_code or account.invitation_code).strip()
        if not session.preview or not session.preview.biz_id:
            raise BadRequestError("请先调用 preview，拿到 bizId 之后再生成二维码")
        qr_cycles: list[dict[str, Any]] = []
        cycle = 0

        while True:
            cycle += 1
            session = self.state_service.load_session(account_id)
            if not session.preview or not session.preview.biz_id:
                regenerated_preview = self.preview_payment(
                    account_id,
                    PreviewPaymentRequest(
                        product_id=product_id,
                        invitation_code=invitation,
                    ),
                )
                session = self.state_service.load_session(account_id)
            else:
                regenerated_preview = session.preview

            biz_id = (session.preview.biz_id or request.biz_id or "").strip() if session.preview else ""
            sign_mode = session.purchase_mode or ("upgrade" if session.is_subscribed else "new_purchase")
            sign_attempts: list[dict[str, Any]] = []

            for sign_attempt in range(1, 4):
                try:
                    result = self._request_sign(
                        account,
                        session,
                        pay_type=request.pay_type,
                        product_id=product_id,
                        biz_id=biz_id,
                        invitation_code=invitation,
                    )
                    payload = self._ensure_dict(result.data, label="createSign.data")
                    sign = str(payload.get("sign") or "")
                    order_id = str(payload.get("orderId") or "")
                    if not sign:
                        raise UpstreamRequestError(
                            "create-sign 没返回 sign，二维码自然也出不来。",
                            details={"payload": result.raw},
                        )

                    sign_attempts.append(
                        {
                            "attempt": sign_attempt,
                            "ok": True,
                            "mode": sign_mode,
                            "order_id": order_id,
                            "biz_id": biz_id,
                            "response": result.raw,
                        }
                    )
                    qr_cycles.append(
                        {
                            "cycle": cycle,
                            "preview_biz_id": biz_id,
                            "sign_attempts": sign_attempts,
                        }
                    )

                    product_name = next(
                        (item.product_name for item in session.products if item.product_id == product_id),
                        "",
                    )
                    amount = session.preview.third_party_amount if session.preview else ""
                    now = utc_now_iso()
                    task = PaymentTaskRecord(
                        id=make_id("task"),
                        account_id=account_id,
                        product_id=product_id,
                        product_name=product_name,
                        pay_type=request.pay_type,
                        biz_id=biz_id,
                        amount=amount,
                        sign=sign,
                        qr_base64=self._build_qr_base64(sign),
                        status="PENDING",
                        raw_preview=session.preview.raw if session.preview else {},
                        raw_sign={
                            "mode": sign_mode,
                            "cycle": cycle,
                            "attempt": sign_attempt,
                            "attempts": qr_cycles,
                            "response": result.raw,
                        },
                        created_at=now,
                        updated_at=now,
                    )
                    session.last_sign = sign
                    session.last_order_id = order_id
                    session.selected_product_id = product_id
                    self.state_service.save_session(session)
                    return self.state_service.save_task(task)
                except UpstreamRequestError as exc:
                    sign_attempts.append(
                        {
                            "attempt": sign_attempt,
                            "ok": False,
                            "mode": sign_mode,
                            "biz_id": biz_id,
                            "message": exc.message,
                            "details": exc.details,
                        }
                    )

            qr_cycles.append(
                {
                    "cycle": cycle,
                    "preview_biz_id": biz_id,
                    "sign_attempts": sign_attempts,
                    "fallback": "rerun_preview_chain",
                }
            )
            session.preview = None
            session.last_sign = ""
            session.last_order_id = ""
            self.state_service.save_session(session)

    def run_payment_flow(
        self,
        account_id: str,
        *,
        product_id: str | None = None,
        pay_type: str = "ALI",
    ) -> PaymentTaskRecord:
        session = self.state_service.load_session(account_id)
        selected_product_id = (product_id or session.selected_product_id).strip()
        if not selected_product_id:
            raise BadRequestError("请先选择套餐，再启动支付链路")
        preview = self.preview_payment(
            account_id,
            PreviewPaymentRequest(product_id=selected_product_id),
        )
        return self.create_qr(
            account_id,
            CreateQrRequest(
                product_id=selected_product_id,
                pay_type=pay_type,
                biz_id=preview.biz_id,
            ),
        )

    def _create_upgrade_sign(
        self,
        account: AccountRecord,
        session: AccountSessionState,
        *,
        pay_type: str,
        product_id: str,
        biz_id: str,
    ):
        summary = session.preview.last_subscription_summary if session.preview else {}
        old_product_id = str(summary.get("productId") or "").strip()
        agreement_no = str(summary.get("agreementNo") or "").strip()
        if not old_product_id or not agreement_no:
            raise BadRequestError(
                "升级签单缺少 lastSubscriptionSummary.productId 或 agreementNo",
                details={
                    "purchase_mode": session.purchase_mode,
                    "last_subscription_summary": summary,
                    "product_id": product_id,
                    "biz_id": biz_id,
                },
            )
        return self.bigmodel_client.update_sign(
            account,
            session,
            pay_type=pay_type,
            old_product_id=old_product_id,
            new_product_id=product_id,
            customer_id=session.customer_number,
            agreement_no=agreement_no,
            biz_id=biz_id,
        )

    def _request_sign(
        self,
        account: AccountRecord,
        session: AccountSessionState,
        *,
        pay_type: str,
        product_id: str,
        biz_id: str,
        invitation_code: str,
    ):
        sign_mode = session.purchase_mode or ("upgrade" if session.is_subscribed else "new_purchase")
        if sign_mode == "upgrade":
            return self._create_upgrade_sign(
                account,
                session,
                pay_type=pay_type,
                product_id=product_id,
                biz_id=biz_id,
            )
        return self.bigmodel_client.create_sign(
            account,
            session,
            pay_type=pay_type,
            product_id=product_id,
            customer_id=session.customer_number,
            biz_id=biz_id,
            invitation_code=invitation_code,
        )

    def check_payment(self, account_id: str, biz_id: str) -> PaymentCheckResult:
        account, session = self._ensure_context(account_id)
        result = self.bigmodel_client.check_payment(account, session, biz_id=biz_id)
        data = result.data
        if isinstance(data, str):
            status = data.strip()
        elif isinstance(data, dict):
            status = str(data.get("status") or data.get("payStatus") or data.get("result") or "")
        else:
            status = str(data)
        status = status or "PENDING"

        task = self.state_service.get_task_by_biz_id(account_id, biz_id)
        if task:
            task.status = status
            task.last_check = result.raw
            task.updated_at = utc_now_iso()
            self.state_service.save_task(task)

        return PaymentCheckResult(biz_id=biz_id, status=status, raw=result.raw)

    def list_tasks(self, account_id: str) -> list[PaymentTaskRecord]:
        return self.state_service.list_tasks(account_id)

    def _attach_pow_if_needed(
        self,
        session: AccountSessionState,
        request: CaptchaVerifyPayloadRequest,
        payload_bundle: dict[str, Any],
    ) -> None:
        raw_challenge = session.captcha_challenge_raw or {}
        pow_cfg = (((raw_challenge.get("data") or {}).get("comm_captcha_cfg") or {}).get("pow_cfg") or {})
        if request.pow_answer or not pow_cfg.get("prefix") or not pow_cfg.get("md5"):
            return
        pow_result = self.captcha_service.solve_pow(
            str(pow_cfg.get("prefix") or ""),
            str(pow_cfg.get("md5") or ""),
        )
        payload_bundle["payload"]["pow_answer"] = pow_result["pow_answer"]
        payload_bundle["payload"]["pow_calc_time"] = pow_result["pow_calc_time"]
        payload_bundle["pow"] = pow_result

    def _resolve_or_solve_preview_captcha(
        self,
        account_id: str,
        session: AccountSessionState,
        request: PreviewPaymentRequest,
    ) -> tuple[str, str]:
        if (request.ticket or "").strip() and (request.randstr or "").strip():
            return self.captcha_service.resolve_preview_captcha(session, request)

        solved = self.solve_captcha(account_id)
        verify = solved.get("verify") if isinstance(solved.get("verify"), dict) else {}
        error_code = str(verify.get("error_code") or "")
        if error_code == "50":
            raise UpstreamRequestError(
                "验证码识别失败（error=50），已刷新重试但仍未通过，停止 preview 请求。",
                details={
                    "verify": verify,
                    "attempts": solved.get("attempts") or [],
                },
            )
        ticket = str(solved.get("ticket") or "")
        randstr = str(solved.get("randstr") or "")
        if not ticket or not randstr:
            raise UpstreamRequestError(
                "自动验证码没通过，已停止 preview 请求。",
                details={
                    "verify": solved.get("verify") or {},
                    "attempts": solved.get("attempts") or [],
                },
            )
        return ticket, randstr

    def _captcha_ocr_gate(self, challenge: dict[str, Any]) -> dict[str, Any]:
        ocr = challenge.get("ocr") if isinstance(challenge.get("ocr"), dict) else {}
        points = ocr.get("points") if isinstance(ocr.get("points"), list) else []
        target_chars = ocr.get("target_chars") if isinstance(ocr.get("target_chars"), list) else []
        instruction_chars = self._extract_instruction_target_chars(str(challenge.get("instruction") or ""))
        expected_points = max(3, len(target_chars), len(instruction_chars))
        confidence = self._safe_float(ocr.get("confidence"))
        min_confidence = max(getattr(self.tencent_captcha_client.settings, "tencent_captcha_min_confidence", 0.0), 0.0)
        point_labels = [
            str(item.get("label") or "").strip()
            for item in points
            if isinstance(item, dict)
        ]
        expected_labels = target_chars or instruction_chars
        labels_match = bool(expected_labels) and point_labels[: len(expected_labels)] == expected_labels
        usable = bool(points) and len(points) >= expected_points and confidence >= min_confidence and labels_match
        return {
            "usable": usable,
            "points": len(points),
            "expected_points": expected_points,
            "confidence": confidence,
            "min_confidence": min_confidence,
            "target_chars": target_chars,
            "instruction_chars": instruction_chars,
            "point_labels": point_labels,
            "labels_match": labels_match,
        }

    def _extract_instruction_target_chars(self, instruction: str) -> list[str]:
        compact = instruction.replace(" ", "").replace("\n", "").strip()
        marker = "请依次点击"
        if marker in compact:
            compact = compact.split(marker, 1)[1]
        compact = compact.replace("：", "").replace(":", "")
        return [char for char in compact if "\u4e00" <= char <= "\u9fff"]

    def _safe_float(self, value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _hydrate_tdc_if_needed(
        self,
        account: AccountRecord,
        session: AccountSessionState,
        request: CaptchaVerifyPayloadRequest,
    ) -> tuple[CaptchaVerifyPayloadRequest, dict[str, Any] | None]:
        if (request.collect or "").strip() and (request.eks or "").strip():
            return request, None
        result = self.tdc_service.collect_for_challenge(account, session.captcha_challenge_raw or {})
        hydrated = request.model_copy(
            update={
                "collect": (request.collect or "").strip() or result.collect_raw,
                "eks": (request.eks or "").strip() or result.eks,
            }
        )
        return hydrated, result.to_payload()

    def _ensure_context(self, account_id: str) -> tuple[AccountRecord, AccountSessionState]:
        account = self.state_service.get_account(account_id)
        session = self.state_service.load_session(account_id)
        if not session.customer_number or not (session.org_id or account.org_id) or not (session.project_id or account.project_id):
            detail = self.bootstrap_account(account_id)
            account = self.state_service.get_account(account_id)
            session = detail.session
        return account, session

    def _merge_products(self, payload: dict[str, Any], *, purchase_mode: str = "new_purchase") -> list[ProductOffer]:
        dynamic_products = payload.get("productList") or []
        dynamic_map = {
            str(item.get("productId")): item
            for item in dynamic_products
            if isinstance(item, dict) and item.get("productId")
        }
        merged: list[ProductOffer] = []
        for static in STATIC_PRODUCTS:
            dynamic = dynamic_map.get(static.product_id, {})
            merged.append(
                ProductOffer(
                    product_id=static.product_id,
                    product_name=static.product_name,
                    unit=static.unit,
                    sale_price=static.sale_price,
                    plan_type=static.plan_type,
                    purchase_mode=purchase_mode,
                    version=static.version,
                    sold_out=False,
                    forbidden=bool(dynamic.get("forbidden")),
                    last_valid=bool(dynamic.get("lastValid")),
                    can_repurchase=bool(dynamic.get("canRepurchase")),
                    delay=bool(dynamic.get("delay")),
                    effective_time=str(dynamic.get("effectiveTime") or ""),
                    monthly_renew_amount=self._string_value(dynamic, "monthlyRenewAmount"),
                    monthly_original_amount=self._string_value(dynamic, "monthlyOriginalAmount"),
                    campaign_discount_details=list(dynamic.get("campaignDiscountDetails") or []),
                    raw=dynamic,
                )
            )
        for product_id, dynamic in dynamic_map.items():
            if any(item.product_id == product_id for item in merged):
                continue
            merged.append(
                ProductOffer(
                    product_id=product_id,
                    product_name=str(dynamic.get("productName") or product_id),
                    unit=str(dynamic.get("unit") or ""),
                    sale_price=self._string_value(dynamic, "salePrice"),
                    plan_type=str(dynamic.get("type") or "unknown"),
                    purchase_mode=purchase_mode,
                    version=str(dynamic.get("version") or "upstream"),
                    sold_out=False,
                    forbidden=bool(dynamic.get("forbidden")),
                    last_valid=bool(dynamic.get("lastValid")),
                    can_repurchase=bool(dynamic.get("canRepurchase")),
                    delay=bool(dynamic.get("delay")),
                    effective_time=str(dynamic.get("effectiveTime") or ""),
                    monthly_renew_amount=self._string_value(dynamic, "monthlyRenewAmount"),
                    monthly_original_amount=self._string_value(dynamic, "monthlyOriginalAmount"),
                    campaign_discount_details=list(dynamic.get("campaignDiscountDetails") or []),
                    raw=dynamic,
                )
            )
        return merged

    def _choose_org_and_project(
        self,
        *,
        organizations: list[dict[str, Any]],
        preferred_org_id: str,
        preferred_project_id: str,
    ) -> tuple[str, str]:
        selected_org = None
        if preferred_org_id:
            selected_org = next(
                (
                    item
                    for item in organizations
                    if self._entity_id(item, ("id", "organizationId", "orgId")) == preferred_org_id
                ),
                None,
            )
        if selected_org is None:
            selected_org = next((item for item in organizations if bool(item.get("isDefault"))), None)
        if selected_org is None and organizations:
            selected_org = organizations[0]
        if selected_org is None:
            return "", ""

        org_id = self._entity_id(selected_org, ("id", "organizationId", "orgId"))
        projects = self._extract_projects(selected_org)
        selected_project = None
        if preferred_project_id:
            selected_project = next(
                (
                    item
                    for item in projects
                    if self._entity_id(item, ("id", "projectId")) == preferred_project_id
                ),
                None,
            )
        if selected_project is None:
            selected_project = next((item for item in projects if int(item.get("projectType") or 0) == 2), None)
        if selected_project is None:
            selected_project = next((item for item in projects if bool(item.get("isDefault"))), None)
        if selected_project is None and projects:
            selected_project = projects[0]
        project_id = self._entity_id(selected_project, ("id", "projectId")) if selected_project else ""
        return org_id, project_id

    def _extract_organizations(self, user_info: dict[str, Any]) -> list[dict[str, Any]]:
        organizations = user_info.get("organizations") or user_info.get("organizationList") or []
        if not isinstance(organizations, list):
            return []
        return [item for item in organizations if isinstance(item, dict)]

    def _extract_projects(self, organization: dict[str, Any]) -> list[dict[str, Any]]:
        for key in ("projects", "projectList", "projectVOList"):
            value = organization.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    def _entity_id(self, payload: dict[str, Any] | None, fields: tuple[str, ...]) -> str:
        if not payload:
            return ""
        for field in fields:
            value = payload.get(field)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    def _build_qr_base64(self, content: str) -> str:
        qr = qrcode.QRCode(border=1, box_size=8)
        qr.add_data(content)
        qr.make(fit=True)
        image = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")

    def _ensure_dict(self, payload: Any, *, label: str) -> dict[str, Any]:
        if isinstance(payload, dict):
            return payload
        raise UpstreamRequestError(f"{label} 结构异常", details={"payload_type": type(payload).__name__})

    def _preview_from_upstream_payload(self, raw: dict[str, Any]) -> PreviewResult:
        data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        return PreviewResult(
            biz_id=str(data.get("bizId") or ""),
            third_party_amount=self._string_value(data, "thirdPartyAmount"),
            sold_out=bool(data.get("soldOut")),
            original_amount=self._string_value(data, "originalAmount"),
            pay_amount=self._string_value(data, "payAmount"),
            residual_amount=self._string_value(data, "residualAmount"),
            give_amount=self._string_value(data, "giveAmount"),
            cash_amount=self._string_value(data, "cashAmount"),
            renew_amount=self._string_value(data, "renewAmount"),
            campaign_discount_details=list(data.get("campaignDiscountDetails") or []),
            last_subscription_summary=self._ensure_dict(
                data.get("lastSubscriptionSummary") or {},
                label="preview.lastSubscriptionSummary",
            ),
            raw=raw,
        )

    def _string_value(self, payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if value is None:
            return ""
        return str(value)


@lru_cache(maxsize=1)
def get_payment_service() -> PaymentService:
    """Get the shared payment service."""
    return PaymentService()
