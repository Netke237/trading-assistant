"""A4g: 1D/1W chart alerts drop the forming daily/weekly bar.

Decision A4C-FOLLOWUPS-LOCKED-2026-09-24 part (4); plan
docs/superpowers/plans/2026-09-25-a4g-forming-daily-weekly-bar-plan.md. Kenneth,
2026-09-25: on the 1D/1W chart path ALL inputs that were fed the chart's candles
get completed bars -- regime snapshot, composite OMM, HMM_daily and the strategy
confirmations. A bar is forming iff its stamp is after the last completed close
INSTANT (round 1 F1), so no calendar-date matching across zones.

2026-06-10 is a Wednesday; 06-12 a Friday; 06-13 a Saturday; 06-08 a Monday.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import market_session as ms
from app.services.market_session import (
    completed_session_bars,
    last_session_close,
    last_week_close,
    todays_bar_is_unclosed,
    week_is_unclosed,
)
from app.services.scheduling_tz import MARKET_TZ
from tests.test_a4c_user_alert_completed_bars import _row, _session

FORMING = 999.0


def _ny(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=MARKET_TZ)


def _ts(dt: datetime) -> int:
    return int(dt.timestamp())


def _day_bar(day: datetime, close: float = 50.0, *, hour: int = 0, utc: bool = False) -> dict:
    """A daily bar for `day`, stamped 00:00 ET (yfinance), 00:00 UTC, or `hour` ET."""
    if utc:
        stamp = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    else:
        stamp = _ny(day.year, day.month, day.day, hour)
    return {"time": _ts(stamp), "open": 50.0, "high": 50.5, "low": 49.5, "close": close, "volume": 1}


def _weekdays_ending(last: datetime, n: int) -> list[datetime]:
    out, d = [], last
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def _daily(last: datetime, n: int = 150, **kw) -> list[dict]:
    """`n` weekday bars ending on `last`; the bar for `last` closes at FORMING."""
    days = _weekdays_ending(last, n)
    return [_day_bar(d, **kw) for d in days[:-1]] + [_day_bar(days[-1], FORMING, **kw)]


def _weekly(this_monday: datetime, n: int = 150) -> list[dict]:
    """`n` Monday-00:00-ET weekly bars ending with this week's (close FORMING)."""
    mondays = [this_monday - timedelta(weeks=n - 1 - i) for i in range(n)]
    return [_day_bar(m) for m in mondays[:-1]] + [_day_bar(mondays[-1], FORMING)]


WED = _ny(2026, 6, 10)


# ── 1. daily truth table ──────────────────────────────────────────────────────

@pytest.mark.parametrize("now,keeps_today,why", [
    (_ny(2026, 6, 10, 10, 0), False, "mid-session: today's bar is forming"),
    (_ny(2026, 6, 10, 8, 0), False, "pre-open: today's stamp is already after yesterday's close"),
    (_ny(2026, 6, 10, 16, 0), False, "16:00:00 exactly reads unclosed, inherited from guard (i)"),
    (_ny(2026, 6, 10, 16, 1), True, "after the close: today's bar is complete"),
    (_ny(2026, 6, 13, 12, 0), True, "Saturday: nothing is forming"),
])
def test_daily_truth_table(now, keeps_today, why):
    bars = _daily(WED, n=5)
    out = completed_session_bars(bars, "1D", now=now)
    assert out == (bars if keeps_today else bars[:-1]), why


@pytest.mark.parametrize("interval", ["1D", "daily"])
def test_daily_aliases(interval):
    bars = _daily(WED, n=5)
    assert completed_session_bars(bars, interval, now=_ny(2026, 6, 10, 10)) == bars[:-1]


def test_utc_midnight_stamp_dropped_mid_session_kept_after_close():
    bars = _daily(WED, n=5, utc=True)          # today's bar = Tue 20:00 ET as an instant
    assert completed_session_bars(bars, "1D", now=_ny(2026, 6, 10, 10)) == bars[:-1]
    assert completed_session_bars(bars, "1D", now=_ny(2026, 6, 10, 17)) == bars


def test_close_stamped_bar_dropped_before_close_kept_at_close():
    bars = _daily(WED, n=5, hour=16)           # stamped exactly at its own session close
    assert completed_session_bars(bars, "1D", now=_ny(2026, 6, 10, 15, 59)) == bars[:-1]
    assert completed_session_bars(bars, "1D", now=_ny(2026, 6, 10, 16, 1)) == bars, (
        "time == close is complete: the comparison is strict `>`"
    )


def test_monday_keeps_fridays_bar_drops_todays():
    mon = _ny(2026, 6, 8)
    bars = _daily(mon, n=5)
    out = completed_session_bars(bars, "1D", now=_ny(2026, 6, 8, 10))
    assert out == bars[:-1]
    assert out[-1]["time"] == _ts(_ny(2026, 6, 5)), "Friday's completed bar must survive Monday"


def test_last_session_close_skips_the_weekend():
    assert last_session_close(_ny(2026, 6, 8, 10)) == _ny(2026, 6, 5, 16)
    assert last_session_close(_ny(2026, 6, 13, 8)) == _ny(2026, 6, 12, 16)
    assert last_session_close(_ny(2026, 6, 13, 12)) == _ny(2026, 6, 12, 16), (
        "guard (i) reads a weekend after 09:30 as 'closed'; without the weekday "
        "check that returns Saturday 16:00, a close no session ever had"
    )
    assert last_session_close(_ny(2026, 6, 14, 21)) == _ny(2026, 6, 12, 16)
    assert last_session_close(_ny(2026, 6, 10, 17)) == _ny(2026, 6, 10, 16)


def test_undatable_last_bar_dropped_middle_kept():
    bars = _daily(WED, n=4)
    weird_last = bars[:-1] + [{"time": "2026-06-10", "close": FORMING}]
    assert completed_session_bars(weird_last, "1D", now=_ny(2026, 6, 10, 17)) == bars[:-1]
    bool_last = bars[:-1] + [{"time": True, "close": FORMING}]
    assert completed_session_bars(bool_last, "1D", now=_ny(2026, 6, 10, 17)) == bars[:-1]
    middle = [bars[0], {"time": None, "close": 1.0}] + bars[1:]
    assert completed_session_bars(middle, "1D", now=_ny(2026, 6, 10, 17)) == middle


@pytest.mark.parametrize("interval", ["15min", "1h", "5m", "banana"])
def test_other_intervals_unchanged(interval):
    bars = _daily(WED, n=4)
    assert completed_session_bars(bars, interval, now=_ny(2026, 6, 10, 10)) is bars


def test_input_not_mutated_and_empty_ok():
    bars = _daily(WED, n=4)
    snapshot = [dict(b) for b in bars]
    completed_session_bars(bars, "1D", now=_ny(2026, 6, 10, 10))
    assert bars == snapshot and len(bars) == 4
    assert completed_session_bars([], "1W", now=_ny(2026, 6, 10, 10)) == []


# ── 2. weekly ─────────────────────────────────────────────────────────────────

MON = _ny(2026, 6, 8)


@pytest.mark.parametrize("now,keeps_this_week,why", [
    (_ny(2026, 6, 10, 10), False, "Wednesday: the week is forming"),
    (_ny(2026, 6, 8, 8), False, "Monday pre-open: the week's bar is already stamped"),
    (_ny(2026, 6, 12, 15, 59), False, "Friday before the close"),
    (_ny(2026, 6, 12, 16, 1), True, "Friday after the close: the week is complete"),
    (_ny(2026, 6, 13, 12), True, "Saturday"),
    (_ny(2026, 6, 14, 20), True, "Sunday evening"),
])
def test_weekly_truth_table(now, keeps_this_week, why):
    bars = _weekly(MON, n=4)
    out = completed_session_bars(bars, "1W", now=now)
    assert out == (bars if keeps_this_week else bars[:-1]), why
    assert out[-1]["time"] >= bars[-2]["time"], "last week's bar is always kept"


def test_weekly_friday_stamp_and_sunday_evening_stamp():
    fri_stamp = [{"time": _ts(_ny(2026, 6, 5, 16))}, {"time": _ts(_ny(2026, 6, 12, 16))}]
    assert completed_session_bars(fri_stamp, "weekly", now=_ny(2026, 6, 11, 12)) == fri_stamp[:1]
    assert completed_session_bars(fri_stamp, "weekly", now=_ny(2026, 6, 12, 16, 1)) == fri_stamp
    sun_utc = [{"time": _ts(datetime(2026, 6, 1, tzinfo=timezone.utc))},
               {"time": _ts(datetime(2026, 6, 8, tzinfo=timezone.utc))}]  # Sun 20:00 ET
    assert completed_session_bars(sun_utc, "1W", now=_ny(2026, 6, 10, 10)) == sun_utc[:1]


def test_last_week_close():
    assert last_week_close(_ny(2026, 6, 10, 10)) == _ny(2026, 6, 5, 16)
    assert last_week_close(_ny(2026, 6, 12, 16, 1)) == _ny(2026, 6, 12, 16)
    assert last_week_close(_ny(2026, 6, 13, 9)) == _ny(2026, 6, 12, 16)
    assert last_week_close(_ny(2026, 6, 14, 23)) == _ny(2026, 6, 12, 16)


# ── 3. the session predicates ─────────────────────────────────────────────────

@pytest.mark.parametrize("now,expected", [
    (_ny(2026, 6, 8, 3), True), (_ny(2026, 6, 11, 23), True),
    (_ny(2026, 6, 12, 16, 0), True), (_ny(2026, 6, 12, 16, 1), False),
    (_ny(2026, 6, 13, 8), False), (_ny(2026, 6, 14, 12), False),
])
def test_week_is_unclosed(now, expected):
    assert week_is_unclosed(now) is expected


@pytest.mark.parametrize("fn", [week_is_unclosed, todays_bar_is_unclosed,
                                last_session_close, last_week_close])
def test_naive_now_raises(fn):
    with pytest.raises(ValueError, match="AWARE"):
        fn(datetime(2026, 6, 10, 12, 0))


def test_aware_utc_equals_its_new_york_equivalent():
    ny = _ny(2026, 6, 12, 20, 0)               # Friday 20:00 ET = Saturday 00:00 UTC
    utc = ny.astimezone(timezone.utc)
    assert week_is_unclosed(utc) is week_is_unclosed(ny) is False
    assert last_session_close(utc) == last_session_close(ny)
    bars = _daily(_ny(2026, 6, 12), n=3, utc=True)
    assert completed_session_bars(bars, "1D", now=utc) == completed_session_bars(bars, "1D", now=ny)


# ── 6. the move ───────────────────────────────────────────────────────────────

def test_the_helper_was_moved_not_copied():
    from app.services import auto_trader as at
    assert at._todays_bar_is_unclosed is ms.todays_bar_is_unclosed
    assert not hasattr(at, "_NYSE_OPEN") and not hasattr(at, "_market_session_open")
    from app.services.strategy_watch_scheduler import _market_open
    assert ms._market_session_open is _market_open


# ── 4/5. the chart path: every reader on 1D/1W ────────────────────────────────

_REGIME_RULE = {"logic": "AND", "conditions": [{"kind": "regime", "model": "OMM", "state": "Bull"}]}
_COMPOSITE_OMM = {"__type": "composite", "primary": {"model": "OMM"}, "confirmations": [],
                  "min_confirmations": 0}
_COMPOSITE_HMM_DAILY = {"__type": "composite",
                        "primary": {"model": "HMM_daily", "to_state": "Trending",
                                    "p_stay_min": 0.0, "p_transition_min": 0.0},
                        "confirmations": [], "min_confirmations": 0}
_COMPOSITE_STRAT = {"__type": "composite", "primary": {"model": "any"}, "confirmations": [],
                    "min_confirmations": 0,
                    "strategy_confirmations": ["mean_reversion_rsi", "mean_reversion_bb"],
                    "min_strategy_confirmations": 1}


# WATCH-RULE-BAR-PARITY (item 8, plan 2.2/2.3): on 1D/1W the composite readers
# (D2 OMM, D3 HMM_daily + strategy confirmations) no longer read the chart's
# candles -- they read the completed get_bars daily rows closed by the judged
# candle's close, as a composite watch does. D1 (the standard rules' regime
# snapshot) is unchanged. GET_BARS rows run to Wednesday 2026-06-10.
from datetime import date as _date  # noqa: E402
from tests.parity_harness import daily_rows  # noqa: E402

GET_BARS = daily_rows(150, _date(2026, 6, 10), close=lambda i: 40.0 + i % 7)


def _rows_through(last_iso: str) -> list[dict]:
    return [r for r in GET_BARS if r["time"] <= last_iso]


async def _run(monkeypatch, interval, candles, as_of):
    from app.routers import chart_alerts
    from tests.parity_harness import patch_feeds
    patch_feeds(monkeypatch, daily=GET_BARS)
    import app.services.regime_omm as regime_omm
    import app.services.regime_hmm as regime_hmm
    import app.services.composite_trigger_evaluator as cte

    Session = await _session()
    monkeypatch.setattr(chart_alerts, "AsyncSessionLocal", Session)
    async with Session() as db:
        for rid, rj in (("s1", _REGIME_RULE), ("c1", _COMPOSITE_OMM),
                        ("c2", _COMPOSITE_HMM_DAILY), ("c3", _COMPOSITE_STRAT)):
            db.add(_row(rid, interval, rj))
        await db.commit()
    seen = {"omm": [], "hmm": [], "strat_daily": [], "strat_intraday": [], "snap": []}
    monkeypatch.setattr(regime_omm, "compute_omm",
                        lambda closes, *a, **kw: seen["omm"].append(list(closes)) or None)
    monkeypatch.setattr(regime_hmm, "compute_intraday_hmm",
                        lambda b: seen["hmm"].append(list(b)) or None)

    def _strat(names, d, i, direction="Bullish", **kw):
        seen["strat_daily"].append(list(d))
        seen["strat_intraday"].append(list(i))
        return 0
    monkeypatch.setattr(cte, "_check_strategy_signals", _strat)
    monkeypatch.setattr(chart_alerts, "build_regime_snapshot",
                        lambda c: seen["snap"].append(list(c)) or {})
    await chart_alerts.evaluate_and_notify_for_symbol(
        "AAPL", interval, candles[-2], candles, [], as_of=as_of)
    return seen


def _assert_every_reader_saw(seen, expected, composite_rows):
    assert seen["snap"] == [expected], "D1 regime snapshot"
    assert seen["omm"] == [[r["close"] for r in composite_rows]], "D2 composite OMM"
    assert seen["hmm"] == [composite_rows], "D3 HMM_daily"
    assert seen["strat_daily"] == [composite_rows], "D3 strategy confirmations (rsi/bb + choppy OMM)"
    assert seen["strat_intraday"] == [[]], "bars_intraday stays [] on 1D/1W"


@pytest.mark.asyncio
async def test_1d_mid_session_every_reader_drops_the_forming_bar(monkeypatch):
    candles = _daily(WED)
    seen = await _run(monkeypatch, "1D", candles, as_of=_ts(_ny(2026, 6, 10, 11)))
    # The judged candle is Tuesday's: its close closes Tuesday's row, not Wednesday's.
    _assert_every_reader_saw(seen, candles[:-1], _rows_through("2026-06-09"))


@pytest.mark.asyncio
async def test_1d_after_the_close_every_reader_keeps_todays_bar(monkeypatch):
    candles = _daily(WED)
    seen = await _run(monkeypatch, "1D", candles, as_of=_ts(_ny(2026, 6, 10, 17)))
    # Q-E: the composite readers follow the judged candle (Tuesday), not as_of.
    _assert_every_reader_saw(seen, candles, _rows_through("2026-06-09"))


@pytest.mark.asyncio
async def test_1w_mid_week_every_reader_drops_this_weeks_bar(monkeypatch):
    candles = _weekly(MON)
    seen = await _run(monkeypatch, "1W", candles, as_of=_ts(_ny(2026, 6, 10, 11)))
    # The judged candle is last week's: rows through its Friday (06-05), never weekly bars.
    _assert_every_reader_saw(seen, candles[:-1], _rows_through("2026-06-05"))


@pytest.mark.asyncio
async def test_1w_after_fridays_close_every_reader_keeps_it(monkeypatch):
    candles = _weekly(MON)
    seen = await _run(monkeypatch, "1W", candles, as_of=_ts(_ny(2026, 6, 12, 17)))
    _assert_every_reader_saw(seen, candles, _rows_through("2026-06-05"))


@pytest.mark.asyncio
async def test_as_of_is_the_fetch_time_not_the_wall_clock(monkeypatch):
    """A snapshot fetched at 15:00 and evaluated later still holds a partial bar."""
    class _Late(datetime):
        @classmethod
        def now(cls, tz=None):
            return _ny(2026, 6, 10, 17).astimezone(tz) if tz else _ny(2026, 6, 10, 17)

    monkeypatch.setattr(ms, "datetime", _Late)
    from app.routers import chart_alerts
    monkeypatch.setattr(chart_alerts, "datetime", _Late)
    candles = _daily(WED)
    seen = await _run(monkeypatch, "1D", candles, as_of=_ts(_ny(2026, 6, 10, 15)))
    assert seen["snap"] == [candles[:-1]]
    assert seen["hmm"] == [_rows_through("2026-06-09")]


@pytest.mark.asyncio
async def test_intraday_rules_unchanged_by_a4g(monkeypatch):
    """A 15min rule never reaches completed_session_bars' daily/weekly branch."""
    import app.data.market as market
    monkeypatch.setattr(market, "intraday_feed_lag_seconds", lambda: 0)
    as_of = _ts(_ny(2026, 6, 10, 11))
    candles = [{"time": as_of - 900 * (150 - i), "open": 50.0, "high": 50.5, "low": 49.5,
                "close": 50.0, "volume": 1} for i in range(150)]
    candles.append({"time": as_of - 60, "open": 50.0, "high": 50.0, "low": 50.0,
                    "close": FORMING, "volume": 1})
    from unittest.mock import AsyncMock
    from app.routers import chart_alerts
    monkeypatch.setattr(chart_alerts, "get_bars", AsyncMock(return_value=[]))
    seen = await _run(monkeypatch, "15min", candles, as_of=as_of)
    assert seen["snap"] == [candles[:-1]], "A4c's intraday trim only -- nothing more"
