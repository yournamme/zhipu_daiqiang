"""Tencent TDC collector executed in a Node VM browser shim."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from app.browser_profiles import resolve_user_agent
from app.clients.fingerprint_http import FingerprintHttpClient
from app.config import PROJECT_ROOT, Settings, get_settings
from app.errors import BadRequestError
from app.models import AccountRecord

@dataclass(frozen=True)
class TdcCollectResult:
    """TDC output needed by cap_union_new_verify."""

    collect_raw: str
    collect: str
    tlg: int
    eks: str
    tokenid: str
    info: dict[str, Any]
    tdc_path: str
    tdc_url: str

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


class TencentTdcService:
    """Fetch dynamic TDC script and collect browser fingerprint payload."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        http_client: FingerprintHttpClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.http_client = http_client or FingerprintHttpClient(self.settings)
        self.cache_dir = self.settings.data_dir / "tdc_cache"
        self.runner_path = PROJECT_ROOT / "app" / "services" / "tdc_vm_runner.cjs"

    def status_payload(self) -> dict[str, Any]:
        runner_exists = self.runner_path.exists()
        node_status = self._node_status_payload()
        problems: list[str] = []
        if not runner_exists:
            problems.append("tdc_vm_runner.cjs 不存在")
        if not node_status["available"]:
            problems.append(str(node_status.get("message") or "Node.js 命令不可用"))
        return {
            "node": self.settings.tencent_captcha_node,
            "node_resolved": node_status.get("resolved"),
            "node_version": node_status.get("version"),
            "available": runner_exists and bool(node_status["available"]),
            "problems": problems,
            "runner": str(self.runner_path),
            "runner_exists": runner_exists,
            "cache_dir": str(self.cache_dir),
        }

    def _node_status_payload(self) -> dict[str, Any]:
        node_command = self.settings.tencent_captcha_node
        resolved = shutil.which(node_command) or node_command
        try:
            completed = subprocess.run(
                [node_command, "-v"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=5,
                check=False,
            )
        except FileNotFoundError:
            return {
                "available": False,
                "resolved": resolved,
                "message": f"Node.js 命令不可用：{node_command}",
            }
        except subprocess.TimeoutExpired:
            return {
                "available": False,
                "resolved": resolved,
                "message": f"Node.js 命令超时：{node_command}",
            }
        version = (completed.stdout or completed.stderr or "").strip()
        if completed.returncode != 0:
            return {
                "available": False,
                "resolved": resolved,
                "version": version,
                "message": f"Node.js 版本检测失败：{version or completed.returncode}",
            }
        return {"available": True, "resolved": resolved, "version": version}

    def collect_for_challenge(
        self,
        account: AccountRecord,
        raw_challenge: dict[str, Any],
    ) -> TdcCollectResult:
        tdc_path = self.extract_tdc_path(raw_challenge)
        if not tdc_path:
            raise BadRequestError("challenge 里没有 tdc_path，没法生成 collect/eks")

        user_agent = resolve_user_agent(account.user_agent, account.browser_impersonate)
        tdc_url = self._build_tdc_url(tdc_path)
        tdc_code = self._fetch_script(
            tdc_url,
            account=account,
            user_agent=user_agent,
        )
        ft_code = self._fetch_ft_script(account=account, user_agent=user_agent)
        result = self._run_vm(
            tdc_code=tdc_code,
            ft_code=ft_code,
            account=account,
            user_agent=user_agent,
        )

        return TdcCollectResult(
            collect_raw=str(result.get("collectRaw") or ""),
            collect=str(result.get("collect") or ""),
            tlg=int(result.get("tlg") or 0),
            eks=str(result.get("eks") or ""),
            tokenid=str(result.get("tokenid") or ""),
            info=result.get("info") if isinstance(result.get("info"), dict) else {},
            tdc_path=tdc_path,
            tdc_url=tdc_url,
        )

    def extract_tdc_path(self, raw_challenge: dict[str, Any]) -> str:
        data = raw_challenge.get("data") if isinstance(raw_challenge, dict) else {}
        cfg = (data or {}).get("comm_captcha_cfg") if isinstance(data, dict) else {}
        return str((cfg or {}).get("tdc_path") or "").strip()

    def _fetch_script(
        self,
        url: str,
        *,
        account: AccountRecord,
        user_agent: str,
    ) -> str:
        cache_path = self._cache_path(url)
        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8")

        code = self.http_client.request_text(
            "GET",
            url,
            headers={
                "Accept": "application/javascript, text/javascript, */*; q=0.01",
                "Referer": self.settings.tencent_captcha_entry_url,
            },
            proxy_url=account.proxy_url or None,
            user_agent=user_agent or None,
            browser_impersonate=account.browser_impersonate or None,
            sec_fetch_site="cross-site",
        )
        if "<html" in code[:500].lower() or len(code) < 1000:
            raise BadRequestError(
                "tdc.js 内容看着不对劲，别拿空壳去跑 verify。",
                details={"url": url, "body_preview": code[:200]},
            )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(code, encoding="utf-8")
        return code

    def _fetch_ft_script(self, *, account: AccountRecord, user_agent: str) -> str:
        url = f"{self.settings.tencent_captcha_domain}/ft.js"
        cache_path = self._cache_path(url)
        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8")
        code = self.http_client.request_text(
            "GET",
            url,
            headers={
                "Accept": "application/javascript, text/javascript, */*; q=0.01",
                "Referer": self.settings.tencent_captcha_entry_url,
            },
            proxy_url=account.proxy_url or None,
            user_agent=user_agent or None,
            browser_impersonate=account.browser_impersonate or None,
            sec_fetch_site="cross-site",
        )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(code, encoding="utf-8")
        return code

    def _run_vm(
        self,
        *,
        tdc_code: str,
        ft_code: str,
        account: AccountRecord,
        user_agent: str,
    ) -> dict[str, Any]:
        if not self.runner_path.exists():
            raise BadRequestError("TDC VM runner 不存在，项目文件可能没打全")

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = tempfile.mkdtemp(dir=self.cache_dir)
        try:
            temp_path = Path(temp_dir)
            tdc_path = temp_path / "tdc.js"
            ft_path = temp_path / "ft.js"
            input_path = temp_path / "input.json"
            tdc_path.write_text(tdc_code, encoding="utf-8")
            ft_path.write_text(ft_code, encoding="utf-8")
            input_path.write_text(
                json.dumps(
                    {
                        "tdcCodePath": str(tdc_path),
                        "ftCodePath": str(ft_path),
                        "entryUrl": self.settings.tencent_captcha_entry_url,
                        "userAgent": user_agent,
                        "cookieHeader": account.cookie_header,
                        "setData": {"refreshcnt": 0},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            try:
                completed = subprocess.run(
                    [self.settings.tencent_captcha_node, str(self.runner_path), str(input_path)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=max(self.settings.request_timeout_seconds, 5),
                    check=False,
                )
            except FileNotFoundError as exc:
                raise BadRequestError(
                    "TDC VM 执行失败：Node.js 命令不可用，请检查 TENCENT_CAPTCHA_NODE 或系统 PATH",
                    details={
                        "node_command": self.settings.tencent_captcha_node,
                        "runner_path": str(self.runner_path),
                        "reason": str(exc),
                    },
                ) from exc
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        if completed.returncode != 0:
            raise BadRequestError(
                "TDC VM 执行失败",
                details={
                    "returncode": completed.returncode,
                    "stderr": completed.stderr[-800:],
                    "stdout": completed.stdout[-300:],
                },
            )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise BadRequestError(
                "TDC VM 输出不是合法 JSON",
                details={"stdout_preview": completed.stdout[:500]},
            ) from exc
        if not isinstance(payload, dict) or not payload.get("collectRaw") or not payload.get("eks"):
            raise BadRequestError(
                "TDC VM 没产出 collect/eks",
                details={"payload": payload},
            )
        return payload

    def _build_tdc_url(self, tdc_path: str) -> str:
        if tdc_path.startswith("http://") or tdc_path.startswith("https://"):
            return tdc_path
        return urljoin(f"{self.settings.tencent_captcha_domain}/", tdc_path.lstrip("/"))

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        return self.cache_dir / f"{digest}.js"


@lru_cache(maxsize=1)
def get_tdc_service() -> TencentTdcService:
    """Get the shared Tencent TDC service."""
    return TencentTdcService()
