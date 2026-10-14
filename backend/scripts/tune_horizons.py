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

``--probe`` (H8) times the signal functions, the gate mask and the trade
simulation on three symbols' bars and projects a full run for the configured
basket and grids at ``--workers N``. It reads JSON bar files only.

Run from repo root:
    python backend/scripts/tune_horizons.py --probe [--workers 8]
    python backend/scripts/tune_horizons.py [--cells pullback_ema:Swing,ma_crossover] \
        [--directions Bullish] [--workers N] [--resume]
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import itertools
import json
import os
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
from app.services.horizon_tuning.signals import MIN_SIGNAL_BARS, signal_series  # noqa: E402
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


def _work(cells: list[wfc.Cell], *, n_sample: int, sample_calls: int, n_trade: int, trade_calls: int,
          gate_bars_per_scoring: int, folds_by_horizon: dict[str, int],
          valid_by_cell: dict[wfc.Cell, int], unique_by_sd: dict[tuple, int]) -> dict:
    """Signal calls, gate bars and simulated windows for these cells.

    Signals: each (strategy, direction)'s valid combinations on every sample
    bar (``sample_calls`` = signal calls over the whole sample), plus per cell
    up to ``folds + 1`` distinct winners on every trade-universe bar (the
    re-check; ``trade_calls`` likewise). Gate masks: one per symbol, direction
    and scoring horizon. Simulation: per cell, every valid combination on
    every fold's train window per sample symbol; each fold's winner again on
    train and twice on test; the held-out year twice; the re-check's test and
    held-out windows on the trade universe."""
    signal_calls = sum(unique_by_sd.values()) * sample_calls
    sim = 0
    scoring = set()
    for c in cells:
        folds = folds_by_horizon.get(c.horizon, 0)
        signal_calls += (min(folds, valid_by_cell[c]) + 1) * trade_calls
        sim += valid_by_cell[c] * n_sample * folds + n_sample * folds * 3 + 2 * n_sample
        sim += n_trade * folds * 2 + 2 * n_trade
        scoring.add((c.direction, _gates.scoring_horizon_for(c.horizon)))
    return {"signal_calls": signal_calls, "gate_bars": len(scoring) * gate_bars_per_scoring,
            "sim_windows": sim}


def _print_projection(p: dict, workers: int) -> None:
    print(f"projected runtime: {p['total_h']:.2f} h at {workers} workers = signals {p['signals_h']:.2f} h "
          f"+ gate masks {p['gates_h']:.2f} h (process pool) + simulation {p['simulation_h']:.2f} h "
          f"(in-process); signal series and gate masks are cached afterwards")
    print("  (upper bound: the full-universe re-check is counted at one distinct winner per fold, and "
          "a combination shared by several horizons' grids at once per horizon)")


def _synthetic_folds(bars_per_symbol: int) -> dict[str, int]:
    days = [d.date() for d in pd.bdate_range(end=date.today(), periods=bars_per_symbol)]
    cfg = sps.get_tuning_config()
    cal = wfc.cell_calendar({"X": days}, held_out_months=cfg["held_out_months"])
    return {h: len(wfc.cell_folds(cal, h, cfg)[0]) for h in TUNED_HORIZONS}


def probe(symbols: list[str], bars_dir: Path, workers: int, bars_per_symbol: int,
          cells: list[wfc.Cell] | None = None) -> None:
    cfg = sps.get_tuning_config()
    basket_n = cfg["basket"]["per_sector"] * N_SECTORS
    series = {s: json.loads((bars_dir / f"{s}_candles.json").read_text(encoding="utf-8")) for s in symbols}
    calls_per_symbol = max(0, bars_per_symbol - (MIN_SIGNAL_BARS - 1))
    windows = [min(len(b), SIGNAL_WINDOW_BARS) for b in series.values()]
    print(f"probe: {', '.join(f'{s} ({len(b)} bars)' for s, b in series.items())} from {bars_dir}")
    print(f"basket {basket_n} symbols ({cfg['basket']['per_sector']} x {N_SECTORS} sectors), "
          f"{bars_per_symbol} bars/symbol, workers {workers}")
    print(f"{'strategy':<22}{'direction':<10}{'ms/call':>9}{'combos':>8}{'projected h':>13}")
    total_s = 0.0
    sig_ms: dict[str, float] = {}
    cells = cells if cells is not None else select_cells(None, None)
    pairs = sorted({(c.strategy, c.direction) for c in cells})
    for strategy, direction in pairs:
        params = _baseline_params(strategy, direction)
        calls, t0 = 0, time.perf_counter()
        for bars in series.values():
            signal_series(bars, strategy, direction, params)
            calls += max(0, len(bars) - (MIN_SIGNAL_BARS - 1))
        ms = (time.perf_counter() - t0) * 1000.0 / max(calls, 1)
        sig_ms[strategy] = max(sig_ms.get(strategy, 0.0), ms)
        combos = _unique_combos(strategy, direction,
                                tuple(c.horizon for c in cells if c.strategy == strategy and c.direction == direction))
        secs = combos * basket_n * calls_per_symbol * ms / 1000.0 / max(workers, 1)
        total_s += secs
        print(f"{strategy:<22}{direction:<10}{ms:>9.3f}{combos:>8}{secs / 3600:>13.2f}")
    print(f"projected signal time (sample grids): {total_s / 3600:.2f} h at {workers} workers")

    first = next(iter(series.values()))
    gate_ms = _time_gate_ms(first, "Bullish")
    sim_ms = _time_sim_ms(first, cells[0].strategy, cells[0].direction, cells[0].horizon)
    print(f"gate mask: {gate_ms:.3f} ms/bar; simulation: {sim_ms:.3f} ms per window "
          f"({len(first)}-bar series)")
    folds = _synthetic_folds(bars_per_symbol)
    valid = {c: len(param_combos(sps.get_search_by_horizon(c.strategy, c.direction, c.horizon)))
             for c in cells}
    universe_n = len(_basket.universe_union())
    # Sample signals are the per-strategy table above (unique_by_sd={}); _work adds the
    # re-check's signals over the universe, the gate masks and the simulation.
    work = _work(cells, n_sample=basket_n, sample_calls=0, n_trade=universe_n,
                 trade_calls=universe_n * calls_per_symbol,
                 gate_bars_per_scoring=universe_n * bars_per_symbol, folds_by_horizon=folds,
                 valid_by_cell=valid, unique_by_sd={})
    proj = _report.project_runtime(
        signal_ms_per_call=sum(sig_ms.values()) / len(sig_ms), gate_ms_per_bar=gate_ms,
        sim_ms_per_window=sim_ms, workers=workers, **work)
    proj["signals_h"] += total_s / 3600
    proj["total_h"] += total_s / 3600
    print(f"folds per horizon on {bars_per_symbol} bars: "
          + ", ".join(f"{h} {n}" for h, n in folds.items()))
    print(f"simulated windows: {work['sim_windows']:,} ({len(cells)} cells, sample {basket_n}, "
          f"universe {universe_n}; grids before invalid combinations are skipped)")
    _print_projection(proj, workers)
    if max(windows) < SIGNAL_WINDOW_BARS:
        print(f"note: these bars give windows of at most {max(windows)} bars; live and tuned signals "
              f"use {SIGNAL_WINDOW_BARS}, so per-call cost on stored history is higher "
              f"(about x{SIGNAL_WINDOW_BARS / max(windows):.1f} if linear in the window)")


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

    # Projected runtime, before starting: signals, gate masks and simulation.
    probe_bars = sample_bars[sample.symbols[0]]
    folds_by_h = {h: len(wfc.cell_folds(pre, h, cfg)[0]) for h in TUNED_HORIZONS}
    valid = {c: sum(1 for combo in (param_combos(grids[c]) if grids[c] else [])
                    if wfc.invalid_reason(c.strategy, c.direction, combo) is None) for c in cells}
    by_sd: dict[tuple, int] = {}
    for c in pending:
        by_sd[(c.strategy, c.direction)] = by_sd.get((c.strategy, c.direction), 0) + valid[c]
    work = _work(pending, n_sample=len(sample.symbols),
                 sample_calls=sum(max(0, len(b) - (MIN_SIGNAL_BARS - 1)) for b in sample_bars.values()),
                 n_trade=len(trade),
                 trade_calls=sum(max(0, len(bars[s]) - (MIN_SIGNAL_BARS - 1)) for s in trade),
                 gate_bars_per_scoring=sum(len(bars[s]) for s in fire),
                 folds_by_horizon=folds_by_h, valid_by_cell=valid, unique_by_sd=by_sd)
    strategies = sorted({c.strategy for c in pending}) or ["ma_crossover"]
    sig_ms = sum(_time_signal_ms(probe_bars, s, "Bullish") for s in strategies) / len(strategies)
    proj = _report.project_runtime(
        signal_ms_per_call=sig_ms, gate_ms_per_bar=_time_gate_ms(probe_bars, "Bullish"),
        sim_ms_per_window=_time_sim_ms(probe_bars, strategies[0], "Bullish", "Swing"),
        workers=args.workers, **work)
    print(f"{len(cells)} cells ({len(cells) - len(pending)} finished, skipped by --resume); "
          f"sample {len(sample.symbols)}, trade universe {len(trade)}, fire-rate universe {len(fire)}")
    _print_projection(proj, args.workers)

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
    ap.add_argument("--bars-per-symbol", type=int, default=DEFAULT_BARS_PER_SYMBOL)
    args = ap.parse_args(argv)
    if args.probe:
        probe([s.strip().upper() for s in (args.symbols or "AAPL,MSFT,NVDA").split(",") if s.strip()],
              args.bars_dir or FIXTURES, args.workers, args.bars_per_symbol, select_cells(args.cells, args.directions))
        return 0
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
