from __future__ import annotations

import os
import stat
import threading
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "config" / "local_credentials.yaml"

_SENSITIVE_KEYS = {"token", "apiToken", "api_token", "password", "secret", "secret_key", "client_secret", "refresh_token"}

# Broker slots that are blocked from live execution until manually enabled.
# Single source of truth — broker_router.py imports this rather than
# redefining it, so the "no live trading" invariant can't drift between files.
# Every recognized live broker key, whether or not an adapter exists for it
# yet — this way a newly-added live adapter (e.g. TradierLiveAdapter) is
# blocked automatically by already being in this set.
LIVE_BROKER_KEYS = {"ibkr_live", "tradier_live", "alpaca_live", "tastytrade_live"}

_PRIVATE_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR  # 0600 — owner read/write only


def _restrict_permissions(path: Path) -> None:
    """Best-effort: this is a local single-user paper-trading tool, not a
    hardened secrets store — we deliberately do NOT encrypt these values.
    Restricting to owner-only is a cheap, meaningful reduction in exposure
    (e.g. other local accounts, backup tools) without key-management overhead.
    """
    try:
        os.chmod(path, _PRIVATE_FILE_MODE)
    except OSError:
        pass  # best-effort; never block credential save/load on this


def _mask(value: str) -> str:
    if not value or len(value) <= 4:
        return "****"
    return "*" * (len(value) - 4) + value[-4:]


def _mask_dict(d: dict) -> dict:
    return {k: _mask(v) if k in _SENSITIVE_KEYS and isinstance(v, str) else v for k, v in d.items()}


class CredentialStore:
    """Thread-safe in-memory credential store backed by a local gitignored YAML file.

    Security note: credentials are persisted to `local_credentials.yaml`
    UNENCRYPTED — `_mask()` below only redacts values in API responses, the
    on-disk file itself is plaintext. This is an accepted risk under the
    explicit assumption that this app runs single-user on a trusted local
    machine, never a shared or internet-exposed host. If that assumption
    ever changes, this needs real encryption-at-rest (e.g. an OS keychain
    or a passphrase-derived key) before broader deployment.
    """

    def __init__(self, path: Path | None = _DEFAULT_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {
            "ibkr_live":     {"base_url": "https://localhost:5000/v1/api", "account_id": ""},
            "ibkr_paper":    {"base_url": "https://localhost:7499/v1/api", "account_id": ""},
            "tradier_live":  {"token": "", "account_id": ""},
            "tradier_paper": {"token": "", "account_id": ""},
            "alpaca_live":   {"key_id": "", "secret_key": "", "base_url": "https://api.alpaca.markets"},
            "alpaca_paper":  {"key_id": "", "secret_key": "", "base_url": "https://paper-api.alpaca.markets"},
            "tastytrade_live":  {"client_secret": "", "refresh_token": "", "account_id": ""},
            "tastytrade_paper": {"client_secret": "", "refresh_token": "", "account_id": ""},
        }
        if self._path and self._path.exists():
            self.load()

    def load(self) -> None:
        if not self._path:
            return
        if self._path.exists():
            # Tighten permissions on a file that may already exist from before
            # this hardening shipped — save() below keeps new writes at 0o600,
            # but this covers files that predate that fix. load() runs far more
            # often than just app start: build_router_from_credentials() in
            # broker_router.py calls it on every broker order-placement request
            # and every auto-trade cycle, so this is a cheap, idempotent no-op
            # on an already-0o600 file, not a startup-only concern.
            os.chmod(self._path, 0o600)
        try:
            raw = yaml.safe_load(self._path.read_text()) or {}
        except (yaml.YAMLError, OSError) as exc:
            import logging
            logging.getLogger(__name__).warning(
                "credential_store: failed to load %s (%s) — using defaults", self._path, exc
            )
            return
        _restrict_permissions(self._path)  # tighten perms on files predating this fix
        with self._lock:
            for k, v in raw.items():
                # Only merge known broker slots; ignore stray/legacy keys in the file
                # so load() mirrors the POST endpoint's key restriction.
                if isinstance(v, dict) and k in self._data:
                    self._data[k] = {**self._data[k], **v}

    def save(self) -> None:
        with self._lock:
            self._save_locked()

    def _save_locked(self) -> None:
        """Persist canonical state while the caller holds the writer lock."""
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".yaml.tmp")
        data_copy = {k: dict(v) for k, v in self._data.items()}
        tmp.write_text(yaml.dump(data_copy, default_flow_style=False))
        # Atomic replacement preserves the temporary inode's owner-only mode.
        _restrict_permissions(tmp)
        os.replace(tmp, self._path)

    def set_and_save(self, key: str, values: dict) -> None:
        """Merge one slot and persist it atomically with respect to other writers."""
        with self._lock:
            previous = self._data
            self._data = {**previous, key: {**previous.get(key, {}), **values}}
            try:
                self._save_locked()
            except Exception:
                self._data = previous
                raise

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


# BAMENDJOU_CREDS_PATH selects where this singleton persists to. There are
# three distinct cases, and the empty one is the reason this is spelled out:
#   unset     -> the real config/local_credentials.yaml
#   ""        -> None, i.e. no file persistence at all (save() and load() both
#                short-circuit on `if not self._path`)
#   a path    -> that path
#
# The empty-string case used to collapse into the default through a falsy
# check, which did the exact OPPOSITE of what setting it to "" asks for:
# a caller opting out of persistence got the singleton aimed at the real
# credentials file, where save() would overwrite the developer's actual broker
# tokens. Distinguish "unset" from "set to empty" explicitly.
_env_creds_path = os.getenv("BAMENDJOU_CREDS_PATH")
if _env_creds_path is None:
    _creds_path: Path | None = _DEFAULT_PATH
elif _env_creds_path == "":
    _creds_path = None
else:
    _creds_path = Path(_env_creds_path)

credential_store = CredentialStore(path=_creds_path)
