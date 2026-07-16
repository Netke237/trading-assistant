"""Persistent background event loop bridging synchronous callers into
tastytrade's async SDK and the shared async Governor.

Every other Governor-gated provider (alpaca, tradier, tiingo, yfinance,
ibkr) is only ever called from async code running on the app's single
long-lived uvicorn event loop. tastytrade is reached from *synchronous*
code as well — a to_thread-wrapped call in a separate OS thread, the paper
adapter, and the health probe. Governor's TokenBucket holds an
asyncio.Lock created once inside the process-wide Governor singleton; an
asyncio.Lock binds to whichever event loop first acquires it, so a second,
independent asyncio.run() call from a different thread trying to acquire
that same Lock instance either raises "bound to a different event loop" or
deadlocks outright under real contention.

Fix: route every sync-to-async tastytrade call through **one** persistent
background event loop, started once and reused for the process lifetime,
so the Governor's asyncio.Lock is always acquired from the same loop
regardless of which thread the sync caller is on.

Every tastytrade call that needs to reach async code from sync code
(tastytrade_iv.py, tastytrade_paper.py, data_sources.py's
_probe_tastytrade) must go through run_coro() here instead of calling
asyncio.run() directly.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Awaitable, TypeVar

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.Lock()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _lock:
        if _loop is not None:
            return _loop
        loop = asyncio.new_event_loop()
        started = threading.Event()

        def _run_forever() -> None:
            asyncio.set_event_loop(loop)
            started.set()
            loop.run_forever()

        threading.Thread(target=_run_forever, daemon=True, name="tastytrade-bridge").start()
        started.wait()
        _loop = loop
        return loop


def run_coro(coro: Awaitable[T]) -> T:
    """Schedule `coro` on the shared bridge loop and block the calling thread
    until it completes. Safe to call from any thread — including from inside
    asyncio.to_thread() — because every call lands on the same loop instead
    of spinning up a fresh one via asyncio.run()."""
    loop = _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()
