"""A4c: the user-built intraday alert models measure on COMPLETED bars.

Kenneth 2026-09-24: "every model that decides or fires" -- intraday intervals
only, regime models only. Plan:
docs/superpowers/plans/2026-09-24-a4c-user-alert-models-completed-bars-plan.md.

Completed bars close at 50.0; the still-forming last bar closes at 999.0, so a
regime model that saw it is read straight off the series it was handed. Feed lag
is pinned to 0 except in the lag tests.
"""
from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.data.market as market
from app.data.market import completed_bars_for_interval
from app.database import Base
from app.models.alert import AlertRuleModel, AlertHistoryModel  # noqa: F401

FORMING = 999.0


def _bars(n: int = 120, span: int = 900, now: int | None = None) -> list[dict]:
    """`n` completed bars of `span` seconds ending one bar ago, then one forming."""
    now = int(time.time()) if now is None else now
    done = [{"time": now - span * (n - i + 1), "open": 50.0, "high": 50.5, "low": 49.5,
             "close": 50.0, "volume": 1_000} for i in range(n)]
    forming = {"time": now - 60, "open": 50.0, "high": 999.0, "low": 50.0,
               "close": FORMING, "volume": 10}
    return done + [forming]


@pytest.fixture(autouse=True)
def _no_feed_lag(request, monkeypatch):
    if "lag" not in request.node.name:
        monkeypatch.setattr(market, "intraday_feed_lag_seconds", lambda: 0)


# ── the helper ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("interval,span", [
    ("1min", 60), ("1m", 60), ("5min", 300), ("5m", 300), ("15min", 900), ("15m", 900),
    ("30min", 1800), ("30m", 1800), ("1h", 3600), ("60m", 3600), ("4h", 18000),
])
def test_each_intraday_interval_keeps_a_bar_only_once_its_span_has_elapsed(interval, span):
    now = 10**6
    bars = [{"time": now - span}, {"time": now - span + 1}]
    assert completed_bars_for_interval(bars, interval, now=now) == [{"time": now - span}]


@pytest.mark.parametrize("interval", ["1D", "1W", "daily", "weekly", "banana"])
def test_daily_weekly_and_unknown_intervals_are_returned_unchanged(interval):
    now = 10**6
    bars = [{"time": now - 10}, {"time": "not-a-date"}]
    assert completed_bars_for_interval(bars, interval, now=now) == bars


def test_sandbox_lag_applies_only_to_the_intervals_tradier_serves(monkeypatch):
    monkeypatch.setattr(market, "intraday_feed_lag_seconds", lambda: 900)
    now = 10**6
    bar = [{"time": now - 900 - 60}]              # 16 minutes old
    assert completed_bars_for_interval(bar, "15min", now=now) == []   # Tradier-served: lag
    assert completed_bars_for_interval(bar, "15m", now=now) == bar    # yfinance only: no lag
    assert completed_bars_for_interval([{"time": now - 1800}], "15min", now=now) == [{"time": now - 1800}]
    assert completed_bars_for_interval([{"time": now - 3600}], "1h", now=now) == [{"time": now - 3600}]


# ── U1: composite watch, scheduled path ──────────────────────────────────────

@pytest.mark.asyncio
async def test_u1_composite_watch_hmm_and_vwap_read_completed_bars(monkeypatch):
    import app.services.strategy_watch_evaluator as swe
    import app.services.composite_trigger_evaluator as cte
    import app.services.regime_hmm as regime_hmm

    intraday = _bars(span=900)
    watch = {"id": "w1", "enabled": True, "watch_type": "composite", "symbol": "AAPL",
             "strategy_key": "composite",
             "direction": "Bullish", "interval": "15m",
             "trigger_def": {"primary": {"model": "HMM_intraday", "to_state": "Trending",
                                         "p_stay_min": 0.0, "p_transition_min": 0.0},
                             "confirmations": [], "min_confirmations": 0,
                             "strategy_confirmations": ["mean_reversion_vwap"],
                             "min_strategy_confirmations": 1}}
    monkeypatch.setattr(swe.strategy_watch_store, "list_watches", lambda: [watch])
    monkeypatch.setattr(swe, "get_bars", AsyncMock(return_value=_bars(n=250, span=86400)))
    monkeypatch.setattr(market, "fetch_intraday_candles", lambda *a, **kw: intraday)
    seen_hmm, seen_strat = [], []
    monkeypatch.setattr(regime_hmm, "compute_intraday_hmm",
                        lambda b: seen_hmm.append(list(b)) or MagicMock())
    monkeypatch.setattr(cte, "_check_primary_hmm", lambda td, r: True)
    monkeypatch.setattr(cte, "_check_strategy_signals",
                        lambda names, d, i, direction="Bullish", **kw: seen_strat.append(list(i)) or 0)

    await swe.evaluate_all()
    assert seen_hmm == [intraday[:-1]]
    # FLIPPED by P4b (VWAP-CONFIRMATION-LIKE-REGIME-MODELS, 2026-09-25): the VWAP
    # confirmation now reads the completed bars too, like the HMM.
    assert seen_strat == [intraday[:-1]]


def test_u1_evaluate_scheduled_regime_series_and_strategy_series_are_separate(monkeypatch):
    import app.services.composite_trigger_evaluator as cte
    import app.services.regime_hmm as regime_hmm

    whole = _bars()
    seen = []
    monkeypatch.setattr(regime_hmm, "compute_intraday_hmm", lambda b: seen.append(list(b)) or None)
    td = {"primary": {"model": "HMM_intraday"}, "min_confirmations": 0}
    cte.evaluate_scheduled("AAPL", td, [], whole, regime_bars_intraday=whole[:-1])
    assert seen == [whole[:-1]]
    seen.clear()
    cte.evaluate_scheduled("AAPL", td, [], whole)   # no regime series: unchanged behaviour
    assert seen == [whole]
    # An all-dropped regime series fails closed without fitting.
    seen.clear()
    assert cte.evaluate_scheduled("AAPL", td, [], whole, regime_bars_intraday=[]) is False
    assert seen == []


# ── U2: the regime snapshot the alert dialog shows ───────────────────────────

@pytest.mark.asyncio
async def test_u2_snapshot_hmm_intraday_reads_completed_bars(monkeypatch):
    import app.routers.composite_watch as cw
    import app.services.regime_hmm as regime_hmm
    import app.services.historical_store as hs

    intraday = _bars(span=1800)
    monkeypatch.setattr(hs, "get_bars", AsyncMock(return_value=_bars(n=250, span=86400)))
    monkeypatch.setattr(market, "fetch_intraday_candles", lambda *a, **kw: intraday)
    seen = []
    res = MagicMock(state="Trending", p_stay=0.9, p_transition=0.1)
    monkeypatch.setattr(regime_hmm, "compute_intraday_hmm", lambda b: seen.append(list(b)) or res)
    await cw.get_regime_snapshot(symbol="AAPL", model="HMM_intraday", direction="Bullish", interval="30m")
    assert seen == [intraday[:-1]]


# ── U3/U4: chart-drawn rules ──────────────────────────────────────────────────

async def _session():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return Session


def _row(rule_id, interval, rule_json):
    return AlertRuleModel(
        id=rule_id, user_id='default', name='R', symbol='AAPL', interval=interval,
        enabled=True, rule_json=json.dumps(rule_json), cooldown_minutes=0, expiry_date=None,
        created_at='2024-01-01T00:00:00Z', last_triggered_at=None, condition_state='{}',
    )


_COMPOSITE_OMM = {"__type": "composite", "primary": {"model": "OMM"}, "confirmations": [],
                  "min_confirmations": 0}
_COMPOSITE_HMM = {"__type": "composite", "primary": {"model": "HMM_intraday", "to_state": "Trending",
                                                      "p_stay_min": 0.0, "p_transition_min": 0.0},
                  "confirmations": [], "min_confirmations": 0,
                  "strategy_confirmations": ["mean_reversion_vwap"], "min_strategy_confirmations": 1}
_REGIME_RULE = {"logic": "AND", "conditions": [{"kind": "regime", "model": "OMM", "state": "Bull"}]}


async def _run(monkeypatch, interval, rows, candles, as_of=None, daily=None):
    from app.routers import chart_alerts
    from tests.parity_harness import patch_feeds
    # WATCH-RULE-BAR-PARITY: composite models read the watch's feeds -- the
    # intraday fetch (stubbed to `candles`) and get_bars daily rows (`daily`).
    patch_feeds(monkeypatch, intraday=candles, daily=daily)
    import app.services.regime_omm as regime_omm
    import app.services.regime_hmm as regime_hmm
    import app.services.composite_trigger_evaluator as cte

    Session = await _session()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    async with Session() as db:
        for r in rows:
            db.add(r)
        await db.commit()
    seen = {"omm": [], "hmm": [], "strat": [], "snap": []}
    monkeypatch.setattr(regime_omm, "compute_omm",
                        lambda closes, *a, **kw: seen["omm"].append(list(closes)) or None)
    monkeypatch.setattr(regime_hmm, "compute_intraday_hmm",
                        lambda b: seen["hmm"].append(list(b)) or None)
    monkeypatch.setattr(cte, "_check_strategy_signals",
                        lambda names, d, i, direction="Bullish", **kw: seen["strat"].append(list(i)) or 0)
    monkeypatch.setattr(chart_alerts, "build_regime_snapshot",
                        lambda c: seen["snap"].append(list(c)) or {})
    await chart_alerts.evaluate_and_notify_for_symbol('AAPL', interval, candles[-2], candles, [], as_of=as_of)
    return seen


@pytest.mark.asyncio
async def test_u3_chart_composite_omm_and_hmm_fit_on_completed_candles(monkeypatch):
    # WATCH-RULE-BAR-PARITY: OMM reads the completed get_bars daily closes (as a
    # composite watch), no longer the chart's intraday candles; the HMM reads the
    # watch's intraday fetch, completed and cut at the closed candle.
    from datetime import date, timedelta
    from tests.parity_harness import daily_rows
    candles = _bars(span=900)
    daily = daily_rows(150, date.today() - timedelta(days=7), close=lambda i: 40.0 + i % 7)
    seen = await _run(monkeypatch, '15min',
                      [_row('c1', '15min', _COMPOSITE_OMM), _row('c2', '15min', _COMPOSITE_HMM)], candles,
                      daily=daily)
    assert seen["omm"] == [[r["close"] for r in daily]]
    assert seen["hmm"] == [candles[:-1]]


@pytest.mark.asyncio
async def test_u3_vwap_confirmation_reads_completed_bars(monkeypatch):
    # FLIPPED by P4b (VWAP-CONFIRMATION-LIKE-REGIME-MODELS): was
    # ..._keeps_the_forming_candle, pinning the superseded A4C-FOLLOWUPS-LOCKED choice.
    import app.services.regime_hmm as regime_hmm
    candles = _bars(span=900)
    from app.routers import chart_alerts
    from tests.parity_harness import patch_feeds
    patch_feeds(monkeypatch, intraday=candles)
    Session = await _session()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    async with Session() as db:
        db.add(_row('c2', '15min', _COMPOSITE_HMM))
        await db.commit()
    import app.services.composite_trigger_evaluator as cte
    seen = []
    res = MagicMock()
    monkeypatch.setattr(regime_hmm, "compute_intraday_hmm", lambda b: res)
    monkeypatch.setattr(cte, "_check_primary_hmm", lambda td, r: True)
    monkeypatch.setattr(cte, "_check_strategy_signals",
                        lambda names, d, i, direction="Bullish", **kw: seen.append(list(i)) or 0)
    await chart_alerts.evaluate_and_notify_for_symbol('AAPL', '15min', candles[-2], candles, [])
    assert seen == [candles[:-1]]


@pytest.mark.asyncio
async def test_u4_regime_condition_snapshot_on_completed_candles(monkeypatch):
    candles = _bars(span=3600)
    seen = await _run(monkeypatch, '1h', [_row('s1', '1h', _REGIME_RULE)], candles)
    assert seen["snap"] == [candles[:-1]]


@pytest.mark.asyncio
async def test_1d_rules_skip_the_intraday_trim(monkeypatch):
    """A4c's span-based intraday trim is not applied to 1D. Since A4g, 1D/1W drop
    the forming daily/weekly bar by session close instead
    (tests/test_a4g_forming_daily_weekly_bar.py), so this pins A4c's half at an
    instant where the two disagree: Friday 17:00 ET, last bar Friday's (00:00 ET
    stamp). A span trim would drop it (00:00 + 86400s is still ahead); A4g keeps
    it (the session closed at 16:00). WATCH-RULE-BAR-PARITY: the composite OMM
    no longer reads these candles -- it reads the get_bars rows closed by the
    judged (Thursday) candle's close, so Friday's row is not among them."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    fri = int(datetime(2026, 6, 12, tzinfo=ny).timestamp())
    candles = [{"time": fri - 86400 * (150 - i), "open": 50.0, "high": 50.5, "low": 49.5,
                "close": 50.0, "volume": 1_000} for i in range(150)]
    candles.append({"time": fri, "open": 50.0, "high": 50.5, "low": 49.5, "close": FORMING, "volume": 1})
    fri_evening = int(datetime(2026, 6, 12, 17, tzinfo=ny).timestamp())
    from datetime import date
    from tests.parity_harness import daily_rows
    daily = daily_rows(150, date(2026, 6, 12), close=lambda i: 40.0 + i % 7)
    seen = await _run(monkeypatch, '1D',
                      [_row('s1', '1D', _REGIME_RULE), _row('c1', '1D', _COMPOSITE_OMM)],
                      candles, as_of=fri_evening, daily=daily)
    assert seen["snap"] == [candles]
    assert daily[-1]["time"] == "2026-06-12"
    assert seen["omm"] == [[r["close"] for r in daily[:-1]]]


@pytest.mark.asyncio
async def test_as_of_judges_completeness_at_fetch_time_not_now(monkeypatch):
    fetched = int(time.time()) - 3600          # fetched an hour ago; its last bar was forming then
    candles = _bars(span=900, now=fetched)
    seen = await _run(monkeypatch, '15min', [_row('s1', '15min', _REGIME_RULE)], candles, as_of=fetched)
    assert seen["snap"] == [candles[:-1]]


# ── the chart cache and both callers ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_chart_cache_reports_the_fetch_time_cached_or_not(monkeypatch):
    import app.data.chart_cache as cc
    cc._INTRADAY_CACHE.clear()
    rows = [{"time": 1, "close": 1.0}]
    monkeypatch.setattr(cc, "fetch_intraday_candles", lambda *a, **kw: rows)
    t0 = time.time()
    r1, f1 = await cc.get_intraday_with_fetched_at("AAA", "15min", 55)
    r2, f2 = await cc.get_intraday_with_fetched_at("AAA", "15min", 55)   # cached
    assert r1 is rows and r2 is rows
    assert t0 - 1 <= f1 <= time.time()
    assert abs(f2 - f1) < 1.0
    assert await cc.get_intraday("AAA", "15min", 55) is rows
    cc._INTRADAY_CACHE.clear()


@pytest.mark.asyncio
async def test_scheduler_passes_the_fetch_time_of_its_candles(monkeypatch):
    import app.services.chart_alert_scheduler as sched
    Session = await _session()
    async with Session() as db:
        db.add(_row('s1', '15min', _REGIME_RULE))
        await db.commit()
    monkeypatch.setattr(sched, 'AsyncSessionLocal', Session)
    candles = _bars(n=5)
    monkeypatch.setattr(sched, 'get_intraday_with_fetched_at', AsyncMock(return_value=(candles, 12345.0)))
    monkeypatch.setattr('app.routers.chart_alerts.closed_candle_structure', lambda *a, **kw: [])  # A4e: the scheduler's structure call
    ev = AsyncMock(return_value=[])
    monkeypatch.setattr('app.routers.chart_alerts.evaluate_and_notify_for_symbol', ev)
    sched._last_seen_candle.clear()
    await sched._tick()
    assert ev.await_args.kwargs["as_of"] == 12345.0
    assert ev.await_args.args[3] is candles


def test_chart_ws_passes_the_fetch_time_of_its_candles():
    import inspect
    import app.routers.chart as chart
    src = inspect.getsource(chart)
    assert "candles, _fetched_at = await get_intraday_with_fetched_at(symbol, interval)" in src
    assert "as_of=_fetched_at" in src
