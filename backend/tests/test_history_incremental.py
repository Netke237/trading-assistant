"""B1 (HISTORY-INCREMENTAL-NIGHTLY plan 2.2-2.6, section 5): the pure nightly classifier.

Every fixture is built from one stored history (Tiingo prefix + Alpaca suffix with a
verified seam) and tonight's Alpaca reply. Factors follow the stored model: a row's
``adj_factor`` is ``BASE`` times the step ratio ``s(E)`` of every ex-date E after it.
Trading days are weekdays; F is the ET date of ``floor_checked_at`` (fetched 20:00 ET).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.ohlcv_daily import OhlcvHistoryStateModel as State
from app.services import historical_store as hs
from app.services import history_incremental as hi
from app.services.history_basis import seam_signature

ET = hs.MARKET_TZ
START = date(2020, 6, 1)    # Monday
SEAM = date(2020, 7, 27)    # Monday: Alpaca's first date; R = 07-27 .. 07-31
R = [date(2020, 7, 27) + timedelta(days=i) for i in range(5)]
BASE = 0.5
PREFIX_FACTOR = 0.95
L = 5
K = hi.NightlyKind


def wd(d: date, n: int) -> date:
    """``d`` moved ``n`` weekdays (test-side reference, independent of the module)."""
    step = 1 if n >= 0 else -1
    while n:
        d += timedelta(days=step)
        if d.weekday() < 5:
            n -= step
    return d


def weekdays(a: date, b: date) -> list[date]:
    out = []
    while a <= b:
        if a.weekday() < 5:
            out.append(a)
        a += timedelta(days=1)
    return out


def et(d: date, hour: int = 20) -> datetime:
    return datetime.combine(d, time(hour), tzinfo=ET)


def close_of(d: date) -> float:
    return 100 + (d.toordinal() % 7) * 0.25


def factor(d: date, events: dict, base: float = BASE) -> float:
    f = base
    for e, s in events.items():
        if d < e:
            f *= s
    return f


def q(x, places: str) -> Decimal:
    return Decimal(str(x)).quantize(Decimal(places))


def bar(d: date, close: float, f: float, source: str = "alpaca") -> dict:
    return {"time": d.isoformat(), "open": close, "high": close + 1, "low": close - 1,
            "close": close, "volume": 100, "adj_factor": f, "split_factor": 1.0,
            "div_cash": 0.0, "source": source}


@dataclass
class Scenario:
    state: State | None
    rows: list
    bars: list
    now: datetime

    def classify(self, **kw):
        with patch.object(hs, "_utcnow", return_value=self.now):
            return hi.classify_nightly_symbol(self.state, self.rows, self.bars, START, self.now, **kw)


def build(today: date, F: date, stored_events: dict | None = None,
          tonight_events: dict | None = None, *, f_hour: int = 20,
          tonight_scale: float = 1.0, drop: tuple = ()) -> Scenario:
    """Stored rows written by last night's write (through the weekday before ``today``);
    tonight's Alpaca reply runs from the seam through ``today``. ``drop`` removes dates
    from both (a missing IEX bar)."""
    stored_events = stored_events or {}
    tonight_events = stored_events if tonight_events is None else tonight_events
    stored_through = wd(today, -1)
    prefix_dates = weekdays(START, SEAM - timedelta(days=1))
    suffix_dates = [d for d in weekdays(SEAM, stored_through) if d not in drop]
    prefix_fetched = et(F, f_hour)
    suffix_fetched = et(stored_through, 20)
    rows = [(d, q(close_of(d), "0.0001"), q(PREFIX_FACTOR, "0.00000001"), Decimal(1), Decimal(0),
             "tiingo", prefix_fetched) for d in prefix_dates]
    rows += [(d, q(close_of(d), "0.0001"), q(factor(d, stored_events), "0.00000001"), Decimal(1),
              Decimal(0), "alpaca", suffix_fetched) for d in suffix_dates]
    boundary = len(prefix_dates)
    state = State(symbol="TEST", floor_requested_start=START, floor_date=START,
                  floor_provider="tiingo", floor_checked_at=prefix_fetched, seam_date=SEAM,
                  old_source="tiingo", seam_signature=seam_signature(rows[boundary - 1], rows[boundary]),
                  basis_provider=None)
    bars = [bar(d, close_of(d), factor(d, tonight_events) * tonight_scale)
            for d in weekdays(SEAM, today) if d not in drop]
    return Scenario(state, rows, bars, et(today, 21))


DEFAULT_TODAY = date(2020, 10, 1)   # Thursday
DEFAULT_F = date(2020, 9, 30)


def default() -> Scenario:
    return build(DEFAULT_TODAY, DEFAULT_F)


# ── 2.2 table: one test per action ──────────────────────────────────────────

def test_suffix_only_when_every_trust_condition_holds():
    action = default().classify()
    assert action.kind == K.SUFFIX_ONLY
    assert action.ratio is None and action.revalidation_due is False
    assert action.prefix_age_days == 1


def test_rescale_on_a_new_event_after_the_prefix_fetch():
    e = date(2020, 9, 29)
    sc = build(date(2020, 9, 30), date(2020, 9, 25), {}, {e: 0.995})
    action = sc.classify()
    assert action.kind == K.RESCALE
    assert abs(float(action.ratio) - 0.995) < 1e-9


def test_confirm_under_d1a_once_the_lag_window_is_over():
    e = date(2020, 9, 2)                       # Wednesday
    F = date(2020, 8, 28)                      # before P(E) = 09-01
    sc = build(wd(e, L), F, {e: 0.99})         # today = E + L
    assert sc.classify().kind == K.CONFIRM


def test_revalidate_only_for_a_selected_due_symbol():
    sc = build(DEFAULT_TODAY, DEFAULT_TODAY - timedelta(days=100))
    selected = sc.classify(revalidate=True)
    assert selected.kind == K.REVALIDATE and selected.prefix_age_days == 100
    unselected = sc.classify()
    assert unselected.kind == K.SUFFIX_ONLY and unselected.revalidation_due is True


def test_full_when_there_is_no_state_row():
    sc = default()
    sc.state = None
    action = sc.classify()
    assert action.kind == K.FULL and action.reason == "no_state"


def test_single_provider_current_recent_and_full():
    now = et(date(2020, 10, 3), 21)            # Saturday: last boundary Fri 10-02 18:00 ET
    tiingo = State(symbol="SPY", basis_provider="tiingo", window_verified_through=date(2020, 10, 2),
                   window_verified_at=et(date(2020, 10, 2), 20))
    assert hi.classify_nightly_symbol(tiingo, [], [], START, now).kind == K.SINGLE_PROVIDER_CURRENT
    stale = replace_state(tiingo, window_verified_at=et(date(2020, 10, 2), 17))
    action = hi.classify_nightly_symbol(stale, [], [], START, now)
    assert action.kind == K.SINGLE_PROVIDER_RECENT
    yf = State(symbol="YF", basis_provider="yfinance")
    action = hi.classify_nightly_symbol(yf, [], [], START, now)
    assert action.kind == K.SINGLE_PROVIDER_FULL and action.reason == "yfinance_basis"


def replace_state(state: State, **changes) -> State:
    fields = ("symbol", "floor_requested_start", "floor_date", "floor_provider", "floor_checked_at",
              "seam_date", "old_source", "seam_signature", "basis_provider", "basis_rebuilt_at",
              "window_verified_through", "window_verified_at")
    values = {f: getattr(state, f) for f in fields}
    values.update(changes)
    return State(**values)


# ── Trust conditions, each failing on its own ────────────────────────────────

@pytest.mark.parametrize("change", [
    {"basis_provider": None, "old_source": None},
    {"old_source": "alpaca"},
    {"seam_signature": None},
])
def test_t1_state_mismatch_is_full(change):
    sc = default()
    sc.state = replace_state(sc.state, **change)
    action = sc.classify()
    assert action.kind == K.FULL and action.reason == "T1"


def test_seam_date_moved_is_full():
    sc = default()
    earlier = wd(SEAM, -1)                     # Alpaca now reaches one day further back
    sc.bars.insert(0, bar(earlier, close_of(earlier), BASE))
    action = sc.classify()
    assert action.kind == K.FULL and action.reason == "T1"


def test_t2_changed_prefix_row_is_full():
    sc = default()
    i = next(i for i, r in enumerate(sc.rows) if r[0] == SEAM) - 1
    d, c, f, sf, dc, src, fetched = sc.rows[i]
    sc.rows[i] = (d, c, f, sf, dc, src, fetched + timedelta(seconds=1))
    action = sc.classify()
    assert action.kind == K.FULL and action.reason == "T2"


def test_t2_wrong_prefix_source_is_full():
    sc = default()
    d, c, f, sf, dc, src, fetched = sc.rows[3]
    sc.rows[3] = (d, c, f, sf, dc, "yfinance", fetched)
    action = sc.classify()
    assert action.kind == K.FULL and action.reason == "T2"


def test_t3_gap_in_prefix_is_full():
    sc = default()
    gap = set(weekdays(date(2020, 6, 15), date(2020, 6, 23)))   # 9 calendar days missing
    sc.rows = [r for r in sc.rows if r[0] not in gap]
    action = sc.classify()
    assert action.kind == K.FULL and action.reason == "T3"


def test_t3_late_first_row_needs_the_observed_provider_floor():
    sc = default()
    cut = date(2020, 6, 15)
    sc.rows = [r for r in sc.rows if r[0] >= cut]
    action = sc.classify()
    assert action.kind == K.FULL and action.reason == "T3"
    sc.state = replace_state(sc.state, floor_date=cut)
    assert sc.classify().kind == K.SUFFIX_ONLY
    sc.state = replace_state(sc.state, floor_provider=None)
    assert sc.classify().reason == "T3"


def test_t4_reference_date_not_stored_is_full():
    sc = default()
    sc.rows = [r for r in sc.rows if r[0] != R[2]]
    action = sc.classify()
    assert action.kind == K.FULL and action.reason == "T4"


def test_t4_alpaca_dropped_a_stored_date_is_full():
    sc = default()
    dropped = date(2020, 9, 15)
    sc.bars = [b for b in sc.bars if b["time"] != dropped.isoformat()]
    action = sc.classify()
    assert action.kind == K.FULL and action.reason == "T4"


def test_t5_unexplained_change_is_full():
    sc = build(DEFAULT_TODAY, DEFAULT_F, tonight_scale=0.99)
    action = sc.classify()
    assert action.kind == K.FULL and action.reason == "unexplained_adjustment"


# ── T6 boundaries (P(E) - 1, P(E) at 20:00 ET, E, E + L - 1, E + L) ─────────

# Monday ex-date: P(E) is the Friday before (weekend between P(E) and E).
# Wednesday ex-date: E + L is the next Wednesday (weekend between E and E + L), so a
# calendar-day reading of E + L - 1 (= Monday) would wrongly trust the prefix.
@pytest.mark.parametrize("e", [date(2020, 8, 17), date(2020, 8, 19)])
@pytest.mark.parametrize("offset,trusted", [
    ("P-1", True), ("P", False), ("E", False), ("E+L-1", False), ("E+L", True),
])
def test_t6_lag_window_boundaries(e, offset, trusted):
    p = wd(e, -1)
    F = {"P-1": wd(p, -1), "P": p, "E": e, "E+L-1": wd(e, L - 1), "E+L": wd(e, L)}[offset]
    sc = build(wd(max(F, e), 1), F, {e: 0.99})
    action = sc.classify()
    if trusted:
        # F = P(E) - 1 at 20:00 ET is P(E) in UTC: trusted only because F is read in ET.
        assert action.kind == K.SUFFIX_ONLY, action
    else:
        assert action.kind == K.FULL and action.reason == "T6_lag_window", action


@pytest.mark.parametrize("which,trusted", [
    ("P-1", True), ("P", False), ("E'+L-1", False), ("E'+L", True),
])
def test_t6_with_the_bar_on_e_missing_opens_at_p_of_the_visible_step(which, trusted):
    e = date(2020, 8, 19)                      # ex-date, no Alpaca bar
    e2 = date(2020, 8, 20)                     # the step shows on E'
    p = date(2020, 8, 18)                      # P(E') = P(E)
    F = {"P-1": wd(p, -1), "P": p, "E'+L-1": wd(e2, L - 1), "E'+L": wd(e2, L)}[which]
    sc = build(wd(max(F, e2), 1), F, {e: 0.99}, drop=(e,))
    events = hi.alpaca_event_dates(
        {hs._bar_date(b): b for b in sc.bars}, Decimal("1e-6"))
    assert [(ev.date, ev.prev_date) for ev in events] == [(e2, p)]
    action = sc.classify()
    assert (action.kind == K.SUFFIX_ONLY) if trusted else (action.reason == "T6_lag_window"), action


def test_lag_exposed_helper():
    ev = hi.AdjustmentEvent(date=date(2020, 8, 17), prev_date=date(2020, 8, 14), ratio=Decimal("0.99"))
    assert not hi.lag_exposed(date(2020, 8, 13), ev, L)
    assert hi.lag_exposed(date(2020, 8, 14), ev, L)
    assert hi.lag_exposed(date(2020, 8, 21), ev, L)
    assert not hi.lag_exposed(date(2020, 8, 24), ev, L)


def test_add_trading_days_skips_weekends():
    assert hi.add_trading_days(date(2020, 8, 19), 5) == date(2020, 8, 26)
    assert hi.add_trading_days(date(2020, 8, 17), -1) == date(2020, 8, 14)
    assert hi.add_trading_days(date(2020, 8, 17), 0) == date(2020, 8, 17)


# ── New events (2.4) ────────────────────────────────────────────────────────

def ev(d: date, ratio: str) -> hi.AdjustmentEvent:
    return hi.AdjustmentEvent(date=d, prev_date=wd(d, -1), ratio=Decimal(ratio))


def test_new_events_new_step_changed_step_unchanged_ignored():
    tol = Decimal("1e-6")
    stored = [ev(date(2020, 8, 17), "0.99"), ev(date(2020, 9, 1), "0.995")]
    tonight = [ev(date(2020, 8, 17), "0.99"), ev(date(2020, 9, 1), "0.994"), ev(date(2020, 9, 21), "0.98")]
    found = hi.new_events(stored, tonight, tol)
    assert [(e.date, r) for e, r in found] == [
        (date(2020, 9, 1), Decimal("0.994") / Decimal("0.995")),
        (date(2020, 9, 21), Decimal("0.98")),
    ]
    assert hi.new_events(stored, stored, tol) == []


def test_rescale_ignores_unchanged_older_steps():
    e1, e2 = date(2020, 8, 17), date(2020, 9, 29)
    sc = build(date(2020, 9, 30), date(2020, 9, 25), {e1: 0.99}, {e1: 0.99, e2: 0.995})
    action = sc.classify()
    assert action.kind == K.RESCALE and abs(float(action.ratio) - 0.995) < 1e-9


def test_rescale_two_new_events_in_one_night_compose():
    e1, e2 = date(2020, 9, 28), date(2020, 9, 30)
    sc = build(date(2020, 10, 1), date(2020, 9, 23), {}, {e1: 0.995, e2: 0.99})
    action = sc.classify()
    assert action.kind == K.RESCALE and abs(float(action.ratio) - 0.995 * 0.99) < 1e-9


def test_rescale_changed_step_after_the_fetch_uses_new_over_old():
    e = date(2020, 9, 28)
    sc = build(date(2020, 10, 1), date(2020, 9, 23), {e: 0.99}, {e: 0.985})
    action = sc.classify()
    assert action.kind == K.RESCALE and abs(float(action.ratio) - 0.985 / 0.99) < 1e-9


def test_rescale_refused_when_the_other_provider_led_alpaca_inside_the_window():
    e = date(2020, 9, 29)
    sc = build(date(2020, 9, 30), wd(e, -1), {}, {e: 0.995})     # F = P(E)
    action = sc.classify()
    assert action.kind == K.FULL and action.reason == "T6_lag_window"


def test_rescale_refused_when_the_step_product_disagrees_with_r_a():
    e = date(2020, 9, 29)
    sc = build(date(2020, 9, 30), date(2020, 9, 25), {}, {e: 0.99}, tonight_scale=0.998)
    action = sc.classify()
    assert action.kind == K.FULL and action.reason == "ratio_product_mismatch"


# ── Condition (iii) isolated (R4-F1): T1-T6 all hold, only (iii) refuses ────

def test_r4f1_a_alpaca_applies_a_dividend_late_after_a_revalidate_fetch():
    """Alpaca's step at X first appears on a night with F = X + L + 1 trading days: the
    prefix (fetched by a REVALIDATE after the other provider applied the 0.4 % dividend)
    already carries it, so a rescale would apply it twice."""
    x = date(2020, 9, 2)                       # after R[4]
    F = wd(x, L + 1)                           # 2020-09-10: past X + L, so T6 holds
    sc = build(wd(F, 1), F, {}, {x: 0.996})
    p = wd(x, -1)
    assert p <= F and not F < hi.add_trading_days(x, L)            # T6 holds for X
    action = sc.classify()
    assert action.kind == K.FULL and action.reason == "event_before_fetch", action
    assert action.ratio is None


def test_r4f1_b_alpaca_changes_the_ratio_of_an_old_step():
    """Alpaca corrects the step ratio of an old ex-date E (after the fifth reference date)
    with F well past E + L: the prefix was fetched long after E, so it is not rescaled."""
    e = date(2020, 8, 5)
    assert e > R[4]
    F = wd(e, 20)                              # F >> E + L
    sc = build(wd(F, 3), F, {e: 0.99}, {e: 0.985})
    action = sc.classify()
    assert action.kind == K.FULL and action.reason == "event_before_fetch", action


# ── CONFIRM (D1-a only, F < P(E), today >= E + L) ───────────────────────────

def test_confirm_not_before_e_plus_l():
    e, F = date(2020, 9, 2), date(2020, 8, 28)
    assert build(wd(e, L - 1), F, {e: 0.99}).classify().kind == K.SUFFIX_ONLY
    assert build(wd(e, L), F, {e: 0.99}).classify().kind == K.CONFIRM


def test_confirm_never_under_d1b():
    e, F = date(2020, 9, 2), date(2020, 8, 28)
    params = hi.IncrementalParams(confirm=False)
    assert build(wd(e, L + 3), F, {e: 0.99}).classify(params=params).kind == K.SUFFIX_ONLY


def test_confirm_only_for_events_after_the_fetch():
    e = date(2020, 9, 2)
    F = wd(e, L)                               # fetched at E + L: provider's own values
    assert build(wd(F, 2), F, {e: 0.99}).classify().kind == K.SUFFIX_ONLY


def test_two_events_before_a_confirmation():
    e1, e2 = date(2020, 9, 2), date(2020, 9, 4)
    F = date(2020, 8, 28)
    assert build(wd(e1, L - 1), F, {e1: 0.99, e2: 0.995}).classify().kind == K.SUFFIX_ONLY
    # E1's window is over, E2's not yet: one CONFIRM re-fetch replaces both rescales.
    assert build(wd(e1, L), F, {e1: 0.99, e2: 0.995}).classify().kind == K.CONFIRM


# ── Revalidation selection ──────────────────────────────────────────────────

def test_select_revalidations_oldest_first_and_capped():
    due = [("AAA", 100), ("BBB", 250), ("CCC", 95), ("DDD", 250)]
    assert hi.select_revalidations(due, 3) == ["BBB", "DDD", "AAA"]
    assert hi.select_revalidations(due, 0) == []
    assert hi.select_revalidations(due, 10) == ["BBB", "DDD", "AAA", "CCC"]
    with pytest.raises(ValueError):
        hi.select_revalidations(due, -1)


def test_revalidation_never_removes_the_suffix_only_write():
    older = build(DEFAULT_TODAY, DEFAULT_TODAY - timedelta(days=200))
    old = build(DEFAULT_TODAY, DEFAULT_TODAY - timedelta(days=120))
    actions = {"OLDER": older.classify(), "OLD": old.classify()}
    assert all(a.kind == K.SUFFIX_ONLY and a.revalidation_due for a in actions.values())
    chosen = hi.select_revalidations([(s, a.prefix_age_days) for s, a in actions.items()], 1)
    assert chosen == ["OLDER"]
    assert older.classify(revalidate=True).kind == K.REVALIDATE
    assert old.classify(revalidate=False).kind == K.SUFFIX_ONLY


def test_revalidation_not_due_at_exactly_revalidate_days():
    sc = build(DEFAULT_TODAY, DEFAULT_TODAY - timedelta(days=90))
    action = sc.classify(revalidate=True)
    assert action.kind == K.SUFFIX_ONLY and not action.revalidation_due


# ── Ratios, raw closes, ADJ_TOL ─────────────────────────────────────────────

def test_uniform_ratio_helper():
    tol = Decimal("1e-6")
    assert hi.uniform_ratio([Decimal("0.99")] * 5, tol) == Decimal("0.99")
    assert hi.uniform_ratio([Decimal("0.99"), Decimal("0.99"), Decimal("0.991")], tol) is None
    assert hi.uniform_ratio([], tol) is None


def test_non_uniform_ratio_is_full():
    sc = default()
    sc.bars[1]["adj_factor"] = BASE * 0.99
    action = sc.classify()
    assert action.kind == K.FULL and action.reason == "non_uniform_ratio"


def test_raw_close_change_on_a_reference_date_is_full():
    sc = default()
    sc.bars[2]["close"] += 0.5
    action = sc.classify()
    assert action.kind == K.FULL and action.reason == "raw_close_changed"


def test_raw_close_compared_at_stored_four_dp_precision():
    sc = default()
    sc.bars[2]["close"] += 0.00004               # rounds to the stored value
    assert sc.classify().kind == K.SUFFIX_ONLY


@pytest.mark.parametrize("new_factor,kind", [
    (0.5000005, K.SUFFIX_ONLY),               # 1e-6: within ADJ_TOL
    (0.4999995, K.SUFFIX_ONLY),
    (0.50001, K.FULL),                        # 2e-5: a $0.01 dividend on $500
    (0.49999, K.FULL),
])
def test_adj_tol_boundary(new_factor, kind):
    sc = default()
    for b in sc.bars:
        b["adj_factor"] = new_factor
    assert sc.classify().kind == kind


# ── Alpaca reply and manual runs ────────────────────────────────────────────

@pytest.mark.parametrize("reply", [[], None])
def test_empty_alpaca_reply_is_full(reply):
    sc = default()
    sc.bars = reply
    action = sc.classify()
    assert action.kind == K.FULL and action.reason == "empty_alpaca"


def test_invalid_alpaca_reply_is_full():
    sc = default()
    sc.bars.append(dict(sc.bars[-1]))           # duplicate provider date
    assert sc.classify().reason == "invalid_alpaca"
    sc = default()
    sc.bars[-1]["source"] = "tiingo"
    assert sc.classify().reason == "invalid_alpaca"


def test_fewer_than_five_alpaca_dates_is_full():
    sc = default()
    sc.bars = sc.bars[:4]
    assert sc.classify().kind == K.FULL


def test_force_backfill_is_full_even_when_trusted():
    action = default().classify(force_backfill=True)
    assert action.kind == K.FULL and action.reason == "force_backfill"


# ── Single-provider (2.6) ───────────────────────────────────────────────────

SP_NOW = et(date(2020, 10, 1), 21)              # Thursday 21:00 ET; boundary Thu 18:00 ET


def sp_state(**kw) -> State:
    values = dict(symbol="SPY", basis_provider="tiingo", window_verified_through=date(2020, 9, 30),
                  window_verified_at=et(date(2020, 9, 30), 20))
    values.update(kw)
    return State(**values)


def test_single_provider_anchor_null_or_too_old_is_full():
    for state in (sp_state(window_verified_through=None, window_verified_at=None),
                  sp_state(window_verified_through=date(2020, 8, 16))):          # 46 days
        action = hi.classify_nightly_symbol(state, [], [], START, SP_NOW)
        assert action.kind == K.SINGLE_PROVIDER_FULL, action
    ok = sp_state(window_verified_through=date(2020, 8, 17))                     # 45 days
    assert hi.classify_nightly_symbol(ok, [], [], START, SP_NOW).kind == K.SINGLE_PROVIDER_RECENT


def test_single_provider_current_needs_a_nightly_write_after_the_boundary():
    at_boundary = sp_state(window_verified_at=et(date(2020, 10, 1), 18))
    assert hi.classify_nightly_symbol(at_boundary, [], [], START, SP_NOW).kind == K.SINGLE_PROVIDER_CURRENT
    naive_utc = sp_state(window_verified_at=datetime(2020, 10, 1, 22, 30))       # SQLite: naive UTC
    assert hi.classify_nightly_symbol(naive_utc, [], [], START, SP_NOW).kind == K.SINGLE_PROVIDER_CURRENT
    before = sp_state(window_verified_at=et(date(2020, 10, 1), 17))
    assert hi.classify_nightly_symbol(before, [], [], START, SP_NOW).kind == K.SINGLE_PROVIDER_RECENT


def test_single_provider_force_backfill_is_full():
    action = hi.classify_nightly_symbol(sp_state(), [], [], START, SP_NOW, force_backfill=True)
    assert action.kind == K.SINGLE_PROVIDER_FULL and action.reason == "force_backfill"


def test_single_provider_window_start():
    assert hi.single_provider_window_start(sp_state()) == date(2020, 9, 9)


def sp_window(reply_factor=lambda d: BASE, *, reply_close=close_of, through=date(2020, 10, 1)):
    """Stored Tiingo rows 2020-08-03 .. 09-30 (factor BASE); tonight's reply for the window
    [09-09, ``through``]."""
    stored = [(d, q(close_of(d), "0.0001"), q(BASE, "0.00000001"), Decimal(1), Decimal(0),
               "tiingo", et(date(2020, 9, 30), 20)) for d in weekdays(date(2020, 8, 3), date(2020, 9, 30))]
    reply = [bar(d, reply_close(d), reply_factor(d), "tiingo")
             for d in weekdays(date(2020, 9, 9), through)]
    return stored, reply


def sp_classify(stored, reply, **kw):
    with patch.object(hs, "_utcnow", return_value=SP_NOW):
        return hi.classify_single_provider_window(sp_state(), stored, reply, SP_NOW, **kw)


def test_single_provider_window_unchanged_is_recent():
    action = sp_classify(*sp_window())
    assert action.kind == K.SINGLE_PROVIDER_RECENT and action.ratio is None


def test_single_provider_window_uniform_event_d1a_full_d1b_rescale():
    stored, reply = sp_window(lambda d: BASE * 0.99 if d < date(2020, 10, 1) else BASE)
    a = sp_classify(stored, reply)
    assert a.kind == K.SINGLE_PROVIDER_FULL and abs(float(a.ratio) - 0.99) < 1e-9
    b = sp_classify(stored, reply, params=hi.IncrementalParams(confirm=False))
    assert b.kind == K.SINGLE_PROVIDER_RECENT and abs(float(b.ratio) - 0.99) < 1e-9


def test_single_provider_window_non_uniform_is_full():
    stored, reply = sp_window(lambda d: BASE * 0.99 if d < date(2020, 9, 20) else BASE)
    action = sp_classify(stored, reply)
    assert action.kind == K.SINGLE_PROVIDER_FULL and action.reason == "non_uniform_ratio"


def test_single_provider_window_identity_failure_is_full():
    stored, reply = sp_window(reply_close=lambda d: close_of(d) * (1.006 if d == date(2020, 9, 14) else 1))
    action = sp_classify(stored, reply)
    assert action.kind == K.SINGLE_PROVIDER_FULL and action.reason == "identity"


def test_single_provider_window_validation_failures_are_full():
    stored, reply = sp_window()
    assert sp_classify(stored, []).kind == K.SINGLE_PROVIDER_FULL
    omits = [b for b in reply if b["time"] != "2020-09-15"]
    assert sp_classify(stored, omits).reason == "omits_stored"
    wrong = [dict(b, source="alpaca") for b in reply]
    assert sp_classify(stored, wrong).reason == "wrong_source"
    gap_stored = [r for r in stored if not date(2020, 9, 10) <= r[0] <= date(2020, 9, 21)]
    gap_reply = [b for b in reply if not "2020-09-10" <= b["time"] <= "2020-09-21"]
    assert sp_classify(gap_stored, gap_reply).reason == "gap"


# ── load_params ─────────────────────────────────────────────────────────────

def test_load_params_absent_block_gives_the_defaults():
    defaults = hi.IncrementalParams()
    assert (defaults.provider_lag_days, defaults.revalidate_days, defaults.revalidate_per_night,
            defaults.confirm, defaults.adj_tol, defaults.anchor_overlap_days,
            defaults.anchor_max_age_days) == (5, 90, 10, True, 1e-6, 21, 45)
    for settings in (None, {}, {"history_incremental": None}, {"scheduling": {}}):
        assert hi.load_params(settings) == defaults


def test_load_params_reads_the_block():
    block = {"provider_lag_days": 7, "revalidate_days": 60, "revalidate_per_night": 0,
             "confirm": False, "adj_tol": 2e-6, "anchor_overlap_days": 14, "anchor_max_age_days": 30}
    assert hi.load_params({"history_incremental": block}) == hi.IncrementalParams(**block)
    partial = hi.load_params({"history_incremental": {"provider_lag_days": 8}})
    assert partial == hi.IncrementalParams(provider_lag_days=8)


@pytest.mark.parametrize("key,value", [
    ("provider_lag_days", -1), ("provider_lag_days", "5"), ("provider_lag_days", 5.0),
    ("provider_lag_days", True),
    ("revalidate_days", -1), ("revalidate_days", None),
    ("revalidate_per_night", -1), ("revalidate_per_night", "10"),
    ("confirm", 1), ("confirm", "yes"),
    ("adj_tol", -1e-6), ("adj_tol", float("nan")), ("adj_tol", "1e-6"), ("adj_tol", True),
    ("anchor_overlap_days", -21), ("anchor_overlap_days", 21.5),
    ("anchor_max_age_days", -1), ("anchor_max_age_days", []),
])
def test_load_params_invalid_value_names_the_key(key, value):
    with pytest.raises(hi.IncrementalConfigError, match=f"history_incremental.{key}"):
        hi.load_params({"history_incremental": {key: value}})
    assert issubclass(hi.IncrementalConfigError, ValueError)


def test_load_params_rejects_unknown_keys_and_non_mappings():
    with pytest.raises(hi.IncrementalConfigError, match="history_incremental.provider_lag_day"):
        hi.load_params({"history_incremental": {"provider_lag_day": 5}})
    with pytest.raises(hi.IncrementalConfigError, match="history_incremental"):
        hi.load_params({"history_incremental": [1, 2]})


# ── Purity ──────────────────────────────────────────────────────────────────

def test_classifier_does_not_mutate_its_inputs():
    sc = default()
    before = (list(sc.rows), [dict(b) for b in sc.bars], sc.state.verified_seam(), sc.state.floor_checked_at)
    sc.classify()
    assert (sc.rows, sc.bars, sc.state.verified_seam(), sc.state.floor_checked_at) == before
