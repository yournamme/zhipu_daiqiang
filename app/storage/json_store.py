"""Small atomic JSON file store helpers."""

from __future__ import annotations

import copy
import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

try:
    import orjson
except ImportError:  # pragma: no cover - optional fallback
    orjson = None


class JsonFileStore:
    """Thread-safe JSON file persistence with atomic writes."""

    _replace_retry_delays = (0.05, 0.1, 0.2, 0.35, 0.5)

    def __init__(self, path: Path, default_factory: Callable[[], Any]) -> None:
        self.path = path
        self.default_factory = default_factory
        self._lock = threading.Lock()

    def read(self) -> Any:
        with self._lock:
            return self._read_unlocked()

    def write(self, payload: Any) -> Any:
        with self._lock:
            self._write_unlocked(payload)
            return payload

    def update(self, updater: Callable[[Any], Any]) -> Any:
        with self._lock:
            current = self._read_unlocked()
            updated = updater(current)
            self._write_unlocked(updated)
            return updated

    def _read_unlocked(self) -> Any:
        if not self.path.exists():
            return copy.deepcopy(self.default_factory())

        raw = self.path.read_bytes()
        if not raw.strip():
            return copy.deepcopy(self.default_factory())
        if orjson is not None:
            return orjson.loads(raw)
        return json.loads(raw.decode("utf-8"))

    def _write_unlocked(self, payload: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        if orjson is not None:
            serialized = orjson.dumps(payload, option=orjson.OPT_INDENT_2) + b"\n"
            temp_path.write_bytes(serialized)
        else:  # pragma: no cover - only used without orjson
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        self._replace_with_retry(temp_path)

    def _replace_with_retry(self, temp_path: Path) -> None:
        last_error: PermissionError | None = None
        for delay in (*self._replace_retry_delays, 0):
            try:
                temp_path.replace(self.path)
                return
            except PermissionError as exc:
                last_error = exc
                if delay <= 0:
                    break
                time.sleep(delay)
        if last_error is not None:
            raise PermissionError(
                f"{last_error}. atomic replace failed after retries for {self.path}"
            ) from last_error
