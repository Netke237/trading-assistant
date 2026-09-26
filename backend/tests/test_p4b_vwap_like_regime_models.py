"""P4b T5: VWAP-CONFIRMATION-LIKE-REGIME-MODELS.

The composite mean_reversion_vwap confirmation reads COMPLETED bars of the
rule/watch's own interval, gives the same answer on the watch path
(strategy_watch_evaluator) and the rule path (chart_alerts), and on 1D/1W runs
mean_reversion_vwap_daily_signal on completed get_bars daily rows (D7). Watches
read with the chart spelling (D5); '4h' runs the intraday signal (D2).

The signal functions are replaced by markers that fire when the LAST bar of the
slice they are handed carries close == TRIG, so each test controls exactly which
bar a path must (or must not) read.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.data.market as market
import app.services.composite_trigger_evaluator as cte
import app.services.regime_omm as regime_omm
import app.services.strategy_engine as strategy_engine
import app.services.strategy_watch_evaluator as swe
from app.database import Base
from app.models.alert import AlertRuleModel
from app.services.composite_trigger_evaluator import completed_daily_rows
from app.services.scheduling_tz import MARKET_TZ

TRIG = 777.0
_ET = MARKET_TZ
WED_MID = datetime(2026, 9, 23, 12, 0, tzinfo=_ET)       # session open
WED_AFTER = datetime(2026, 9, 23, 17, 0, tzinfo=_ET)     # after the close
SAT = datetime(2026, 9, 26, 12, 0, tzinfo=_ET)

_TD = {"primary": {"model": "any"}, "confirmations": [], "min_confirmations": 0,
       "strategy_confirmations": ["mean_reversion_vwap"], "min_strategy_confirmations": 1,
       "direction": "Bullish"}


# ── fixtures ──────────────────────────────────────────────────────────────────

def _bar(t, close=100.0):
    return {"time": t, "open": 100.0, "high": 101.0, "low": 99.0, "close": close, "volume": 1_000}


def _intraday(now_ts: float, span: int, *, trig: str | None, n: int = 80) -> list[dict]:
    """n completed bars ending one bar ago, then one forming bar. trig marks the
    forming bar ("forming") or the last completed bar ("completed")."""
    now = int(now_ts)
    done = [_bar(now - span * (n - i + 1)) for i in range(n)]
    forming = _bar(now - 60)
    if trig == "completed":
        done[-1] = {**done[-1], "close": TRIG}
    if trig == "forming":
        forming = {**forming, "close": TRIG}
    return done + [forming]


def _daily_rows(last: date, *, trig_last: bool, n: int = 80) -> list[dict]:
    """get_bars-style rows: ISO date strings, oldest first, ending on `last`."""
    rows = [_bar((last - timedelta(days=n - 1 - i)).isoformat()) for i in range(n)]
    if trig_last:
        rows[-1] = {**rows[-1], "close": TRIG}
    return rows


def _chart_daily(last_close: datetime, n: int = 80) -> list[dict]:
    """Chart-cache daily candles (int times), never firing."""
    t = int(last_close.timestamp())
    return [_bar(t - 86400 * (n - 1 - i)) for i in range(n)]


@pytest.fixture
def signals(monkeypatch):
    """Marker signals; record (interval, last bar) per call."""
    seen = {"intraday": [], "daily": [], "rsi": []}

    def _vwap(bars, *, direction="Bullish", interval="15m", **kw):
        seen["intraday"].append((interval, bars[-1]))
        return object() if bars[-1]["close"] == TRIG else None

    def _vwap_daily(bars, *, direction="Bullish", **kw):
        seen["daily"].append(bars[-1])
        return object() if bars[-1]["close"] == TRIG else None

    def _rsi(bars, *, direction="Bullish", **kw):
        seen["rsi"].append(bars[-1])
        return None

    monkeypatch.setattr(strategy_engine, "mean_reversion_vwap_signal", _vwap)
    monkeypatch.setattr(strategy_engine, "mean_reversion_vwap_daily_signal", _vwap_daily)
    monkeypatch.setattr(strategy_engine, "mean_reversion_rsi_signal", _rsi)
    return seen


@pytest.fixture(autouse=True)
def _no_feed_lag(request, monkeypatch):
    # The sandbox feed lag reads TRADIER_BASE_URL from a developer .env; pinned
    # so these tests mean the same on every machine ([r3#4]). "lag" tests set it.
    if "lag" not in request.node.name:
        monkeypatch.setattr(market, "intraday_feed_lag_seconds", lambda: 0)
    monkeypatch.setattr(regime_omm, "compute_omm", lambda *a, **kw: None)


def _composite_watch(interval: str | None, td: dict = _TD) -> dict:
    w = {"id": "c1", "symbol": "AAPL", "watch_type": "composite", "direction": "Bullish",
         "enabled": True, "trigger_def": td, "last_state": {"phase": "idle"}}
    if interval is not None:
        w["interval"] = interval
    return w


async def _watch_fired(monkeypatch, watch, *, daily, intraday=None, now: datetime):
    store = MagicMock()
    store.list_watches.return_value = [watch]
    monkeypatch.setattr(swe, "strategy_watch_store", store)
    monkeypatch.setattr(swe, "get_bars", AsyncMock(return_value=daily))
    fetch = MagicMock(return_value=intraday or [])
    monkeypatch.setattr(market, "fetch_intraday_candles", fetch)
    events = await swe.evaluate_all(now_ts=now.timestamp())
    return bool(events), fetch


async def _rule_fired(monkeypatch, interval, candles, *, as_of: float, td: dict = _TD,
                      get_bars_rows=None, get_bars_exc=None):
    from app.routers import chart_alerts
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(chart_alerts, "AsyncSessionLocal", Session)
    gb = AsyncMock(return_value=get_bars_rows or [], side_effect=get_bars_exc)
    monkeypatch.setattr(chart_alerts, "get_bars", gb)
    async with Session() as db:
        db.add(AlertRuleModel(
            id="r1", user_id="default", name="Composite", symbol="AAPL", interval=interval,
            enabled=True, rule_json=json.dumps({**td, "__type": "composite"}),
            cooldown_minutes=0, expiry_date=None, created_at="2024-01-01T00:00:00Z",
            last_triggered_at=None,
        ))
        await db.commit()
    triggered = await chart_alerts.evaluate_and_notify_for_symbol(
        "AAPL", interval, candles[-2], candles, [], as_of=as_of)
    return bool(triggered), gb


# ── 1-2: intraday reads completed bars; watch == rule ────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("trig, expected", [("forming", False), ("completed", True)])
async def test_intraday_vwap_reads_completed_bars_on_both_paths(monkeypatch, signals, trig, expected):
    now = WED_MID
    candles = _intraday(now.timestamp(), 900, trig=trig)
    daily = _daily_rows(date(2026, 9, 22), trig_last=False)
    watch, _ = await _watch_fired(monkeypatch, _composite_watch("15m"), daily=daily,
                                  intraday=candles, now=now)
    rule, _ = await _rule_fired(monkeypatch, "15min", candles, as_of=now.timestamp())
    assert watch is expected
    assert rule is expected          # parity: same bars, same answer


@pytest.mark.asyncio
@pytest.mark.parametrize("lag, expected", [(0, True), (900, False)])
async def test_feed_lag_drops_the_same_bar_on_both_paths(monkeypatch, signals, lag, expected):
    """The trigger bar closed 300s ago. Without the sandbox lag both paths read
    it; with the 900s lag ('15min' is a Tradier interval) both drop it."""
    monkeypatch.setattr(market, "intraday_feed_lag_seconds", lambda: lag)
    now = WED_MID
    candles = _intraday(now.timestamp() + 600, 900, trig="completed")   # last bar ends now-300
    daily = _daily_rows(date(2026, 9, 22), trig_last=False)
    watch, _ = await _watch_fired(monkeypatch, _composite_watch("15m"), daily=daily,
                                  intraday=candles, now=now)
    rule, _ = await _rule_fired(monkeypatch, "15min", candles, as_of=now.timestamp())
    assert watch is expected
    assert rule is expected


# ── 3-4: D5 spelling; the interval reaches the signal ─────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("stored, fetched, signal_iv", [
    ("15m", "15min", "15m"), ("5m", "5min", "5m"), ("4h", "4h", "4h"), ("1h", "1h", "1h"),
])
async def test_watch_fetches_with_the_chart_spelling(monkeypatch, signals, stored, fetched, signal_iv):
    completed_ivs = []
    real = market.completed_bars_for_interval
    monkeypatch.setattr(market, "completed_bars_for_interval",
                        lambda bars, iv, now=None: completed_ivs.append(iv) or real(bars, iv, now=now))
    now = WED_MID
    span = {"15m": 900, "5m": 300, "4h": 14400, "1h": 3600}[stored]
    _, fetch = await _watch_fired(monkeypatch, _composite_watch(stored),
                                  daily=_daily_rows(date(2026, 9, 22), trig_last=False),
                                  intraday=_intraday(now.timestamp(), span, trig=None), now=now)
    assert fetch.call_args.kwargs["interval"] == fetched
    assert completed_ivs == [fetched]
    assert {iv for iv, _ in signals["intraday"]} == {signal_iv}


@pytest.mark.asyncio
async def test_rule_passes_its_interval_to_the_signal(monkeypatch, signals):
    now = WED_MID
    await _rule_fired(monkeypatch, "15min", _intraday(now.timestamp(), 900, trig=None),
                      as_of=now.timestamp())
    assert {iv for iv, _ in signals["intraday"]} == {"15m"}


# ── 5-7: 1D / 1W read completed get_bars rows (D7) ───────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("now, last, expected", [
    (WED_MID, date(2026, 9, 23), False),    # (a) today's bar is forming -> not read
    (WED_AFTER, date(2026, 9, 23), True),   # (b) after the close -> kept and read
    (SAT, date(2026, 9, 25), True),         # (c) Saturday, Friday's bar -> kept
])
async def test_1d_watch_and_rule_read_completed_get_bars_rows(monkeypatch, signals, now, last, expected):
    rows = _daily_rows(last, trig_last=True)
    watch, fetch = await _watch_fired(monkeypatch, _composite_watch("1D"), daily=rows, now=now)
    fetch.assert_not_called()                       # no "intraday" fetch on 1D
    assert watch is expected
    # the rule's own chart candles never fire; only the get_bars rows can
    rule, gb = await _rule_fired(monkeypatch, "1D", _chart_daily(now), as_of=now.timestamp(),
                                 get_bars_rows=rows)
    gb.assert_awaited()
    assert rule is expected
    assert signals["intraday"] == []


@pytest.mark.asyncio
async def test_1w_rule_reads_daily_rows_not_weekly_candles(monkeypatch, signals):
    now = SAT
    rows = _daily_rows(date(2026, 9, 25), trig_last=True)
    weekly = [_bar(int(now.timestamp()) - 7 * 86400 * (80 - i)) for i in range(80)]
    rule, gb = await _rule_fired(monkeypatch, "1W", weekly, as_of=now.timestamp(), get_bars_rows=rows)
    gb.assert_awaited()
    assert rule is True
    assert all(isinstance(b["time"], str) for b in signals["daily"])   # never a weekly candle
    watch, _ = await _watch_fired(monkeypatch, _composite_watch("1W"), daily=rows, now=now)
    assert watch is True


@pytest.mark.asyncio
async def test_1w_rule_get_bars_failure_fails_closed(monkeypatch, signals):
    now = SAT
    weekly = [_bar(int(now.timestamp()) - 7 * 86400 * (80 - i), close=TRIG) for i in range(80)]
    rule, _ = await _rule_fired(monkeypatch, "1W", weekly, as_of=now.timestamp(),
                                get_bars_exc=RuntimeError("feed down"))
    assert rule is False
    assert signals["daily"] == []       # the daily variant never ran on weekly bars


@pytest.mark.asyncio
async def test_intraday_rule_daily_rows_drop_the_forming_session(monkeypatch, signals):
    """7b: an intraday rule's rsi/bb read the get_bars rows through
    completed_daily_rows (today's bar dropped mid-session)."""
    now = WED_MID
    td = {**_TD, "strategy_confirmations": ["mean_reversion_rsi"]}
    rows = _daily_rows(date(2026, 9, 23), trig_last=False)
    await _rule_fired(monkeypatch, "15min", _intraday(now.timestamp(), 900, trig=None),
                      as_of=now.timestamp(), td=td, get_bars_rows=rows)
    assert signals["rsi"]
    assert all(b["time"] != "2026-09-23" for b in signals["rsi"])


# ── 7c: completed_daily_rows ──────────────────────────────────────────────────

def test_completed_daily_rows_string_and_int_times():
    close_wed = datetime(2026, 9, 23, 16, 0, tzinfo=_ET).timestamp()
    rows = [_bar("2026-09-22"), _bar("2026-09-23")]
    assert completed_daily_rows(rows, WED_MID) == rows[:1]
    assert completed_daily_rows(rows, WED_AFTER) == rows
    ints = [_bar(int(close_wed) - 86400), _bar(int(close_wed) + 60)]
    assert completed_daily_rows(ints, WED_AFTER) == ints[:1]
    mixed = [_bar(int(close_wed) - 86400), _bar("2026-09-23")]
    assert completed_daily_rows(mixed, WED_MID) == mixed[:1]


@pytest.mark.parametrize("bad_time", [None, 1.5, True, "t5", {}])
def test_completed_daily_rows_undatable_last_bar_is_dropped_alone(bad_time):
    rows = [_bar("2026-09-21"), _bar("2026-09-22"), _bar(bad_time)]
    snapshot = [dict(r) for r in rows]
    assert completed_daily_rows(rows, WED_AFTER) == rows[:2]
    assert rows == snapshot                       # input not mutated


def test_completed_daily_rows_empty():
    assert completed_daily_rows([], WED_MID) == []


# ── 8: 4h runs the real intraday signal (D2) ──────────────────────────────────

def test_real_vwap_signal_accepts_4h():
    from app.services.strategy_engine import mean_reversion_vwap_signal
    bars = [{"time": i, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1_000}
            for i in range(40)]
    bars += [{"time": 40, "open": 96.5, "high": 96.8, "low": 95.8, "close": 96.0, "volume": 1_000},
             {"time": 41, "open": 96.0, "high": 97.2, "low": 95.9, "close": 97.0, "volume": 1_000}]
    assert mean_reversion_vwap_signal(bars, direction="Bullish", interval="1h") is not None
    assert mean_reversion_vwap_signal(bars, direction="Bullish", interval="4h") is not None


# ── 9-10: starved vs definite; the store's default interval ──────────────────

def _sched(bars_daily, bars_intraday, interval, bars_vwap_daily):
    return cte.evaluate_scheduled("AAPL", _TD, bars_daily, bars_intraday, unknown_as_none=True,
                                  interval=interval, bars_vwap_daily=bars_vwap_daily)


def test_1d_with_too_few_daily_bars_is_no_reading(signals):
    rows = _daily_rows(date(2026, 9, 22), trig_last=False, n=30)
    assert _sched(rows, [], "1D", rows) is None


def test_1d_with_enough_daily_bars_and_no_signal_is_false(signals):
    """Distinguishes a matcher that reads bars_intraday (empty -> starved ->
    None) from one that reads the daily rows ([r3#2])."""
    rows = _daily_rows(date(2026, 9, 22), trig_last=False, n=80)
    assert _sched(rows, [], "1D", rows) is False
    assert signals["daily"]


def test_unknown_interval_never_matches_and_is_not_starved(signals):
    rows = _daily_rows(date(2026, 9, 22), trig_last=True, n=80)
    assert _sched(rows, [], "2h", rows) is False
    assert signals["daily"] == [] and signals["intraday"] == []


@pytest.mark.asyncio
async def test_missing_interval_is_the_stores_1d(monkeypatch, signals):
    rows = _daily_rows(date(2026, 9, 22), trig_last=True)
    fired, fetch = await _watch_fired(monkeypatch, _composite_watch(None), daily=rows, now=WED_MID)
    fetch.assert_not_called()
    assert fired is True


def test_1d_vwap_never_falls_back_to_bars_daily(signals):
    """bars_vwap_daily None -> VWAP not judged: no fallback to bars_daily, not
    starved -> a definite False (code round 1, finding 3)."""
    rows = _daily_rows(date(2026, 9, 22), trig_last=True, n=80)
    assert _sched(rows, [], "1D", None) is False
    assert signals["daily"] == []


def test_describe_match_reports_vwap_from_bars_vwap_daily_alone(signals):
    """The describe gate counts bars_vwap_daily ([r3#10]; code round 1, finding 4)."""
    rows = _daily_rows(date(2026, 9, 22), trig_last=True, n=80)
    detail = cte.describe_match(_TD, bars_daily=[], bars_intraday=[], bars_vwap_daily=rows, interval="1D")
    assert detail["strategy_matched"] == ["mean_reversion_vwap"]
