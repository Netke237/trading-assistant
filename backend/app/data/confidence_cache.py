from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_store: dict[str, dict] = {}

_TTL_SECONDS = 7 * 24 * 3600  # weekly


def cache_key(symbol: str, direction: str, horizon: str, atr_mult: float = 1.5) -> str:
    # atr_mult is part of the key: changing it changes the computed confidence,
    # so cached results under a different multiple must not be reused.
    return f"{symbol.upper()}|{direction.lower()}|{horizon.lower()}|{float(atr_mult):g}"


def set_cached(key: str, value: dict) -> None:
    with _lock:
        _store[key] = {**value, "_ts": time.time()}


def get_cached(key: str) -> dict | None:
    with _lock:
        v = _store.get(key)
        if v is None:
            return None
        if time.time() - v.get("_ts", 0) > _TTL_SECONDS:
            del _store[key]
            return None
        return {k: val for k, val in v.items() if k != "_ts"}


def clear_cache() -> None:
    with _lock:
        _store.clear()
