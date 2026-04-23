"""Local OCR wrapper for Tencent click captcha images."""

from __future__ import annotations

import base64
import importlib.util
import multiprocessing
import os
import threading
import time
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FuturesTimeoutError
from concurrent.futures.process import BrokenProcessPool
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


def _clear_proxy_env() -> None:
    for key in PROXY_ENV_KEYS:
        os.environ.pop(key, None)


def _load_adapter_module():
    from app.services import tenvision_adapter

    return tenvision_adapter


def _worker_initializer() -> None:
    _clear_proxy_env()
    _load_adapter_module().get_engine()


def _warmup_worker(index: int) -> dict[str, Any]:
    _clear_proxy_env()
    _load_adapter_module().get_engine()
    time.sleep(0.1)
    return {"index": index, "pid": os.getpid()}


def _worker_analyze(data: bytes, prompt_text: str, include_debug: bool) -> dict[str, Any]:
    _clear_proxy_env()
    adapter = _load_adapter_module()
    started_at = time.perf_counter()
    result = adapter.analyze_image_bytes(
        data,
        prompt_text=prompt_text,
        include_debug=include_debug,
    )
    result["_worker_pid"] = os.getpid()
    result["_worker_elapsed_ms"] = round((time.perf_counter() - started_at) * 1000, 2)
    return result


class OcrService:
    """Run the vendored TenVision captcha OCR pipeline in this project."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._executor: ProcessPoolExecutor | None = None
        self._executor_lock = threading.Lock()

    def status_payload(self) -> dict[str, Any]:
        missing = self._missing_dependencies()
        return {
            "enabled": self.settings.tencent_ocr_enabled,
            "adapter": "local-tenvision-process-pool",
            "available": not missing,
            "missing_dependencies": missing,
            "include_debug": self.settings.tencent_ocr_include_debug,
            "workers": self.settings.tencent_ocr_workers,
            "timeout_seconds": self.settings.tencent_ocr_timeout_seconds,
            "executor_ready": self._executor is not None,
        }

    def warmup(self) -> None:
        if not self.settings.tencent_ocr_enabled:
            return
        missing = self._missing_dependencies()
        if missing:
            raise BadRequestError(
                "本地 OCR 依赖没装全，先运行 pip install -r requirements.txt，别让发动机缺缸还硬跑。",
                details={"missing_dependencies": missing},
            )
        executor = self._ensure_executor()
        futures = [executor.submit(_warmup_worker, index) for index in range(self.settings.tencent_ocr_workers)]
        timeout = max(self.settings.tencent_ocr_timeout_seconds, 1)
        for future in futures:
            future.result(timeout=timeout)

    def shutdown(self) -> None:
        with self._executor_lock:
            if self._executor is None:
                return
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

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
            result = self._run_worker(image_bytes, prompt_text)
        except FuturesTimeoutError as exc:
            raise BadRequestError(
                "验证码 OCR 识别超时",
                details={"timeout_seconds": self.settings.tencent_ocr_timeout_seconds},
            ) from exc
        except Exception as exc:
            raise BadRequestError("验证码 OCR 识别失败", details={"reason": str(exc)}) from exc

        return self._normalize_result(result)

    def _run_worker(self, image_bytes: bytes, prompt_text: str) -> dict[str, Any]:
        timeout = max(self.settings.tencent_ocr_timeout_seconds, 1)
        payload_prompt = prompt_text or ""
        for attempt in range(1, 3):
            executor = self._ensure_executor()
            future = executor.submit(
                _worker_analyze,
                image_bytes,
                payload_prompt,
                self.settings.tencent_ocr_include_debug,
            )
            try:
                return future.result(timeout=timeout)
            except FuturesTimeoutError:
                future.cancel()
                raise
            except BrokenProcessPool:
                self.shutdown()
                if attempt >= 2:
                    raise
            except Exception:
                raise
        raise RuntimeError("OCR worker 未返回结果")

    def _ensure_executor(self) -> ProcessPoolExecutor:
        with self._executor_lock:
            if self._executor is not None:
                return self._executor
            mp_context = multiprocessing.get_context("spawn")
            self._executor = ProcessPoolExecutor(
                max_workers=max(1, self.settings.tencent_ocr_workers),
                mp_context=mp_context,
                initializer=_worker_initializer,
            )
            return self._executor

    def _missing_dependencies(self) -> list[str]:
        return [name for name in OCR_DEPENDENCIES if importlib.util.find_spec(name) is None]

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


_ocr_service: OcrService | None = None


def get_ocr_service() -> OcrService:
    """Get the shared OCR service."""
    global _ocr_service
    if _ocr_service is None:
        _ocr_service = OcrService()
    return _ocr_service
