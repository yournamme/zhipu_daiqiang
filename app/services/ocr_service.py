"""Local OCR wrapper for Tencent click captcha images."""

from __future__ import annotations

import base64
import importlib.util
import os
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from app.config import Settings, get_settings
from app.errors import BadRequestError

OCR_DEPENDENCIES = ("cv2", "numpy", "rapidocr", "onnxruntime")
PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)


class OcrService:
    """Run the vendored TenVision captcha OCR pipeline in this project."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def status_payload(self) -> dict[str, Any]:
        missing = self._missing_dependencies()
        return {
            "enabled": self.settings.tencent_ocr_enabled,
            "adapter": "local-tenvision",
            "available": not missing,
            "missing_dependencies": missing,
            "include_debug": self.settings.tencent_ocr_include_debug,
        }

    def warmup(self) -> None:
        if not self.settings.tencent_ocr_enabled:
            return
        with self._without_proxy_env():
            self._load_adapter().get_engine()

    def analyze_captcha_image(self, image_bytes: bytes, *, prompt_text: str) -> dict[str, Any]:
        if not self.settings.tencent_ocr_enabled:
            raise BadRequestError("本地 OCR 已关闭，请设置 TENCENT_OCR_ENABLED=1")

        missing = self._missing_dependencies()
        if missing:
            raise BadRequestError(
                "本地 OCR 依赖没装全，先运行 pip install -r requirements.txt，别让发动机缺缸还硬跑。",
                details={"missing_dependencies": missing},
            )

        try:
            with self._without_proxy_env():
                result = self._load_adapter().analyze_image_bytes(
                    image_bytes,
                    prompt_text=prompt_text,
                    include_debug=self.settings.tencent_ocr_include_debug,
                )
        except Exception as exc:
            raise BadRequestError("验证码 OCR 识别失败", details={"reason": str(exc)}) from exc

        return self._normalize_result(result)

    def _load_adapter(self):
        try:
            from app.services import tenvision_adapter
        except ImportError as exc:
            raise BadRequestError("本地 OCR adapter 加载失败", details={"reason": str(exc)}) from exc
        return tenvision_adapter

    def _missing_dependencies(self) -> list[str]:
        return [name for name in OCR_DEPENDENCIES if importlib.util.find_spec(name) is None]

    @contextmanager
    def _without_proxy_env(self):
        saved = {key: os.environ.get(key) for key in PROXY_ENV_KEYS}
        try:
            for key in PROXY_ENV_KEYS:
                os.environ.pop(key, None)
            yield
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def _normalize_result(self, result: dict[str, Any]) -> dict[str, Any]:
        normalized = self._json_safe(dict(result))
        debug_png = normalized.pop("debug_png", b"")
        if isinstance(debug_png, bytes) and debug_png:
            normalized["debug_image_base64"] = "data:image/png;base64," + base64.b64encode(debug_png).decode("ascii")
        return normalized

    def _json_safe(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): self._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._json_safe(item) for item in value]
        if isinstance(value, bytes):
            return value
        if hasattr(value, "item"):
            return value.item()
        return value


@lru_cache(maxsize=1)
def get_ocr_service() -> OcrService:
    """Get the shared OCR service."""
    return OcrService()
