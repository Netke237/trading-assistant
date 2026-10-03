"""Audit round 1, F5: every WFO fold -- TRAIN as well as test -- gets the full
WARMUP_BARS warm-up (decision D2).

`run_optimization` used to fetch exactly 3 years and start the first fold at the
first bar, so train folds 0-3 had a warm-up of 0, 65, 130 and 195 bars: a
200-period trend filter could trade only the tail of those windows, which
handicapped long look-backs in the grid search. It now fetches WARMUP_BARS of
extra history BEFORE the first fold; the folds' own date ranges are unchanged.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

import app.services.historical_store as historical_store
import app.services.strategy_param_optimizer as opt
from app.services.walk_forward import WARMUP_BARS, slice_with_warmup


def _weekday_bars(start: date, end: date) -> list[dict]:
    out, d, px = [], start, 100.0
    while d <= end:
        if d.weekday() < 5:
            out.append({"time": d.isoformat(), "open": px, "high": px + 1,
                        "low": px - 1, "close": px, "volume": 1_000_000})
            px += 0.1
        d += timedelta(days=1)
    return out


def _run(monkeypatch):
    requested: list[tuple[date, date]] = []
    captured: dict = {}

    async def _get_bars(sym, start, end):
        requested.append((start, end))
        return _weekday_bars(start, end)

    def _capture(strategy, direction, basket_bars, folds, *a, **kw):
        captured["bars"], captured["folds"] = basket_bars, folds
        return None

    monkeypatch.setattr(historical_store, "get_bars", _get_bars)
    monkeypatch.setattr(opt, "_optimize_strategy_sync", _capture)
    monkeypatch.setattr("app.services.strategy_param_store.get_search_space",
                        lambda s: {"x": [1, 2]})
    asyncio.run(opt.run_optimization(
        ["pullback_ema"], ["AAA", "BBB"],
        {"train_months": 12, "test_months": 3, "type": "rolling"},
        {"fee_pct": 0.0, "slippage_pct": 0.0}, lambda done, total: None,
        direction="Bullish",
    ))
    return requested, captured


def test_every_train_and_test_fold_gets_the_full_warmup(monkeypatch):
    _, captured = _run(monkeypatch)
    folds = captured["folds"]
    assert len(folds) >= 5
    for bars in captured["bars"].values():
        for i, f in enumerate(folds):
            for label, (s, e) in (("train", (f.train_start, f.train_end)),
                                  ("test", (f.test_start, f.test_end))):
                window, n_scored = slice_with_warmup(bars, s, e)
                assert len(window) - n_scored == WARMUP_BARS, (i, label, len(window) - n_scored)


def test_the_folds_own_date_ranges_are_unchanged(monkeypatch):
    """The first fold still starts at the first trading day of the 3-year
    window: the extra history is warm-up only, never scored."""
    requested, captured = _run(monkeypatch)
    window_start = date.today() - relativedelta(years=3)
    first_trading = window_start
    while first_trading.weekday() >= 5:
        first_trading += timedelta(days=1)
    assert captured["folds"][0].train_start == first_trading
    # ...and the fetch reached back far enough to hold WARMUP_BARS before it.
    assert all(start < window_start for start, _ in requested)
