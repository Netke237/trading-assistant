"""COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD unit A: momentum_match (plan 3.1) and
the evaluator's use of it (3.2). Plan tests 1-7, 12, 14 and 17; each names the
mutation it must kill.

Plan: docs/superpowers/plans/2026-09-29-composite-momentum-confirmations-plan.md
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date

import pytest

import app.services.indicator_compute as ic
from app.services.composite_trigger_evaluator import (
    MomentumInput, _matched_indexes, describe_match, evaluate_from_context,
    evaluate_scheduled, format_composite_reason, has_momentum, momentum_confirmation_error,
)
from app.services.indicator_compute import (
    _macd_last_two, _wilder_rsi_last_two, momentum_match, momentum_session_bars,
)
from tests.momentum_fixtures import (
    HOURLY_SLOTS, bar, daily_bars, et_ts, intraday_bars, osc_closes, session_times,
    weekdays, weekdays_before, with_last,
)

N = ic.MOMENTUM_RSI_MACD_HISTORY + 1          # 201


@pytest.fixture(autouse=True)
def _fresh_warnings():
    ic._momentum_warned.clear()
    yield
    ic._momentum_warned.clear()


def mm(bars, kind, direction=None, level=60, interval="1D", key="k"):
    return momentum_match(bars, interval, kind, direction, level, key)


def rsi_pair(closes):
    return _wilder_rsi_last_two(closes[-N:])


# ── test 1: per kind x direction ──────────────────────────────────────────────

UP = daily_bars(with_last(osc_closes(N - 1), 5))       # RSI up through 60
DOWN = daily_bars(with_last(osc_closes(N - 1), -5))    # RSI down through 40


def test_fixture_preconditions():
    prev, cur = rsi_pair([b["close"] for b in UP])
    assert prev <= 60 < cur
    prev, cur = rsi_pair([b["close"] for b in DOWN])
    assert prev >= 40 > cur and not (prev >= 60 > cur)


@pytest.mark.parametrize("direction, up, down", [
    ("Bullish", True, False), ("Bearish", False, True), (None, True, True),
])
def test_rsi_cross_direction(direction, up, down):
    """Mutations: ignore direction; drop 100-L; null = 'through L either way'."""
    assert mm(UP, "rsi_cross", direction) is up
    assert mm(DOWN, "rsi_cross", direction) is down


def test_rsi_null_does_not_match_down_through_L():
    """A fall through 60 (not through 40) is not a Bearish cross, so null (Bullish OR
    Bearish) does not match it. Mutation: null = 'through L either way'."""
    closes = with_last(osc_closes(N - 1), 25)       # RSI well above 60
    closes = closes + [closes[-1] - 18]             # ... then drops back below 60, above 40
    bars = daily_bars(closes)
    prev, cur = rsi_pair(closes)
    assert prev >= 60 > cur > 40
    assert mm(bars, "rsi_cross", None) is False
    assert mm(bars, "rsi_cross", "Bearish") is False


def test_rsi_prev_equal_to_level_edge():
    """Bullish is prev <= L < cur. Mutation: `<=` -> `<`."""
    prev, cur = rsi_pair([b["close"] for b in UP])
    lvl_prev = int(prev)
    if prev == lvl_prev:     # prev exactly on an integer level
        assert mm(UP, "rsi_cross", "Bullish", level=lvl_prev) is True
    # Force the edge with a stubbed RSI pair.
    orig = ic._wilder_rsi_last_two
    try:
        ic._wilder_rsi_last_two = lambda closes, period=14: (60.0, 61.0)
        assert mm(UP, "rsi_cross", "Bullish", level=60) is True
        ic._wilder_rsi_last_two = lambda closes, period=14: (60.0, 60.0)
        assert mm(UP, "rsi_cross", "Bullish", level=60) is False      # L < cur is strict
        ic._wilder_rsi_last_two = lambda closes, period=14: (40.0, 39.0)
        assert mm(UP, "rsi_cross", "Bearish", level=60) is True       # prev >= 100-L
        ic._wilder_rsi_last_two = lambda closes, period=14: (40.0, 40.0)
        assert mm(UP, "rsi_cross", "Bearish", level=60) is False
    finally:
        ic._wilder_rsi_last_two = orig


MACD_UP = daily_bars(with_last(osc_closes(N - 1), 4))
MACD_DOWN = daily_bars(with_last(osc_closes(N)[:-1], -4))


@pytest.mark.parametrize("bars, direction, expected", [
    (MACD_UP, "Bullish", True), (MACD_UP, "Bearish", False), (MACD_UP, None, True),
    (MACD_DOWN, "Bearish", True), (MACD_DOWN, "Bullish", False), (MACD_DOWN, None, True),
])
def test_macd_cross_direction(bars, direction, expected):
    (pl, ps), (cl, cs) = _macd_last_two([b["close"] for b in bars][-N:])
    assert (pl <= ps and cl > cs) or (pl >= ps and cl < cs)
    assert mm(bars, "macd_cross", direction) is expected


def _vol_bars(last_volume, last_open, last_close):
    closes = [100.0] * 30 + [last_close]
    opens = [100.0] * 30 + [last_open]
    return daily_bars(closes, volumes=[1000] * 30 + [last_volume], opens=opens)


@pytest.mark.parametrize("direction, open_, close, expected", [
    ("Bullish", 100, 101, True), ("Bullish", 101, 100, False),
    ("Bearish", 101, 100, True), ("Bearish", 100, 101, False),
    (None, 101, 100, True), (None, 100, 101, True),
])
def test_volume_spike_candle_colour(direction, open_, close, expected):
    """Mutation: ignore direction (the wrong candle colour must not match)."""
    assert mm(_vol_bars(2000, open_, close), "volume_spike", direction) is expected


def test_volume_spike_ratio_edge():
    assert mm(_vol_bars(2000, 100, 101), "volume_spike", "Bullish") is True
    assert mm(_vol_bars(1999, 100, 101), "volume_spike", "Bullish") is False


# ── test 2: MACD from a correct EMA ──────────────────────────────────────────

def test_macd_spike_on_the_last_bar_crosses_on_that_bar():
    """Mutation: reuse the lagged _ema_values (it does not fold the current bar
    in, so a last-bar spike cannot move the line on that bar)."""
    assert mm(MACD_UP, "macd_cross", "Bullish") is True
    lagged = ic._calc_macd([b["close"] for b in MACD_UP], [b["time"] for b in MACD_UP], 12, 26, 9)
    assert not (lagged["macd"][-2] <= lagged["signal"][-2] and lagged["macd"][-1] > lagged["signal"][-1])


def test_ema_seeded_is_the_textbook_ema():
    assert ic._ema_seeded([1.0] * 30 + [100.0], 3)[-1] == pytest.approx(50.5)
    assert ic._ema_seeded([1.0, 2.0, 3.0], 3) == [None, None, 2.0]


# ── test 3: history ──────────────────────────────────────────────────────────

def test_201_bars_judged_200_not(caplog):
    """Mutation: min 200 instead of 201."""
    assert mm(UP, "rsi_cross", "Bullish") is True
    with caplog.at_level(logging.WARNING):
        assert mm(UP[1:], "rsi_cross", "Bullish", key="short") is False
        assert mm(UP[1:], "rsi_cross", "Bullish", key="short") is False
        assert mm(UP[1:], "macd_cross", "Bullish", key="short") is False
    msgs = [r for r in caplog.records if "history" in r.getMessage()]
    assert len(msgs) == 2          # once per (id, kind)


def test_only_the_last_201_bars_are_read():
    """A huge move just before the window moves full-history Wilder RSI; the
    window answer must not change with 300 vs 1500 bars. Mutation: drop the slice."""
    import random
    rnd = random.Random(7)
    closes = [100.0]
    for _ in range(1298):
        closes.append(closes[-1] + rnd.choice((-1.0, 1.0)))
    closes.append(closes[-1] + 1e7)                 # outside the 201-bar window
    for _ in range(200):
        closes.append(closes[-1] + rnd.choice((-1.0, 1.0)) * rnd.random())
    bars = daily_bars(closes)
    assert len(bars) == 1500
    window = closes[-N:]
    full_prev, full_cur = _full_rsi_last_two(closes)
    win_prev, win_cur = _wilder_rsi_last_two(window)
    disagree = []
    for lvl in range(1, 100):
        w = (win_prev <= lvl < win_cur) or (win_prev >= 100 - lvl > win_cur)
        f = (full_prev <= lvl < full_cur) or (full_prev >= 100 - lvl > full_cur)
        a_short = mm(bars[-300:], "rsi_cross", None, level=lvl)
        a_long = mm(bars, "rsi_cross", None, level=lvl)
        assert a_short is a_long is w
        if w != f:
            disagree.append(lvl)
    assert (full_prev, full_cur) != (win_prev, win_cur)
    assert disagree, "fixture must make the full-history RSI answer differ at some level"


def _full_rsi_last_two(closes):
    return _wilder_rsi_last_two(closes)


# ── test 4: volume baselines ─────────────────────────────────────────────────

def _hourly(days, open_vol, other_vol, judged_vol, *, judged_open=100.0, judged_close=101.0):
    """1h regular bars (09:30..15:30 ET) over `days`, plus the judged 09:30 bar the day after."""
    times = session_times(days[:-1], HOURLY_SLOTS) + [et_ts(days[-1], 9, 30)]
    vols = [open_vol if i % 7 == 0 else other_vol for i in range(len(times) - 1)] + [judged_vol]
    closes = [100.0] * (len(times) - 1) + [judged_close]
    opens = [100.0] * (len(times) - 1) + [judged_open]
    return intraday_bars(times, closes, vols, opens)


def test_open_bar_compared_with_its_slot_not_the_previous_20_bars():
    """Mutation: prior-20 intraday baseline (U-shaped volume flags every open)."""
    days = weekdays(date(2025, 3, 3), 12)
    bars = _hourly(days, open_vol=1000, other_vol=100, judged_vol=1500)
    prior20 = sum(b["volume"] for b in bars[-21:-1]) / 20
    assert 1500 >= 2 * prior20
    assert mm(bars, "volume_spike", "Bullish", interval="1h") is False
    bars = _hourly(days, open_vol=1000, other_vol=100, judged_vol=2000)
    assert mm(bars, "volume_spike", "Bullish", interval="1h") is True


def test_zero_volume_symbol_and_missing_volume_are_not_matched():
    """Mutation: drop `baseline > 0`."""
    days = weekdays(date(2025, 3, 3), 12)
    assert mm(_hourly(days, 0, 0, 0), "volume_spike", None, interval="1h") is False
    zero_base = _hourly(days, 0, 0, 5)
    assert mm(zero_base, "volume_spike", None, interval="1h") is False
    missing = _hourly(days, 100, 100, 1000)
    missing[-1] = {k: v for k, v in missing[-1].items() if k != "volume"}
    assert mm(missing, "volume_spike", None, interval="1h") is False
    nan = _hourly(days, 100, 100, 1000)
    nan[-1]["volume"] = float("nan")
    assert mm(nan, "volume_spike", None, interval="1h") is False


def test_slot_baseline_needs_five_sessions(caplog):
    days = weekdays(date(2025, 3, 3), 5)          # 4 earlier sessions + the judged day
    with caplog.at_level(logging.WARNING):
        assert mm(_hourly(days, 100, 100, 10_000), "volume_spike", None, interval="1h", key="w") is False
    assert any("slot" in r.getMessage() for r in caplog.records)
    days = weekdays(date(2025, 3, 3), 6)          # 5 earlier sessions
    assert mm(_hourly(days, 100, 100, 10_000), "volume_spike", None, interval="1h") is True


def test_daily_needs_twenty_prior_bars():
    closes = [100.0] * 19 + [101.0]
    assert mm(daily_bars(closes, volumes=[1000] * 19 + [5000], opens=[100.0] * 20),
              "volume_spike", "Bullish") is False
    closes = [100.0] * 20 + [101.0]
    assert mm(daily_bars(closes, volumes=[1000] * 20 + [5000], opens=[100.0] * 21),
              "volume_spike", "Bullish") is True


def _five_min_session(d, open_vol, later_vol):
    """09:30 and 10:30 5min bars of one session (enough for the slot key)."""
    return [bar(et_ts(d, 9, 30), 100.0, volume=open_vol), bar(et_ts(d, 10, 30), 100.0, volume=later_vol)]


def test_5min_open_after_november_dst_switch_uses_eastern_slot():
    """Mutation: UTC time-of-day slot (after the switch 09:30 EST == 10:30 EDT in UTC)."""
    before = weekdays_before(date(2025, 11, 3), 6)            # EDT sessions
    judged_day = date(2025, 11, 3)                              # first EST session
    bars = [b for d in before for b in _five_min_session(d, open_vol=1000, later_vol=100)]
    judged = bar(et_ts(judged_day, 9, 30), 101.0, open_=100.0, volume=1500)
    assert mm(bars + [judged], "volume_spike", "Bullish", interval="5min") is False
    judged = bar(et_ts(judged_day, 9, 30), 101.0, open_=100.0, volume=2000)
    assert mm(bars + [judged], "volume_spike", "Bullish", interval="5min") is True


def test_tradier_premarket_bar_never_in_the_open_baseline():
    days = weekdays(date(2025, 3, 3), 7)
    bars = []
    for d in days[:-1]:
        bars += [bar(et_ts(d, 9, 25), 100.0, volume=1), bar(et_ts(d, 9, 30), 100.0, volume=1000)]
    bars.append(bar(et_ts(days[-1], 9, 30), 101.0, open_=100.0, volume=2000))
    assert mm(bars, "volume_spike", "Bullish", interval="5min") is True
    assert all(b["time"] != et_ts(days[0], 9, 25) for b in momentum_session_bars(bars, "5min"))


def test_4h_baseline_across_dst_uses_only_its_own_regime():
    """4h UTC-epoch buckets start 08:00 ET (EDT) but 07:00 ET (EST): the Eastern
    slot key alone separates them. Mutation: UTC time-of-day slot."""
    edt = weekdays_before(date(2025, 11, 3), 10)
    est = weekdays(date(2025, 11, 3), 4)
    bars = [bar(et_ts(d, 8, 0), 100.0, volume=100) for d in edt]
    bars += [bar(et_ts(d, 7, 0), 100.0, volume=100) for d in est[:-1]]
    bars.append(bar(et_ts(est[-1], 7, 0), 101.0, open_=100.0, volume=10_000))
    assert mm(bars, "volume_spike", "Bullish", interval="4h") is False   # 3 EST sessions < 5


# ── test 5: normalisation ────────────────────────────────────────────────────

def test_direction_is_case_insensitive():
    assert mm(UP, "rsi_cross", "bullish") is True
    assert mm(UP, "rsi_cross", "BULLISH") is True
    assert mm(UP, "rsi_cross", "up") is False


@pytest.mark.parametrize("level", ["60", True, 0, 100, 60.0, None.__class__])
def test_bad_rsi_level_is_not_matched_and_never_raises(level):
    assert mm(UP, "rsi_cross", "Bullish", level=level) is False


def test_missing_level_uses_the_schema_default():
    assert mm(UP, "rsi_cross", "Bullish", level=None) is True


def test_unknown_kind_and_bad_rows_are_false():
    assert mm(UP, "rsi_crossing", None) is False
    assert mm([], "rsi_cross", None) is False
    broken = [dict(b) for b in UP]
    broken[-5]["close"] = float("nan")
    assert mm(broken, "rsi_cross", "Bullish") is False
    assert mm(UP, "rsi_cross", None, interval="3h") is False
    assert momentum_match(None, "1D", "rsi_cross", None, 60, "k") is False   # guarded, never raises


# ── test 6: standard rules unchanged ─────────────────────────────────────────

_STANDARD_NAMES = ["ema", "ema9", "ema50", "sma", "sma50", "rsi", "macd", "macd_signal", "atr",
                   "bb_upper", "bb_lower", "bb_mid", "vwap", "volume", "close"]
# Pinned on main's indicator_compute (these functions are unchanged by this build).
_GOLDEN_SHA = "8de19a4ad8d4bb355ebe6b2812ace8b65b12196fca0da7193208f164518ac098"


def _golden_payload():
    import random
    rnd = random.Random(3)
    days = weekdays(date(2025, 3, 3), 40)
    times = session_times(days, HOURLY_SLOTS)
    c, candles = 100.0, []
    for t in times:
        o = c
        c = round(c + rnd.uniform(-1, 1), 4)
        candles.append({"time": t, "open": o, "high": max(o, c) + 0.3, "low": min(o, c) - 0.3,
                        "close": c, "volume": rnd.randint(100, 1000)})
    conds = [{"kind": "indicator", "indicator": n} for n in _STANDARD_NAMES]
    out = ic.compute_indicators_for_conditions(candles, conds)
    return json.dumps(out, sort_keys=True)


def test_standard_rule_indicators_byte_for_byte_unchanged():
    assert hashlib.sha256(_golden_payload().encode()).hexdigest() == _GOLDEN_SHA


# ── test 7: the indicator_values leak is gone ────────────────────────────────

def test_a_standard_series_named_rsi_cross_no_longer_satisfies_a_composite():
    td = {"primary": {"model": "any"}, "min_confirmations": 1,
          "confirmations": [{"type": "momentum", "signal_kind": "rsi_cross", "min_confidence": 60}]}
    assert evaluate_from_context(td, None, [], {"rsi_cross": 99.0}) is False
    flat = MomentumInput(daily_bars([100.0] * N), "1D", "k")
    assert evaluate_from_context(td, None, [], {"rsi_cross": 99.0}, momentum=flat) is False
    assert evaluate_from_context(td, None, [], {}, momentum=MomentumInput(UP, "1D", "k")) is True


# ── test 12: three-valued gate, one count ────────────────────────────────────

_MOM = {"type": "momentum", "signal_kind": "rsi_cross", "direction": "Bullish", "min_confidence": 60}
_BOS = {"type": "structure", "signal_kind": "BOS", "direction": "Bullish", "min_confidence": 0}


def _sched(td, momentum, bars_daily=None, monkeypatch=None):
    return evaluate_scheduled("AAPL", td, bars_daily if bars_daily is not None else daily_bars([100.0] * 5), [],
                              unknown_as_none=True, momentum=momentum)


def test_momentum_false_with_structure_raising_is_false(monkeypatch):
    """momentum-only trigger: structure detection raising must not turn a
    definite momentum False into no reading. Mutation: OR instead of the count."""
    import app.services.market_structure as ms
    monkeypatch.setattr(ms, "compute_structure", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    td = {"primary": {"model": "any"}, "min_confirmations": 1, "confirmations": [_MOM]}
    flat = MomentumInput(daily_bars([100.0] * N), "1D", "k")
    assert _sched(td, flat) is False


def test_momentum_unread_is_no_reading_only_when_it_could_reach_the_minimum(monkeypatch):
    import app.services.market_structure as ms
    monkeypatch.setattr(ms, "compute_structure", lambda *a, **k: [])
    td = {"primary": {"model": "any"}, "min_confirmations": 1, "confirmations": [_BOS, _MOM]}
    assert _sched(td, None) is None                           # 0 + 1 unread >= 1
    td2 = {**td, "min_confirmations": 2}
    assert _sched(td2, None) is False                         # BOS read, not met: 0 + 1 < 2
    monkeypatch.setattr(ms, "compute_structure",
                        lambda *a, **k: [{"kind": "BOS", "direction": "bullish", "confidence": 90}])
    assert _sched(td2, None) is None                          # 1 + 1 >= 2
    assert _sched(td, None) is True                           # BOS alone meets 1


def test_rule_path_momentum_none_fails_closed():
    td = {"primary": {"model": "any"}, "min_confirmations": 1, "confirmations": [_MOM]}
    assert evaluate_from_context(td, None, [], {}, momentum=None) is False


# ── has_momentum / validation ────────────────────────────────────────────────

def test_has_momentum_needs_a_positive_minimum():
    assert has_momentum({"confirmations": [_MOM]}) is True                   # default min 1
    assert has_momentum({"confirmations": [_MOM], "min_confirmations": 0}) is False
    assert has_momentum({"confirmations": [_BOS]}) is False
    assert has_momentum(None) is False


@pytest.mark.parametrize("conf, ok", [
    (_MOM, True), ({**_MOM, "direction": None}, True), ({**_MOM, "direction": "bearish"}, True),
    ({**_MOM, "min_confidence": 0}, False), ({**_MOM, "min_confidence": "60"}, False),
    ({**_MOM, "min_confidence": True}, False), ({**_MOM, "min_confidence": 100}, False),
    ({**_MOM, "signal_kind": "rsi"}, False), ({**_MOM, "direction": "up"}, False),
    ({"type": "momentum", "signal_kind": "macd_cross", "min_confidence": 0}, True),
    ({"type": "momentum", "signal_kind": "rsi_cross"}, True),
    (_BOS, True),
])
def test_momentum_confirmation_error(conf, ok):
    assert (momentum_confirmation_error({"confirmations": [conf]}) is None) is ok


# ── test 14: checklist marks the right row ───────────────────────────────────

def test_checklist_marks_by_index_not_kind():
    """Mutation: match by kind (both rsi_cross rows would read met)."""
    from app.routers.chart_alerts import _composite_checklist
    closes = with_last(osc_closes(N - 1), 5)
    prev, cur = _wilder_rsi_last_two(closes[-N:])
    assert prev <= 60 < cur and not cur > 70
    td = {"primary": {"model": "any"}, "min_confirmations": 1, "confirmations": [
        {**_MOM, "min_confidence": 60}, {**_MOM, "min_confidence": 70}]}
    detail = describe_match(td, structure_signals=[], momentum=MomentumInput(daily_bars(closes), "1D", "k"))
    assert detail["matched_indexes"] == [0]
    assert detail["momentum_matched"] == ["rsi_cross"] and detail["momentum_total"] == 2
    assert detail["structure_total"] == 0
    rows = _composite_checklist(td, detail)
    assert [r["met"] for r in rows[1:]] == [True, False]
    assert rows[1]["label"] == "RSI crosses up through 60"
    assert "1/2 momentum confirmations (rsi_cross)" in format_composite_reason("Bull", detail)


def test_checklist_fallback_without_matched_indexes():
    from app.routers.chart_alerts import _composite_checklist
    td = {"confirmations": [_MOM, _BOS]}
    rows = _composite_checklist(td, {"structure_matched": ["BOS"], "strategy_matched": []})
    assert [r["met"] for r in rows[1:]] == [False, True]
    rows = _composite_checklist(td, {"structure_matched": [], "momentum_matched": ["rsi_cross"],
                                     "strategy_matched": []})
    assert [r["met"] for r in rows[1:]] == [True, False]


# ── test 17: regular session only (Q11, span overlap) ────────────────────────

def test_session_filter_edges_5min():
    """A 09:25 5min bar ends at 09:30; a 16:00 bar starts at the close: both out.
    Mutation: overlap test with `<=` at the edges."""
    d = date(2025, 3, 4)
    bars = [bar(et_ts(d, 9, 25), 1), bar(et_ts(d, 9, 30), 1), bar(et_ts(d, 15, 55), 1), bar(et_ts(d, 16, 0), 1)]
    kept = [b["time"] for b in momentum_session_bars(bars, "5min")]
    assert kept == [et_ts(d, 9, 30), et_ts(d, 15, 55)]


def _regular_5min(days):
    slots = [(9, 30 + 5 * i) for i in range(6)]
    return session_times(days, slots)


def test_extended_hours_bars_are_not_rsi_inputs():
    """Post-market bars that would erase the cross are ignored. Mutation: no session filter."""
    days = weekdays(date(2025, 3, 3), 40)
    times = _regular_5min(days)
    closes = with_last(osc_closes(len(times) - 1), 5)
    regular = intraday_bars(times, closes)
    assert mm(regular, "rsi_cross", "Bullish", interval="5min") is True
    # Tradier-style post-market run-up the evening before the judged bar.
    evening = days[-2]
    extra = [bar(et_ts(evening, 16, 5 * (i + 1)), closes[-2] + 3 * (i + 1)) for i in range(8)]
    mixed = sorted(regular + extra, key=lambda b: b["time"])
    assert mm(mixed, "rsi_cross", "Bullish", interval="5min") is True


def test_a_judged_post_market_bar_is_not_matched():
    days = weekdays(date(2025, 3, 3), 40)
    times = _regular_5min(days)
    closes = osc_closes(len(times))
    bars = intraday_bars(times, closes) + [bar(et_ts(days[-1], 16, 30), closes[-1] + 50, volume=10**9)]
    for kind in ("rsi_cross", "macd_cross", "volume_spike"):
        assert mm(bars, kind, None, interval="5min") is False


@pytest.mark.parametrize("first_day, morning", [
    (date(2025, 5, 5), (8, 0)),      # EDT: morning bucket stamped 08:00 ET
    (date(2025, 12, 1), (7, 0)),     # EST: 07:00 ET
])
def test_4h_morning_bucket_is_regular_and_judged(first_day, morning):
    """Mutation: classify by start time (drops every morning 4h bar)."""
    days = weekdays(first_day, 110)
    slots = [morning, (morning[0] + 4, 0)]
    times = session_times(days, slots)
    closes = with_last(osc_closes(len(times) - 2), 5)       # the judged bar is a morning bar
    times = times[:len(closes)]
    bars = intraday_bars(times, closes)
    assert len(momentum_session_bars(bars, "4h")) == len(bars)
    assert mm(bars, "rsi_cross", "Bullish", interval="4h") is True
    # The same reading as the unfiltered 4h RSI on a regular-only source.
    assert _wilder_rsi_last_two(closes[-N:]) == _wilder_rsi_last_two(
        [b["close"] for b in momentum_session_bars(bars, "4h")][-N:])


def test_daily_and_weekly_are_not_filtered():
    bars = [bar(et_ts(date(2025, 3, 3), 0, 0), 1)]
    assert momentum_session_bars(bars, "1D") == bars
    assert momentum_session_bars(bars, "1W") == bars
    assert momentum_session_bars(bars, "bogus") == []
