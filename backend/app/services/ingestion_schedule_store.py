"""Persists nightly ingestion schedule config to a local YAML file.

Stored at backend/config/ingestion_schedule.yaml (gitignored).
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import yaml

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "config" / "ingestion_schedule.yaml"

_DEFAULTS: dict = {
    "enabled": False,
    "time": "02:00",
}


class IngestionScheduleStore:
    """Thread-safe store for ingestion schedule settings."""

    def __init__(self, path: Path = _DEFAULT_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: dict = dict(_DEFAULTS)
        if self._path.exists():
            self._load()

    def _load(self) -> None:
        try:
            raw = yaml.safe_load(self._path.read_text()) or {}
            with self._lock:
                for k in _DEFAULTS:
                    if k in raw:
                        self._data[k] = raw[k]
        except Exception:
            pass

    def get(self) -> dict:
        with self._lock:
            return dict(self._data)

    def set(self, enabled: bool, time: str) -> None:
        with self._lock:
            candidate = dict(self._data)
            candidate["enabled"] = bool(enabled)
            candidate["time"] = time
            self._save_locked(candidate)
            self._data = candidate

    def _save_locked(self, candidate: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".yaml.tmp")
        try:
            tmp.write_text(yaml.dump(candidate, default_flow_style=False), encoding="utf-8")
            os.replace(tmp, self._path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def _save(self) -> None:
        with self._lock:
            self._save_locked(self._data)


_store_path = Path(
    os.getenv("BAMENDJOU_SCHEDULE_PATH", str(_DEFAULT_PATH))
)
ingestion_schedule_store = IngestionScheduleStore(path=_store_path)
