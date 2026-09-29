"""WATCH-RULE-BAR-PARITY test harness (plan section 3).

A composite RULE now reads the composite WATCH's feeds: the intraday model
series through chart_cache (which binds market.fetch_intraday_candles at
import) and the daily rows through get_bars. `patch_feeds` points every import
site of both at one stub, so a test states each path's input once and a test
never reaches a real provider.
"""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from typing import Callable
from unittest.mock import AsyncMock

import pytest


def daily_rows(n: int, last: date, close: float | Callable[[int], float] = 50.0) -> list[dict]:
    """``n`` get_bars-shaped rows on consecutive weekdays ending at ``last``."""
    days: list[date] = []
    d = last
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    out = []
    for i, d in enumerate(days):
        c = close(i) if callable(close) else close
        out.append({"time": d.isoformat(), "open": c, "high": c + 0.5, "low": c - 0.5,
                    "close": c, "volume": 1_000})
    return out


def patch_feeds(monkeypatch, *, intraday=None, daily=None, now: float | None = None):
    """Patch both feeds at every import site; returns (intraday_calls, get_bars mock).

    ``intraday``: a list (returned for every call) or a callable
    ``(symbol, interval, days) -> list``; None -> []. ``daily``: a list of rows
    or an AsyncMock used as get_bars; None -> [].
    ``now``: when given, chart_cache's wall clock reads this epoch instant, so
    the rule's model series is completed as if fetched then (its monotonic
    clock, and so the cache TTLs, stay real).
    ``intraday_calls`` records ``(symbol, interval, days)`` of every fetch.
    """
    import app.data.chart_cache as cc
    import app.data.market as market

    calls: list[tuple] = []

    def _fetch(symbol, interval="15min", days=55, *a, **kw):
        interval = kw.get("interval", interval)
        days = kw.get("days", days)
        calls.append((symbol, interval, days))
        if intraday is None:
            return []
        return intraday(symbol, interval, days) if callable(intraday) else intraday

    monkeypatch.setattr(cc, "fetch_intraday_candles", _fetch)
    monkeypatch.setattr(market, "fetch_intraday_candles", _fetch)
    cc._INTRADAY_CACHE.clear()
    if now is not None:
        import time as _time
        monkeypatch.setattr(cc, "time", SimpleNamespace(time=lambda: now, monotonic=_time.monotonic))

    gb = daily if isinstance(daily, AsyncMock) else AsyncMock(return_value=list(daily or []))
    monkeypatch.setattr("app.routers.chart_alerts.get_bars", gb)
    monkeypatch.setattr("app.services.strategy_watch_evaluator.get_bars", gb)
    monkeypatch.setattr("app.services.historical_store.get_bars", gb)
    return calls, gb


@pytest.fixture(autouse=True)
def parity_no_real_feeds(monkeypatch):
    """Autouse when imported into a test module: every composite-rule call in it
    reads empty feeds unless the test patches its own, so none reaches a real
    provider (plan section 3, suite hygiene)."""
    patch_feeds(monkeypatch)
