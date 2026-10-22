"""Per-cell walk-forward (STOCKS-HORIZON-T1 H9): calendar, folds, entry
cut-offs, selection, OOS, final parameters and the held-out year.

Most tests plant a fake signal function (``signals._signal_fn``) and an
all-pass gate mask so the edge is known exactly; one test runs the real
``ma_crossover`` and the real gate mask through the process pool.
"""
from __future__ import annotations

import copy
import math
import random
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from pandas.tseries.holiday import USFederalHolidayCalendar

from app.services.horizon_tuning import gates, signals
from app.services.horizon_tuning import walk_forward_cell as wfc
from app.services.horizon_tuning.cache import TuningCache
from app.services.horizon_tuning.simulate import bar_dates, simulate_trades
from app.services.strategy_param_store import get_tuning_config

# ── synthetic exchange calendar 2009-10-01 .. 2026-10-02 ─────────────────────

_HOLIDAYS = set(d.date() for d in USFederalHolidayCalendar().holidays("2009-01-01", "2027-01-01"))


def _exchange_days(start: str = "2009-10-01", end: str = "2026-10-02") -> list[date]:
    """Weekdays minus US federal holidays (a synthetic exchange calendar)."""
    return [d.date() for d in pd.bdate_range(start, end) if d.date() not in _HOLIDAYS]


CAL = _exchange_days()


def _sawtooth(days: list[date]) -> list[dict]:
    """Period-7 sawtooth: phase p = index % 7 closes at 100 + p. A buy limit
    at the phase-0 close (100) fills at the phase-1 open (100); phase k's high
    is 100 + k + 0.5, so a target of 100 + k is hit on phase k (k <= 6).
    ``volume`` = index + 1, so the fake signal can read the bar index."""
    out = []
    for i, d in enumerate(days):
        p = i % 7
        if p == 0:
            o, h, lo, c = 100.2, 100.5, 99.5, 100.0
        else:
            o, h, lo, c = 100.0 + p - 1, 100.0 + p + 0.5, 100.0 + p - 1.2, 100.0 + p
        out.append({"time": d.isoformat(), "open": o, "high": h, "low": lo, "close": c,
                    "volume": float(i + 1)})
    return out


def _fake_fn(bars, *, direction, **p):
    """Fires on phase-0 bars (close 100) when the window holds >= lookback
    bars and (index // 7) % every == 0. Entry 100, stop 90, target
    100 * (1 + k / 100); ``only`` = a set of bar indices it is limited to."""
    last = bars[-1]
    idx = int(last["volume"]) - 1
    if len(bars) < p.get("lookback", 0):
        return None
    only = p.get("only")
    if only is not None:
        if idx not in only:
            return None
        c = last["close"]
        return SimpleNamespace(entry_price=c * 1.05, stop_price=c * 0.5, target_price=c * 10)
    if last["close"] != 100.0 or (idx // 7) % p.get("every", 1):
        return None
    k = p.get("k", 5)
    if "every" in p and "k" not in p:
        k = 5 if p["every"] > 1 else 3
    return SimpleNamespace(entry_price=100.0, stop_price=90.0, target_price=100.0 * (1 + k / 100))


@pytest.fixture
def planted(monkeypatch):
    monkeypatch.setattr(signals, "_signal_fn", lambda strategy: _fake_fn)
    monkeypatch.setattr(gates, "gate_mask", lambda bars, *a, **k: [True] * len(bars))


def _config(**over) -> dict:
    cfg = copy.deepcopy(get_tuning_config())
    cfg["min_train_trades"] = 1
    cfg["fire_rate_floor_per_day"] = {h: 0.0 for h in cfg["fire_rate_floor_per_day"]}
    for k, v in over.items():
        cfg[k] = v
    return cfg


def _data(bars: dict[str, list[dict]], *, grid: dict, config: dict | None = None,
          universe: int | None = None, **kw) -> wfc.CellData:
    return wfc.CellData(
        bars=bars,
        sectors={s: "Information Technology" for s in bars},
        n_universe_by_sector={"Information Technology": universe or len(bars)},
        config=config or _config(),
        grid=grid,
        **kw,
    )


def _universe(n: int = 4, days: list[date] = CAL) -> dict[str, list[dict]]:
    return {f"S{i}": _sawtooth(days) for i in range(n)}


CELL_SWING = wfc.Cell("pullback_ema", "Bullish", "Swing")


# ── calendar and folds ───────────────────────────────────────────────────────

def test_data_end_is_the_latest_date_with_ninety_percent_of_symbols():
    base = CAL[:600]
    dates = {f"S{i}": list(base) for i in range(9)}
    dates["S9"] = list(base) + CAL[600:620]          # one symbol runs on: 1 of 10 < 90%
    dates["S8"] = list(base[:-5])                     # one ends early: 9 of 10 still >= 90%
    cal = wfc.cell_calendar(dates, held_out_months=12)
    assert cal.data_end == base[-1]
    assert cal.dates[0] == base[0] and cal.dates[-1] == CAL[619]
    assert cal.warm_start == base[400]


def _fold_dates(horizon: str):
    cal = wfc.cell_calendar({"A": CAL, "B": CAL}, held_out_months=12)
    folds, dropped = wfc.cell_folds(cal, horizon, get_tuning_config())
    return cal, folds, dropped


def test_calendar_on_the_synthetic_2009_2026_span():
    cal, _, _ = _fold_dates("Swing")
    assert cal.warm_start == date(2011, 5, 9)        # calendar[SIGNAL_WINDOW_BARS]
    assert cal.data_end == date(2026, 10, 2)
    assert cal.heldout_start == date(2025, 10, 2)


@pytest.mark.parametrize("horizon,n,first,last,last_test_entry_end,first_train_entry_end", [
    # (count, first fold (train_start, train_end, test_end), last fold, ...)
    ("Swing", 53, (date(2011, 5, 9), date(2012, 5, 9), date(2012, 8, 9)),
     (date(2024, 5, 9), date(2025, 5, 9), date(2025, 8, 9)), date(2025, 8, 9), date(2012, 4, 10)),
    ("Position", 53, (date(2011, 5, 9), date(2012, 5, 9), date(2012, 8, 9)),
     (date(2024, 5, 9), date(2025, 5, 9), date(2025, 8, 9)), date(2025, 8, 4), date(2012, 3, 11)),
    ("Quarterly", 40, (date(2011, 5, 9), date(2012, 5, 9), date(2012, 9, 9)),
     (date(2024, 5, 9), date(2025, 5, 9), date(2025, 9, 9)), date(2025, 7, 20), date(2012, 2, 25)),
    ("SemiAnnual", 19, (date(2011, 5, 9), date(2012, 9, 9), date(2013, 5, 9)),
     (date(2023, 5, 9), date(2024, 9, 9), date(2025, 5, 9)), date(2025, 5, 9), date(2012, 5, 13)),
    ("Annual", 12, (date(2011, 5, 9), date(2013, 5, 9), date(2014, 5, 9)),
     (date(2022, 5, 9), date(2024, 5, 9), date(2025, 5, 9)), date(2025, 3, 2), date(2012, 10, 7)),
])
def test_fold_dates_pinned_per_horizon(horizon, n, first, last, last_test_entry_end, first_train_entry_end):
    cal, folds, dropped = _fold_dates(horizon)
    assert len(folds) == n and dropped == 0
    f0, fl = folds[0], folds[-1]
    assert (f0.train_start, f0.train_end, f0.test_end) == first
    assert (fl.train_start, fl.train_end, fl.test_end) == last
    assert f0.test_start == f0.train_end
    # Entry cut-offs: train [train_start, train_end - hold - 14); test
    # [test_start, min(test_end, heldout_start - hold - 14)).
    assert f0.train_entry == (f0.train_start, first_train_entry_end)
    assert fl.test_entry == (fl.test_start, last_test_entry_end)
    # Every fold's test window ends on or before heldout_start.
    assert all(f.test_end <= cal.heldout_start for f in folds)


def test_heldout_entry_span_per_horizon():
    cal = wfc.cell_calendar({"A": CAL}, held_out_months=12)
    cfg = get_tuning_config()
    assert wfc.heldout_entry(cal, "Swing", cfg) == (date(2025, 10, 2), date(2026, 9, 3))
    # Annual: about 12 months - 214 days.
    assert wfc.heldout_entry(cal, "Annual", cfg) == (date(2025, 10, 2), date(2026, 3, 2))


def test_a_fold_with_an_empty_entry_window_is_dropped_and_thin_is_flagged():
    cfg = _config()
    cfg["windows"] = dict(cfg["windows"], Annual={"train_months": 7, "test_months": 12})
    cal = wfc.cell_calendar({"A": CAL}, held_out_months=12)
    folds, dropped = wfc.cell_folds(cal, "Annual", cfg)
    # train 7 months (~212 days) < hold 200 + buffer 14: every train entry window is empty.
    assert folds == [] and dropped > 0


# ── the windowed simulation equals the full-series simulation ───────────────

def test_windowed_simulation_matches_the_full_series(planted):
    bars = _sawtooth(CAL[:1500])
    sig = signals.signal_series(bars, "pullback_ema", "Bullish", {"k": 8})
    dates = bar_dates(bars)
    allowed = [i >= 399 for i in range(len(bars))]
    start, end, restriction = CAL[700], CAL[900], CAL[950]
    full = simulate_trades(bars, sig, direction="Bullish", commission=0.0005, hold_max_days=15,
                           entry_start=start, entry_end=end, allowed=allowed, dates=dates)
    expected = [t for t in full if t.exit_date < restriction]
    state = wfc.SymbolState.build("X", bars, allowed_mask=[True] * len(bars))
    win = wfc.simulate_window(state, sig, entry=(start, end), restriction=restriction,
                              inclusive=False, commission=0.0005, hold_max_days=15)
    assert win.trades == expected and expected


# ── planted edge ─────────────────────────────────────────────────────────────

def test_planted_edge_wins_every_fold_and_is_final(planted):
    res = wfc.tune_cell(CELL_SWING, _data(_universe(), grid={"k": [1, 3, 5, 8]}))
    assert len(res.folds) == 53 and not res.thin
    assert all(f.winner == {"k": 5} for f in res.folds)
    assert res.final_params == {"k": 5}
    assert res.counts["tried"] == 4 and res.counts["invalid"] == 0
    assert res.counts["no_winner_folds"] == 0
    # OOS at both costs, the stress cost costing more.
    cost, stress = res.oos_trades["cost_per_leg"], res.oos_trades["stress_cost_per_leg"]
    assert cost and len(cost) == len(stress)
    assert {t.symbol for t in cost} == {"S0", "S1", "S2", "S3"}
    assert all(math.isclose(t.trade.exit_price, 105.0) for t in cost)
    assert res.oos["cost_per_leg"].net_expectancy > res.oos["stress_cost_per_leg"].net_expectancy > 0
    assert res.heldout["cost_per_leg"].n_trades > 0
    assert res.fire_rate == pytest.approx(4 / 7, rel=0.02)


def test_a_combination_below_the_fire_rate_floor_never_wins(planted):
    # every=5 fires a fifth as often (rate ~0.11/day) with a 5% target;
    # every=1 (~0.57/day) has a 3% target.
    grid = {"every": [1, 5]}
    open_floor = wfc.tune_cell(CELL_SWING, _data(_universe(), grid=grid, config=_config(min_train_trades=10)))
    assert all(f.winner == {"every": 5} for f in open_floor.folds)        # control: it would win
    cfg = _config(min_train_trades=10)
    cfg["fire_rate_floor_per_day"]["Swing"] = 0.3
    floored = wfc.tune_cell(CELL_SWING, _data(_universe(), grid=grid, config=cfg))
    assert all(f.winner == {"every": 1} for f in floored.folds)
    assert floored.final_params == {"every": 1}
    assert floored.counts["ineligible"] >= len(floored.folds)


def test_no_eligible_combination_means_no_winner_and_is_counted(planted):
    cfg = _config(min_train_trades=10_000)
    res = wfc.tune_cell(CELL_SWING, _data(_universe(2), grid={"k": [5]}, config=cfg))
    assert all(f.winner is None for f in res.folds)
    assert res.counts["no_winner_folds"] == len(res.folds) and res.final_params is None
    assert res.oos_trades["cost_per_leg"] == [] and res.heldout_trades["cost_per_leg"] == []


def test_invalid_combinations_are_skipped_and_counted(planted):
    # pullback_ema needs trend_ema + 10 bars: 400 > the 400-bar window -> never fires.
    res = wfc.tune_cell(CELL_SWING, _data(_universe(2), grid={"k": [5], "trend_ema": [100, 395]}))
    assert res.counts == dict(res.counts, tried=2, invalid=1)
    assert all(f.winner == {"k": 5, "trend_ema": 100} for f in res.folds)


def test_ma_crossover_fast_not_below_slow_is_invalid():
    assert wfc.invalid_reason("ma_crossover", "Bullish", {"fast": 50, "slow": 50}) is not None
    assert wfc.invalid_reason("ma_crossover", "Bullish", {"fast": 20, "slow": 50}) is None


def test_multi_grid_keys_address_variant_fields():
    p = wfc.combo_params("mean_reversion_multi", "Bullish",
                         {"min_confirmations": 3, "mean_reversion_rsi.rsi_oversold": 25})
    assert p["min_confirmations"] == 3
    assert p["variant_params"]["mean_reversion_rsi"]["rsi_oversold"] == 25
    # The variant base is its direction baseline (merge_multi_params).
    assert "trend_sma" in p["variant_params"]["mean_reversion_rsi"]
    assert wfc.invalid_reason("mean_reversion_multi", "Bullish",
                              {"min_confirmations": 4}) is not None
    assert wfc.invalid_reason("mean_reversion_multi", "Bullish",
                              {"pullback_ema.tolerance": 0.02}) is not None


# ── warm-up ──────────────────────────────────────────────────────────────────

def test_355_bar_lookback_is_eligible_from_fold_0_and_no_entry_before_the_400th_bar(planted):
    bars = _universe(3)
    late_days = [d for d in CAL if d >= date(2013, 1, 2)]
    bars["LATE"] = _sawtooth(late_days)
    res = wfc.tune_cell(CELL_SWING, _data(bars, grid={"lookback": [355]}))
    assert res.folds[0].winner == {"lookback": 355}
    late = [t for t in res.oos_trades["cost_per_leg"] if t.symbol == "LATE"]
    assert late, "the late listing trades out of sample"
    assert min(t.trade.entry_date for t in late) > late_days[399]
    # Without the own-400th-bar rule the 355-bar signal would enter earlier.
    assert any(late_days[355] <= f.fold.test_entry[1] and f.fold.test_entry[0] <= late_days[399]
               for f in res.folds)


# ── exits never cross their window's restriction ────────────────────────────

@pytest.mark.parametrize("horizon", ["Swing", "Annual"])
def test_exits_stay_inside_their_windows_on_a_holiday_calendar(planted, horizon):
    # k=8 never reaches its target: every trade is a time exit, the latest exit possible.
    res = wfc.tune_cell(wfc.Cell("pullback_ema", "Bullish", horizon),
                        _data(_universe(2), grid={"k": [8]}))
    assert res.folds and all(f.winner == {"k": 8} for f in res.folds)
    assert res.boundary_dropped == {"train": 0, "oos": 0, "heldout": 0}
    assert res.end_dropped == {"train": 0, "oos": 0, "heldout": 0}
    for t in res.oos_trades["cost_per_leg"] + res.oos_trades["stress_cost_per_leg"]:
        assert t.trade.exit_date < res.calendar.heldout_start
        assert t.trade.exit_reason == "time"
    held = res.heldout_trades["cost_per_leg"]
    assert held and all(res.calendar.heldout_start <= t.trade.entry_date
                        and t.trade.exit_date <= res.calendar.data_end for t in held)


def test_train_exits_are_before_train_end(planted, monkeypatch):
    seen = []
    real = wfc.simulate_window

    def spy(state, sig, *, entry, restriction, inclusive, **kw):
        out = real(state, sig, entry=entry, restriction=restriction, inclusive=inclusive, **kw)
        seen.append((entry, restriction, inclusive, out))
        return out

    monkeypatch.setattr(wfc, "simulate_window", spy)
    res = wfc.tune_cell(CELL_SWING, _data(_universe(2), grid={"k": [8]}))
    train_calls = [(e, r, o) for e, r, inc, o in seen if r in {f.fold.train_end for f in res.folds}]
    assert train_calls
    for (start, end), restriction, out in train_calls:
        for t in out.trades:
            assert start < t.entry_date and t.exit_date < restriction


def test_a_ten_day_bar_hole_drops_and_counts_the_crossing_trade(planted):
    days = list(CAL)
    cal = wfc.cell_calendar({"A": days}, held_out_months=12)
    folds, _ = wfc.cell_folds(cal, "Swing", get_tuning_config())
    f0 = folds[0]
    signal_day = max(d for d in days if d < f0.train_entry[1])              # 2012-04-09
    fill_day = days[days.index(signal_day) + 1]
    trigger = min(d for d in days if (d - fill_day).days >= 15)
    hole = days[days.index(trigger) + 1: days.index(trigger) + 11]          # 10 bars
    holed_days = [d for d in days if d not in set(hole)]
    exit_day = holed_days[holed_days.index(trigger) + 1]
    assert exit_day >= f0.train_end, "setup: the hole must push the exit past train_end"

    def run(sym_days):
        bars = _sawtooth(sym_days)
        idx = {sym_days.index(signal_day)}
        grid = {"only": [frozenset(idx)]}
        data = _data({"A": _sawtooth(days), "H": bars}, grid=grid, config=_config(min_train_trades=0))
        return wfc.tune_cell(CELL_SWING, data)

    clean, holed = run(days), run(holed_days)
    assert clean.boundary_dropped["train"] == 0
    assert holed.boundary_dropped["train"] == 1      # fold 0's train window only


# ── process pool ─────────────────────────────────────────────────────────────

def _random_walk(days: list[date], seed: int) -> list[dict]:
    rng = random.Random(seed)
    c, out = 50.0, []
    for d in days:
        o = c * (1 + rng.gauss(0, 0.004))
        c = max(1.0, o * (1 + rng.gauss(0.0006, 0.015)))
        h, lo = max(o, c) * (1 + abs(rng.gauss(0, 0.004))), min(o, c) * (1 - abs(rng.gauss(0, 0.004)))
        out.append({"time": d.isoformat(), "open": o, "high": h, "low": lo, "close": c,
                    "volume": float(1_000_000 + rng.randint(0, 500_000))})
    return out


def test_process_pool_matches_in_process(tmp_path):
    days = _exchange_days("2020-01-02", "2024-06-28")
    bars = {"R1": _random_walk(days, 1), "R2": _random_walk(days, 2)}
    grid = {"fast": [10, 20], "slow": [50]}
    cell = wfc.Cell("ma_crossover", "Bullish", "Swing")
    inproc = wfc.tune_cell(cell, _data(bars, grid=grid))
    pooled = wfc.tune_cell(cell, _data(bars, grid=grid, cache=TuningCache(tmp_path), workers=2))
    assert any((tmp_path / "signals").iterdir()) and any((tmp_path / "gates").iterdir())
    assert inproc.oos_trades["cost_per_leg"] and inproc.heldout_trades["cost_per_leg"]
    assert pooled.final_params == inproc.final_params
    assert [f.winner for f in pooled.folds] == [f.winner for f in inproc.folds]
    assert pooled.oos_trades == inproc.oos_trades
    assert pooled.heldout_trades == inproc.heldout_trades


def test_workers_above_one_need_a_cache():
    with pytest.raises(ValueError, match="cache"):
        wfc.tune_cell(CELL_SWING, _data({"A": _sawtooth(CAL[:500])}, grid={"k": [5]}, workers=2))
