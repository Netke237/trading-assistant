"""Cached tastytrade OAuth Session, one per credential slot.

tastytrade session tokens last 15 minutes but the SDK (tastytrade>=12.0.0)
auto-refreshes them transparently on every call using the refresh token,
which never expires. That means a Session object, once built, can be reused
for the lifetime of the process — there is no daily re-login step, unlike
IBKR's Client Portal Gateway (see backend/app/data/ibkr.py's module
docstring for that contrast).

is_test is always False here: tastytrade's sandbox/cert environment resets
every 24 hours and always serves 15-minute-delayed data (confirmed against
https://developer.tastytrade.com/sandbox/), so it is not a fit for Kenneth's
persistent paper-trading or IV-data use — "paper trading account" at
tastytrade is a real, funded-adjacent production account, distinct from the
sandbox environment.
"""
from __future__ import annotations

import threading

from tastytrade import Session

from app.services.credential_store import credential_store

_SESSION_CACHE: dict[str, Session] = {}
_lock = threading.Lock()


def get_session(slot: str) -> Session | None:
    """Return a cached Session for the given credential slot
    ("tastytrade_paper" or "tastytrade_live"), or None if unconfigured."""
    with _lock:
        cached = _SESSION_CACHE.get(slot)
        if cached is not None:
            return cached

    creds = credential_store.get(slot) or {}
    client_secret = (creds.get("client_secret") or "").strip()
    refresh_token = (creds.get("refresh_token") or "").strip()
    if not client_secret or not refresh_token:
        return None

    session = Session(client_secret, refresh_token, is_test=False)

    with _lock:
        _SESSION_CACHE[slot] = session
    return session


def clear_cache() -> None:
    """Drop cached sessions — call after credentials are updated via the
    /settings/credentials endpoint so the next call rebuilds with fresh creds."""
    with _lock:
        _SESSION_CACHE.clear()
