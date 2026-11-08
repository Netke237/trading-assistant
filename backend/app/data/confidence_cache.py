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

# Serialises a guarded SQLite write (set_cached with bars_generation) against
# invalidate_symbol's SQLite DELETE (audit R2-F1): without it the DELETE can run
# between set_cached's memory write and its INSERT OR REPLACE, and the stale row
# returns on the next restart's _warm_load. Lock order: _db_lock, then _lock nested
# inside it, or _lock alone; never _lock then _db_lock, so the two cannot deadlock.
_db_lock = threading.Lock()

# Invalidation generations (audit R2-F1). A computation in flight across a refresh
# (bars read, then historical_store.refresh_adjustments evicts the symbol, then the
# computation calls set_cached) must not re-store the pre-refresh confidence for the
# whole TTL. invalidate_symbol stamps the symbol with a new generation; a writer
# captures generation() before reading its bars and passes it to set_cached, which
# drops the value when the symbol was invalidated after that capture. In memory on
# purpose: in-flight computations do not survive a restart, and the eviction already
# removed the persisted row.
_generation = 0
_symbol_generation: dict[str, int] = {}
# clear_cache() invalidates every symbol at once: it stamps this with a new
# generation, and a value whose bars_generation precedes it is dropped like one
# whose symbol was invalidated (TRADING-REVIEW-PHASE-C-HYGIENE T2).
_clear_generation = 0

_TTL_SECONDS = 7 * 24 * 3600  # weekly

# Basis version of the bar-derived values cached here, appended to every key so
# a value computed on an older basis is never served (it simply misses and its
# row expires under the TTL; no migration, no delete). Bump it whenever the bars
# or the replay that produce a cached confidence change. It moved to "b2"
# for TRADING-REVIEW-PHASE-C: T1 (historical_store._read_bars scales open/high/
# low by adj_factor like close) and T7 (the stock trigger honours
# trigger.setup_window_bars); b3 for STOCKS-HORIZON-P0A A4: the confidence
# replay counts non-overlapping fires; b4 for PROVIDER-FALLBACK-FORMING-BAR
# (#536): the Options DB-miss fallback no longer scores forming bars.
# stock_scan._backtest_key carries the same token.
BARS_BASIS_VERSION = "b4"

# L2 SQLite path — sits in backend/data/; overridable in tests via _DB_PATH.
# BAMENDJOU_CONFIDENCE_CACHE_DB (when set and non-empty) replaces the default.
# Read once here, before _warm_load() at the bottom of this module, which reads
# the file and deletes its expired rows. tests/conftest.py pins it to a session
# temp file so a test run can never touch the real cache (TRADING-REVIEW-PHASE-C-
# HYGIENE T1). Unset in production, so the default path is unchanged there.
_DB_PATH: str = (
    os.environ.get("BAMENDJOU_CONFIDENCE_CACHE_DB")
    or str(Path(__file__).parent.parent.parent / "data" / "confidence_cache.db")
)


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


# ── Invalidation rule ─────────────────────────────────────────────────────────
# One rule for "invalidated after generation g", shared by set_cached's memory check
# and _write_db_guarded's SQLite re-check so the two cannot drift. Both helpers below
# take NO lock: the caller must already hold _lock. _lock is a plain non-reentrant
# threading.Lock and both checks run inside it, so taking it here would hang. A public
# wrapper that needs the rule from outside _lock takes _lock around
# _invalidated_after_locked.

def _invalidated_after_locked(symbol: str, bars_generation: int) -> bool:
    """True when ``symbol`` (or the whole cache) was invalidated after
    ``bars_generation``. Caller holds _lock."""
    return max(_symbol_generation.get(symbol.upper(), 0), _clear_generation) > bars_generation


def _invalidated_after(key: str, bars_generation: int | None) -> bool:
    """The rule for a cache key (its symbol is the prefix before the first ``|``).
    None never counts as invalidated (the unconditional write). Caller holds _lock."""
    if bars_generation is None:
        return False
    return _invalidated_after_locked(key.split("|", 1)[0], bars_generation)


def _write_db_guarded(key: str, value: dict, expires_at: float,
                      bars_generation: int | None) -> None:
    """_write_db under _db_lock, dropped if the symbol (or the whole cache) was
    invalidated after ``bars_generation`` (re-checked here because invalidate_symbol
    or clear_cache may have run since set_cached's memory write). None keeps the
    unconditional write."""
    with _db_lock:
        with _lock:
            if _invalidated_after(key, bars_generation):
                return
        _write_db(key, value, expires_at)


# ── Public API ──────────────────────────────────────────────────────────────

def generation() -> int:
    """The current invalidation generation; capture it before reading the bars."""
    with _lock:
        return _generation


def invalidated_since(symbol: str, bars_generation: int) -> bool:
    """True when ``symbol`` (or the whole cache) was invalidated after
    ``bars_generation``: a value computed from bars read at that generation is
    pre-refresh and must not be stored. The same rule set_cached applies, for
    callers keeping their own caches (stock_scan's _BACKTEST_CACHE,
    TRADING-REVIEW-PHASE-C-HYGIENE T6). Takes _lock; never call it while holding it."""
    with _lock:
        return _invalidated_after_locked(symbol, bars_generation)


async def set_cached(key: str, value: dict, *, bars_generation: int | None = None) -> None:
    now = time.time()
    expires_at = now + _TTL_SECONDS
    with _lock:
        # Checked under the same lock as the write, so an invalidation cannot land
        # between the check and the store. None keeps the unconditional write.
        if _invalidated_after(key, bars_generation):
            return   # computed from bars read before this symbol's (or the cache's) last invalidation
        _store[key] = {**value, "_ts": now}
    # The SQLite write runs outside _lock (SQLite serialises writers via file
    # locking; between two writers of the same deterministic value last-writer-
    # wins is fine) but under _db_lock, with the generation re-checked inside it
    # (R2-F1). An invalidate_symbol landing after the memory write is then safe
    # either way: if its generation bump precedes the re-check, the write is
    # skipped; if it follows, the writer still holds _db_lock, so the
    # invalidation's DELETE waits and removes the row just written.
    # Offloaded to a thread: this does synchronous disk I/O (open/write/commit/
    # close) and is called from async request handlers running concurrently
    # across up to ~500 symbols per scan — running it inline on the event loop
    # would stall every other concurrent request for the duration of each write.
    await asyncio.to_thread(_write_db_guarded, key, value, expires_at, bars_generation)


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
    """Remove every cached confidence from memory and SQLite, and invalidate every
    computation in flight (a set_cached whose bars_generation precedes the clear is
    dropped, in memory and in SQLite), the whole-cache form of invalidate_symbol."""
    global _generation, _clear_generation
    with _lock:
        _generation += 1
        _clear_generation = _generation
        _store.clear()
    # Same lock order as invalidate_symbol: _lock is released before _db_lock is
    # taken. A guarded write that re-checks after the bump above skips; one already
    # past its re-check holds _db_lock, so this DELETE waits for its INSERT and then
    # removes it.
    try:
        with _db_lock:
            conn = sqlite3.connect(_DB_PATH)
            try:
                conn.execute("DELETE FROM confidence_cache")
                conn.commit()
            finally:
                conn.close()
    except Exception:
        pass


def invalidate_symbol(symbol: str) -> int:
    """Remove every cached confidence for ``symbol`` from memory and SQLite.

    The key does not depend on the bars, so a bar refresh (historical_store.
    refresh_adjustments rewriting adj_factors) changes the inputs under an unchanged
    key; without this the stale value would be served until its TTL. The SQL uses an
    exact prefix comparison, not LIKE (``_``/``%`` are wildcards there), and the ``|``
    delimiter keeps ``AAPL`` from matching ``AAPLX``. Returns the number removed, or
    the in-memory count if the DB step fails.
    """
    global _generation
    prefix = f"{symbol.upper()}|"
    with _lock:
        _generation += 1
        _symbol_generation[symbol.upper()] = _generation
        keys = [k for k in _store if k.startswith(prefix)]
        for k in keys:
            del _store[k]
    # _lock is released before _db_lock is taken (lock order: _db_lock then _lock,
    # never the reverse). The bump above is already visible, so a guarded write that
    # re-checks after it skips; one already past its re-check holds _db_lock, and this
    # DELETE waits for its INSERT and then removes it (R2-F1).
    try:
        with _db_lock:
            conn = sqlite3.connect(_DB_PATH)
            try:
                cur = conn.execute(
                    "DELETE FROM confidence_cache WHERE substr(cache_key, 1, ?) = ?",
                    (len(prefix), prefix),
                )
                conn.commit()
                return max(cur.rowcount, len(keys))
            finally:
                conn.close()
    except Exception:
        return len(keys)


# Warm-load on module import (once per process).
_warm_load()
