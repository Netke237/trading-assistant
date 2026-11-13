"""TUNER-RECHECK-WINDOW Task 1: ordinary re-check winners need only entry-window signals.

``simulate_trades`` reads ``signals[i]`` only after its entry-start/end guards,
so a fold winner's series is only consulted on the bars dated inside that
fold's ``test_entry``. Every optimized result below is compared by exact
equality with an independent full-series path (``_full_reference`` /
``_full_recheck_reference``: the pre-change logic, a full series for every
winner), never with the optimized helper itself.
"""
from __future__ import annotations

import bisect
import copy
import inspect
import json
from collections import Counter
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.horizon_profiles import HOLD_MAX_DAYS
from app.services.horizon_tuning import cache, gates, report, signals
from app.services.horizon_tuning import walk_forward_cell as wfc
from app.services.setup_entries import setup_series
from app.services.strategy_backtest import normalize_direction
from app.services.strategy_engine import SIGNAL_WINDOW_BARS
from app.services.strategy_param_store import get_tuning_config

_FIXTURES = Path(__file__).parent / "fixtures"
_OHLCV = ("open", "high", "low", "close", "volume")
TUNED = ("pullback_ema", "breakout_base", "ma_crossover",
         "mean_reversion_rsi", "mean_reversion_bb", "mean_reversion_multi")
SETUPS = ("breakout_setup", "fibonacci_pullback")

# Two grid combinations per tuned strategy that fire on the spliced fixture
# bars below (A is also the final parameter set of the real re-check cells).
REAL_COMBOS = {
    "pullback_ema": ({"ema_period": 20, "tolerance": 0.02}, {}),
    "breakout_base": ({"base_lookback": 15, "volume_mult": 1.1},
                      {"base_lookback": 30, "atr_tight_max": 4.5, "volume_mult": 1.1}),
    "ma_crossover": ({"fast": 10, "slow": 50, "lookback": 5}, {}),
    "mean_reversion_rsi": ({"rsi_period": 7, "rsi_oversold": 35, "trend_sma": 100, "exit_sma_period": 10},
                           {"rsi_period": 2, "rsi_oversold": 20, "trend_sma": 50, "exit_sma_period": 5}),
    "mean_reversion_bb": ({"bb_period": 10, "bb_std": 1.5, "trend_sma": 50, "stop_atr_mult": 1.0}, {}),
    "mean_reversion_multi": ({"min_confirmations": 1},
                             {"min_confirmations": 2, "mean_reversion_rsi.rsi_oversold": 40,
                              "mean_reversion_bb.bb_std": 1.5,
                              "mean_reversion_vwap_daily.vwap_deviation_pct": 0.01,
                              "mean_reversion_vwap_daily.vwap_lookback": 10}),
}


# ── real fixture bars ────────────────────────────────────────────────────────

@lru_cache(maxsize=None)
def _spliced_raw(order: tuple[str, ...], start: date) -> tuple[tuple, ...]:
    """Real fixture OHLCV chained end to end (each later series price-scaled to
    open at the previous close), re-dated on consecutive weekdays."""
    out, d = [], start
    for sym in order:
        rows = json.loads((_FIXTURES / f"{sym}_candles.json").read_text())
        scale = out[-1][4] / rows[0]["open"] if out else 1.0
        for r in rows:
            while d.weekday() >= 5:
                d += timedelta(days=1)
            out.append((str(d), *(r[k] * scale for k in _OHLCV[:4]), float(r["volume"])))
            d += timedelta(days=1)
    return tuple(out)


def _spliced(order=("AAPL", "MSFT", "NVDA", "SPY"), start=date(2019, 1, 1), n=None) -> list[dict]:
    rows = _spliced_raw(tuple(order), start)[:n]
    return [dict(zip(("time", *_OHLCV), r)) for r in rows]


def _r1():
    return _spliced()


def _r2():   # later start, earlier end, different shape: unequal history
    return _spliced(("MSFT", "NVDA", "SPY", "AAPL"), date(2019, 3, 4), 900)


# ── independent full-series reference ────────────────────────────────────────

def _full_reference_uncached(bars, strategy, direction, params):
    """The pre-change generator loop for every bar, written independently of
    the window implementation; setup strategies via ``setup_series``."""
    if strategy in SETUPS:
        return setup_series(bars, strategy, direction, params)
    fn = signals._signal_fn(strategy)
    eff = signals.effective_params(strategy, params)
    clean = [{k: float(b[k]) for k in _OHLCV} for b in bars]
    width = 350 if strategy == "mean_reversion_vwap" else SIGNAL_WINDOW_BARS
    out = [None] * len(bars)
    for t in range(59, len(bars)):
        sig = fn(clean[max(0, t + 1 - width):t + 1], direction=normalize_direction(direction), **eff)
        if sig is not None:
            out[t] = signals.SignalPoint(float(sig.entry_price), float(sig.stop_price), float(sig.target_price))
    return out


_REAL_MEMO: dict = {}


def _real_reference(bars, strategy, direction, params):
    """Memoized only for the real (unpatched) strategy functions."""
    key = (cache.ohlcv_hash(bars), strategy, normalize_direction(direction),
           json.dumps(params, sort_keys=True, default=str))
    if key not in _REAL_MEMO:
        _REAL_MEMO[key] = _full_reference_uncached(bars, strategy, direction, params)
    return _REAL_MEMO[key]


def _full_recheck_reference(res, universe, cfg, series=_full_reference_uncached):
    """Full-series re-check written without scoped preparation or report helpers."""
    costs = (wfc.COST, wfc.STRESS)
    oos, held = {k: [] for k in costs}, {k: [] for k in costs}
    boundary, end = {"oos": 0, "heldout": 0}, {"oos": 0, "heldout": 0}
    wf, ho = {}, {}
    cell, cal = res.cell, res.calendar
    direction = normalize_direction(cell.direction)
    trade = [s for s in universe.trade_universe if s in universe.bars]
    fire = [s for s in universe.fire_rate_universe if s in universe.bars]
    sh = gates.scoring_horizon_for(cell.horizon)
    for s in sorted(set(trade) | set(fire)):
        bars = universe.bars[s]
        mask = gates.gate_mask(bars, direction, sh, min_price=cfg["gates"]["min_price"],
                               max_price=cfg["gates"]["max_price"], benchmark=universe.benchmark)
        st = wfc.SymbolState.build(s, bars, mask, direction)
        final = series(bars, cell.strategy, direction, wfc.combo_params(cell.strategy, direction, res.final_params))
        if s in fire:
            wf[s] = wfc.count_fires(st, final, cal.warm_start, cal.heldout_start)
            ho[s] = wfc.count_fires(st, final, cal.heldout_start, cal.data_end, inclusive=True)
        if s not in trade:
            continue
        runs = [("oos", f.fold.test_entry, cal.heldout_start, False,
                 series(bars, cell.strategy, direction, wfc.combo_params(cell.strategy, direction, f.winner)))
                for f in res.folds if f.winner is not None]
        if res.heldout_entry is not None:
            runs.append(("heldout", res.heldout_entry, cal.data_end, True, final))
        for kind, entry, restriction, inclusive, sig in runs:
            for cost in costs:
                win = wfc.simulate_window(st, sig, entry=entry, restriction=restriction,
                                          inclusive=inclusive, commission=res.costs[cost],
                                          hold_max_days=HOLD_MAX_DAYS[cell.horizon])
                (oos if kind == "oos" else held)[cost].extend(wfc.SymbolTrade(s, t) for t in win.trades)
                if cost == wfc.COST:
                    boundary[kind] += win.boundary_dropped
                    end[kind] += win.end_dropped
    oos = {k: wfc._ordered(v) for k, v in oos.items()}
    held = {k: wfc._ordered(v) for k, v in held.items()}
    wf_days = bisect.bisect_left(cal.dates, cal.heldout_start) - bisect.bisect_left(cal.dates, cal.warm_start)
    ho_days = bisect.bisect_right(cal.dates, cal.data_end) - bisect.bisect_left(cal.dates, cal.heldout_start)
    return report.Recheck(oos, {k: wfc.TradeStats.of(v) for k, v in oos.items()}, held,
                          {k: wfc.TradeStats.of(v) for k, v in held.items()}, sum(wf.values()) / wf_days,
                          sum(ho.values()) / ho_days, {s: wf[s] + ho[s] for s in wf},
                          len(trade), len(fire), boundary, end)


def _assert_same_recheck(got, ref, res, cfg):
    assert got.oos_trades == ref.oos_trades and got.heldout_trades == ref.heldout_trades
    assert got.oos == ref.oos and got.heldout == ref.heldout
    assert (got.fire_rate, got.heldout_fire_rate, got.fires_by_symbol) == \
        (ref.fire_rate, ref.heldout_fire_rate, ref.fires_by_symbol)
    assert (got.boundary_dropped, got.end_dropped) == (ref.boundary_dropped, ref.end_dropped)
    assert got == ref
    assert report.adoption_verdict(res.cell, got, cfg) == report.adoption_verdict(res.cell, ref, cfg)


# ── deterministic planted calendars ──────────────────────────────────────────

def _calendar_bars(n=620, start=0, skip=()):
    """Flat bars on consecutive days ``start..start+n-1`` (minus ``skip``);
    ``volume`` carries the absolute day so planted signals follow dates."""
    return [dict(time=str(date(2020, 1, 1) + timedelta(days=i)), open=100., high=101.,
                 low=99., close=100., volume=float(i)) for i in range(start, start + n) if i not in skip]


def _param_value(params) -> int:
    return params["k"] if "k" in params else params["min_confirmations"]


def _planted(bars, *, direction, **params):
    """Fires every 15 days (offset by the parameter value, so winners differ);
    every other fire closes quickly, the rest cross a restriction or history end."""
    i = int(bars[-1]["volume"]) - (_param_value(params) - 1)
    if i % 15:
        return None
    short = direction == "Bearish"
    target = (99.5 if short else 100.5) if i % 30 == 0 else (1. if short else 1000.)
    return SimpleNamespace(entry_price=100., stop_price=110. if short else 90., target_price=target)


def _mask(bars, *a, **kw):
    return [i % 13 != 7 for i in range(len(bars))]


def _combo(strategy, v):
    return None if v is None else ({"min_confirmations": v} if strategy == "mean_reversion_multi" else {"k": v})


FOLDS = [(405, 450), (465, 500), (465, 500)]   # starts on planted days; 450 is planted too


def _result(strategy="pullback_ema", direction="Bullish", winners=(1, 2, 1), final=1,
            dates=None, folds=FOLDS, heldout=(510, None), warm=400, heldout_start=500, combo=None):
    dates = dates or wfc.bar_dates(_calendar_bars())
    combo = combo or (lambda v: _combo(strategy, v))
    cal = wfc.CellCalendar(tuple(dates), dates[warm], dates[-1], dates[heldout_start])
    res = wfc._empty_result(wfc.Cell(strategy, direction, "Swing"), cal,
                            {wfc.COST: .001, wfc.STRESS: .003}, {})
    res.final_params = combo(final)
    res.heldout_entry = None if heldout is None else (dates[heldout[0]], dates[heldout[1] or -1])
    for i, (lo, hi) in enumerate(folds):
        fold = wfc.CellFold(i, dates[warm], dates[warm + 10], dates[lo], dates[hi],
                            (dates[warm], dates[warm + 9]), (dates[lo], dates[hi]))
        res.folds.append(wfc.FoldResult(fold, combo(winners[i])))
    return res


def _planted_universe(**kw):
    bars = {"Z": _calendar_bars(), "A": _calendar_bars(475), "LATE": _calendar_bars(560, start=37),
            "GAP": _calendar_bars(skip={404, 405, 450, 465}), "EV": _calendar_bars(560)}
    return report.UniverseData(bars, ["Z", "A", "LATE", "GAP"], ["Z", "A", "LATE", "GAP", "EV"], **kw)


@pytest.fixture
def planted(monkeypatch):
    monkeypatch.setattr(signals, "_signal_fn", lambda _: _planted)
    monkeypatch.setattr(gates, "gate_mask", _mask)


# ── counted calls: only entry-window indices invoke the ordinary strategy ────

@pytest.mark.parametrize("strategy", TUNED)
def test_only_entry_window_indices_invoke_the_ordinary_strategy(strategy, monkeypatch):
    bars = _r1()
    params = wfc.combo_params(strategy, "Bullish", REAL_COMBOS[strategy][0])
    ref = _real_reference(bars, strategy, "Bullish", params)
    real_fn = signals._signal_fn(strategy)
    seen = []

    def counted(window_bars, **kw):
        seen.append(window_bars)
        return real_fn(window_bars, **kw)
    monkeypatch.setattr(signals, "_signal_fn", lambda _: counted)
    lo, hi = 420, 431
    # Without a window argument the pre-change generator runs fully, so the
    # failure measures the excess strategy calls, not a missing keyword.
    kw = {"window": (lo, hi)} if "window" in inspect.signature(signals.signal_series).parameters else {}
    out = signals.signal_series(bars, strategy, "Bullish", params, **kw)
    assert len(seen) == hi - lo
    assert seen == [[{k: float(b[k]) for k in _OHLCV} for b in bars[t + 1 - SIGNAL_WINDOW_BARS:t + 1]]
                    for t in range(lo, hi)]
    assert out == [v if lo <= i < hi else None for i, v in enumerate(ref)]


def test_recheck_invokes_winner_strategy_only_inside_its_entry_windows(planted, monkeypatch):
    calls = Counter()

    def recording(bars, *, direction, **params):
        calls[(_param_value(params), int(bars[-1]["volume"]))] += 1
        return _planted(bars, direction=direction, **params)
    monkeypatch.setattr(signals, "_signal_fn", lambda _: recording)
    res = _result()
    u = report.UniverseData({"Z": _calendar_bars()}, ["Z"], ["Z"])
    got = report.full_universe_recheck(res, u, get_tuning_config())
    _assert_same_recheck(got, _full_recheck_reference(res, u, get_tuning_config()), res, get_tuning_config())
    calls.clear()
    report.full_universe_recheck(res, u, get_tuning_config())
    # Winner k=2 (fold 1 only): exactly [465, 500). Final k=1 is full; the k=1
    # winners add their own scoped windows [405, 450) and [465, 500) once each.
    assert {d for (k, d) in calls if k == 2} == set(range(465, 500))
    assert all(calls[(2, d)] == 1 for d in range(465, 500))
    expected_k1 = Counter({(1, d): 1 for d in range(59, 620)})
    expected_k1.update({(1, d): 1 for d in [*range(405, 450), *range(465, 500)]})
    assert Counter({key: n for key, n in calls.items() if key[0] == 1}) == expected_k1


# ── the generator window ─────────────────────────────────────────────────────

@pytest.mark.parametrize("window,indices", [((0, 59), []), ((0, 60), [59]), ((59, 62), [59, 60, 61]),
                                           ((410, 412), [410, 411]), ((618, 630), [618, 619]),
                                           ((620, 630), []), ((700, 710), []), ((60, 60), [])])
def test_warmup_exclusive_end_and_original_trailing_input(window, indices, monkeypatch):
    bars = _calendar_bars()
    seen = []

    def fn(b, **kw):
        seen.append(b)
        return SimpleNamespace(entry_price=b[-1]["volume"], stop_price=1., target_price=1000.)
    monkeypatch.setattr(signals, "_signal_fn", lambda _: fn)
    out = signals.signal_series(bars, "pullback_ema", "Bullish", {}, window=window)
    assert len(out) == len(bars)
    assert [i for i, s in enumerate(out) if s is not None] == indices
    assert [s.entry for s in out if s is not None] == [float(i) for i in indices]
    assert seen == [[{k: float(row[k]) for k in _OHLCV}
                     for row in bars[max(0, i + 1 - SIGNAL_WINDOW_BARS):i + 1]] for i in indices]


@pytest.mark.parametrize("strategy", [*TUNED, "mean_reversion_vwap"])
@pytest.mark.parametrize("direction", ["Bullish", "Bearish"])
@pytest.mark.parametrize("which", [0, 1])
def test_real_strategy_windows_equal_the_full_reference(strategy, direction, which):
    bars = _r1()
    combo = {} if strategy == "mean_reversion_vwap" else REAL_COMBOS[strategy][which]
    params = (wfc.combo_params(strategy, direction, combo) if strategy != "mean_reversion_vwap"
              else ({} if which == 0 else {"vwap_dev_pct": 1.0}))
    ref = _real_reference(bars, strategy, direction, params)
    assert signals.signal_series(bars, strategy, direction, params) == ref   # default stays full
    n = len(bars)
    for lo, hi in [(0, 60), (59, 61), (300, 420), (420, 520), (760, 870),
                   (n - 3, n + 20), (n + 3, n + 10), (500, 500)]:
        got = signals.signal_series(bars, strategy, direction, params, window=(lo, hi))
        assert got == [v if lo <= i < hi else None for i, v in enumerate(ref)]


@pytest.mark.parametrize("window", [(-1, 5), (5, 4), (0, 1.5), (False, 4), (0, True), (0,), (0, 5, 6),
                                    [0, 5], "04", 3])
def test_invalid_windows_rejected(window, tmp_path):
    bars = _calendar_bars()
    for strategy in ("pullback_ema", "fibonacci_pullback"):
        with pytest.raises(ValueError):
            signals.signal_series(bars, strategy, "Bullish", {}, window=window)
        with pytest.raises(ValueError):
            cache.TuningCache(tmp_path).window_signal_series("S", bars, strategy, "Bullish", {}, window=window)
    with pytest.raises(ValueError):     # the scoped operation always names its window
        cache.TuningCache(tmp_path).window_signal_series("S", bars, "pullback_ema", "Bullish", {}, window=None)
    assert not tmp_path.exists() or not any(tmp_path.iterdir())


# ── setup strategies stay full ───────────────────────────────────────────────

@pytest.mark.parametrize("strategy", SETUPS)
@pytest.mark.parametrize("direction", ["Bullish", "Bearish"])
def test_setup_window_keeps_full_series_with_pending_origin_before_window(strategy, direction, tmp_path):
    from tests.test_setup_tuning import synthetic_bars
    bars = synthetic_bars(strategy, direction=direction)
    full = setup_series(bars, strategy, direction, {})
    trigger = next(i for i, s in enumerate(full) if s is not None and s.setup_age > 0)
    window = (trigger, trigger + 1)   # the pending setup originated strictly before lo
    assert trigger - full[trigger].setup_age < window[0]
    assert signals.signal_series(bars, strategy, direction, {}, window=window) == full
    c = cache.TuningCache(tmp_path)
    assert c.window_signal_series("S", bars, strategy, direction, {}, window=window) == full
    assert c.signal_series("S", bars, strategy, direction, {}) == full
    assert (c.hits, c.misses) == (1, 1)               # one full entry, shared
    assert not (tmp_path / "signal_windows").exists()


@pytest.mark.parametrize("strategy", SETUPS)
@pytest.mark.parametrize("direction", ["Bullish", "Bearish"])
def test_setup_recheck_uses_full_series(strategy, direction, tmp_path, monkeypatch):
    from tests.test_setup_tuning import synthetic_bars
    monkeypatch.setattr(gates, "gate_mask", lambda b, *a, **kw: [True] * len(b))
    bars = synthetic_bars(strategy, direction=direction)
    full = setup_series(bars, strategy, direction, {})
    trigger = next(i for i, s in enumerate(full) if s is not None and s.setup_age > 0 and i > 450)
    dates = wfc.bar_dates(bars)
    combo = lambda v: None if v is None else {"setup_expiry_bars": v}
    # Fold 1 starts on a trigger whose setup began before the window.
    res = _result(strategy, direction, winners=(5, 3, 5), final=5, dates=dates,
                  folds=[(420, trigger), (trigger, 760), (760, 880)], heldout=(900, None),
                  heldout_start=890, combo=combo)
    u = report.UniverseData({"X": bars, "Y": bars[:950]}, ["X", "Y"], ["X", "Y"],
                            cache=cache.TuningCache(tmp_path))
    cfg = get_tuning_config()
    ref = _full_recheck_reference(res, u, cfg)
    assert ref.oos[wfc.COST].n_trades > 0 and ref.heldout[wfc.COST].n_trades > 0
    for _ in range(2):    # cold, then warm
        _assert_same_recheck(report.full_universe_recheck(res, u, cfg), ref, res, cfg)
    assert not (tmp_path / "signal_windows").exists()
    assert len(list((tmp_path / "signals").glob("*.json"))) == 4   # X, Y x two distinct params
    no_cache = report.UniverseData(u.bars, u.trade_universe, u.fire_rate_universe)
    _assert_same_recheck(report.full_universe_recheck(res, no_cache, cfg), ref, res, cfg)


# ── the scoped cache ─────────────────────────────────────────────────────────

def _payload(series):
    return [None if v is None else dict(v.__dict__) for v in series]


def test_scoped_cache_cold_warm_isolated_and_corruption_recomputed(tmp_path, monkeypatch):
    bars = _calendar_bars()
    monkeypatch.setattr(signals, "_signal_fn", lambda _: lambda b, **kw: SimpleNamespace(
        entry_price=b[-1]["volume"], stop_price=1, target_price=1000))
    full_ref = _full_reference_uncached(bars, "pullback_ema", "Bullish", {})
    c = cache.TuningCache(tmp_path)
    args = ("S", bars, "pullback_ema", "Bullish", {})
    a = c.window_signal_series(*args, window=(60, 65))
    b = c.window_signal_series(*args, window=(65, 70))
    assert a == [v if 60 <= i < 65 else None for i, v in enumerate(full_ref)]
    assert b == [v if 65 <= i < 70 else None for i, v in enumerate(full_ref)]
    assert c.window_signal_series(*args, window=(60, 65)) == a                 # warm
    assert (c.hits, c.misses) == (1, 2)
    assert not (tmp_path / "signals").exists()           # never written to a full path
    paths = sorted((tmp_path / "signal_windows").glob("*.json"))
    assert len(paths) == 2
    path_a = next(p for p in paths if json.loads(p.read_text())[60] is not None)

    # A full call never reads a scoped payload, and a scoped call never reads a full one.
    assert c.signal_series(*args) == full_ref
    assert (c.hits, c.misses) == (1, 3)
    assert c.window_signal_series(*args, window=(60, 65)) == a
    assert (c.hits, c.misses) == (2, 3)

    corruptions = [
        _payload(full_ref),                                                   # full payload under a window key
        [*_payload(a)[:61], {**_payload(a)[61], "entry": float("nan")}, *_payload(a)[62:]],
        [*_payload(a)[:61], {**_payload(a)[61], "extra": 1}, *_payload(a)[62:]],
        _payload(a)[:-1],                                                     # wrong length
        {"not": "a list"},
    ]
    misses = c.misses
    for bad in corruptions:
        path_a.write_text(json.dumps(bad))
        assert c.window_signal_series(*args, window=(60, 65)) == a
        misses += 1
        assert c.misses == misses
        assert json.loads(path_a.read_text()) == _payload(a)                  # rewritten atomically
    path_a.write_text('[null, {"entry": 1')                                   # truncated JSON
    assert c.window_signal_series(*args, window=(60, 65)) == a and c.misses == misses + 1
    assert cache.TuningCache(tmp_path).signal_series(*args) == full_ref       # full entry untouched


def test_scoped_cache_off_uses_the_same_generator_window(monkeypatch):
    bars = _calendar_bars()
    monkeypatch.setattr(signals, "_signal_fn", lambda _: lambda b, **kw: SimpleNamespace(
        entry_price=b[-1]["volume"], stop_price=1, target_price=1000))
    seen = []
    real = signals.signal_series

    def counted(*a, **kw):
        seen.append(kw.get("window"))
        return real(*a, **kw)
    monkeypatch.setattr(signals, "signal_series", counted)
    res = _result(winners=(2, 2, 2), final=1)
    monkeypatch.setattr(gates, "gate_mask", _mask)
    u = report.UniverseData({"Z": _calendar_bars()}, ["Z"], ["Z"])
    report.full_universe_recheck(res, u, get_tuning_config())
    assert sorted(seen, key=str) == sorted([None, (405, 450), (465, 500)], key=str)


def test_scoped_keys_cover_full_identity_and_exact_normalized_window(tmp_path, monkeypatch):
    bars = _calendar_bars()
    monkeypatch.setattr(signals, "_signal_fn", lambda _: lambda b, **kw: SimpleNamespace(
        entry_price=b[-1]["volume"], stop_price=1, target_price=1000))
    calls = []
    real = signals.signal_series

    def counted(*a, **kw):
        calls.append(kw.get("window"))
        return real(*a, **kw)
    monkeypatch.setattr(signals, "signal_series", counted)
    c = cache.TuningCache(tmp_path)
    args = ("S", bars, "pullback_ema", "Bullish", {})
    for window in [(60, 65), (61, 66), (60, 66), (60, 64)]:     # overlapping, never unioned
        c.window_signal_series(*args, window=window)
    c.window_signal_series("S", bars, "pullback_ema", "Bullish", {"ema_period": 30}, window=(60, 65))
    c.window_signal_series("S", bars, "pullback_ema", "Bearish", {}, window=(60, 65))
    c.window_signal_series("T", bars, "pullback_ema", "Bullish", {}, window=(60, 65))
    c.window_signal_series("S", bars, "breakout_base", "Bullish", {}, window=(60, 65))
    changed = [dict(b) for b in bars]
    changed[0]["close"] += 1
    c.window_signal_series("S", changed, "pullback_ema", "Bullish", {}, window=(60, 65))
    # Beyond the history both windows normalize to the same empty (620, 620).
    c.window_signal_series(*args, window=(len(bars) + 2, len(bars) + 5))
    c.window_signal_series(*args, window=(len(bars) + 3, len(bars) + 6))
    c.window_signal_series(*args, window=(600, len(bars) + 6))
    c.window_signal_series(*args, window=(600, len(bars)))      # the same normalized window
    assert calls == [(60, 65), (61, 66), (60, 66), (60, 64), (60, 65), (60, 65), (60, 65), (60, 65),
                     (60, 65), (620, 620), (600, 620)]
    assert c.hits == 2
    assert len(list((tmp_path / "signal_windows").glob("*.json"))) == 11
    # Same params as a scoped entry: the full namespace is separate.
    assert c.signal_series(*args) == _full_reference_uncached(bars, "pullback_ema", "Bullish", {})
    assert calls[-1] is None and len(list((tmp_path / "signals").glob("*.json"))) == 1


# ── re-check parity ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("strategy", TUNED)
@pytest.mark.parametrize("direction", ["Bullish", "Bearish"])
@pytest.mark.parametrize("disk", [False, True])
def test_planted_recheck_exact_trades_stats_fires_drops_and_verdict(strategy, direction, disk, planted,
                                                                   tmp_path):
    res = _result(strategy, direction)
    u = _planted_universe(cache=cache.TuningCache(tmp_path) if disk else None)
    cfg = get_tuning_config()
    ref = _full_recheck_reference(res, u, cfg)
    assert ref.oos[wfc.COST].n_trades > 0 and ref.heldout[wfc.STRESS].n_trades > 0
    assert len({t.symbol for t in ref.oos_trades[wfc.COST]}) == 4
    assert ref.boundary_dropped["oos"] > 0 and ref.end_dropped["oos"] > 0
    assert ref.end_dropped["heldout"] > 0 and ref.fires_by_symbol["EV"] > 0
    for _ in range(2):    # cache off twice, or cold then warm
        _assert_same_recheck(report.full_universe_recheck(res, u, cfg), ref, res, cfg)
    if disk:
        # Final params equal fold winners 0 and 2: both namespaces exist.
        assert any((tmp_path / "signals").iterdir()) and any((tmp_path / "signal_windows").iterdir())
        # A later full read of a winner's params is never served a window.
        for s in ("Z", "LATE"):
            winner = wfc.combo_params(strategy, direction, res.folds[1].winner)
            assert cache.TuningCache(tmp_path).signal_series(s, u.bars[s], strategy, direction, winner) == \
                _full_reference_uncached(u.bars[s], strategy, direction, winner)


@pytest.mark.parametrize("winners,final", [((None, None, None), 1), ((1, 1, 1), 1), ((2, 2, 2), 1),
                                           ((2, None, 2), 2), ((1, 2, 2), 2)])
def test_no_same_or_different_winners_and_winner_equal_final(winners, final, planted):
    res = _result(winners=winners, final=final)
    u = _planted_universe()
    cfg = get_tuning_config()
    _assert_same_recheck(report.full_universe_recheck(res, u, cfg), _full_recheck_reference(res, u, cfg),
                         res, cfg)


def test_no_final_params_is_empty(planted):
    res = _result(final=None)
    assert report.full_universe_recheck(res, _planted_universe(), get_tuning_config()) == \
        report._empty_recheck(4, 5)


def test_windows_outside_history_and_verdict_threshold_boundaries(planted):
    res = _result()
    u = report.UniverseData({"A": _calendar_bars(), "EARLY": _calendar_bars(100),
                             "AFTER": _calendar_bars(80, start=530)},
                            ["EARLY", "AFTER", "A"], ["EARLY", "AFTER", "A"])
    cfg = copy.deepcopy(get_tuning_config())
    ref = _full_recheck_reference(res, u, cfg)
    got = report.full_universe_recheck(res, u, cfg)
    _assert_same_recheck(got, ref, res, cfg)
    assert got.fires_by_symbol["EARLY"] == 0 and got.oos[wfc.COST].n_trades > 0
    cfg["adoption"]["min_oos_trades"] = got.oos[wfc.COST].n_trades
    cfg["adoption"]["min_symbols"] = got.oos[wfc.COST].n_symbols
    cfg["fire_rate_floor_per_day"]["Swing"] = got.fire_rate
    baseline = report.adoption_verdict(res.cell, got, cfg)
    assert not {"min_oos_trades", "min_symbols", "fire_rate"}.intersection(baseline.failed)
    for target in ("min_oos_trades", "min_symbols", "fire_rate"):
        changed = copy.deepcopy(cfg)
        if target == "fire_rate":
            changed["fire_rate_floor_per_day"]["Swing"] += .000001
        else:
            changed["adoption"][target] += 1
        verdict = report.adoption_verdict(res.cell, got, changed)
        assert verdict == report.adoption_verdict(res.cell, ref, changed)
        assert verdict.failed == [k for k in report.CRITERIA if k in {*baseline.failed, target}]


def _real_result(strategy, direction, dates):
    a, b = REAL_COMBOS[strategy]
    combo = lambda v: None if v is None else (a if v == "A" else b)
    return _result(strategy, direction, winners=("A", "B", "B", "A"), final="A", dates=dates,
                   folds=[(405, 520), (520, 640), (640, 760), (760, 870)], heldout=(880, None),
                   heldout_start=880, combo=combo)


@pytest.mark.parametrize("strategy", TUNED)
@pytest.mark.parametrize("direction", ["Bullish", "Bearish"])
def test_real_fixture_recheck_exact(strategy, direction, monkeypatch):
    monkeypatch.setattr(gates, "gate_mask", _mask)
    r1, r2 = _r1(), _r2()
    res = _real_result(strategy, direction, wfc.bar_dates(r1))
    u = report.UniverseData({"R1": r1, "R2": r2}, ["R1", "R2"], ["R1", "R2"])
    cfg = get_tuning_config()
    ref = _full_recheck_reference(res, u, cfg, series=_real_reference)
    # The winners' real signals do land inside their entry windows.
    inside = sum(1 for b in (r1, r2) for f in res.folds for d, v in zip(wfc.bar_dates(b), _real_reference(
        b, strategy, direction, wfc.combo_params(strategy, direction, f.winner)))
        if v is not None and f.fold.test_entry[0] <= d < f.fold.test_entry[1])
    assert inside > 0
    _assert_same_recheck(report.full_universe_recheck(res, u, cfg), ref, res, cfg)


# ── the pool ─────────────────────────────────────────────────────────────────

def test_report_pool_actually_prewarms_scoped_requests(tmp_path, planted, monkeypatch):
    calls = []
    real = signals.signal_series

    def counted(*a, **kw):
        calls.append((a[1], kw.get("window")))
        return real(*a, **kw)
    monkeypatch.setattr(signals, "signal_series", counted)
    mapped = []

    class Pool:   # in-process stand-in: proves what the parent hands the workers
        def __init__(self, max_workers):
            assert max_workers == 2

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def map(self, fn, units):
            assert fn is report._prewarm_recheck
            for unit in units:
                mapped.append(unit[1])
                yield fn(unit)
            # After the pool, the parent must only read warmed entries.
            monkeypatch.setattr(signals, "signal_series", lambda *a, **kw: pytest.fail("unwarmed request"))
            monkeypatch.setattr(gates, "gate_mask", lambda *a, **kw: pytest.fail("unwarmed gate"))
    monkeypatch.setattr(report, "ProcessPoolExecutor", Pool)
    res = _result()
    u = _planted_universe(cache=cache.TuningCache(tmp_path), workers=2)
    cfg = get_tuning_config()
    got = report.full_universe_recheck(res, u, cfg)
    assert mapped == ["A", "EV", "GAP", "LATE", "Z"]
    assert u.cache.misses == 0
    assert Counter(w for _, w in calls) == Counter({
        None: 5,                                   # final params, every symbol
        (405, 450): 2, (465, 500): 2,              # Z: k=1 and k=2 share (465, 500) only by params
        (465, 475): 2,                             # A ends at 475 with a trade open; (405, 450) above
        (368, 413): 1, (428, 463): 2,              # LATE: the symbol's own index origin
        (404, 448): 1, (462, 496): 2,              # GAP: bisect-left past missing entry dates
    })
    monkeypatch.undo()
    monkeypatch.setattr(signals, "_signal_fn", lambda _: _planted)
    monkeypatch.setattr(gates, "gate_mask", _mask)
    _assert_same_recheck(got, _full_recheck_reference(res, _planted_universe(), cfg), res, cfg)


def test_real_process_pool_recheck_smoke(tmp_path):
    """A real ProcessPoolExecutor with the real strategy, gates and a temp disk
    cache; nothing is monkeypatched across the process boundary."""
    r1, r2, ev = _r1(), _r2(), _spliced(("NVDA", "SPY", "AAPL", "MSFT"), date(2019, 2, 1), 700)
    res = _real_result("pullback_ema", "Bullish", wfc.bar_dates(r1))
    cfg = get_tuning_config()
    bars = {"R1": r1, "R2": r2, "EV": ev}
    u = report.UniverseData(bars, ["R1", "R2"], ["R1", "R2", "EV"], cache=cache.TuningCache(tmp_path), workers=2)
    got = report.full_universe_recheck(res, u, cfg)
    assert u.cache.misses == 0                         # every parent read was warmed by a worker
    assert u.cache.hits == 3 + 3 + 8                    # finals, gate masks, scoped winners
    assert len(list((tmp_path / "signals").glob("*.json"))) == 3
    assert len(list((tmp_path / "gates").glob("*.json"))) == 3
    assert len(list((tmp_path / "signal_windows").glob("*.json"))) == 8   # 4 folds x 2 symbols, no unions
    ref = _full_recheck_reference(res, report.UniverseData(bars, ["R1", "R2"], ["R1", "R2", "EV"]), cfg,
                                  series=_real_reference)
    assert ref.oos[wfc.COST].n_trades > 0 and ref.heldout[wfc.COST].n_trades > 0
    _assert_same_recheck(got, ref, res, cfg)
