"""Captcha ticket persistence helpers."""

from __future__ import annotations

import hashlib
import json
import math
import time
from functools import lru_cache
from typing import Any
from urllib.parse import unquote

from app.config import get_settings
from app.errors import BadRequestError
from app.models import (
    AccountSessionState,
    CaptchaPoint,
    CaptchaVerifyPayloadRequest,
    ManualCaptchaRequest,
    PreviewPaymentRequest,
 )
from app.services.account_state import utc_now_iso


class CaptchaService:
    """Store and resolve manual captcha tickets."""

    def store_manual_ticket(
        self,
        session: AccountSessionState,
        request: ManualCaptchaRequest,
    ) -> AccountSessionState:
        if request.ret not in (None, 0):
            raise BadRequestError(
                "验证码回调 ret 不是 0，这票据八成是废的，别拿来糊弄上游。",
                details={"ret": request.ret},
            )
        ticket = request.ticket.strip()
        randstr = request.randstr.strip()
        if not ticket or not randstr:
            raise BadRequestError("ticket 和 randstr 不能为空")
        session.captcha_ticket = ticket
        session.captcha_randstr = randstr
        session.captcha_updated_at = utc_now_iso()
        return session

    def store_challenge_snapshot(
        self,
        session: AccountSessionState,
        *,
        sess: str,
        sid: str,
        instruction: str,
        raw: dict[str, Any],
        ocr: dict[str, Any] | None = None,
    ) -> AccountSessionState:
        session.captcha_challenge_sess = sess.strip()
        session.captcha_challenge_sid = sid.strip()
        session.captcha_challenge_instruction = instruction.strip()
        session.captcha_challenge_raw = raw
        session.captcha_challenge_ocr = ocr or {}
        session.captcha_challenge_updated_at = utc_now_iso()
        return session

    def resolve_preview_captcha(
        self,
        session: AccountSessionState,
        request: PreviewPaymentRequest,
    ) -> tuple[str, str]:
        ticket = (request.ticket or "").strip() or session.captcha_ticket
        randstr = (request.randstr or "").strip() or session.captcha_randstr
        if not ticket or not randstr:
            raise BadRequestError("支付预览缺少验证码票据，请先提交 ticket / randstr")
        return ticket, randstr

    def build_click_answer(self, points: list[CaptchaPoint | dict[str, Any]]) -> list[dict[str, Any]]:
        if not points:
            raise BadRequestError("缺少点击点位，没法组装腾讯 verify 的 ans")

        normalized: list[tuple[int, int, int]] = []
        for index, item in enumerate(points, start=1):
            point = item if isinstance(item, CaptchaPoint) else CaptchaPoint.model_validate(item)
            order = int(point.order or index)
            normalized.append(
                (
                    order,
                    self._js_round(point.x),
                    self._js_round(point.y),
                )
            )

        normalized.sort(key=lambda item: (item[0], item[1], item[2]))
        answer: list[dict[str, Any]] = []
        for elem_id, (_, x, y) in enumerate(normalized, start=1):
            answer.append(
                {
                    "elem_id": elem_id,
                    "type": "DynAnswerType_POS",
                    "data": f"{x},{y}",
                }
            )
        return answer

    def extract_points_from_ocr(self, ocr_payload: dict[str, Any]) -> list[CaptchaPoint]:
        raw_points = ocr_payload.get("points")
        if not isinstance(raw_points, list):
            raise BadRequestError("OCR 结果里没有 `points`，这会儿没法自动拼 verify 点击数据")
        return [CaptchaPoint.model_validate(item) for item in raw_points]

    def build_verify_payload(
        self,
        session: AccountSessionState,
        request: CaptchaVerifyPayloadRequest,
    ) -> dict[str, Any]:
        sess = (request.sess or "").strip() or session.captcha_challenge_sess
        if not sess:
            raise BadRequestError("缺少 challenge sess，请先拉一次验证码 challenge 或手动传 sess")

        points = request.points
        if not points:
            points = self.extract_points_from_ocr(session.captcha_challenge_ocr)

        answer = self.build_click_answer(points)
        collect = self._normalize_collect(request.collect)
        settings = get_settings()
        payload: dict[str, Any] = {
            "aid": settings.tencent_captcha_aid,
            "protocol": "https",
            "sess": sess,
            "ans": json.dumps(answer, ensure_ascii=False, separators=(",", ":")),
            "collect": collect,
            "tlg": str(len(collect)),
            "eks": (request.eks or "").strip(),
        }
        pow_answer = (request.pow_answer or "").strip()
        if pow_answer:
            payload["pow_answer"] = pow_answer
        if request.pow_calc_time is not None:
            payload["pow_calc_time"] = str(int(request.pow_calc_time))
        if request.vdata:
            payload["vData"] = request.vdata

        return {
            "endpoint": "/cap_union_new_verify",
            "method": "POST",
            "content_type": "application/x-www-form-urlencoded; charset=UTF-8",
            "answer": answer,
            "payload": payload,
            "notes": [
                "collect 来自 TDC.getData(true) 后再 decodeURIComponent。",
                "eks 来自 TDC.getInfo().info。",
                "tlg 等于 collect 解码后的字符串长度。",
                "pow_answer 是 prefix + suffix，不是单独的整数 suffix。",
                "vData 只有 window.getVData 存在时才会附加，当前源码里它是可选字段。",
            ],
        }

    def solve_pow(self, prefix: str, target_md5: str, *, timeout_ms: int = 30000) -> dict[str, str]:
        normalized_prefix = prefix.strip()
        normalized_target = target_md5.strip().lower()
        if not normalized_prefix or not normalized_target:
            raise BadRequestError("pow 计算缺少 prefix 或 md5 目标值")

        started = time.perf_counter()
        suffix = 0
        timeout_seconds = max(timeout_ms, 1) / 1000
        while True:
            candidate = f"{normalized_prefix}{suffix}"
            digest = hashlib.md5(candidate.encode("utf-8")).hexdigest()
            if digest == normalized_target:
                duration_ms = int((time.perf_counter() - started) * 1000)
                return {
                    "pow_answer": candidate,
                    "pow_suffix": str(suffix),
                    "pow_calc_time": str(duration_ms),
                }
            if (time.perf_counter() - started) >= timeout_seconds:
                raise BadRequestError(
                    "pow 计算超时，腾讯这活儿有点脏，得换线程或 node worker 顶上。",
                    details={
                        "prefix": normalized_prefix,
                        "target_md5": normalized_target,
                        "last_suffix": suffix,
                    },
                )
            suffix += 1

    def _normalize_collect(self, collect: str | None) -> str:
        normalized = (collect or "").strip()
        if not normalized:
            return ""
        try:
            return unquote(normalized)
        except Exception:
            return normalized

    def _js_round(self, value: float) -> int:
        if value >= 0:
            return int(math.floor(value + 0.5))
        return int(math.ceil(value - 0.5))


@lru_cache(maxsize=1)
def get_captcha_service() -> CaptchaService:
    """Get the shared captcha service."""
    return CaptchaService()
