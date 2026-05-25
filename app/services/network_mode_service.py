"""Runtime network egress mode selection."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.config import get_settings
from app.errors import BadRequestError
from app.models import NetworkEgressMode
from app.storage.json_store import JsonFileStore

VALID_NETWORK_MODES: set[str] = {"local", "dynamic_proxy"}


class NetworkModeService:
    """Persist and validate the active outbound network mode."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.store = JsonFileStore(
            self.settings.data_dir / "network_mode.json",
            default_factory=lambda: {"mode": self.settings.network_egress_mode},
        )

    def get_mode(self) -> NetworkEgressMode:
        payload = self.store.read()
        mode = str((payload or {}).get("mode") or self.settings.network_egress_mode).strip()
        if mode not in VALID_NETWORK_MODES:
            return "local"
        return mode  # type: ignore[return-value]

    def set_mode(self, mode: NetworkEgressMode) -> dict[str, Any]:
        normalized = str(mode).strip()
        if normalized not in VALID_NETWORK_MODES:
            raise BadRequestError("网络出口模式不支持", details={"mode": mode})
        status = self.status_payload(mode=normalized)
        if not bool(status.get("available")):
            raise BadRequestError(str(status.get("message") or "网络出口配置不可用"), details=status)
        self.store.write({"mode": normalized})
        return self.status_payload()

    def status_payload(self, *, mode: str | None = None) -> dict[str, Any]:
        active_mode = str(mode or self.get_mode()).strip()
        modes = {
            "local": {
                "available": True,
                "message": "本地出口模式已启用",
                "label": "本地",
            },
            "dynamic_proxy": {
                "available": bool(self.settings.fallback_proxy_url.strip()),
                "message": (
                    f"动态代理模式：{self.settings.fallback_proxy_url}"
                    if self.settings.fallback_proxy_url.strip()
                    else "动态代理模式缺少 FALLBACK_PROXY_URL"
                ),
                "label": "动态代理",
                "url": self.settings.fallback_proxy_url,
            },
        }
        current = modes.get(active_mode, modes["local"])
        return {
            "mode": active_mode,
            "available": bool(current.get("available")),
            "message": current.get("message", ""),
            "label": current.get("label", active_mode),
            "ticket_pool_only": self.settings.fallback_proxy_ticket_pool_only,
            "modes": modes,
        }


@lru_cache(maxsize=1)
def get_network_mode_service() -> NetworkModeService:
    """Return the process-wide network mode service."""
    return NetworkModeService()
