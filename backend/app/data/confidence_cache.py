from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

_lock = threading.Lock()
_store: dict[str, dict] = {}

_TTL_SECONDS = 7 * 24 * 3600  # weekly

# Basis version of the bar-derived values cached here, appended to every key so
# a value computed on an older basis is never served (it simply misses and its
# row expires under the TTL; no migration, no delete). Bump it whenever the bars
# or the replay that produce a cached confidence change. It last moved to "b2"
# for TRADING-REVIEW-PHASE-C: T1 (historical_store._read_bars scales open/high/
# low by adj_factor like close) and T7 (the stock trigger honours
# trigger.setup_window_bars). stock_scan._backtest_key carries the same token.
BARS_BASIS_VERSION = "b2"

# L2 SQLite path — sits in backend/data/; overridable in tests via _DB_PATH.
_DB_PATH: str = str(Path(__file__).parent.parent.parent / "data" / "confidence_cache.db")


def cache_key(
    symbol: str,
    direction: str,
    horizon: str,
    atr_mult_target: float | None = None,
    atr_mult_stop: float | None = None,
    scoring_mode: str = "options",
) -> str:
    # atr_mult_target/atr_mult_stop are part of the key: changing either changes
    # the computed confidence, so cached results under a different pair must
    # not be reused. None means "no override" (compute_confidence uses the
    # per-horizon config's asymmetric values) and must key differently from any
    # explicit pair — those are genuinely different computations, not the same
    # thing spelled two ways. Settings/Step-3 expose this as a per-horizon
    # target/stop pair (see settingsStore.ts's ConfidenceGate.atrMult and
    # step-3-direction/page.tsx's confidence_atr_mult_target/_stop rows).
    target_key = "default" if atr_mult_target is None else f"{float(atr_mult_target):g}"
    stop_key = "default" if atr_mult_stop is None else f"{float(atr_mult_stop):g}"
    mult_key = f"{target_key}:{stop_key}"
    # scoring_mode is also part of the key: 'stock' and 'options' apply materially
    # different scoring rules, so a value computed under one mode must never be
    # served to a lookup under the other (Critical finding #4, 2026-07-15 audit).
    return (f"{symbol.upper()}|{direction.lower()}|{horizon.lower()}|{mult_key}|{scoring_mode.lower()}"
            f"|{BARS_BASIS_VERSION}")


# ── SQLite helpers ─────────────────────────────────────────────────────────────

def _init_db() -> None:
    """Create the SQLite table if it doesn't exist."""
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS confidence_cache (
                cache_key  TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                expires_at REAL NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()


def _warm_load() -> None:
    """On startup: load all non-expired DB rows into the in-memory store."""
    try:
        _init_db()
        now = time.time()
        conn = sqlite3.connect(_DB_PATH)
        try:
            rows = conn.execute(
                "SELECT cache_key, value, expires_at FROM confidence_cache WHERE expires_at > ?",
                (now,),
            ).fetchall()
            # Purge expired entries while the connection is open
            conn.execute("DELETE FROM confidence_cache WHERE expires_at <= ?", (now,))
            conn.commit()
        finally:
            conn.close()
        with _lock:
            for key, value_json, expires_at in rows:
                try:
                    parsed = json.loads(value_json)
                    # Re-add a synthetic _ts so get_cached TTL check works
                    parsed["_ts"] = expires_at - _TTL_SECONDS
                    _store[key] = parsed
                except Exception:
                    pass
    except Exception:
        pass  # Never block startup on cache failure


def _write_db(key: str, value: dict, expires_at: float) -> None:
    """Write or update one row in SQLite. Called from set_cached."""
    try:
        payload = {k: v for k, v in value.items() if k != "_ts"}
        conn = sqlite3.connect(_DB_PATH)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO confidence_cache VALUES (?, ?, ?)",
                (key, json.dumps(payload), expires_at),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass  # Never block a scan on cache write failure


# ── Public API ──────────────────────────────────────────────────────────────

async def set_cached(key: str, value: dict) -> None:
    now = time.time()
    expires_at = now + _TTL_SECONDS
    with _lock:
        _store[key] = {**value, "_ts": now}
    # _write_db is intentionally called outside _lock: SQLite has its own
    # write serialisation via file locking. For this cache (deterministic
    # confidence scores, weekly TTL, low write rate) last-writer-wins is safe.
    # Offloaded to a thread: this does synchronous disk I/O (open/write/commit/
    # close) and is called from async request handlers running concurrently
    # across up to ~500 symbols per scan — running it inline on the event loop
    # would stall every other concurrent request for the duration of each write.
    await asyncio.to_thread(_write_db, key, value, expires_at)


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
    try:
        conn = sqlite3.connect(_DB_PATH)
        try:
            conn.execute("DELETE FROM confidence_cache")
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


# Warm-load on module import (once per process).
_warm_load()
