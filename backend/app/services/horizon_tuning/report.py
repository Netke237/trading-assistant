"""Full-universe re-check, adoption bar and report — STOCKS-HORIZON-T1 H10.

* **Full-universe re-check** (T1-BASKET-SECTOR-SAMPLE-2026-10-08). Selection
  stays on the sample (``walk_forward_cell.tune_cell``); evaluation is
  repeated on the full universe: each fold's winner trades that fold's test
  entries on every **trade-universe** symbol (still out of sample), and the
  final parameters trade the held-out year on every trade-universe symbol, at
  both costs. The **fire-rate universe** gives the measured (unscaled) fire
  rate of the final parameters over the walk-forward span ``[warm_start,
  heldout_start)`` and the held-out year ``[heldout_start, data_end]``; its
  evidence-scope symbols add fires, never trades. The cell's own calendar,
  folds and entry cut-offs are reused, so the windows are the sample's.
* **Adoption bar** (ADR decision 5), at ``cost_per_leg`` on the full-universe
  numbers. Criteria 1-4 come from the trade universe, criterion 5 from the
  fire-rate universe:

  1. ``oos_ci_lower``: the OOS net-expectancy CI lower bound > 0, by a
     cluster bootstrap over symbols (``cluster_bootstrap_ci``);
  2. ``heldout_expectancy``: held-out net expectancy > 0;
  3. ``min_oos_trades``: pooled OOS trades >= ``adoption.min_oos_trades``;
  4. ``min_symbols``: symbols with >= 1 OOS trade >= ``adoption.min_symbols``;
  5. ``fire_rate``: the measured full-universe fire rate over the
     walk-forward span >= the horizon's floor.

  Bearish cells are computed and shown, labelled ``blocked (P0B)`` whatever
  the verdict. Nothing is written to ``active:`` (T2).
* **Chance count** over the bullish cells only:
  ``expected ~= n x (1 - ci_level) / 2 x 0.5``.
"""
from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from app.services.horizon_profiles import HOLD_MAX_DAYS
from app.services.horizon_tuning import NOT_APPLIED
from app.services.horizon_tuning import basket
from app.services.horizon_tuning import gates as _gates
from app.services.horizon_tuning import signals as _signals
from app.services.horizon_tuning import walk_forward_cell as wfc
from app.services.horizon_tuning.cache import TuningCache
from app.services.horizon_tuning.walk_forward_cell import (
    COST, STRESS, Cell, CellResult, SymbolState, SymbolTrade, TradeStats,
)

CRITERIA: tuple[str, ...] = ("oos_ci_lower", "heldout_expectancy", "min_oos_trades",
                             "min_symbols", "fire_rate")


# ── bootstrap ────────────────────────────────────────────────────────────────

def _tails(means: np.ndarray, ci_level: float) -> tuple[float, float]:
    tail = (1 - ci_level) / 2 * 100
    return float(np.percentile(means, tail)), float(np.percentile(means, 100 - tail))


def cluster_bootstrap_ci(trades: list[SymbolTrade], *, resamples: int, seed: int,
                         ci_level: float) -> tuple[float, float] | None:
    """Net-expectancy CI by a cluster bootstrap over symbols: trades grouped
    by symbol; each resample draws ``S`` symbols with replacement (``S`` =
    symbols with >= 1 trade), concatenates all their trades and takes the
    trade-weighted mean. ``numpy.random.default_rng(seed)``. ``None`` for no
    trades."""
    if not trades:
        return None
    sums: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for t in trades:
        sums[t.symbol] += t.trade.net_return_pct
        counts[t.symbol] += 1
    syms = sorted(sums)
    s_arr = np.array([sums[s] for s in syms])
    n_arr = np.array([counts[s] for s in syms])
    rng = np.random.default_rng(seed)
    means = np.empty(resamples)
    for r in range(resamples):
        pick = rng.integers(0, len(syms), size=len(syms))
        means[r] = s_arr[pick].sum() / n_arr[pick].sum()
    return _tails(means, ci_level)


def per_trade_bootstrap_ci(trades: list[SymbolTrade], *, resamples: int, seed: int,
                           ci_level: float) -> tuple[float, float] | None:
    """The naive per-trade bootstrap (shown for comparison only: it ignores
    that one symbol's trades move together)."""
    if not trades:
        return None
    vals = np.array([t.trade.net_return_pct for t in trades])
    rng = np.random.default_rng(seed)
    means = np.empty(resamples)
    for r in range(resamples):
        means[r] = vals[rng.integers(0, len(vals), size=len(vals))].mean()
    return _tails(means, ci_level)


# ── full-universe re-check ───────────────────────────────────────────────────

@dataclass
class UniverseData:
    """``bars`` for every symbol of both universes; ``trade_universe`` (the
    union minus both exclusion scopes) and ``fire_rate_universe`` (minus the
    scan scope only)."""
    bars: dict[str, list[dict]]
    trade_universe: list[str]
    fire_rate_universe: list[str]
    benchmark: list[dict] | None = None
    cache: TuningCache | None = None
    workers: int = 1


@dataclass
class Recheck:
    oos_trades: dict[str, list[SymbolTrade]]
    oos: dict[str, TradeStats]
    heldout_trades: dict[str, list[SymbolTrade]]
    heldout: dict[str, TradeStats]
    fire_rate: float | None             # measured, final params, [warm_start, heldout_start)
    heldout_fire_rate: float | None     # measured, final params, [heldout_start, data_end]
    fires_by_symbol: dict[str, int]     # walk-forward span + held-out year
    n_trade_symbols: int
    n_fire_symbols: int
    boundary_dropped: dict[str, int]
    end_dropped: dict[str, int]


def _empty_recheck(n_trade: int, n_fire: int) -> Recheck:
    empty = {COST: [], STRESS: []}
    return Recheck({COST: [], STRESS: []}, {k: TradeStats.of([]) for k in empty},
                   {COST: [], STRESS: []}, {k: TradeStats.of([]) for k in empty},
                   None, None, {}, n_trade, n_fire, {"oos": 0, "heldout": 0}, {"oos": 0, "heldout": 0})


def full_universe_recheck(result: CellResult, universe: UniverseData, config: dict) -> Recheck:
    """Fold winners and final parameters re-evaluated on the full universe
    (see the module docstring)."""
    import bisect
    cell, cal = result.cell, result.calendar
    trade_syms = [s for s in universe.trade_universe if s in universe.bars]
    fire_syms = [s for s in universe.fire_rate_universe if s in universe.bars]
    if universe.workers > 1 and universe.cache is None:
        raise ValueError("full_universe_recheck: workers > 1 needs a disk cache")
    winners = [f for f in result.folds if f.winner is not None]
    if result.final_params is None or cal is None or cal.warm_start is None:
        return _empty_recheck(len(trade_syms), len(fire_syms))

    direction, strategy = wfc.normalize_direction(cell.direction), cell.strategy
    hold = HOLD_MAX_DAYS[cell.horizon]
    scoring_horizon = _gates.scoring_horizon_for(cell.horizon)
    min_price, max_price = config["gates"]["min_price"], config["gates"]["max_price"]
    final_params = wfc.combo_params(strategy, direction, result.final_params)
    winner_params = {id(f): wfc.combo_params(strategy, direction, f.winner) for f in winners}
    distinct: list[dict] = []
    for p in [*winner_params.values(), final_params]:
        if p not in distinct:
            distinct.append(p)
    symbols = sorted(set(trade_syms) | set(fire_syms))

    if universe.workers > 1:
        units = [(str(universe.cache.root), s, universe.bars[s], strategy, direction, distinct,
                  scoring_horizon, min_price, max_price, universe.benchmark) for s in symbols]
        with ProcessPoolExecutor(max_workers=universe.workers) as pool:
            list(pool.map(wfc._compute_unit, units))

    def _signal(sym: str, params: dict):
        if universe.cache is not None:
            return universe.cache.signal_series(sym, universe.bars[sym], strategy, direction, params)
        return _signals.signal_series(universe.bars[sym], strategy, direction, params)

    def _state(sym: str) -> SymbolState:
        kw = dict(min_price=min_price, max_price=max_price, benchmark=universe.benchmark)
        if universe.cache is not None:
            mask = universe.cache.gate_mask(sym, universe.bars[sym], direction, scoring_horizon, **kw)
        else:
            mask = _gates.gate_mask(universe.bars[sym], direction, scoring_horizon, **kw)
        return SymbolState.build(sym, universe.bars[sym], mask, direction)

    boundary = {"oos": 0, "heldout": 0}
    end = {"oos": 0, "heldout": 0}
    oos: dict[str, list[SymbolTrade]] = {COST: [], STRESS: []}
    held: dict[str, list[SymbolTrade]] = {COST: [], STRESS: []}
    fires_wf: dict[str, int] = {}
    fires_ho: dict[str, int] = {}
    span = result.heldout_entry
    trade_set = set(trade_syms)

    fires = wfc.count_fires

    for s in symbols:
        st = _state(s)
        final_sig = _signal(s, final_params)
        if s in fire_syms:
            fires_wf[s] = fires(st, final_sig, cal.warm_start, cal.heldout_start)
            fires_ho[s] = fires(st, final_sig, cal.heldout_start, cal.data_end, inclusive=True)
        if s not in trade_set:
            continue                      # evidence scope: fires only, never a trade
        for f in winners:
            sig = _signal(s, winner_params[id(f)])
            for label in (COST, STRESS):
                win = wfc.simulate_window(st, sig, entry=f.fold.test_entry, restriction=cal.heldout_start,
                                          inclusive=False, commission=result.costs[label],
                                          hold_max_days=hold)
                if label == COST:
                    boundary["oos"] += win.boundary_dropped
                    end["oos"] += win.end_dropped
                oos[label].extend(SymbolTrade(s, t) for t in win.trades)
        if span is None:
            continue
        for label in (COST, STRESS):
            win = wfc.simulate_window(st, final_sig, entry=span, restriction=cal.data_end, inclusive=True,
                                      commission=result.costs[label], hold_max_days=hold)
            if label == COST:
                boundary["heldout"] += win.boundary_dropped
                end["heldout"] += win.end_dropped
            held[label].extend(SymbolTrade(s, t) for t in win.trades)

    dates = cal.dates
    wf_days = bisect.bisect_left(dates, cal.heldout_start) - bisect.bisect_left(dates, cal.warm_start)
    ho_days = bisect.bisect_right(dates, cal.data_end) - bisect.bisect_left(dates, cal.heldout_start)
    oos = {k: wfc._ordered(v) for k, v in oos.items()}
    held = {k: wfc._ordered(v) for k, v in held.items()}
    return Recheck(
        oos_trades=oos, oos={k: TradeStats.of(v) for k, v in oos.items()},
        heldout_trades=held, heldout={k: TradeStats.of(v) for k, v in held.items()},
        fire_rate=sum(fires_wf.values()) / wf_days if wf_days > 0 else None,
        heldout_fire_rate=sum(fires_ho.values()) / ho_days if ho_days > 0 else None,
        fires_by_symbol={s: fires_wf[s] + fires_ho[s] for s in fires_wf},
        n_trade_symbols=len(trade_syms), n_fire_symbols=len(fire_syms),
        boundary_dropped=boundary, end_dropped=end,
    )


# ── adoption bar and chance count ────────────────────────────────────────────

@dataclass
class Verdict:
    passes_bar: bool
    failed: list[str]
    blocked: bool
    ci: dict[str, tuple[float, float] | None] = field(default_factory=dict)

    @property
    def label(self) -> str:
        if self.blocked:
            return "blocked (P0B)"
        return "passes" if self.passes_bar else "fails"


def adoption_verdict(cell: Cell, recheck: Recheck, config: dict) -> Verdict:
    """The five-criterion bar on the full-universe numbers (module docstring)."""
    a = config["adoption"]
    ci = {label: cluster_bootstrap_ci(recheck.oos_trades[label], resamples=a["bootstrap_resamples"],
                                      seed=a["seed"], ci_level=a["ci_level"])
          for label in (COST, STRESS)}
    oos, held = recheck.oos[COST], recheck.heldout[COST]
    ok = {
        "oos_ci_lower": ci[COST] is not None and ci[COST][0] > 0,
        "heldout_expectancy": held.net_expectancy is not None and held.net_expectancy > 0,
        "min_oos_trades": oos.n_trades >= a["min_oos_trades"],
        "min_symbols": oos.n_symbols >= a["min_symbols"],
        "fire_rate": (recheck.fire_rate is not None
                      and recheck.fire_rate >= config["fire_rate_floor_per_day"][cell.horizon]),
    }
    failed = [c for c in CRITERIA if not ok[c]]
    return Verdict(passes_bar=not failed, failed=failed,
                   blocked=wfc.normalize_direction(cell.direction) == "Bearish", ci=ci)


def chance_count(verdicts: list[tuple[Cell, Verdict]], *, ci_level: float) -> dict:
    """Bullish cells passed vs expected by chance (bearish cells are blocked)."""
    bullish = [v for c, v in verdicts if wfc.normalize_direction(c.direction) == "Bullish"]
    miss = (1 - ci_level) / 2
    n = len(bullish)
    return {
        "bullish_cells_evaluated": n,
        "bullish_cells_passed": sum(1 for v in bullish if v.passes_bar),
        "expected_by_chance": n * miss * 0.5,
        "formula": (f"expected by chance ~= n_bullish_cells_evaluated x {miss:g} x 0.5 = "
                    f"{n} x {miss:g} x 0.5 = {n * miss * 0.5:.4g} (one-sided CI miss under no edge x "
                    f"an independent held-out coin flip; an approximation: cells share symbols and "
                    f"periods, so they are not independent)"),
    }


# ── runtime projection ───────────────────────────────────────────────────────

def project_runtime(*, signal_ms_per_call: float, gate_ms_per_bar: float, sim_ms_per_window: float,
                    signal_calls: int, gate_bars: int, sim_windows: int, workers: int) -> dict:
    """Hours for signal series and gate masks (in the process pool, divided by
    ``workers``) and for the simulation (in-process)."""
    w = max(1, workers)
    sig = signal_calls * signal_ms_per_call / 1000 / w / 3600
    gate = gate_bars * gate_ms_per_bar / 1000 / w / 3600
    sim = sim_windows * sim_ms_per_window / 1000 / 3600
    return {"signals_h": sig, "gates_h": gate, "simulation_h": sim, "total_h": sig + gate + sim}


# ── rows and files ───────────────────────────────────────────────────────────

REPORT_COLUMNS: tuple[str, ...] = (
    "strategy", "direction", "horizon", "final_params",
    "sample_oos_trades", "sample_oos_symbols", "sample_oos_exp_cost", "sample_oos_ci_cost",
    "sample_oos_exp_stress", "sample_oos_ci_stress",
    "oos_trades", "oos_symbols", "oos_exp_cost", "oos_ci_cost", "oos_exp_stress", "oos_ci_stress",
    "sample_heldout_exp_cost", "sample_heldout_exp_stress",
    "heldout_trades", "heldout_exp_cost", "heldout_exp_stress", "heldout_entry_span",
    "fire_rate_scaled", "fire_rate_full_wf", "fire_rate_full_heldout",
    "folds", "thin", "verdict", "failed_criteria",
)


def _iso(span) -> list[str] | None:
    return None if span is None else [span[0].isoformat(), span[1].isoformat()]


def cell_row(result: CellResult, recheck: Recheck, verdict: Verdict, config: dict) -> dict:
    """One report row (every ``REPORT_COLUMNS`` key, no trade lists)."""
    a = config["adoption"]
    sample_ci = {label: cluster_bootstrap_ci(result.oos_trades[label], resamples=a["bootstrap_resamples"],
                                             seed=a["seed"], ci_level=a["ci_level"])
                 for label in (COST, STRESS)}
    c = result.cell
    return {
        "strategy": c.strategy, "direction": c.direction, "horizon": c.horizon,
        "research_only": c.strategy in ("breakout_setup", "fibonacci_pullback"),
        "fire_rate_basis": ("gated confirmed entry events" if c.strategy in
                            ("breakout_setup", "fibonacci_pullback") else "gated strategy signals"),
        "final_params": result.final_params,
        "sample_oos_trades": result.oos[COST].n_trades,
        "sample_oos_symbols": result.oos[COST].n_symbols,
        "sample_oos_exp_cost": result.oos[COST].net_expectancy,
        "sample_oos_ci_cost": sample_ci[COST],
        "sample_oos_exp_stress": result.oos[STRESS].net_expectancy,
        "sample_oos_ci_stress": sample_ci[STRESS],
        "oos_trades": recheck.oos[COST].n_trades,
        "oos_symbols": recheck.oos[COST].n_symbols,
        "oos_exp_cost": recheck.oos[COST].net_expectancy,
        "oos_ci_cost": verdict.ci.get(COST),
        "oos_exp_stress": recheck.oos[STRESS].net_expectancy,
        "oos_ci_stress": verdict.ci.get(STRESS),
        "sample_heldout_exp_cost": result.heldout[COST].net_expectancy,
        "sample_heldout_exp_stress": result.heldout[STRESS].net_expectancy,
        "heldout_trades": recheck.heldout[COST].n_trades,
        "heldout_exp_cost": recheck.heldout[COST].net_expectancy,
        "heldout_exp_stress": recheck.heldout[STRESS].net_expectancy,
        "heldout_entry_span": _iso(result.heldout_entry),
        "fire_rate_scaled": result.fire_rate,
        "fire_rate_full_wf": recheck.fire_rate,
        "fire_rate_full_heldout": recheck.heldout_fire_rate,
        "folds": len(result.folds),
        "thin": result.thin,
        "verdict": verdict.label,
        "passes_bar": verdict.passes_bar,
        "failed_criteria": list(verdict.failed),
        "counts": dict(result.counts),
        "fold_dates": [{"train": [f.fold.train_start.isoformat(), f.fold.train_end.isoformat()],
                        "test": [f.fold.test_start.isoformat(), f.fold.test_end.isoformat()],
                        "winner": f.winner} for f in result.folds],
        "boundary_dropped": {"sample": dict(result.boundary_dropped),
                             "universe": dict(recheck.boundary_dropped)},
        "end_dropped": {"sample": dict(result.end_dropped), "universe": dict(recheck.end_dropped)},
    }


def _trade_list(trades: dict[str, list[SymbolTrade]]) -> dict[str, list[dict]]:
    return {label: [{"symbol": t.symbol, **{k: (v.isoformat() if hasattr(v, "isoformat") else v)
                                            for k, v in asdict(t.trade).items()}} for t in lst]
            for label, lst in trades.items()}


def cell_payload(row: dict, result: CellResult, recheck: Recheck, run_key: str) -> dict:
    """The per-cell JSON under ``--data``: the row plus every trade list."""
    return {
        "run_key": run_key,
        "row": row,
        "final_effective_params": result.final_effective_params,
        "sample": {"oos_trade_list": _trade_list(result.oos_trades),
                   "heldout_trade_list": _trade_list(result.heldout_trades)},
        "universe": {"oos_trade_list": _trade_list(recheck.oos_trades),
                     "heldout_trade_list": _trade_list(recheck.heldout_trades),
                     "fires_by_symbol": recheck.fires_by_symbol},
    }


def cell_file(data_dir: Path, cell: Cell) -> Path:
    return Path(data_dir) / "cells" / f"{cell.strategy}__{cell.direction}__{cell.horizon}.json"


def load_finished(data_dir: Path, cell: Cell, run_key: str) -> dict | None:
    """The finished cell's row when its file exists for the same ``run_key``."""
    try:
        payload = json.loads(cell_file(data_dir, cell).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload.get("row") if payload.get("run_key") == run_key else None


def write_cell(data_dir: Path, cell: Cell, payload: dict) -> None:
    path = cell_file(data_dir, cell)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")


def _fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.3f}"
    if isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(x, float) for x in v):
        return f"[{v[0]:.3f}, {v[1]:.3f}]"
    if isinstance(v, dict):
        return ", ".join(f"{k}={x}" for k, x in v.items()) or "-"
    if isinstance(v, list):
        return ", ".join(map(str, v)) or "-"
    return str(v).replace("|", "/")


def _table(rows: list[dict]) -> list[str]:
    out = ["| " + " | ".join(REPORT_COLUMNS) + " |", "|" + "---|" * len(REPORT_COLUMNS)]
    for r in rows:
        cells = [(" .. ".join(r[c]) if c == "heldout_entry_span" and r.get(c) else _fmt(r.get(c)))
                 for c in REPORT_COLUMNS]
        out.append("| " + " | ".join(cells) + " |")
    return out


def header_lines(header: dict) -> list[str]:
    cost, stress = header["cost_per_leg"], header["stress_cost_per_leg"]
    return [
        "# Per-horizon tuning report (STOCKS-HORIZON-T1)",
        "",
        f"- git commit: {header['git_commit']}",
        f"- data range: {header['data_range'][0]} .. {header['data_range'][1]}",
        f"- sample: {header['sample_size']} symbols, {basket.SAMPLE_LABEL}; "
        f"per sector {header['per_sector']}",
        f"- universe: trade universe {header['trade_universe_size']} symbols (S&P 500 + NDX 100 minus both "
        f"exclusion scopes); fire-rate universe {header['fire_rate_universe_size']} symbols (minus the "
        f"scan scope only: evidence-scope symbols add fires, never trades)",
        f"- cost model: {cost * 100:g}% per leg (selection and the adoption bar); stress {stress * 100:g}% "
        f"per leg (reported). The live Step-6 backtest gate keeps its own costs.",
        f"- runtime: {header['runtime_s']:.0f} s total; projected {header['projected_h']:.2f} h",
        "- gates not applied (decision STOCKS-HORIZON-T1-DESIGN-2026-10-05): " + "; ".join(NOT_APPLIED),
        "- current_price: live scans pass the live quote as `current_price` to pullback_ema; "
        "the tuner uses the close",
        "- legacy Settings tuner has no time exit: Settings -> Strategy Tuning "
        "(strategy_param_optimizer.py / walk_forward.py) still runs without a hold.",
        "- survivorship / bull-market label: the universe is today's constituents only (no delisted names), "
        "and the history is mostly a bull market; results overstate what a point-in-time universe would show.",
        "- Annual window note: Annual tests 12 months < 2 x its 200-day hold (13.2 months), as decided; "
        "its held-out entry span is about 12 months - 214 days.",
        "- breakout_setup / fibonacci_pullback are research only: fire rates count gated confirmed "
        "entry events at setup AND trigger, never raw scanner setups. Their scanner UI has no "
        "backtest, adoption, entry/exit integration or broker order bridge. Synthetic fixtures "
        "validate machinery only; historical evidence requires historical data.",
        "- Nothing is written to `active:` (adoption is T2). Bearish cells are blocked (P0B).",
        "- adoption bar (full-universe numbers, cost per leg): OOS cluster-bootstrap CI lower bound > 0; "
        "held-out net expectancy > 0; pooled OOS trades >= min_oos_trades; symbols with an OOS trade >= "
        "min_symbols; measured full-universe walk-forward fire rate >= the horizon floor.",
        "- columns: `sample_*` = the sector sample (selection); unprefixed = the full-universe re-check; "
        f"`*_cost` at {cost * 100:g}%, `*_stress` at {stress * 100:g}%; net expectancy in % per trade.",
    ]


def write_report(out_dir: Path, header: dict, rows: list[dict], chance: dict) -> None:
    """``tuning_report.md`` and ``tuning_summary.json`` (no trade lists)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    bullish = [r for r in rows if r["direction"] == "Bullish"]
    bearish = [r for r in rows if r["direction"] != "Bullish"]
    lines = header_lines(header)
    lines += ["", "## Bullish cells", "", *_table(bullish),
              "", "## Bearish cells (blocked (P0B))", "", *_table(bearish),
              "", "## Chance count (bullish cells only)", "",
              f"- bullish cells passed: {chance['bullish_cells_passed']} of "
              f"{chance['bullish_cells_evaluated']}",
              f"- expected by chance: {chance['expected_by_chance']:.4g}",
              f"- {chance['formula']}", ""]
    (out_dir / "tuning_report.md").write_text("\n".join(lines), encoding="utf-8")
    (out_dir / "tuning_summary.json").write_text(
        json.dumps({"header": header, "chance_count": chance, "cells": rows}, indent=1, default=str),
        encoding="utf-8")
