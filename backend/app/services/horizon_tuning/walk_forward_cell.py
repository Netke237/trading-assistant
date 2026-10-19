"""Walk-forward for one cell (strategy x direction x tuned horizon) — STOCKS-HORIZON-T1 H9.

``tune_cell(cell, data) -> CellResult``:

* **Calendar.** The sorted union of bar dates over the sample. ``data_end`` =
  the latest date on which >= 90% of the sample symbols have a bar; the
  held-out year is ``[heldout_start, data_end]``, ``heldout_start = data_end -
  held_out_months``.
* **Warm-up.** ``warm_start`` = the calendar date at index
  ``SIGNAL_WINDOW_BARS``, the same for every cell. Per symbol, no entry before
  its own 400th bar (``allowed[t]`` is False for ``t < SIGNAL_WINDOW_BARS - 1``),
  so every tuned signal is computed on a full window, as live.
* **Folds.** ``walk_forward.build_folds(warm_start, heldout_start, ...)`` with
  the horizon's ``tuning.windows``. Entry cut-offs (calendar days, ``cut = hold
  + exit_buffer_days``): train ``[train_start, train_end - cut)``, test
  ``[test_start, min(test_end, heldout_start - cut))``, held-out
  ``[heldout_start, data_end - cut)``. A fold with an empty train or test entry
  window is dropped. Fewer than ``min_folds_not_thin`` folds -> ``thin``.
* **Restriction guard.** A trade must exit before ``train_end`` (train), before
  ``heldout_start`` (test) and on or before ``data_end`` (held-out). Each
  window is simulated on the bars before its restriction, so a trade still
  open there (a halt or ingestion hole) is dropped and counted in
  ``boundary_dropped``; a trade open where the symbol's own series ends is
  counted in ``end_dropped``. Neither is ever kept.
* **Selection per fold.** Each valid grid combination trades the train entries
  at ``cost_per_leg`` with the gate mask. Eligible: pooled train trades >=
  ``min_train_trades`` (and > 0) and the sector-scaled train fire rate (over
  ``[train_start, train_end)``) >= the horizon's floor. Winner: highest pooled
  net expectancy; tie -> more trades, then grid order.
* **Out-of-sample.** Each fold's winner trades its test entries at
  ``cost_per_leg`` and ``stress_cost_per_leg``; the pooled trades are the
  walk-forward evidence.
* **Final parameters.** The combination that won the most folds (always a grid
  point); tie -> highest net expectancy over the union of all train entry
  windows (entries allowed where the signal bar lies in any fold's train entry
  window, exits before the last fold's ``train_end``), then grid order.
* **Held-out year.** The final parameters trade the held-out entries once, at
  both costs.

Grid combinations: a non-multi combination is laid over the strategy's
direction baseline (``get_active``); a ``mean_reversion_multi`` combination
addresses variant fields with dots and goes through ``merge_multi_params``
(variant base = the direction baseline). A combination is **invalid** (skipped
and counted) when it can never produce a signal or is incoherent:
``bars_needed`` above ``SIGNAL_WINDOW_BARS``; ``ma_crossover`` with ``fast >=
slow``; a multi ``min_confirmations`` outside ``1..len(variants)`` or a dotted
key naming a variant that is not voting.

Signal series and gate masks are computed in a ``ProcessPoolExecutor``
(``data.workers > 1``; one work unit per symbol x strategy x direction, through
the disk cache, which is then required); simulation runs in-process.
"""
from __future__ import annotations

import bisect
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from app.services.horizon_profiles import HOLD_MAX_DAYS
from app.services.horizon_tuning import basket as _basket
from app.services.horizon_tuning import gates as _gates
from app.services.horizon_tuning import signals as _signals
from app.services.horizon_tuning.cache import TuningCache
from app.services.horizon_tuning.signals import SignalPoint
from app.services.horizon_tuning.simulate import bar_dates, simulate_trades
from app.services.strategy_backtest import TradeRecord, normalize_direction
from app.services.walk_forward import build_folds, param_combos

COST = "cost_per_leg"
STRESS = "stress_cost_per_leg"
DATA_END_SHARE = 0.9
# simulate_trades returns nothing for fewer than 100 bars; a window slice keeps
# this many bars before its first entry date (no trade can be open there).
_LEAD_BARS = 100


# ── inputs ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Cell:
    strategy: str
    direction: str
    horizon: str


@dataclass
class CellData:
    """What one cell is tuned on.

    ``bars``: the sample (trade-universe symbols), ascending bars per symbol.
    ``sectors``: sample symbol -> stratum. ``n_universe_by_sector``: names per
    stratum in the fire-rate universe (the fire-rate scaling). ``config``: the
    ``tuning:`` block (``None`` -> ``get_tuning_config()``). ``grid``: the
    cell's grid (``None`` -> ``get_search_by_horizon``). ``cache``: the disk
    cache (``None`` = compute in memory; required when ``workers > 1``).
    """
    bars: dict[str, list[dict]]
    sectors: dict[str, str]
    n_universe_by_sector: dict[str, int]
    config: dict | None = None
    grid: dict | None = None
    benchmark: list[dict] | None = None
    cache: TuningCache | None = None
    workers: int = 1


# ── outputs ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CellCalendar:
    dates: tuple[date, ...]
    warm_start: date | None
    data_end: date
    heldout_start: date


@dataclass(frozen=True)
class CellFold:
    index: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    train_entry: tuple[date, date]
    test_entry: tuple[date, date]


@dataclass(frozen=True)
class SymbolTrade:
    symbol: str
    trade: TradeRecord


@dataclass(frozen=True)
class TradeStats:
    n_trades: int
    n_symbols: int
    net_expectancy: float | None     # mean net_return_pct over the pooled trades

    @classmethod
    def of(cls, trades: list[SymbolTrade]) -> "TradeStats":
        n = len(trades)
        return cls(n, len({t.symbol for t in trades}),
                   sum(t.trade.net_return_pct for t in trades) / n if n else None)


@dataclass
class FoldResult:
    fold: CellFold
    winner: dict | None
    winner_train: TradeStats | None = None
    winner_train_fire_rate: float | None = None
    oos: dict[str, TradeStats] = field(default_factory=dict)


@dataclass
class CellResult:
    cell: Cell
    calendar: CellCalendar | None
    costs: dict[str, float]
    final_params: dict | None
    final_effective_params: dict | None
    folds: list[FoldResult]
    oos_trades: dict[str, list[SymbolTrade]]
    oos: dict[str, TradeStats]
    heldout_entry: tuple[date, date] | None
    heldout_trades: dict[str, list[SymbolTrade]]
    heldout: dict[str, TradeStats]
    fire_rate: float | None                 # final params, sample-scaled, [warm_start, heldout_start)
    heldout_fire_rate: float | None         # final params, sample-scaled, [heldout_start, data_end]
    counts: dict[str, int]
    thin: bool
    boundary_dropped: dict[str, int]
    end_dropped: dict[str, int]


# ── calendar and folds ───────────────────────────────────────────────────────

def cell_calendar(dates_by_symbol: dict[str, list[date]], *, held_out_months: int) -> CellCalendar:
    """The union calendar, ``data_end`` (latest date with >= 90% of symbols),
    ``heldout_start`` and ``warm_start`` (index ``SIGNAL_WINDOW_BARS``)."""
    from app.services.strategy_engine import SIGNAL_WINDOW_BARS
    if not dates_by_symbol:
        raise ValueError("cell_calendar: no symbols")
    counts: Counter = Counter()
    for ds in dates_by_symbol.values():
        counts.update(set(ds))
    dates = tuple(sorted(counts))
    n = len(dates_by_symbol)
    covered = [d for d in dates if counts[d] >= DATA_END_SHARE * n - 1e-9]
    if not covered:
        raise ValueError("cell_calendar: no date has 90% of the symbols")
    data_end = covered[-1]
    warm_start = dates[SIGNAL_WINDOW_BARS] if len(dates) > SIGNAL_WINDOW_BARS else None
    return CellCalendar(dates, warm_start, data_end, data_end - relativedelta(months=held_out_months))


def _cut(horizon: str, config: dict) -> timedelta:
    return timedelta(days=HOLD_MAX_DAYS[horizon] + config["exit_buffer_days"])


def cell_folds(cal: CellCalendar, horizon: str, config: dict) -> tuple[list[CellFold], int]:
    """The horizon's folds with their entry windows, and how many were dropped
    for an empty train or test entry window."""
    if cal.warm_start is None:
        return [], 0
    w = config["windows"][horizon]
    cut = _cut(horizon, config)
    out: list[CellFold] = []
    dropped = 0
    for f in build_folds(cal.warm_start, cal.heldout_start,
                         train_months=w["train_months"], test_months=w["test_months"]):
        train_entry = (f.train_start, f.train_end - cut)
        test_entry = (f.test_start, min(f.test_end, cal.heldout_start - cut))
        if train_entry[1] <= train_entry[0] or test_entry[1] <= test_entry[0]:
            dropped += 1
            continue
        out.append(CellFold(len(out), f.train_start, f.train_end, f.test_start, f.test_end,
                            train_entry, test_entry))
    return out, dropped


def heldout_entry(cal: CellCalendar, horizon: str, config: dict) -> tuple[date, date] | None:
    """``[heldout_start, data_end - hold - buffer)``; ``None`` when empty."""
    span = (cal.heldout_start, cal.data_end - _cut(horizon, config))
    return span if span[1] > span[0] else None


# ── grid combinations ────────────────────────────────────────────────────────

def combo_params(strategy: str, direction: str, combo: dict) -> dict:
    """The params a grid combination runs with (before signals' ``exit:`` merge)."""
    from app.services.strategy_engine import merge_multi_params
    from app.services.strategy_param_store import get_active
    direction = normalize_direction(direction)
    if strategy != "mean_reversion_multi":
        return {**get_active(strategy, direction), **combo}
    overrides: dict = {"variant_params": {}}
    for key, value in combo.items():
        if "." in key:
            variant, name = key.split(".", 1)
            overrides["variant_params"].setdefault(variant, {})[name] = value
        else:
            overrides[key] = value
    return merge_multi_params(direction, get_active(strategy, direction), overrides)


def invalid_reason(strategy: str, direction: str, combo: dict) -> str | None:
    """Why a grid combination cannot be tuned (see the module docstring), else ``None``."""
    from app.services import strategy_engine as se
    if strategy == "mean_reversion_multi":
        for key in combo:
            if "." not in key and key not in ("min_confirmations", "variants"):
                return f"unknown multi key {key!r}"
        params = combo_params(strategy, direction, combo)
        variants = params.get("variants") or []
        for key in combo:
            if "." in key and key.split(".", 1)[0] not in variants:
                return f"{key!r} names a variant that does not vote"
        mc = params.get("min_confirmations")
        if not variants or not isinstance(mc, int) or not 1 <= mc <= len(variants):
            return f"min_confirmations {mc!r} outside 1..{len(variants)}"
    else:
        params = combo_params(strategy, direction, combo)
    if strategy in ("breakout_setup", "fibonacci_pullback"):
        from app.services.setup_entries import setup_params
        try:
            setup_params(strategy, params)
        except ValueError as exc:
            return str(exc)
    eff = _signals.effective_params(strategy, params)
    if strategy == "ma_crossover":
        fn = se.ma_crossover_signal
        if se._param(fn, eff, "fast") >= se._param(fn, eff, "slow"):
            return "fast >= slow"
    try:
        need = se.bars_needed(strategy, eff)
    except Exception as exc:   # a malformed value the guards cannot read
        return f"bars_needed failed: {exc}"
    if need > se.SIGNAL_WINDOW_BARS:
        return f"needs {need} bars > the {se.SIGNAL_WINDOW_BARS}-bar window"
    return None


# ── per-symbol state and the windowed simulation ─────────────────────────────

@dataclass
class SymbolState:
    symbol: str
    bars: list[dict]
    dates: list[date]
    allowed: list[bool]      # gate mask AND the symbol's own 400th bar
    direction: str = "Bullish"

    @classmethod
    def build(cls, symbol: str, bars: list[dict], allowed_mask: list[bool],
              direction: str = "Bullish") -> "SymbolState":
        from app.services.strategy_engine import SIGNAL_WINDOW_BARS
        first = SIGNAL_WINDOW_BARS - 1
        return cls(symbol, bars, bar_dates(bars),
                   [bool(m) and t >= first for t, m in enumerate(allowed_mask)],
                   normalize_direction(direction))


def count_fires(state: SymbolState, sig, start: date, stop: date, inclusive: bool = False,
                *, extra_allowed: list[bool] | None = None) -> int:
    """Gated events: research entries require setup AND trigger in this span.

    Shared by sample selection and full-universe evidence. Confirmation fires
    are independent of holdings and need not become filled/closed trades.
    """
    from app.services.setup_entries import event_allowed
    lo = bisect.bisect_left(state.dates, start)
    hi = (bisect.bisect_right if inclusive else bisect.bisect_left)(state.dates, stop)
    allowed = state.allowed if extra_allowed is None else [
        a and b for a, b in zip(state.allowed, extra_allowed)]
    end = stop + timedelta(days=1) if inclusive else stop
    return sum(1 for t in range(lo, hi) if sig[t] is not None and
               event_allowed(sig[t], t, state.dates, allowed=allowed,
                             entry_start=start, entry_end=end))


@dataclass
class WindowTrades:
    trades: list[TradeRecord]
    boundary_dropped: int
    end_dropped: int


def simulate_window(state: SymbolState, sig: list[SignalPoint | None], *, entry: tuple[date, date],
                    restriction: date, inclusive: bool, commission: float, hold_max_days: int,
                    extra_allowed: list[bool] | None = None) -> WindowTrades:
    """Trades with signal bars in ``[entry[0], entry[1])`` whose exits are
    before ``restriction`` (on or before it when ``inclusive``).

    The series is cut at the restriction, so a trade that would exit at or
    beyond it is still open at the slice's end: dropped, counted as
    ``boundary_dropped`` when the symbol has bars beyond the cut, else
    ``end_dropped``. ``_LEAD_BARS`` bars before the first entry date are kept
    (no trade is open there, so the result equals the full-series run's).
    """
    dates = state.dates
    lo = max(0, bisect.bisect_left(dates, entry[0]) - _LEAD_BARS)
    hi = (bisect.bisect_right if inclusive else bisect.bisect_left)(dates, restriction)
    if hi <= lo:
        return WindowTrades([], 0, 0)
    allowed = state.allowed[lo:hi]
    if extra_allowed is not None:
        allowed = [a and b for a, b in zip(allowed, extra_allowed[lo:hi])]
    res = simulate_trades(state.bars[lo:hi], sig[lo:hi], direction=state.direction,
                          commission=commission, hold_max_days=hold_max_days,
                          entry_start=entry[0], entry_end=entry[1], allowed=allowed,
                          dates=dates[lo:hi])
    inside = (lambda d: d <= restriction) if inclusive else (lambda d: d < restriction)
    kept = [t for t in res if inside(t.exit_date)]
    crossing = len(res) - len(kept) + (res.dropped_open if hi < len(dates) else 0)
    return WindowTrades(kept, crossing, res.dropped_open if hi >= len(dates) else 0)


# ── process pool ─────────────────────────────────────────────────────────────

def _compute_unit(args) -> str:
    """Worker: one symbol x strategy x direction -> every valid combination's
    signal series and the symbol's gate mask, written to the disk cache."""
    (root, symbol, bars, strategy, direction, params_list,
     scoring_horizon, min_price, max_price, benchmark) = args
    cache = TuningCache(root)
    for params in params_list:
        cache.signal_series(symbol, bars, strategy, direction, params)
    cache.gate_mask(symbol, bars, direction, scoring_horizon,
                    min_price=min_price, max_price=max_price, benchmark=benchmark)
    return symbol


# ── the cell ─────────────────────────────────────────────────────────────────

def _empty_result(cell: Cell, cal, costs, counts, thin=True) -> CellResult:
    zero = {"train": 0, "oos": 0, "heldout": 0}
    return CellResult(cell, cal, costs, None, None, [], {COST: [], STRESS: []},
                      {COST: TradeStats.of([]), STRESS: TradeStats.of([])}, None,
                      {COST: [], STRESS: []}, {COST: TradeStats.of([]), STRESS: TradeStats.of([])},
                      None, None, counts, thin, dict(zero), dict(zero))


def tune_cell(cell: Cell, data: CellData) -> CellResult:
    """Walk-forward for one cell (see the module docstring)."""
    from app.services.strategy_param_store import get_search_by_horizon, get_tuning_config
    if data.workers > 1 and data.cache is None:
        raise ValueError("tune_cell: workers > 1 needs a disk cache (data.cache)")
    direction = normalize_direction(cell.direction)
    strategy, horizon = cell.strategy, cell.horizon
    cfg = data.config if data.config is not None else get_tuning_config()
    grid = data.grid if data.grid is not None else get_search_by_horizon(strategy, direction, horizon)
    hold = HOLD_MAX_DAYS[horizon]
    costs = {COST: cfg["cost_per_leg"], STRESS: cfg["stress_cost_per_leg"]}
    floor = cfg["fire_rate_floor_per_day"][horizon]
    scoring_horizon = _gates.scoring_horizon_for(horizon)
    min_price, max_price = cfg["gates"]["min_price"], cfg["gates"]["max_price"]

    combos = param_combos(grid) if grid else []
    valid: list[tuple[int, dict, dict]] = []      # (grid index, combo, params)
    for gi, combo in enumerate(combos):
        if invalid_reason(strategy, direction, combo) is None:
            valid.append((gi, combo, combo_params(strategy, direction, combo)))
    counts = {"tried": len(combos), "invalid": len(combos) - len(valid), "ineligible": 0,
              "no_winner_folds": 0, "dropped_folds": 0}

    symbols = sorted(data.bars)
    cal = cell_calendar({s: bar_dates(data.bars[s]) for s in symbols},
                        held_out_months=cfg["held_out_months"])
    folds, counts["dropped_folds"] = cell_folds(cal, horizon, cfg)
    thin = len(folds) < cfg["min_folds_not_thin"]
    if not valid:
        return _empty_result(cell, cal, costs, counts, thin)

    # Signals and gate masks: pool -> disk cache, then read in-process.
    if data.workers > 1:
        units = [(str(data.cache.root), s, data.bars[s], strategy, direction,
                  [p for _, _, p in valid], scoring_horizon, min_price, max_price, data.benchmark)
                 for s in symbols]
        with ProcessPoolExecutor(max_workers=data.workers) as pool:
            list(pool.map(_compute_unit, units))

    def _signal(sym: str, params: dict) -> list[SignalPoint | None]:
        if data.cache is not None:
            return data.cache.signal_series(sym, data.bars[sym], strategy, direction, params)
        return _signals.signal_series(data.bars[sym], strategy, direction, params)

    states: dict[str, SymbolState] = {}
    for s in symbols:
        if data.cache is not None:
            mask = data.cache.gate_mask(s, data.bars[s], direction, scoring_horizon,
                                        min_price=min_price, max_price=max_price,
                                        benchmark=data.benchmark)
        else:
            mask = _gates.gate_mask(data.bars[s], direction, scoring_horizon,
                                    min_price=min_price, max_price=max_price,
                                    benchmark=data.benchmark)
        states[s] = SymbolState.build(s, data.bars[s], mask, direction)
    return _tune(cell, data, cfg, cal, folds, valid, states, _signal, costs, counts,
                 hold, floor, thin)


def _tune(cell, data, cfg, cal, folds, valid, states, _signal, costs, counts, hold, floor, thin):
    symbols = sorted(states)
    boundary = {"train": 0, "oos": 0, "heldout": 0}
    end = {"train": 0, "oos": 0, "heldout": 0}
    n_sample_by_sector: dict[str, int] = defaultdict(int)
    for s in symbols:
        n_sample_by_sector[data.sectors[s]] += 1
    cal_dates = cal.dates

    def scan_days(start: date, stop: date, inclusive: bool = False) -> int:
        hi = (bisect.bisect_right if inclusive else bisect.bisect_left)(cal_dates, stop)
        return max(0, hi - bisect.bisect_left(cal_dates, start))

    fires = count_fires

    def rate(fires_by_sector: dict[str, int], days: int) -> float:
        if days <= 0:
            return 0.0
        return _basket.scaled_fire_rate(fires_by_sector, days, data.n_universe_by_sector,
                                         dict(n_sample_by_sector))

    def add(win: WindowTrades, kind: str) -> None:
        boundary[kind] += win.boundary_dropped
        end[kind] += win.end_dropped

    # 1. Selection: every valid combination on every fold's train entries.
    n_valid = len(valid)
    tr_sum = [[0.0] * n_valid for _ in folds]
    tr_n = [[0] * n_valid for _ in folds]
    tr_fires = [[defaultdict(int) for _ in range(n_valid)] for _ in folds]
    for s in symbols:
        st, sector = states[s], data.sectors[s]
        for ci, (_, _, params) in enumerate(valid):
            sig = _signal(s, params)
            for f in folds:
                win = simulate_window(st, sig, entry=f.train_entry, restriction=f.train_end,
                                      inclusive=False, commission=costs[COST], hold_max_days=hold)
                add(win, "train")
                tr_n[f.index][ci] += len(win.trades)
                tr_sum[f.index][ci] += sum(t.net_return_pct for t in win.trades)
                tr_fires[f.index][ci][sector] += fires(st, sig, f.train_start, f.train_end)

    fold_results: list[FoldResult] = []
    winners: list[int | None] = []
    for f in folds:
        days = scan_days(f.train_start, f.train_end)
        best: tuple | None = None
        best_ci: int | None = None
        best_rate = None
        for ci, (gi, _, _) in enumerate(valid):
            n = tr_n[f.index][ci]
            r = rate(tr_fires[f.index][ci], days)
            if n <= 0 or n < cfg["min_train_trades"] or r < floor:
                counts["ineligible"] += 1
                continue
            key = (tr_sum[f.index][ci] / n, n, -gi)
            if best is None or key > best:
                best, best_ci, best_rate = key, ci, r
        winners.append(best_ci)
        if best_ci is None:
            counts["no_winner_folds"] += 1
            fold_results.append(FoldResult(f, None))
        else:
            fold_results.append(FoldResult(
                f, dict(valid[best_ci][1]),
                TradeStats(best[1], 0, best[0]), best_rate))

    # 2. Out-of-sample: each fold's winner on its test entries, both costs.
    oos_trades: dict[str, list[SymbolTrade]] = {COST: [], STRESS: []}
    per_fold: dict[int, dict[str, list[SymbolTrade]]] = {f.index: {COST: [], STRESS: []} for f in folds}
    train_symbols: dict[int, set] = defaultdict(set)
    winner_cis = sorted({ci for ci in winners if ci is not None})
    for s in symbols:
        st = states[s]
        for ci in winner_cis:
            sig = _signal(s, valid[ci][2])
            for f in folds:
                if winners[f.index] != ci:
                    continue
                won = simulate_window(st, sig, entry=f.train_entry, restriction=f.train_end,
                                      inclusive=False, commission=costs[COST], hold_max_days=hold)
                if won.trades:
                    train_symbols[f.index].add(s)
                for label in (COST, STRESS):
                    win = simulate_window(st, sig, entry=f.test_entry, restriction=cal.heldout_start,
                                          inclusive=False, commission=costs[label], hold_max_days=hold)
                    if label == COST:
                        add(win, "oos")
                    per_fold[f.index][label].extend(SymbolTrade(s, t) for t in win.trades)
    for fr in fold_results:
        if fr.winner is None:
            continue
        fr.winner_train = TradeStats(fr.winner_train.n_trades, len(train_symbols[fr.fold.index]),
                                     fr.winner_train.net_expectancy)
        for label in (COST, STRESS):
            trades = _ordered(per_fold[fr.fold.index][label])
            fr.oos[label] = TradeStats.of(trades)
            oos_trades[label].extend(trades)

    # 3. Final parameters: most fold wins; tie -> union-of-train-windows expectancy, grid order.
    wins = Counter(ci for ci in winners if ci is not None)
    if not wins:
        res = _empty_result(cell, cal, costs, counts, thin)
        res.folds, res.boundary_dropped, res.end_dropped = fold_results, boundary, end
        return res
    top = max(wins.values())
    tied = [ci for ci in sorted(wins) if wins[ci] == top]
    final_ci = tied[0]
    if len(tied) > 1:
        final_ci = _union_tiebreak(tied, valid, folds, states, _signal, costs[COST], hold)
    final_combo, final_params = dict(valid[final_ci][1]), valid[final_ci][2]

    # 4. Held-out year and the final parameters' fire rates.
    span = heldout_entry(cal, cell.horizon, cfg)
    held: dict[str, list[SymbolTrade]] = {COST: [], STRESS: []}
    wf_fires: dict[str, int] = defaultdict(int)
    ho_fires: dict[str, int] = defaultdict(int)
    for s in symbols:
        st, sector = states[s], data.sectors[s]
        sig = _signal(s, final_params)
        wf_fires[sector] += fires(st, sig, cal.warm_start, cal.heldout_start)
        ho_fires[sector] += fires(st, sig, cal.heldout_start, cal.data_end, inclusive=True)
        if span is None:
            continue
        for label in (COST, STRESS):
            win = simulate_window(st, sig, entry=span, restriction=cal.data_end, inclusive=True,
                                  commission=costs[label], hold_max_days=hold)
            if label == COST:
                add(win, "heldout")
            held[label].extend(SymbolTrade(s, t) for t in win.trades)
    held = {k: _ordered(v) for k, v in held.items()}

    return CellResult(
        cell=cell, calendar=cal, costs=costs,
        final_params=final_combo,
        final_effective_params=_signals.effective_params(cell.strategy, final_params),
        folds=fold_results,
        oos_trades=oos_trades,
        oos={k: TradeStats.of(v) for k, v in oos_trades.items()},
        heldout_entry=span,
        heldout_trades=held,
        heldout={k: TradeStats.of(v) for k, v in held.items()},
        fire_rate=rate(wf_fires, scan_days(cal.warm_start, cal.heldout_start)),
        heldout_fire_rate=rate(ho_fires, scan_days(cal.heldout_start, cal.data_end, inclusive=True)),
        counts=counts, thin=thin, boundary_dropped=boundary, end_dropped=end,
    )


def _ordered(trades: list[SymbolTrade]) -> list[SymbolTrade]:
    return sorted(trades, key=lambda t: (t.trade.entry_date, t.symbol))


def _union_tiebreak(tied, valid, folds, states, _signal, commission, hold) -> int:
    """Highest pooled net expectancy over the union of the train entry windows
    (signal bar inside any fold's train entry window; exits before the last
    fold's ``train_end``); then grid order."""
    start = min(f.train_entry[0] for f in folds)
    stop = max(f.train_entry[1] for f in folds)
    restriction = max(f.train_end for f in folds)
    spans = sorted(f.train_entry for f in folds)
    best_key, best_ci = None, tied[0]
    for ci in tied:
        total, n = 0.0, 0
        for s in sorted(states):
            st = states[s]
            in_union = [any(a <= d < b for a, b in spans) for d in st.dates]
            win = simulate_window(st, _signal(s, valid[ci][2]), entry=(start, stop),
                                  restriction=restriction, inclusive=False,
                                  commission=commission, hold_max_days=hold,
                                  extra_allowed=in_union)
            total += sum(t.net_return_pct for t in win.trades)
            n += len(win.trades)
        key = (total / n if n else float("-inf"), -valid[ci][0])
        if best_key is None or key > best_key:
            best_key, best_ci = key, ci
    return best_ci
