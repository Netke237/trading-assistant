"""Persists daily strategy tuning (WFO) schedule to a local YAML file."""
from __future__ import annotations

import os
import threading
from pathlib import Path

import yaml

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "config" / "tuning_schedule.yaml"

_DEFAULTS: dict = {
    "enabled": False,
    "time": "05:00",
    "days_of_week": [5],  # Saturday-only — compute-heavy, weekly cadence (Part 0)
}


class TuningScheduleStore:
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

    def set(self, enabled: bool, time: str, days_of_week: list[int] | None = None) -> None:
        with self._lock:
            candidate = dict(self._data)
            candidate["enabled"] = bool(enabled)
            candidate["time"] = time
            if days_of_week is not None:
                candidate["days_of_week"] = list(days_of_week)
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


_store_path = Path(os.getenv("BAMENDJOU_TUNING_SCHEDULE_PATH", str(_DEFAULT_PATH)))
tuning_schedule_store = TuningScheduleStore(path=_store_path)
