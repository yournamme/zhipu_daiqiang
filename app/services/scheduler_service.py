"""Background scheduler for timed payment flow execution."""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.errors import GlmDeskError
from app.services.account_state import get_account_state_service, utc_now_iso
from app.services.payment_service import get_payment_service

logger = logging.getLogger(__name__)
try:
    SCHEDULER_TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:  # pragma: no cover - Windows without tzdata
    SCHEDULER_TZ = None


class SchedulerService:
    """Run account payment flows at configured local times."""

    def __init__(self) -> None:
        self.state_service = get_account_state_service()
        self.payment_service = get_payment_service()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._running_accounts: set[str] = set()
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="glm-desk-scheduler", daemon=True)
        self._thread.start()
        threading.Thread(target=self.check_cached_accounts_once, name="glm-desk-account-check", daemon=True).start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.poll_once()
            except Exception as exc:  # pragma: no cover - defensive scheduler guard
                logger.exception("scheduler poll failed: %s", exc)
            self._stop_event.wait(1)

    def poll_once(self) -> None:
        now = datetime.now(SCHEDULER_TZ) if SCHEDULER_TZ is not None else datetime.now().astimezone()
        current_hms = now.strftime("%H:%M:%S")
        current_date = now.strftime("%Y-%m-%d")
        for public_account in self.state_service.list_accounts():
            if not public_account.schedule_enabled or not public_account.scheduled_start_time:
                continue
            if public_account.scheduled_start_time > current_hms:
                continue
            account = self.state_service.get_account(public_account.id)
            if self._already_ran_today(account, current_date):
                continue
            with self._lock:
                if account.id in self._running_accounts:
                    continue
                self._running_accounts.add(account.id)
            account.last_scheduled_run_at = utc_now_iso()
            account.last_schedule_status = "running"
            account.last_schedule_message = ""
            self.state_service.update_account(account)
            threading.Thread(
                target=self._run_account_flow,
                args=(account.id,),
                name=f"glm-desk-run-{account.id}",
                daemon=True,
            ).start()

    def check_cached_accounts_once(self) -> None:
        for public_account in self.state_service.list_accounts():
            account_id = public_account.id
            with self._lock:
                if account_id in self._running_accounts:
                    continue
                self._running_accounts.add(account_id)
            try:
                self.payment_service.bootstrap_account(account_id)
                self.state_service.set_account_status(
                    account_id,
                    status="valid",
                    message="启动检查通过",
                )
            except GlmDeskError as exc:
                self.state_service.set_account_status(
                    account_id,
                    status="expired",
                    message=exc.message,
                )
            except Exception as exc:  # pragma: no cover - defensive startup check
                self.state_service.set_account_status(
                    account_id,
                    status="error",
                    message=str(exc),
                )
                logger.exception("account startup check failed for %s: %s", account_id, exc)
            finally:
                with self._lock:
                    self._running_accounts.discard(account_id)

    def _already_ran_today(self, account, current_date: str) -> bool:
        raw = (account.last_scheduled_run_at or "").strip()
        return raw.startswith(current_date)

    def _run_account_flow(self, account_id: str) -> None:
        try:
            task = self.payment_service.run_payment_flow(account_id)
            account = self.state_service.get_account(account_id)
            account.last_schedule_status = "success"
            account.last_schedule_message = f"生成二维码成功：{task.biz_id}"
            account.account_status = "valid"
            account.account_status_message = "最近一次执行成功"
            account.account_checked_at = utc_now_iso()
            self.state_service.update_account(account)
        except Exception as exc:
            account = self.state_service.get_account(account_id)
            account.last_schedule_status = "failed"
            account.last_schedule_message = str(exc)
            account.account_status = "error"
            account.account_status_message = str(exc)
            account.account_checked_at = utc_now_iso()
            self.state_service.update_account(account)
            logger.exception("scheduled account flow failed for %s: %s", account_id, exc)
        finally:
            with self._lock:
                self._running_accounts.discard(account_id)


_scheduler_service: SchedulerService | None = None


def get_scheduler_service() -> SchedulerService:
    global _scheduler_service
    if _scheduler_service is None:
        _scheduler_service = SchedulerService()
    return _scheduler_service
