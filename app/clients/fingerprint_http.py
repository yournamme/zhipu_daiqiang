"""HTTP client wrapper with browser-like TLS/HTTP impersonation."""

from __future__ import annotations

from typing import Any

import httpx

from app.browser_profiles import (
    AVAILABLE_BROWSER_PROFILES,
    BrowserProfile,
    resolve_browser_impersonate,
    resolve_transport_impersonate,
)
from app.config import Settings, get_settings
from app.errors import UpstreamRequestError

try:
    from curl_cffi import requests as curl_requests
except ImportError:  # pragma: no cover - optional fallback
    curl_requests = None


class FingerprintHttpClient:
    """Send requests through curl-cffi when available, otherwise httpx."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def transport_name(self) -> str:
        if curl_requests is not None:
            return f"curl-cffi:{self.settings.browser_impersonate}"
        return "httpx"

    # ------------------------------------------------------------------
    # Public request helpers
    # ------------------------------------------------------------------

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        json_body: Any | None = None,
        form_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
        user_agent: str | None = None,
        browser_impersonate: str | None = None,
        sec_fetch_site: str = "same-origin",
    ) -> dict[str, Any] | list[Any] | str | int | float | bool | None:
        has_body = json_body is not None or form_body is not None
        merged_headers = self._build_headers(
            method=method,
            headers=headers,
            user_agent=user_agent,
            browser_impersonate=browser_impersonate,
            has_body=has_body,
            sec_fetch_site=sec_fetch_site,
        )
        response = self._dispatch(
            method=method,
            url=url,
            headers=merged_headers,
            cookies=cookies or {},
            json_body=json_body,
            form_body=form_body,
            params=params,
            proxy_url=proxy_url,
            browser_impersonate=browser_impersonate,
        )
        return self._decode_response(response=response, url=url)

    def request_text(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        form_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
        user_agent: str | None = None,
        browser_impersonate: str | None = None,
        sec_fetch_site: str = "same-origin",
    ) -> str:
        has_body = form_body is not None
        merged_headers = self._build_headers(
            method=method,
            headers=headers,
            user_agent=user_agent,
            browser_impersonate=browser_impersonate,
            has_body=has_body,
            sec_fetch_site=sec_fetch_site,
        )
        response = self._dispatch(
            method=method,
            url=url,
            headers=merged_headers,
            cookies=cookies or {},
            json_body=None,
            form_body=form_body,
            params=params,
            proxy_url=proxy_url,
            browser_impersonate=browser_impersonate,
        )
        self._ensure_success(response=response, url=url)
        return str(getattr(response, "text", ""))

    def request_bytes(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        form_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
        user_agent: str | None = None,
        browser_impersonate: str | None = None,
        sec_fetch_site: str = "same-origin",
    ) -> bytes:
        has_body = form_body is not None
        merged_headers = self._build_headers(
            method=method,
            headers=headers,
            user_agent=user_agent,
            browser_impersonate=browser_impersonate,
            has_body=has_body,
            sec_fetch_site=sec_fetch_site,
        )
        response = self._dispatch(
            method=method,
            url=url,
            headers=merged_headers,
            cookies=cookies or {},
            json_body=None,
            form_body=form_body,
            params=params,
            proxy_url=proxy_url,
            browser_impersonate=browser_impersonate,
        )
        self._ensure_success(response=response, url=url)
        return bytes(getattr(response, "content", b""))

    # ------------------------------------------------------------------
    # Header construction
    # ------------------------------------------------------------------

    def _resolve_profile(self, browser_impersonate: str | None) -> BrowserProfile:
        """Look up the BrowserProfile for a given impersonate string."""
        profile_id = resolve_browser_impersonate(
            browser_impersonate or self.settings.browser_impersonate
        )
        return AVAILABLE_BROWSER_PROFILES[profile_id]

    @staticmethod
    def _pop_header(d: dict[str, str], *names: str) -> str | None:
        """Case-insensitive pop of the first matching key from a header dict."""
        for name in names:
            for key in list(d.keys()):
                if key.lower() == name.lower():
                    return d.pop(key)
        return None

    def _build_headers(
        self,
        *,
        method: str,
        headers: dict[str, str] | None,
        user_agent: str | None,
        browser_impersonate: str | None,
        has_body: bool = False,
        sec_fetch_site: str = "same-origin",
    ) -> dict[str, str]:
        """Build a Chrome-compliant ordered header dict.

        Header order follows Chrome's HTTP/2 frame ordering as captured via
        packet inspection (Charles Proxy / Wireshark):

        1. sec-ch-ua group (Chrome/Edge only – low-entropy Client Hints)
        2. content-type (body requests only)
        3. user-agent
        4. accept
        5. origin (body requests; or when caller provides it explicitly)
        6. caller-provided custom headers (Authorization, X-Requested-With …)
        7. sec-fetch-site / sec-fetch-mode / sec-fetch-dest
        8. referer
        9. accept-encoding
        10. accept-language
        11. priority  (Chrome/Edge 119+, XHR/fetch requests)
        """
        profile = self._resolve_profile(browser_impersonate)
        ua = (user_agent or "").strip() or profile.user_agent

        # Work on a mutable copy of caller headers; pop positionally-sensitive
        # keys so we can place them at the right positions ourselves.
        caller: dict[str, str] = {k: v for k, v in (headers or {}).items() if v}
        pop = self._pop_header  # shorthand

        accept       = pop(caller, "Accept")       or "application/json, text/plain, */*"
        content_type = pop(caller, "Content-Type")
        origin       = pop(caller, "Origin")
        referer      = pop(caller, "Referer")      or self.settings.bigmodel_referer
        accept_lang  = pop(caller, "Accept-Language") or self.settings.default_language

        # Content-Type: only include when there is a request body.
        # Callers may already provide a specific type (e.g. form-urlencoded).
        if has_body and not content_type:
            content_type = "application/json;charset=utf-8"

        # Origin: browsers send it on body (POST/PUT …) requests.
        if not origin and has_body:
            origin = self.settings.bigmodel_origin

        merged: dict[str, str] = {}

        # ── 1. Chrome / Edge Client Hints (sec-ch-ua group) ──────────────
        # These are "low-entropy" hints that Chrome sends by default on every
        # HTTPS request without needing an Accept-CH response header.
        # Firefox and Safari do NOT send these at all.
        if profile.sec_ch_ua:
            merged["sec-ch-ua"] = profile.sec_ch_ua
            merged["sec-ch-ua-mobile"] = "?0"
            merged["sec-ch-ua-platform"] = f'"{profile.sec_ch_ua_platform}"'

        # ── 2. Content-Type ───────────────────────────────────────────────
        if content_type:
            merged["Content-Type"] = content_type

        # ── 3. User-Agent ─────────────────────────────────────────────────
        merged["User-Agent"] = ua

        # ── 4. Accept ─────────────────────────────────────────────────────
        merged["Accept"] = accept

        # ── 5. Origin ─────────────────────────────────────────────────────
        if origin:
            merged["Origin"] = origin

        # ── 6. Remaining custom caller headers ────────────────────────────
        # (Authorization, Bigmodel-Organization, X-Requested-With, etc.)
        merged.update(caller)

        # ── 7. Sec-Fetch metadata (browser-injected, always present) ──────
        merged["Sec-Fetch-Site"] = sec_fetch_site
        merged["Sec-Fetch-Mode"] = "cors"
        merged["Sec-Fetch-Dest"] = "empty"

        # ── 8. Referer ────────────────────────────────────────────────────
        if referer:
            merged["Referer"] = referer

        # ── 9. Accept-Encoding ────────────────────────────────────────────
        # Chrome 120+ advertises zstd in addition to gzip/deflate/br.
        merged["Accept-Encoding"] = "gzip, deflate, br, zstd"

        # ── 10. Accept-Language ───────────────────────────────────────────
        merged["Accept-Language"] = accept_lang

        # ── 11. Priority (RFC 9218, Chrome/Edge 119+) ─────────────────────
        # XHR / fetch: urgency=1, incremental
        if profile.family in ("chrome", "edge"):
            merged["priority"] = "u=1, i"

        return merged

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        cookies: dict[str, str],
        json_body: Any | None,
        form_body: dict[str, Any] | None,
        params: dict[str, Any] | None,
        proxy_url: str | None,
        browser_impersonate: str | None,
    ):
        if json_body is not None and form_body is not None:
            raise UpstreamRequestError(
                "HTTP 请求体配置冲突",
                details={"url": url, "reason": "json_body and form_body are mutually exclusive"},
            )
        if curl_requests is not None:
            session = curl_requests.Session(trust_env=False)
            try:
                kwargs: dict[str, Any] = {
                    "method": method.upper(),
                    "url": url,
                    "headers": headers,
                    "cookies": cookies,
                    "params": params,
                    "timeout": self.settings.request_timeout_seconds,
                    "allow_redirects": True,
                    "impersonate": resolve_transport_impersonate(
                        browser_impersonate or self.settings.browser_impersonate,
                    ),
                }
                if json_body is not None:
                    kwargs["json"] = json_body
                if form_body is not None:
                    kwargs["data"] = form_body
                effective_proxy = proxy_url or self.settings.fallback_proxy_url
                if effective_proxy:
                    kwargs["proxies"] = {"http": effective_proxy, "https": effective_proxy}
                else:
                    kwargs["proxies"] = {"all": ""}
                return session.request(**kwargs)
            except Exception as exc:
                raise UpstreamRequestError(
                    "上游请求失败",
                    details={"transport": self.transport_name, "url": url, "reason": str(exc)},
                ) from exc
            finally:
                session.close()

        try:
            kwargs = {
                "method": method.upper(),
                "url": url,
                "headers": headers,
                "cookies": cookies,
                "params": params,
            }
            if json_body is not None:
                kwargs["json"] = json_body
            if form_body is not None:
                kwargs["data"] = form_body
            client_kwargs: dict[str, Any] = {
                "timeout": self.settings.request_timeout_seconds,
                "follow_redirects": True,
                "trust_env": False,
            }
            effective_proxy = proxy_url or self.settings.fallback_proxy_url
            if effective_proxy:
                client_kwargs["proxy"] = effective_proxy
            with httpx.Client(**client_kwargs) as client:
                return client.request(**kwargs)
        except Exception as exc:
            raise UpstreamRequestError(
                "上游请求失败",
                details={"transport": self.transport_name, "url": url, "reason": str(exc)},
            ) from exc

    # ------------------------------------------------------------------
    # Response helpers
    # ------------------------------------------------------------------

    def _decode_response(self, *, response: Any, url: str):
        self._ensure_success(response=response, url=url)
        try:
            payload = response.json()
        except Exception as exc:
            raise UpstreamRequestError(
                "上游返回了非 JSON 数据",
                details={
                    "transport": self.transport_name,
                    "url": url,
                    "status_code": getattr(response, "status_code", "unknown"),
                    "body_preview": getattr(response, "text", "")[:500],
                },
            ) from exc
        return payload

    def _ensure_success(self, *, response: Any, url: str) -> None:
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code < 400:
            return
        body_preview = str(getattr(response, "text", ""))[:500]
        raise UpstreamRequestError(
            "上游接口返回错误",
            details={"url": url, "status_code": status_code, "body_preview": body_preview},
        )

    def _extract_message(self, payload: Any) -> str:
        if isinstance(payload, dict):
            for key in ("message", "msg", "error", "detail"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        if isinstance(payload, str):
            return payload
        return ""
