"""Per-horizon strategy tuner CLI (STOCKS-HORIZON-T1, H8 probe + H10 run).

Tuning run (H10): for each selected cell (strategy x direction x tuned
horizon; default all 60) the walk-forward on the sector sample
(``walk_forward_cell.tune_cell``), the full-universe re-check of the fold
winners and final parameters (``report.full_universe_recheck``), and the
adoption bar (``report.adoption_verdict``). Writes ``tuning_report.md`` and
``tuning_summary.json`` to ``--out`` and one JSON per cell with its trade lists
to ``--data``. Prints the projected runtime (signals, gate masks AND the
simulation) before starting. Nothing is written to ``active:`` (T2).

Bars come from the stored history (``ohlcv_daily``, read only, never fetched),
or from ``<SYMBOL>_candles.json`` files with ``--bars-dir``. The real run is
on the mini PC (T1-MINI-PC-2026-10-09), which holds the latest bars.

``--probe`` (H8) times the signal functions and the trade simulation per
strategy and direction, and the gate mask per direction, on three symbols'
bars, and projects a full run for the configured basket and grids at
``--workers N`` on a synthetic calendar (``--bars-per-symbol`` business days
ending at the export manifest's end date in ``--bars-dir``, else today,
labelled assumed). It reads JSON bar files only; ``--probe-json PATH`` also
writes its summary (command, Python and code identity, fixture hashes,
per-pair costs and the old/new re-check call-count model). Both projections
weight each strategy/direction's work with its own measured cost; they are
projections, not runtime guarantees.

Run from repo root:
    python backend/scripts/tune_horizons.py --probe [--workers 8] [--probe-json PATH]
    python backend/scripts/tune_horizons.py [--cells pullback_ema:Swing,ma_crossover] \
        [--directions Bullish] [--workers N] [--resume]
"""
from __future__ import annotations

import argparse
import asyncio
import bisect
import hashlib
import itertools
import json
import os
import platform
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

# Allow running from repo root: python backend/scripts/tune_horizons.py
sys.path.insert(0, str(Path(__file__).parent.parent))
import pandas as pd  # noqa: E402

import app.services.strategy_param_store as sps  # noqa: E402
from app.services.horizon_profiles import HOLD_MAX_DAYS, TUNED_HORIZONS  # noqa: E402
from app.services.horizon_tuning import basket as _basket  # noqa: E402
from app.services.horizon_tuning import gates as _gates  # noqa: E402
from app.services.horizon_tuning import report as _report  # noqa: E402
from app.services.horizon_tuning import walk_forward_cell as wfc  # noqa: E402
from app.services.horizon_tuning.cache import (  # noqa: E402
    DEFAULT_CACHE_DIR, SIGNAL_CACHE_VERSION, TuningCache, _gate_sources, ohlcv_hash, signal_sources,
)
from app.services.horizon_tuning.signals import (  # noqa: E402
    MIN_SIGNAL_BARS, STATEFUL_STRATEGIES, signal_series,
)
from app.services.horizon_tuning.simulate import bar_dates  # noqa: E402
from app.services.strategy_engine import SIGNAL_WINDOW_BARS, merge_multi_params  # noqa: E402
from app.services.walk_forward import param_combos  # noqa: E402

TUNED_STRATEGIES = ("pullback_ema", "breakout_base", "ma_crossover",
                    "mean_reversion_rsi", "mean_reversion_bb", "mean_reversion_multi")
RESEARCH_STRATEGIES = ("breakout_setup", "fibonacci_pullback")
DIRECTIONS = ("Bullish", "Bearish")
N_SECTORS = 11
# ~2009-10 .. 2026-10 at 252 trading days a year (STOCKS-HORIZON-HISTORY's span).
DEFAULT_BARS_PER_SYMBOL = 4280
BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
FIXTURES = BACKEND / "tests" / "fixtures"
HISTORY_START = date(2000, 1, 1)


def _baseline_params(strategy: str, direction: str) -> dict:
    if strategy == "mean_reversion_multi":
        return merge_multi_params(direction, sps.get_profile(strategy, direction, None)[0], None)
    return sps.get_active(strategy, direction)


def _unique_combos(strategy: str, direction: str, horizons=TUNED_HORIZONS) -> int:
    seen: set[tuple] = set()
    for h in horizons:
        grid = sps.get_search_by_horizon(strategy, direction, h)
        keys = sorted(grid)
        for values in itertools.product(*(grid[k] for k in keys)):
            seen.add(tuple(zip(keys, map(repr, values))))
    return len(seen)


# ── unit-cost calibration (shared by --probe and the run's projection) ────────

def _time_signal_ms(bars: list[dict], strategy: str, direction: str) -> float:
    t0 = time.perf_counter()
    signal_series(bars, strategy, direction, _baseline_params(strategy, direction))
    return (time.perf_counter() - t0) * 1000.0 / max(1, len(bars) - (MIN_SIGNAL_BARS - 1))


def _time_gate_ms(bars: list[dict], direction: str) -> float:
    sample = bars[-200:]
    t0 = time.perf_counter()
    _gates.gate_mask(sample, direction, "Swing", min_price=None, max_price=None, benchmark=None)
    return (time.perf_counter() - t0) * 1000.0 / max(1, len(sample))


def _time_sim_ms(bars: list[dict], strategy: str, direction: str, horizon: str) -> float:
    """One ``simulate_window`` over the series (the unit the walk-forward repeats;
    an upper bound for a fold's shorter window)."""
    sig = signal_series(bars, strategy, direction, _baseline_params(strategy, direction))
    state = wfc.SymbolState.build("PROBE", bars, [True] * len(bars), direction)
    dates = state.dates
    entry = (dates[min(len(dates) - 1, SIGNAL_WINDOW_BARS)], dates[-1])
    reps = 5
    t0 = time.perf_counter()
    for _ in range(reps):
        wfc.simulate_window(state, sig, entry=entry, restriction=dates[-1], inclusive=True,
                            commission=0.0005, hold_max_days=HOLD_MAX_DAYS[horizon])
    return (time.perf_counter() - t0) * 1000.0 / reps


# ── workload model (shared by --probe and the run's projection) ──────────────

def _signal_calls(n_bars: int) -> int:
    """Strategy calls of one full series: every bar from the 60th on."""
    return max(0, n_bars - (MIN_SIGNAL_BARS - 1))


def _entry_window_calls(dates: list[date], entry: tuple[date, date]) -> int:
    """Strategy calls of an ordinary fold winner's scoped series on one symbol:
    the re-check's absolute window ``[bisect_left(dates, entry[0]),
    bisect_left(dates, entry[1]))`` (end exclusive) from the 60th bar on, as
    ``signals.signal_series(..., window=...)`` evaluates it."""
    lo, hi = bisect.bisect_left(dates, entry[0]), bisect.bisect_left(dates, entry[1])
    return max(0, hi - max(lo, MIN_SIGNAL_BARS - 1))


def _work(cells: list[wfc.Cell], *, n_sample: int, sample_calls_by_pair: dict[tuple[str, str], int],
          trade_dates: dict[str, list[date]], final_bars: list[int],
          folds_by_horizon: dict[str, list[wfc.CellFold]], valid_by_cell: dict[wfc.Cell, int]) -> dict:
    """Signal calls and simulated windows per ``(strategy, direction)`` pair,
    gate-mask bars per direction, for these cells.

    Signal calls of a pair: ``sample_calls`` (the sample grid on full history,
    given by the caller) + ``winner_calls`` + ``final_calls`` (the full-universe
    re-check). Before any winner exists the re-check counts one distinct winner
    per fold (a cold-cache upper bound: identical cached series reduce the
    actual work): an ordinary winner only on the eligible bars of its fold's
    test-entry window on each trade-universe symbol's own dates
    (``_entry_window_calls``); a stateful setup winner on full series for up to
    ``min(folds, valid)`` distinct winners. The final parameters run on the full
    series of every trade- AND fire-rate-universe symbol (``final_bars``,
    evidence-only symbols included). A cell with no valid combination or no
    fold has no fold winner, so no final parameters and no re-check.
    ``legacy_recheck_calls`` is the pre-window model (``min(folds, valid) + 1``
    full series per trade symbol), kept for comparison only.

    Gate masks: one per symbol, direction and scoring horizon. Simulation (per
    cell): every valid combination on every fold's train window per sample
    symbol; each fold's winner again on train and twice on test; the held-out
    year twice; the re-check's test (both costs) and inclusive held-out windows
    on the trade universe."""
    n_trade = len(trade_dates)
    trade_full = sum(_signal_calls(len(d)) for d in trade_dates.values())
    final_full = sum(_signal_calls(n) for n in final_bars)
    windows: dict[str, int] = {}
    pairs: dict[tuple[str, str], dict] = {}
    scoring: dict[str, set] = {}
    for c in cells:
        pair = (c.strategy, c.direction)
        p = pairs.setdefault(pair, {"cells": 0, "sample_calls": sample_calls_by_pair.get(pair, 0),
                                    "winner_calls": 0, "final_calls": 0, "legacy_recheck_calls": 0,
                                    "sim_windows": 0})
        p["cells"] += 1
        folds = folds_by_horizon.get(c.horizon, [])
        nf, valid = len(folds), valid_by_cell[c]
        p["legacy_recheck_calls"] += (min(nf, valid) + 1) * trade_full
        if valid == 0:
            continue
        scoring.setdefault(c.direction, set()).add(_gates.scoring_horizon_for(c.horizon))
        if nf == 0:
            continue
        if c.strategy in STATEFUL_STRATEGIES:
            p["winner_calls"] += min(nf, valid) * trade_full
        else:
            if c.horizon not in windows:
                by_list: dict[int, int] = {}       # symbols sharing one date list (the probe's)
                windows[c.horizon] = sum(
                    by_list.setdefault(id(d), sum(_entry_window_calls(d, f.test_entry) for f in folds))
                    for d in trade_dates.values())
            p["winner_calls"] += windows[c.horizon]
        p["final_calls"] += final_full
        p["sim_windows"] += (valid * n_sample * nf + n_sample * nf * 3 + 2 * n_sample
                             + n_trade * nf * 2 + 2 * n_trade)
    gate_per_scoring = sum(final_bars)
    return {"pairs": pairs, "gate_bars": {d: len(s) * gate_per_scoring for d, s in sorted(scoring.items())}}


def _has_work(p: dict) -> bool:
    return bool(p["sample_calls"] + p["winner_calls"] + p["final_calls"] + p["sim_windows"])


def _calibrate(work: dict, cells: list[wfc.Cell], series: list[list[dict]]) -> tuple[dict, dict, dict]:
    """Measured unit costs, only where work remains: per pair the signal
    ms/call (call-weighted over ``series``) and the simulation ms/window (on
    ``series[0]``, at the pair's first cell's hold); per direction the gate
    ms/bar."""
    sig: dict[tuple[str, str], float] = {}
    sim: dict[tuple[str, str], float] = {}
    weights = [_signal_calls(len(b)) for b in series]
    for pair, p in sorted(work["pairs"].items()):
        if not _has_work(p):
            continue
        strategy, direction = pair
        sig[pair] = (sum(_time_signal_ms(b, strategy, direction) * w for b, w in zip(series, weights))
                     / max(1, sum(weights)))
        horizon = next(c.horizon for c in cells if (c.strategy, c.direction) == pair)
        sim[pair] = _time_sim_ms(series[0], strategy, direction, horizon)
    gate = {d: _time_gate_ms(series[0], d) for d, n in work["gate_bars"].items() if n}
    return sig, sim, gate


def _project(work: dict, *, signal_ms: dict, sim_ms: dict, gate_ms: dict, workers: int) -> dict:
    """Hours per pair (its signal calls at its own ms/call, its simulated
    windows at its own ms/window) and for the gate masks (per direction),
    summed. Signal series and gate masks run in the process pool (divided by
    ``workers``); the simulation runs in-process (never divided)."""
    out = {"pairs": {}, "signals_h": 0.0, "gates_h": 0.0, "simulation_h": 0.0, "total_h": 0.0}
    for pair, p in sorted(work["pairs"].items()):
        part = _report.project_runtime(
            signal_ms_per_call=signal_ms.get(pair, 0.0), gate_ms_per_bar=0.0,
            sim_ms_per_window=sim_ms.get(pair, 0.0),
            signal_calls=p["sample_calls"] + p["winner_calls"] + p["final_calls"], gate_bars=0,
            sim_windows=p["sim_windows"], workers=workers)
        out["pairs"][pair] = part
        for k in ("signals_h", "simulation_h", "total_h"):
            out[k] += part[k]
    for d, n in work["gate_bars"].items():
        part = _report.project_runtime(signal_ms_per_call=0.0, gate_ms_per_bar=gate_ms.get(d, 0.0),
                                       sim_ms_per_window=0.0, signal_calls=0, gate_bars=n, sim_windows=0,
                                       workers=workers)
        out["gates_h"] += part["gates_h"]
        out["total_h"] += part["gates_h"]
    return out


def _print_projection(p: dict, workers: int) -> None:
    print(f"projected runtime: {p['total_h']:.2f} h at {workers} workers = signals {p['signals_h']:.2f} h "
          f"+ gate masks {p['gates_h']:.2f} h (process pool: divided by {workers} workers) "
          f"+ simulation {p['simulation_h']:.2f} h (in-process: not divided); "
          f"signal series and gate masks are cached afterwards")
    for (strategy, direction), part in sorted(p["pairs"].items()):
        print(f"  {strategy} {direction}: signals {part['signals_h']:.2f} h + simulation "
              f"{part['simulation_h']:.2f} h")
    print("  (a projection, not a runtime guarantee: each strategy/direction is weighted with its own measured "
          "cost; the full-universe re-check is counted at one distinct winner per fold, a cold-cache upper bound "
          "(identical cached series reduce the actual work), an ordinary winner only on its fold's entry-window "
          "bars, a setup winner and the final parameters on full series)")


def _probe_end(bars_dir: Path) -> tuple[date, str]:
    """The fixed export end date from ``manifest.json`` in the bars directory
    (``export_tuning_bars.py``), else today, labelled as assumed."""
    manifest = Path(bars_dir) / "manifest.json"
    if not manifest.exists():
        return date.today(), "assumed: today (no export manifest.json in the bars directory)"
    end = date.fromisoformat(json.loads(manifest.read_text(encoding="utf-8"))["bounds"]["end"])
    return end, f"fixed export end date (export manifest {manifest})"


def probe(symbols: list[str], bars_dir: Path, workers: int, bars_per_symbol: int,
          cells: list[wfc.Cell] | None = None) -> dict:
    """Time each pair on the probe bars and project a full run of ``cells``.

    The projected history is synthetic: ``bars_per_symbol`` business days per
    symbol ending at the export manifest's end date (else today, labelled
    assumed). Returns the summary (``--probe-json``)."""
    cfg = sps.get_tuning_config()
    basket_n = cfg["basket"]["per_sector"] * N_SECTORS
    raw = {s: (Path(bars_dir) / f"{s}_candles.json").read_bytes() for s in symbols}
    series = {s: json.loads(raw[s].decode("utf-8")) for s in symbols}
    cells = cells if cells is not None else select_cells(None, None)
    end, end_source = _probe_end(bars_dir)
    union = _basket.universe_union()
    trade_names = _basket.trade_universe(union)
    recheck_names = sorted(set(trade_names) | set(_basket.fire_rate_universe(union)))
    days = [d.date() for d in pd.bdate_range(end=end, periods=bars_per_symbol)]
    cal = wfc.cell_calendar({"SYNTHETIC": days}, held_out_months=cfg["held_out_months"])
    folds = {h: wfc.cell_folds(cal, h, cfg)[0] for h in TUNED_HORIZONS}
    valid = {c: len(param_combos(sps.get_search_by_horizon(c.strategy, c.direction, c.horizon))) for c in cells}
    pairs = sorted({(c.strategy, c.direction) for c in cells})
    combos = {(s, d): _unique_combos(s, d, tuple(c.horizon for c in cells if (c.strategy, c.direction) == (s, d)))
              for s, d in pairs}
    full = _signal_calls(bars_per_symbol)
    work = _work(cells, n_sample=basket_n,
                 sample_calls_by_pair={pair: combos[pair] * basket_n * full for pair in pairs},
                 trade_dates={f"T{i}": days for i in range(len(trade_names))},
                 final_bars=[bars_per_symbol] * len(recheck_names), folds_by_horizon=folds, valid_by_cell=valid)
    sig, sim, gate = _calibrate(work, cells, list(series.values()))
    proj = _project(work, signal_ms=sig, sim_ms=sim, gate_ms=gate, workers=workers)

    print(f"probe: {', '.join(f'{s} ({len(b)} bars)' for s, b in series.items())} from {bars_dir}")
    print(f"basket {basket_n} symbols ({cfg['basket']['per_sector']} x {N_SECTORS} sectors), trade universe "
          f"{len(trade_names)}, re-check universe {len(recheck_names)} (trade + fire-rate), workers {workers}")
    print(f"projected history (not measured): {bars_per_symbol} bars/symbol, business days ending {end} "
          f"({end_source})")
    print("folds per horizon: " + ", ".join(f"{h} {len(f)}" for h, f in folds.items()))
    print(f"{'strategy':<22}{'direction':<10}{'ms/call':>9}{'ms/sim':>8}{'combos':>8}{'sample calls':>15}"
          f"{'winner calls':>15}{'final calls':>14}{'old recheck':>15}{'projected h':>13}")
    for pair in pairs:
        p, part = work["pairs"][pair], proj["pairs"][pair]
        print(f"{pair[0]:<22}{pair[1]:<10}{sig.get(pair, 0.0):>9.3f}{sim.get(pair, 0.0):>8.3f}{combos[pair]:>8}"
              f"{p['sample_calls']:>15,}{p['winner_calls']:>15,}{p['final_calls']:>14,}"
              f"{p['legacy_recheck_calls']:>15,}{part['total_h']:>13.2f}")
    totals = {k: sum(p[k] for p in work["pairs"].values())
              for k in ("sample_calls", "winner_calls", "final_calls", "legacy_recheck_calls", "sim_windows")}
    totals["new_recheck_calls"] = totals["winner_calls"] + totals["final_calls"]
    ratio = (f" ({totals['new_recheck_calls'] / totals['legacy_recheck_calls']:.3f} x)"
             if totals["legacy_recheck_calls"] else "")
    print(f"re-check signal calls (call-count model): new {totals['new_recheck_calls']:,} = winners "
          f"{totals['winner_calls']:,} + final {totals['final_calls']:,}; old full-span model "
          f"{totals['legacy_recheck_calls']:,}{ratio}; sample grids {totals['sample_calls']:,} (full history, "
          f"unchanged)")
    print("gate mask: " + (", ".join(f"{d} {ms:.3f} ms/bar" for d, ms in gate.items()) or "nothing to time"))
    print(f"simulated windows: {totals['sim_windows']:,} ({len(cells)} cells, sample {basket_n}, "
          f"trade universe {len(trade_names)}; grids before invalid combinations are skipped)")
    _print_projection(proj, workers)
    windows = [min(len(b), SIGNAL_WINDOW_BARS) for b in series.values()]
    if windows and max(windows) < SIGNAL_WINDOW_BARS:
        print(f"note: these bars give windows of at most {max(windows)} bars; live and tuned signals "
              f"use {SIGNAL_WINDOW_BARS}, so per-call cost on stored history is higher "
              f"(about x{SIGNAL_WINDOW_BARS / max(windows):.1f} if linear in the window)")
    return {
        "symbols": list(symbols), "bars_dir": str(bars_dir), "workers": workers, "cells": len(cells),
        "fixtures": {s: {"file": f"{s}_candles.json", "sha256": hashlib.sha256(raw[s]).hexdigest(),
                         "ohlcv_hash": ohlcv_hash(series[s]), "bars": len(series[s]),
                         "first": series[s][0]["time"] if series[s] else None,
                         "last": series[s][-1]["time"] if series[s] else None} for s in symbols},
        "assumptions": {"end": end.isoformat(), "end_source": end_source, "bars_per_symbol": bars_per_symbol,
                        "basket": basket_n, "trade_universe": len(trade_names),
                        "recheck_universe": len(recheck_names),
                        "folds": {h: len(f) for h, f in folds.items()}},
        "pairs": {f"{s}|{d}": {**work["pairs"][(s, d)], "combos": combos[(s, d)],
                               "signal_ms_per_call": sig.get((s, d)), "sim_ms_per_window": sim.get((s, d)),
                               **{k: proj["pairs"][(s, d)][k] for k in ("signals_h", "simulation_h", "total_h")}}
                  for s, d in pairs},
        "gate_ms_per_bar": gate, "gate_bars": work["gate_bars"], "totals": totals,
        "projection": {k: proj[k] for k in ("signals_h", "gates_h", "simulation_h", "total_h")},
    }


# ── loading bars ─────────────────────────────────────────────────────────────

def _load_bars_dir(symbols: list[str], bars_dir: Path) -> dict[str, list[dict]]:
    out = {}
    for s in symbols:
        path = Path(bars_dir) / f"{s}_candles.json"
        if path.exists():
            out[s] = json.loads(path.read_text(encoding="utf-8"))
    return out


def _load_bars_db(symbols: list[str]) -> dict[str, list[dict]]:
    """Stored adjusted bars from ``ohlcv_daily`` (read only: no provider fetch)."""
    from app.database import AsyncSessionLocal
    from app.services.historical_store import _read_bars

    async def _all():
        out = {}
        async with AsyncSessionLocal() as db:
            for s in symbols:
                bars = await _read_bars(s, HISTORY_START, date.today(), db)
                if bars:
                    out[s] = bars
        return out
    return asyncio.run(_all())


def _benchmarks(load, scoring_horizons: set[str]) -> dict[str, list[dict] | None]:
    """The relative-strength benchmark each scoring horizon's scorer reads, resolved as the scan does."""
    from app.routers.stock_scan import _RS_BENCHMARK_PROXY
    from app.scoring.stock_scorer import resolve_rs_benchmark
    out: dict[str, list[dict] | None] = {}
    for h in sorted(scoring_horizons):
        name = resolve_rs_benchmark(h, None)
        proxy = _RS_BENCHMARK_PROXY.get(name.upper()) if name else None
        out[h] = load([proxy]).get(proxy) if proxy else None
        if name and not out[h]:
            print(f"warning: no {proxy or name} bars for the {h} relative-strength benchmark; "
                  f"its trend is unmeasured, as in a scan whose benchmark fetch fails")
    return out


# ── the run ──────────────────────────────────────────────────────────────────

def select_cells(cells_arg: str | None, directions_arg: str | None) -> list[wfc.Cell]:
    """``--cells``: comma-separated ``strategy``, ``horizon`` or ``strategy:horizon``
    tokens (a cell matching any token is selected); ``--directions``: comma-separated."""
    directions = [d.strip().capitalize() for d in (directions_arg or "Bullish,Bearish").split(",") if d.strip()]
    for d in directions:
        if d not in DIRECTIONS:
            raise SystemExit(f"unknown direction {d!r}")
    tokens = [t.strip() for t in (cells_arg or "").split(",") if t.strip()]
    for t in tokens:
        parts = t.split(":")
        if len(parts) > 2 or not all(p in (*TUNED_STRATEGIES, *RESEARCH_STRATEGIES) or p in TUNED_HORIZONS for p in parts):
            raise SystemExit(f"unknown --cells token {t!r}")

    def match(c: wfc.Cell) -> bool:
        return not tokens or any(all(p in (c.strategy, c.horizon) for p in t.split(":")) for t in tokens)
    selected_strategies = (*TUNED_STRATEGIES, *(s for s in RESEARCH_STRATEGIES
                           if any(s in t.split(":") for t in tokens)))
    return [c for s in selected_strategies for d in directions for h in TUNED_HORIZONS
            if match(c := wfc.Cell(s, d, h))]


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def run_identity(cell: wfc.Cell, config: dict, grid: dict, data_hash: str) -> str:
    """Identity for resumable results, including signal/order implementation."""
    return _sha({"cell": [cell.strategy, cell.direction, cell.horizon],
                 "tuning": config, "grid": grid,
                 "baseline": wfc.combo_params(cell.strategy, cell.direction, {}),
                 "exit": sps.get_exit(cell.strategy), "signal_version": SIGNAL_CACHE_VERSION,
                 "signal_sources": signal_sources(), "window": SIGNAL_WINDOW_BARS,
                 "gate_sources": _gate_sources(), "data": data_hash})


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True,
                              timeout=10).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def run(args) -> int:
    t_start = time.perf_counter()
    cfg = sps.get_tuning_config()
    cells = select_cells(args.cells, args.directions)
    union = ([s.strip().upper() for s in args.symbols.split(",") if s.strip()]
             if args.symbols else _basket.universe_union())
    trade_names = _basket.trade_universe(union)
    fire_names = _basket.fire_rate_universe(union)

    def load(symbols):
        return _load_bars_dir(symbols, args.bars_dir) if args.bars_dir else _load_bars_db(symbols)

    bars = load(sorted(set(fire_names) | set(trade_names)))
    trade = [s for s in trade_names if s in bars]
    fire = [s for s in fire_names if s in bars]
    if not trade:
        print("no trade-universe symbol has stored bars")
        return 1

    # The sample: liquidity before heldout_start on the trade universe's calendar.
    pre = wfc.cell_calendar({s: bar_dates(bars[s]) for s in trade}, held_out_months=cfg["held_out_months"])
    liq = {s: _basket.dollar_volume(bars[s], pre.heldout_start) for s in trade}
    sample = _basket.sample_basket(trade, liq, per_sector=cfg["basket"]["per_sector"])
    if not sample.symbols:
        print("the sector sample is empty (no sectored trade-universe symbol has bars)")
        return 1
    sectors = {s: _basket.sector_of(s) for s in sample.symbols}
    n_universe_by_sector = _basket.sector_counts(fire)
    benchmarks = _benchmarks(load, {_gates.scoring_horizon_for(c.horizon) for c in cells})
    cache = TuningCache(args.cache_dir)
    sample_bars = {s: bars[s] for s in sample.symbols}

    data_hash = _sha({"sample": sample.symbols, "trade": trade, "fire": fire,
                      "bars": {s: ohlcv_hash(bars[s]) for s in sorted(bars)},
                      "benchmarks": {h: ohlcv_hash(b) for h, b in sorted(benchmarks.items())},
                      "sectors": sectors, "n_universe_by_sector": n_universe_by_sector})
    grids = {c: sps.get_search_by_horizon(c.strategy, c.direction, c.horizon) for c in cells}

    def run_key(c: wfc.Cell) -> str:
        return run_identity(c, cfg, grids[c], data_hash)

    keys = {c: run_key(c) for c in cells}
    finished = {c: _report.load_finished(args.data, c, keys[c]) for c in cells} if args.resume else {}
    pending = [c for c in cells if finished.get(c) is None]

    # Projected runtime of the PENDING cells, before starting: each pair's signal
    # calls and simulation at its own measured cost, plus the gate masks. The
    # folds are tune_cell's: the sample's calendar. Nothing pending: nothing timed.
    proj = _project({"pairs": {}, "gate_bars": {}}, signal_ms={}, sim_ms={}, gate_ms={}, workers=args.workers)
    if pending:
        cell_cal = wfc.cell_calendar({s: bar_dates(b) for s, b in sample_bars.items()},
                                     held_out_months=cfg["held_out_months"])
        folds_by_h = {h: wfc.cell_folds(cell_cal, h, cfg)[0] for h in sorted({c.horizon for c in pending})}
        valid = {c: sum(1 for combo in (param_combos(grids[c]) if grids[c] else [])
                        if wfc.invalid_reason(c.strategy, c.direction, combo) is None) for c in pending}
        by_sd: dict[tuple, int] = {}
        for c in pending:
            by_sd[(c.strategy, c.direction)] = by_sd.get((c.strategy, c.direction), 0) + valid[c]
        sample_calls = sum(_signal_calls(len(b)) for b in sample_bars.values())
        work = _work(pending, n_sample=len(sample.symbols),
                     sample_calls_by_pair={sd: n * sample_calls for sd, n in by_sd.items()},
                     trade_dates={s: bar_dates(bars[s]) for s in trade},
                     final_bars=[len(bars[s]) for s in sorted(set(trade) | set(fire))],
                     folds_by_horizon=folds_by_h, valid_by_cell=valid)
        sig, sim, gate = _calibrate(work, pending, [sample_bars[sample.symbols[0]]])
        proj = _project(work, signal_ms=sig, sim_ms=sim, gate_ms=gate, workers=args.workers)
    print(f"{len(cells)} cells ({len(cells) - len(pending)} finished, skipped by --resume); "
          f"sample {len(sample.symbols)}, trade universe {len(trade)}, fire-rate universe {len(fire)}")
    _print_projection(proj, args.workers)
    print("  (a grid combination shared by several horizons' grids is counted once per horizon)")

    rows: list[dict] = []
    verdicts: list[tuple[wfc.Cell, _report.Verdict]] = []
    for c in cells:
        row = finished.get(c)
        if row is None:
            t0 = time.perf_counter()
            bench = benchmarks.get(_gates.scoring_horizon_for(c.horizon))
            result = wfc.tune_cell(c, wfc.CellData(
                bars=sample_bars, sectors=sectors, n_universe_by_sector=n_universe_by_sector,
                config=cfg, grid=grids[c], benchmark=bench, cache=cache, workers=args.workers))
            recheck = _report.full_universe_recheck(result, _report.UniverseData(
                bars=bars, trade_universe=trade, fire_rate_universe=fire,
                benchmark=bench, cache=cache, workers=args.workers), cfg)
            verdict = _report.adoption_verdict(c, recheck, cfg)
            row = _report.cell_row(result, recheck, verdict, cfg)
            row["runtime_s"] = time.perf_counter() - t0
            _report.write_cell(args.data, c, _report.cell_payload(row, result, recheck, keys[c]))
            print(f"{c.strategy} {c.direction} {c.horizon}: {row['verdict']} ({row['runtime_s']:.0f} s)")
        rows.append(row)
        verdicts.append((c, _report.Verdict(passes_bar=row["passes_bar"], failed=row["failed_criteria"],
                                            blocked=row["verdict"] == "blocked (P0B)")))

    all_dates = sorted({d for s in trade for d in bar_dates(bars[s])})
    header = {
        "git_commit": _git_commit(),
        "data_range": [all_dates[0].isoformat(), all_dates[-1].isoformat()],
        "sample_size": len(sample.symbols), "sample_symbols": sample.symbols,
        "sample_unsectored": sample.unsectored, "per_sector": cfg["basket"]["per_sector"],
        "trade_universe_size": len(trade), "fire_rate_universe_size": len(fire),
        "cost_per_leg": cfg["cost_per_leg"], "stress_cost_per_leg": cfg["stress_cost_per_leg"],
        "runtime_s": time.perf_counter() - t_start, "projected_h": proj["total_h"],
        "not_applied": list(_report.NOT_APPLIED), "tuning": cfg,
    }
    chance = _report.chance_count(verdicts, ci_level=cfg["adoption"]["ci_level"])
    _report.write_report(args.out, header, rows, chance)
    print(f"wrote {Path(args.out) / 'tuning_report.md'} and {Path(args.data) / 'cells'}")
    return 0


def _code_identity() -> dict:
    """HEAD, uncommitted changes to the tuner code, and the LF-normalized
    sha256 of the files the projection runs."""
    paths = [Path(__file__).resolve(), *sorted((BACKEND / "app" / "services" / "horizon_tuning").glob("*.py"))]
    try:
        changed = subprocess.run(["git", "status", "--porcelain", "--", "backend/scripts/tune_horizons.py",
                                  "backend/app/services/horizon_tuning"], cwd=REPO, capture_output=True,
                                 text=True, timeout=10).stdout.splitlines()
    except Exception:
        changed = ["unknown"]
    return {"git_commit": _git_commit(), "uncommitted_tuner_changes": changed,
            "sources": {p.relative_to(REPO).as_posix(): hashlib.sha256(
                p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in paths},
            "signal_sources": signal_sources()}


def _write_probe_json(path: Path, summary: dict, argv: list[str]) -> None:
    out = {"command": ["python", "backend/scripts/tune_horizons.py", *argv],
           "python": platform.python_version(), "code": _code_identity(), **summary}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(out, indent=1, sort_keys=False, default=str) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    today = date.today().isoformat()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--probe", action="store_true", help="time signals, gates and simulation; project a full run")
    ap.add_argument("--cells", default=None,
                    help="comma-separated strategy, horizon or strategy:horizon filters (default: all 60 cells)")
    ap.add_argument("--directions", default="Bullish,Bearish")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--resume", action="store_true", help="skip cells already finished for this config + data")
    ap.add_argument("--out", type=Path,
                    default=REPO / "docs" / "superpowers" / "measurements" / f"{today}-horizon-tuning")
    ap.add_argument("--data", type=Path, default=BACKEND / "data" / "tuning_runs" / today)
    ap.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    ap.add_argument("--symbols", default=None,
                    help="restrict the universe (run) / the three probe symbols (default AAPL,MSFT,NVDA)")
    ap.add_argument("--bars-dir", type=Path, default=None,
                    help="read <SYMBOL>_candles.json bars from here instead of ohlcv_daily")
    ap.add_argument("--bars-per-symbol", type=int, default=DEFAULT_BARS_PER_SYMBOL,
                    help="--probe: assumed bars per symbol of the projected history")
    ap.add_argument("--probe-json", type=Path, default=None,
                    help="--probe: also write the probe summary (identity, fixtures, per-pair costs) here")
    args = ap.parse_args(argv)
    if args.probe:
        summary = probe([s.strip().upper() for s in (args.symbols or "AAPL,MSFT,NVDA").split(",") if s.strip()],
                        args.bars_dir or FIXTURES, args.workers, args.bars_per_symbol,
                        select_cells(args.cells, args.directions))
        if args.probe_json is not None:
            _write_probe_json(args.probe_json, summary, list(sys.argv[1:] if argv is None else argv))
        return 0
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
