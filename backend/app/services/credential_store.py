from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "config" / "local_credentials.yaml"

_SENSITIVE_KEYS = {"token", "apiToken", "api_token", "password", "secret"}


def _mask(value: str) -> str:
    if not value or len(value) <= 4:
        return "****"
    return "*" * (len(value) - 4) + value[-4:]


def _mask_dict(d: dict) -> dict:
    return {k: _mask(v) if k in _SENSITIVE_KEYS and isinstance(v, str) else v for k, v in d.items()}


class CredentialStore:
    """Thread-safe in-memory credential store backed by a local gitignored YAML file."""

    def __init__(self, path: Path | None = _DEFAULT_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {
            "ibkr_live":     {"base_url": "https://localhost:5000/v1/api", "account_id": ""},
            "ibkr_paper":    {"base_url": "https://localhost:7499/v1/api", "account_id": ""},
            "tradier_live":  {"token": "", "account_id": ""},
            "tradier_paper": {"token": "", "account_id": ""},
        }
        if self._path and self._path.exists():
            self.load()

    def load(self) -> None:
        if not self._path:
            return
        with self._lock:
            raw = yaml.safe_load(self._path.read_text()) or {}
            for k, v in raw.items():
                if isinstance(v, dict):
                    self._data[k] = {**self._data.get(k, {}), **v}

    def save(self) -> None:
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._path.write_text(yaml.dump(self._data, default_flow_style=False))

    def get(self, key: str) -> dict | None:
        with self._lock:
            return dict(self._data[key]) if key in self._data else None

    def set(self, key: str, values: dict) -> None:
        with self._lock:
            self._data[key] = {**self._data.get(key, {}), **values}

    def get_masked(self, key: str) -> dict | None:
        d = self.get(key)
        return _mask_dict(d) if d is not None else None

    def all_masked(self) -> dict[str, dict]:
        with self._lock:
            return {k: _mask_dict(dict(v)) for k, v in self._data.items()}


import os as _os
_creds_path = Path(_os.getenv("BAMENDJOU_CREDS_PATH", str(_DEFAULT_PATH))) if _os.getenv("BAMENDJOU_CREDS_PATH") else _DEFAULT_PATH
credential_store = CredentialStore(path=_creds_path)
