"""Persists daily S&P 500 liquidity update schedule to a local YAML file."""
from __future__ import annotations

import os
import threading
from pathlib import Path

import yaml

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "config" / "sp500_schedule.yaml"

_DEFAULTS: dict = {
    "enabled": False,
    "time": "04:00",
}


class Sp500ScheduleStore:
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
            self._data["enabled"] = bool(enabled)
            self._data["time"] = time
        self._save()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".yaml.tmp")
        with self._lock:
            data_copy = dict(self._data)
        tmp.write_text(yaml.dump(data_copy, default_flow_style=False))
        os.replace(tmp, self._path)


_store_path = Path(os.getenv("BAMENDJOU_SP500_SCHEDULE_PATH", str(_DEFAULT_PATH)))
sp500_schedule_store = Sp500ScheduleStore(path=_store_path)
