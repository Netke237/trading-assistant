"""WATCH-RULE-BAR-PARITY unit B: a composite chart RULE and a composite WATCH on
the same symbol and interval read the same bars.

Plan: docs/superpowers/plans/2026-09-28-watch-rule-bar-parity-plan.md (r6),
sections 2.1-2.9; tests 1-12 and 21 of section 3. Both paths are driven through
their real entry points -- chart_alerts.evaluate_and_notify_for_symbol (rule)
and strategy_watch_evaluator._eval_composite_watch (watch) -- with ONE pure
intraday stub of (interval, days) and one get_bars stub behind both
(tests/parity_harness.py). The models are replaced by recorders, so each test
reads straight off what each path handed them.

NOW is Wednesday 2026-09-23 12:10 ET; D = that Wednesday.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.data.market as market
import app.routers.chart_alerts as ca
import app.services.composite_trigger_evaluator as cte
import app.services.historical_store as hs
import app.services.regime_hmm as regime_hmm
import app.services.regime_omm as regime_omm
import app.services.strategy_engine as strategy_engine
import app.services.strategy_watch_evaluator as swe
from app.database import Base
from app.models.alert import AlertRuleModel, AlertHistoryModel  # noqa: F401
from app.services.composite_trigger_evaluator import (
    _NOMINAL_SPAN_SECONDS, candle_close_instant, daily_rows_at_candle, omm_direction,
)
from app.services.scheduling_tz import MARKET_TZ
from tests.parity_harness import daily_rows, parity_no_real_feeds, patch_feeds  # noqa: F401

ET = MARKET_TZ
D = date(2026, 9, 23)                                  # a Wednesday
NOW = datetime(2026, 9, 23, 12, 10, tzinfo=ET)
NOW_TS = NOW.timestamp()
TRIG = 777.0


def _ts(y, mo, d, h=0, mi=0, s=0) -> int:
    return int(datetime(y, mo, d, h, mi, s, tzinfo=ET).timestamp())


# ── the synthetic universe ────────────────────────────────────────────────────

_STAMPS = {   # bar-start times (ET) of one session per interval
    "15min": [(9 + (30 + 15 * k) // 60, (30 + 15 * k) % 60) for k in range(26)],
    "5min": [(9 + (30 + 5 * k) // 60, (30 + 5 * k) % 60) for k in range(78)],
    "1h": [(9 + k, 30) for k in range(7)],
    "4h": [(9, 30), (13, 30)],
}


def universe(interval: str, days: int, now: datetime = NOW) -> list[dict]:
    """``days + 4`` calendar days of session bars of ``interval`` ending at the bar
    forming at ``now`` (bars starting after ``now`` do not exist). Closes are a
    deterministic function of time, so two windows agree on every shared bar."""
    out = []
    d = now.date() - timedelta(days=days + 4)
    while d <= now.date():
        if d.weekday() < 5:
            for h, m in _STAMPS[interval]:
                t = int(datetime(d.year, d.month, d.day, h, m, tzinfo=ET).timestamp())
                if t <= now.timestamp():
                    c = 100.0 + (t // 60) % 97 * 0.01
                    out.append({"time": t, "open": c, "high": c + 0.5, "low": c - 0.5,
                                "close": c, "volume": 1000})
        d += timedelta(days=1)
    return out


def _stub(symbol, interval, days):
    return universe(interval, days)


ROWS = daily_rows(500, D, close=lambda i: 50.0 + (i * 7) % 13)   # get_bars rows through D


# ── recorders + drivers ──────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _pins(monkeypatch):
    monkeypatch.setattr(market, "intraday_feed_lag_seconds", lambda: 0)


@pytest.fixture
def rec(monkeypatch):
    """Record every model input; the HMM and the strategy gate pass, OMM returns None."""
    seen = {"hmm": [], "omm": [], "strat": [], "vwap": []}
    res = SimpleNamespace(state="Trending", p_stay=0.9, p_transition=0.1)
    monkeypatch.setattr(regime_hmm, "compute_intraday_hmm", lambda b: seen["hmm"].append(list(b)) or res)
    monkeypatch.setattr(cte, "_check_primary_hmm", lambda td, r: True)
    monkeypatch.setattr(regime_omm, "compute_omm",
                        lambda closes, *a, **kw: seen["omm"].append((list(closes), kw.get("direction"))) or None)

    def _strat(names, d, i, direction="Bullish", **kw):
        seen["strat"].append({"daily": list(d), "intraday": list(i),
                              "vwap_daily": kw.get("bars_vwap_daily")})
        return 0
    monkeypatch.setattr(cte, "_check_strategy_signals", _strat)

    def _vwap(bars, *, direction="Bullish", interval="15m", **kw):
        seen["vwap"].append(list(bars))
        return None
    monkeypatch.setattr(strategy_engine, "mean_reversion_vwap_signal", _vwap)
    return seen


async def _rule(monkeypatch, interval, td, candles, *, closed=None, as_of=NOW_TS):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(ca, "AsyncSessionLocal", Session)
    monkeypatch.setattr(ca, "_dispatch", AsyncMock())
    monkeypatch.setattr(ca, "_load_notification_config", lambda: {})
    async with Session() as db:
        db.add(AlertRuleModel(
            id="r1", user_id="default", name="R", symbol="AAPL", interval=interval, enabled=True,
            rule_json=json.dumps({**td, "__type": "composite"}), cooldown_minutes=0, expiry_date=None,
            created_at="2024-01-01T00:00:00Z", last_triggered_at=None, condition_state="{}",
        ))
        await db.commit()
    return await ca.evaluate_and_notify_for_symbol(
        "AAPL", interval, closed if closed is not None else candles[-2], candles, [], as_of=as_of)


async def _watch(interval, td, *, now: datetime = NOW):
    w = {"id": "w1", "symbol": "AAPL", "watch_type": "composite", "direction": "Bullish",
         "enabled": True, "interval": interval, "trigger_def": td, "last_state": {"phase": "idle"}}
    end = date.today()
    return await swe._eval_composite_watch(w, end - timedelta(days=730), end, now.timestamp(), now)


def _td(model="any", **kw) -> dict:
    primary = {"model": model, "to_state": "Trending", "p_stay_min": 0.0, "p_transition_min": 0.0}
    return {"primary": primary, "confirmations": [], "min_confirmations": 0, **kw}


# ── 1-3: one HMM_intraday window ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_1_1h_hmm_both_paths_fetch_180_days_and_fit_the_same_bars(monkeypatch, rec):
    calls, _ = patch_feeds(monkeypatch, intraday=_stub, daily=ROWS, now=NOW_TS)
    await _watch("1h", _td("HMM_intraday"))
    chart = universe("1h", 730)                      # the chart's own 1h window
    await _rule(monkeypatch, "1h", _td("HMM_intraday"), chart)
    assert calls == [("AAPL", "1h", 180), ("AAPL", "1h", 180)]
    watch_bars, rule_bars = rec["hmm"]
    assert rule_bars == watch_bars
    assert len(rule_bars) >= 800                     # the HMM fits its last 800
    assert rule_bars[-1]["time"] == chart[-2]["time"]


@pytest.mark.asyncio
async def test_2_4h_hmm_both_paths_fetch_180_days(monkeypatch, rec):
    calls, _ = patch_feeds(monkeypatch, intraday=_stub, daily=ROWS, now=NOW_TS)
    await _watch("4h", _td("HMM_intraday"))
    chart = universe("4h", 730)
    await _rule(monkeypatch, "4h", _td("HMM_intraday"), chart)
    assert calls == [("AAPL", "4h", 180), ("AAPL", "4h", 180)]
    watch_bars, rule_bars = rec["hmm"]
    assert rule_bars == watch_bars
    assert 240 <= len(rule_bars) < 300
    assert rule_bars != chart[:-1][-800:]            # the old rule input (730d, last 800)


@pytest.mark.asyncio
async def test_3_15min_rule_reuses_the_charts_cache_entry(monkeypatch, rec):
    import app.data.chart_cache as cc
    calls, _ = patch_feeds(monkeypatch, intraday=_stub, daily=ROWS, now=NOW_TS)
    chart, _f = await cc.get_intraday_with_fetched_at("AAPL", "15min")   # the chart's fetch
    await _rule(monkeypatch, "15min", _td("HMM_intraday"), chart)
    assert calls == [("AAPL", "15min", 55)]           # one fetch, shared
    await _watch("15min", _td("HMM_intraday"))
    assert calls[-1] == ("AAPL", "15min", 55)
    rule_bars, watch_bars = rec["hmm"]
    assert rule_bars == watch_bars == chart[:-1]


# ── 4: intraday VWAP ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_4_1h_vwap_identical_slices(monkeypatch, rec):
    monkeypatch.undo()   # the real _check_strategy_signals: the slices reach the signal
    monkeypatch.setattr(market, "intraday_feed_lag_seconds", lambda: 0)
    seen = []
    monkeypatch.setattr(strategy_engine, "mean_reversion_vwap_signal",
                        lambda bars, **kw: seen.append(list(bars)) or None)
    patch_feeds(monkeypatch, intraday=_stub, daily=ROWS, now=NOW_TS)
    td = _td("any", strategy_confirmations=["mean_reversion_vwap"], min_strategy_confirmations=1)
    await _watch("1h", td)
    n = len(seen)
    await _rule(monkeypatch, "1h", td, universe("1h", 730))
    assert n > 0 and seen[:n] == seen[n:2 * n]


# ── 5: 1D / 1W read completed get_bars rows ──────────────────────────────────

_DAILY_TD = _td("HMM_daily", strategy_confirmations=["mean_reversion_rsi", "mean_reversion_bb",
                                                    "mean_reversion_vwap"],
                min_strategy_confirmations=1)


def _chart_daily(last: date, n: int = 300) -> list[dict]:
    """Chart daily candles (00:00 ET stamps) closing at TRIG, so any read shows."""
    out, d = [], last
    while len(out) < n:
        if d.weekday() < 5:
            out.append({"time": _ts(d.year, d.month, d.day), "open": TRIG, "high": TRIG,
                        "low": TRIG, "close": TRIG, "volume": 1})
        d -= timedelta(days=1)
    return out[::-1]


def _through(iso: str) -> list[dict]:
    return [r for r in ROWS if r["time"] <= iso]


@pytest.mark.asyncio
async def test_5_1d_each_path_reads_get_bars_rows(monkeypatch, rec):
    patch_feeds(monkeypatch, daily=ROWS)
    evening = datetime(2026, 9, 23, 17, 0, tzinfo=ET)
    chart = _chart_daily(D)
    # D evening (Q-E): the rule judges candles[-2] (D-1); the watch reads to D.
    await _rule(monkeypatch, "1D", _DAILY_TD, chart, as_of=evening.timestamp())
    await _watch("1D", _DAILY_TD, now=evening)
    # D+1: the rule judges D's candle and keeps row D.
    await _rule(monkeypatch, "1D", _DAILY_TD, chart + _chart_daily(D + timedelta(days=1), 1),
                as_of=evening.timestamp() + 86400)
    rule_eve, watch_eve, rule_next = rec["hmm"]
    assert rule_eve == _through("2026-09-22")
    assert watch_eve == _through("2026-09-23")
    assert rule_next == _through("2026-09-23")
    for s in rec["strat"]:
        assert s["daily"] and all(isinstance(r["time"], str) for r in s["daily"])
        assert s["vwap_daily"] == s["daily"]
        assert s["intraday"] == []
    assert [s["daily"] for s in rec["strat"]] == rec["hmm"]


@pytest.mark.asyncio
async def test_5_1w_each_path_reads_get_bars_rows(monkeypatch, rec):
    patch_feeds(monkeypatch, daily=ROWS)
    weekly = [{"time": _ts(2026, 9, 21) - 7 * 86400 * (99 - i), "open": TRIG, "high": TRIG,
               "low": TRIG, "close": TRIG, "volume": 1} for i in range(100)]   # Mondays to 09-21
    # Mid-week: the rule judges last week (rows to Friday 09-18); the watch reads to Tuesday.
    await _rule(monkeypatch, "1W", _DAILY_TD, weekly)
    await _watch("1W", _DAILY_TD)
    # The Monday after: the rule judges this week and keeps Friday 09-25's row.
    rows_fri = daily_rows(500, date(2026, 9, 25), close=lambda i: 50.0 + (i * 7) % 13)
    patch_feeds(monkeypatch, daily=rows_fri)
    ca._DAILY_ROWS_MEMO.clear()
    weekly2 = weekly + [{**weekly[-1], "time": _ts(2026, 9, 28)}]
    await _rule(monkeypatch, "1W", _DAILY_TD, weekly2, as_of=_ts(2026, 9, 28, 12))
    rule_mid, watch_mid, rule_next = rec["hmm"]
    assert rule_mid == _through("2026-09-18")
    assert watch_mid == _through("2026-09-22")
    assert rule_next[-1]["time"] == "2026-09-25"
    assert all(s["vwap_daily"] == s["daily"] for s in rec["strat"])


# ── 6: OMM ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("interval", ["15min", "1D", "1W"])
@pytest.mark.parametrize("direction", ["Bullish", "Bearish"])
async def test_6_omm_same_closes_and_direction_on_both_paths(monkeypatch, rec, interval, direction):
    patch_feeds(monkeypatch, intraday=_stub, daily=ROWS, now=NOW_TS)
    td = _td("OMM", direction=direction)
    if interval == "15min":
        candles = universe("15min", 55)
        closed = candles[-2]
    else:
        # A candle the rule judges whose close is NOW's most recent completed
        # session close, so both paths read rows through D-1.
        stamp = _ts(2026, 9, 22) if interval == "1D" else _ts(2026, 9, 18)
        candles = [{"time": stamp, "open": 1.0, "high": 1.0, "low": 1.0, "close": TRIG, "volume": 1}] * 2
        closed = candles[0]
    await _rule(monkeypatch, interval, td, candles, closed=closed)
    await _watch(interval, td)
    rule_in, watch_in = rec["omm"]
    assert rule_in[1] == watch_in[1] == direction
    if interval == "1W":
        # Q-E: the 1W rule reads to last Friday; the watch to yesterday.
        assert rule_in[0] == [r["close"] for r in _through("2026-09-18")]
        assert watch_in[0] == [r["close"] for r in _through("2026-09-22")]
    else:
        assert rule_in[0] == watch_in[0] == [r["close"] for r in _through("2026-09-22")]


@pytest.mark.asyncio
@pytest.mark.parametrize("td", [
    {"confirmations": [], "min_confirmations": 0},                               # primary missing
    {"primary": None, "confirmations": [], "min_confirmations": 0},
    {"primary": {"model": None}, "confirmations": [], "min_confirmations": 0},
])
async def test_6_malformed_primary_never_raises(monkeypatch, rec, td):
    patch_feeds(monkeypatch, intraday=_stub, daily=ROWS, now=NOW_TS)
    candles = universe("15min", 55)
    await _rule(monkeypatch, "15min", td, candles)   # no exception escapes
    await _watch("15min", td)


@pytest.mark.asyncio
async def test_6_non_dict_primary_never_escapes_the_rule_block(monkeypatch, rec):
    # Rule path only: the watch's own `.get("model")` on a str primary is in
    # strategy_watch_evaluator (not owned); _collect isolates that watch.
    patch_feeds(monkeypatch, intraday=_stub, daily=ROWS, now=NOW_TS)
    td = {"primary": "OMM", "confirmations": [], "min_confirmations": 0}
    assert await _rule(monkeypatch, "15min", td, universe("15min", 55)) == []


# ── 7: which daily rows a candle may read (2.2) ──────────────────────────────

_R = daily_rows(5, D)          # Thu 09-17 .. Wed 09-23


def _last(rows):
    return rows[-1]["time"] if rows else None


@pytest.mark.parametrize("stamp, interval, last", [
    (_ts(2026, 9, 23, 15, 15), "15min", "2026-09-22"),      # closes 15:30 -> no row D
    (_ts(2026, 9, 23, 15, 45), "15min", "2026-09-23"),      # closes 16:00:00 -> row D
    (_ts(2026, 9, 23, 15, 44, 59), "15min", "2026-09-22"),  # closes 15:59:59
    (_ts(2026, 9, 23, 15, 45, 1), "15min", "2026-09-23"),   # closes 16:00:01
    (_ts(2026, 9, 23, 11), "4h", "2026-09-22"),             # closes 15:00 (nominal, not 5h)
    (_ts(2026, 9, 23, 12), "4h", "2026-09-23"),             # closes 16:00
    (_ts(2026, 9, 23, 15, 30), "1h", "2026-09-23"),         # closes 16:30
    (_ts(2026, 9, 23, 14, 30), "1h", "2026-09-22"),         # closes 15:30
    (_ts(2026, 9, 23), "1D", "2026-09-23"),                 # 00:00 ET stamp
    (int(datetime(2026, 9, 23, tzinfo=__import__("datetime").timezone.utc).timestamp()), "1D",
     "2026-09-23"),                                         # 00:00 UTC of D (20:00 ET D-1) is D's bar
    (_ts(2026, 9, 23, 9, 30), "1D", "2026-09-23"),          # session-open stamp
    (_ts(2026, 9, 23, 16), "1D", "2026-09-23"),             # session-close stamp
    (_ts(2026, 9, 22, 16, 0, 1), "1D", "2026-09-23"),       # just after D-1's close -> D's candle
    (_ts(2026, 9, 21), "1W", "2026-09-23"),                 # Monday stamp -> Friday 09-25
    (_ts(2026, 9, 14), "1W", "2026-09-18"),                 # last week's Monday -> Friday 09-18
    (_ts(2026, 9, 18, 16), "1W", "2026-09-18"),             # Friday close stamp
    (_ts(2026, 9, 19, 12), "1D", "2026-09-21"),             # Saturday stamp -> Monday's close
])
def test_7_daily_rows_at_candle(stamp, interval, last):
    assert _last(daily_rows_at_candle(_R, {"time": stamp}, interval)) == last


@pytest.mark.parametrize("t", ["2026-09-23", None, True, 1.5e9])
def test_7_undatable_candle_fails_closed(t, caplog):
    assert daily_rows_at_candle(_R, {"time": t}, "15min") == []
    assert daily_rows_at_candle(_R, "not a dict", "1D") == []
    assert any("cannot date" in r.getMessage() for r in caplog.records)


def test_7_nominal_span_is_not_the_completion_lag():
    from app.data.market import _INTERVAL_COMPLETION_SECONDS
    assert _NOMINAL_SPAN_SECONDS["4h"] == 4 * 3600 != _INTERVAL_COMPLETION_SECONDS["4h"]
    assert candle_close_instant({"time": 0}, "banana") is None
    assert daily_rows_at_candle(_R, {"time": _ts(2026, 9, 23)}, "banana") == []


def test_7_rows_not_mutated_and_bad_rows_dropped():
    rows = _R + [{"time": 12345}, {"time": "garbage"}, "x"]
    snapshot = [dict(r) if isinstance(r, dict) else r for r in rows]
    out = daily_rows_at_candle(rows, {"time": _ts(2026, 9, 24)}, "1D")
    assert out == _R
    assert rows == snapshot


# ── 8: catch-up ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_8_catch_up_candle_reads_no_later_bar(monkeypatch, rec):
    patch_feeds(monkeypatch, intraday=_stub, daily=ROWS, now=NOW_TS)
    candles = universe("15min", 55)
    k = next(i for i, c in enumerate(candles) if c["time"] == _ts(2026, 9, 21, 11))   # Monday 11:00
    view = candles[:k + 1]
    td = _td("HMM_intraday", strategy_confirmations=["mean_reversion_rsi"], min_strategy_confirmations=1)
    await _rule(monkeypatch, "15min", td, view, closed=view[-1])
    (hmm,) = rec["hmm"]
    assert hmm[-1]["time"] == view[-1]["time"]
    assert all(b["time"] <= view[-1]["time"] for b in hmm)
    (s,) = rec["strat"]
    assert _last(s["daily"]) == "2026-09-18"          # Monday 11:15 closes no Monday session
    assert all(b["time"] <= view[-1]["time"] for b in s["intraday"])


# ── 9: /regime-snapshot ──────────────────────────────────────────────────────

class _Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["OMM", "HMM_daily"])
async def test_9_snapshot_reads_the_watch_rows(monkeypatch, rec, model):
    import app.routers.composite_watch as cw
    import datetime as _dt
    monkeypatch.setattr(_dt, "datetime", _Clock)          # the router's lazy import
    monkeypatch.setattr(regime_omm, "compute_omm",
                        lambda closes, *a, **kw: rec["omm"].append((list(closes), kw.get("direction")))
                        or SimpleNamespace(state="Bull", p_stay=0.9, conviction_pct=80,
                                           conviction_label="High"))
    _, gb = patch_feeds(monkeypatch, daily=ROWS)
    await cw.get_regime_snapshot(symbol="AAPL", model=model, direction="Bearish", interval="15min")
    monkeypatch.undo()
    monkeypatch.setattr(market, "intraday_feed_lag_seconds", lambda: 0)
    watch_seen = []
    monkeypatch.setattr(regime_hmm, "compute_intraday_hmm", lambda b: watch_seen.append(list(b)) or None)
    monkeypatch.setattr(regime_omm, "compute_omm",
                        lambda closes, *a, **kw: watch_seen.append(
                            [{"close": c} for c in closes]) or None)
    patch_feeds(monkeypatch, daily=ROWS)
    await _watch("15min", _td(model, direction="Bearish"))
    expect = _through("2026-09-22")
    if model == "OMM":
        assert rec["omm"] == [([r["close"] for r in expect], "Bearish")]
        assert watch_seen == [[{"close": r["close"]} for r in expect]]
    else:
        assert rec["hmm"] == [expect] and watch_seen == [expect]
    assert gb.await_args.args[1] == gb.await_args.args[2] - timedelta(days=730)


@pytest.mark.asyncio
async def test_9_snapshot_hmm_intraday_does_not_need_daily_rows(monkeypatch, rec):
    import app.routers.composite_watch as cw
    _, gb = patch_feeds(monkeypatch, intraday=_stub, daily=[])
    out = await cw.get_regime_snapshot(symbol="AAPL", model="HMM_intraday", direction="Bullish",
                                       interval="15min")
    assert out["model"] == "HMM_intraday"
    gb.assert_not_awaited()


# ── 10: the daily-row memo ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_10_one_get_bars_per_memo_window_and_settle_boundary(monkeypatch, rec):
    _, gb = patch_feeds(monkeypatch, intraday=_stub, daily=ROWS, now=NOW_TS)
    import time as _time
    mono = [_time.monotonic()]
    monkeypatch.setattr(ca, "time", SimpleNamespace(monotonic=lambda: mono[0], time=_time.time))
    utc = [NOW.astimezone(__import__("datetime").timezone.utc)]
    monkeypatch.setattr(hs, "_utcnow", lambda: utc[0])
    candles = universe("15min", 55)
    for _ in range(3):
        await _rule(monkeypatch, "15min", _td("OMM"), candles)
    assert gb.await_count == 1
    mono[0] += ca._DAILY_ROWS_TTL                          # memo window over
    await _rule(monkeypatch, "15min", _td("OMM"), candles)
    assert gb.await_count == 2
    utc[0] = datetime(2026, 9, 23, 18, 0, tzinfo=ET)       # D's settle boundary crossed
    await _rule(monkeypatch, "15min", _td("OMM"), candles)
    assert gb.await_count == 3
    utc[0] = datetime(2026, 9, 23, 19, 30, tzinfo=ET)      # same boundary, within the window
    await _rule(monkeypatch, "15min", _td("OMM"), candles)
    assert gb.await_count == 3
    assert len(ca._DAILY_ROWS_MEMO) == 1                   # the old boundary's copy is gone


def test_10_last_settle_boundary():
    at = lambda *a: datetime(*a, tzinfo=ET)  # noqa: E731
    close = lambda d: datetime(d.year, d.month, d.day, 18, 0, tzinfo=ET)  # noqa: E731
    assert hs.last_settle_boundary(at(2026, 9, 23, 17, 59, 59)) == close(date(2026, 9, 22))
    assert hs.last_settle_boundary(at(2026, 9, 23, 18, 0)) == close(date(2026, 9, 23))
    assert hs.last_settle_boundary(at(2026, 9, 21, 9)) == close(date(2026, 9, 18))   # Monday -> Friday
    assert hs.last_settle_boundary(at(2026, 9, 26, 12)) == close(date(2026, 9, 25))  # Saturday


@pytest.mark.asyncio
async def test_10_get_bars_failure_fails_closed_and_is_not_memoised(monkeypatch, rec):
    gb = AsyncMock(side_effect=[RuntimeError("down"), ROWS])
    patch_feeds(monkeypatch, intraday=_stub, daily=gb, now=NOW_TS)
    candles = universe("15min", 55)
    await _rule(monkeypatch, "15min", _td("OMM"), candles)
    assert rec["omm"] == []                                # no rows -> OMM not computed
    await _rule(monkeypatch, "15min", _td("OMM"), candles)
    assert gb.await_count == 2 and len(rec["omm"]) == 1


# ── 11: a model series that cannot reach the closed candle ───────────────────

@pytest.mark.asyncio
async def test_11_stalled_entry_one_refetch_then_fail_closed(monkeypatch, rec, caplog):
    stalled = [b for b in universe("15min", 55) if b["time"] < _ts(2026, 9, 22)]
    calls, _ = patch_feeds(monkeypatch, intraday=lambda s, i, d: stalled, daily=ROWS, now=NOW_TS)
    candles = universe("15min", 55)
    await _rule(monkeypatch, "15min", _td("HMM_intraday"), candles)
    assert len(calls) == 2                                  # the fetch + one forced refetch
    assert rec["hmm"] == []                                 # fail closed
    assert any("before the closed candle" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_11_catch_up_of_three_candles_forces_one_refetch(monkeypatch, rec):
    import app.services.chart_alert_scheduler as sched
    stalled = [b for b in universe("15min", 55) if b["time"] < _ts(2026, 9, 22)]
    calls, _ = patch_feeds(monkeypatch, intraday=lambda s, i, d: stalled, daily=ROWS, now=NOW_TS)
    monkeypatch.setattr(ca, "closed_candle_structure", lambda *a, **kw: [])
    candles = universe("15min", 55)
    sched._last_seen_candle.clear()
    sched._last_seen_candle[("AAPL", "15min")] = candles[-5]["time"]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(ca, "AsyncSessionLocal", Session)
    async with Session() as db:
        db.add(AlertRuleModel(
            id="r1", user_id="default", name="R", symbol="AAPL", interval="15min", enabled=True,
            rule_json=json.dumps({**_td("HMM_intraday"), "__type": "composite"}), cooldown_minutes=0,
            expiry_date=None, created_at="2024-01-01T00:00:00Z", last_triggered_at=None,
            condition_state="{}",
        ))
        await db.commit()
    await sched.evaluate_closed_candles("AAPL", "15min", candles, NOW_TS)
    assert len(calls) == 2                                  # three candles, one forced refetch
    assert rec["hmm"] == []
    sched._last_seen_candle.clear()


# ── 12: trigger_values.omm_state ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_12_omm_state_on_an_hmm_intraday_only_fire(monkeypatch, rec):
    monkeypatch.setattr(regime_omm, "compute_omm",
                        lambda closes, *a, **kw: SimpleNamespace(state="Bull", p_stay=0.9,
                                                                 conviction_pct=80.0))
    patch_feeds(monkeypatch, intraday=_stub, daily=ROWS, now=NOW_TS)
    fired = await _rule(monkeypatch, "15min", _td("HMM_intraday"), universe("15min", 55))
    assert len(fired) == 1
    assert fired[0]["trigger_values"]["omm_state"] == "Bull"


# ── 21: composite direction ──────────────────────────────────────────────────

@pytest.mark.parametrize("td, expected", [
    ({"direction": "Bullish"}, "Bullish"),
    ({"direction": "Bearish"}, "Bearish"),
    ({"direction": "bullish"}, "Bullish"),
    ({"direction": "bearish"}, "Bullish"),
    ({"direction": "Neutral"}, "Bullish"),
    ({"direction": None}, "Bullish"),
    ({}, "Bullish"),
    ("Bearish", "Bullish"),
    (None, "Bullish"),
])
def test_21_omm_direction(td, expected):
    assert omm_direction(td) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("direction, expected", [("bullish", "Bullish"), (None, "Bullish"),
                                                 ("Bearish", "Bearish"), ("sideways", "Bullish")])
async def test_21_both_paths_reach_compute_omm_with_a_valid_direction(monkeypatch, direction, expected):
    import app.services.regime_omm as ro
    real = ro.compute_omm
    seen = []
    monkeypatch.setattr(ro, "compute_omm",
                        lambda closes, *a, **kw: seen.append(kw.get("direction")) or real(closes, *a, **kw))
    patch_feeds(monkeypatch, intraday=_stub, daily=ROWS, now=NOW_TS)
    td = _td("OMM", direction=direction)
    await _rule(monkeypatch, "15min", td, universe("15min", 55))   # the real compute_omm: no raise
    await _watch("15min", td)
    assert seen == [expected, expected]


# ── code round 1 finding 1: the sandbox feed lag is not a stalled entry ──────

@pytest.mark.asyncio
@pytest.mark.parametrize("interval, days", [("15min", 55), ("5min", 55), ("1h", 180)])
async def test_r1_feed_lag_rule_reads_what_the_watch_reads(monkeypatch, rec, interval, days):
    """With the Tradier-sandbox lag (900 s) the completed series ends before the
    candle the scheduler judges at time + span. The rule must still fit on the
    lag-completed bars, as the watch does -- no forced refetch, no fail closed."""
    monkeypatch.setattr(market, "intraday_feed_lag_seconds", lambda: 900)
    import app.data.chart_cache as cc
    # 30 s past NOW: at NOW itself a 5min bar completes exactly on the instant
    # (11:50 + 300 + 900 = 12:10:00), and the harness' cache fetched_at is a few
    # ms before its clock, so the two paths would straddle that boundary.
    at = NOW_TS + 30
    calls, _ = patch_feeds(monkeypatch, intraday=_stub, daily=ROWS, now=at)
    chart, _f = await cc.get_intraday_with_fetched_at("AAPL", interval)
    await _rule(monkeypatch, interval, _td("HMM_intraday"), chart, as_of=at)
    await _watch(interval, _td("HMM_intraday"), now=NOW + timedelta(seconds=30))
    rule_bars, watch_bars = rec["hmm"]
    assert rule_bars == watch_bars and len(rule_bars) > 200
    if interval != "1h":                    # the lag applies to the Tradier intervals only
        assert rule_bars[-1]["time"] < chart[-2]["time"]
    assert len([c for c in calls if c[1] == interval and c[2] == days]) <= 2   # no forced refetch
    assert ca._MODEL_REFETCHED == {}
