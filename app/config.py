"""Application settings and path resolution."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    """Environment-backed runtime settings."""

    app_host: str
    app_port: int
    data_dir: Path
    runtime_logs_dir: Path
    accounts_path: Path
    tasks_path: Path
    sessions_dir: Path
    bigmodel_api_base: str
    bigmodel_origin: str
    bigmodel_referer: str
    browser_impersonate: str
    bootstrap_fingerprint_max_retries: int
    request_timeout_seconds: float
    default_language: str
    tencent_captcha_domain: str
    tencent_captcha_aid: str
    tencent_captcha_entry_url: str
    tencent_captcha_max_retries: int
    tencent_captcha_min_confidence: float
    tencent_captcha_node: str
    tencent_ocr_enabled: bool
    tencent_ocr_include_debug: bool
    tencent_ocr_workers: int
    tencent_ocr_timeout_seconds: int
    tencent_ocr_opencv_threads: int
    tencent_ocr_onnx_threads: int
    runtime_log_level: str
    runtime_log_retention_days: int
    ticket_pool_start_jitter_ms: int
    ticket_pool_drain_jitter_ms: int
    ticket_pool_drain_mode: str
    network_egress_mode: str
    fallback_proxy_url: str  # when set, used for accounts without their own proxy_url
    fallback_proxy_ticket_pool_only: bool
    zenproxy_relay_url: str
    zenproxy_api_key: str
    zenproxy_country: str
    zenproxy_residential: bool
    zenproxy_chatgpt: bool
    zenproxy_google: bool
    zenproxy_risk_max: str
    zenproxy_type: str
    zenproxy_proxy_id: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache project settings."""
    data_dir = _resolve_path(os.getenv("DATA_DIR", "data"))
    sessions_dir = data_dir / "sessions"
    runtime_logs_dir = data_dir / "logs" / "runtime"
    data_dir.mkdir(parents=True, exist_ok=True)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    runtime_logs_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        app_host=os.getenv("APP_HOST", "127.0.0.1").strip() or "127.0.0.1",
        app_port=_parse_int(os.getenv("APP_PORT", "8787"), field_name="APP_PORT"),
        data_dir=data_dir,
        runtime_logs_dir=runtime_logs_dir,
        accounts_path=data_dir / "accounts.json",
        tasks_path=data_dir / "tasks.json",
        sessions_dir=sessions_dir,
        bigmodel_api_base=os.getenv("BIGMODEL_API_BASE", "https://www.bigmodel.cn/api").rstrip("/"),
        bigmodel_origin=os.getenv("BIGMODEL_ORIGIN", "https://www.bigmodel.cn").rstrip("/"),
        bigmodel_referer=os.getenv("BIGMODEL_REFERER", "https://www.bigmodel.cn/glm-coding").strip(),
        browser_impersonate=os.getenv("BROWSER_IMPERSONATE", "chrome146").strip() or "chrome146",
        bootstrap_fingerprint_max_retries=max(
            1,
            _parse_int(
                os.getenv("BOOTSTRAP_FINGERPRINT_MAX_RETRIES", "99"),
                field_name="BOOTSTRAP_FINGERPRINT_MAX_RETRIES",
            ),
        ),
        request_timeout_seconds=_parse_float(
            os.getenv("REQUEST_TIMEOUT_SECONDS", "20"),
            field_name="REQUEST_TIMEOUT_SECONDS",
        ),
        default_language=os.getenv("DEFAULT_LANGUAGE", "zh-CN").strip() or "zh-CN",
        tencent_captcha_domain=os.getenv(
            "TENCENT_CAPTCHA_DOMAIN",
            "https://turing.captcha.qcloud.com",
        ).rstrip("/"),
        tencent_captcha_aid=os.getenv("TENCENT_CAPTCHA_AID", "196026326").strip() or "196026326",
        tencent_captcha_entry_url=os.getenv(
            "TENCENT_CAPTCHA_ENTRY_URL",
            "https://www.bigmodel.cn/glm-coding",
        ).strip()
        or "https://www.bigmodel.cn/glm-coding",
        tencent_captcha_max_retries=_parse_int(
            os.getenv("TENCENT_CAPTCHA_MAX_RETRIES", "3"),
            field_name="TENCENT_CAPTCHA_MAX_RETRIES",
        ),
        tencent_captcha_min_confidence=_parse_float(
            os.getenv("TENCENT_CAPTCHA_MIN_CONFIDENCE", "0.55"),
            field_name="TENCENT_CAPTCHA_MIN_CONFIDENCE",
        ),
        tencent_captcha_node=os.getenv("TENCENT_CAPTCHA_NODE", "node").strip() or "node",
        tencent_ocr_enabled=_parse_bool(os.getenv("TENCENT_OCR_ENABLED", "1")),
        tencent_ocr_include_debug=_parse_bool(os.getenv("TENCENT_OCR_INCLUDE_DEBUG", "0")),
        tencent_ocr_workers=_parse_int(
            os.getenv("TENCENT_OCR_WORKERS", "4"),
            field_name="TENCENT_OCR_WORKERS",
        ),
        tencent_ocr_timeout_seconds=_parse_int(
            os.getenv("TENCENT_OCR_TIMEOUT_SECONDS", "6"),
            field_name="TENCENT_OCR_TIMEOUT_SECONDS",
        ),
        tencent_ocr_opencv_threads=max(
            1,
            _parse_int(
                os.getenv("TENCENT_OCR_OPENCV_THREADS", "1"),
                field_name="TENCENT_OCR_OPENCV_THREADS",
            ),
        ),
        tencent_ocr_onnx_threads=max(
            1,
            _parse_int(
                os.getenv("TENCENT_OCR_ONNX_THREADS", "1"),
                field_name="TENCENT_OCR_ONNX_THREADS",
            ),
        ),
        runtime_log_level=os.getenv("RUNTIME_LOG_LEVEL", "INFO").strip() or "INFO",
        runtime_log_retention_days=_parse_int(
            os.getenv("RUNTIME_LOG_RETENTION_DAYS", "7"),
            field_name="RUNTIME_LOG_RETENTION_DAYS",
        ),
        ticket_pool_start_jitter_ms=_parse_bounded_int(
            os.getenv("TICKET_POOL_START_JITTER_MS", "0"),
            field_name="TICKET_POOL_START_JITTER_MS",
            minimum=0,
            maximum=10_000,
        ),
        ticket_pool_drain_jitter_ms=_parse_bounded_int(
            os.getenv("TICKET_POOL_DRAIN_JITTER_MS", "0"),
            field_name="TICKET_POOL_DRAIN_JITTER_MS",
            minimum=0,
            maximum=10_000,
        ),
        ticket_pool_drain_mode=_parse_choice(
            os.getenv("TICKET_POOL_DRAIN_MODE", "serial"),
            field_name="TICKET_POOL_DRAIN_MODE",
            choices={"serial", "parallel"},
        ),
        network_egress_mode=_parse_choice(
            os.getenv("NETWORK_EGRESS_MODE", "local"),
            field_name="NETWORK_EGRESS_MODE",
            choices={"local", "dynamic_proxy", "zenproxy"},
        ),
        fallback_proxy_url=os.getenv("FALLBACK_PROXY_URL", "").strip(),
        fallback_proxy_ticket_pool_only=_parse_bool(os.getenv("FALLBACK_PROXY_TICKET_POOL_ONLY", "0")),
        zenproxy_relay_url=os.getenv("ZENPROXY_RELAY_URL", "").strip().rstrip("/"),
        zenproxy_api_key=os.getenv("ZENPROXY_API_KEY", "").strip(),
        zenproxy_country=os.getenv("ZENPROXY_COUNTRY", "").strip(),
        zenproxy_residential=_parse_bool(os.getenv("ZENPROXY_RESIDENTIAL", "0")),
        zenproxy_chatgpt=_parse_bool(os.getenv("ZENPROXY_CHATGPT", "0")),
        zenproxy_google=_parse_bool(os.getenv("ZENPROXY_GOOGLE", "0")),
        zenproxy_risk_max=os.getenv("ZENPROXY_RISK_MAX", "").strip(),
        zenproxy_type=os.getenv("ZENPROXY_TYPE", "").strip(),
        zenproxy_proxy_id=os.getenv("ZENPROXY_PROXY_ID", "").strip(),
    )


def _resolve_path(raw: str) -> Path:
    normalized = (raw or "").strip()
    if not normalized:
        raise ValueError("DATA_DIR must not be empty")
    path = Path(normalized).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _parse_int(raw: str, *, field_name: str) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _parse_float(raw: str, *, field_name: str) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number") from exc


def _parse_bounded_int(raw: str, *, field_name: str, minimum: int, maximum: int) -> int:
    value = _parse_int(raw, field_name=field_name)
    if value < minimum or value > maximum:
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}")
    return value


def _parse_choice(raw: str | None, *, field_name: str, choices: set[str]) -> str:
    value = (raw or "").strip().lower()
    if value not in choices:
        allowed = ", ".join(sorted(choices))
        raise ValueError(f"{field_name} must be one of: {allowed}")
    return value


def _parse_bool(raw: str | None) -> bool:
    return (raw or "").strip().lower() in {"1", "true", "yes", "on"}
