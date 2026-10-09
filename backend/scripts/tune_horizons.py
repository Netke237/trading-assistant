"""Per-horizon strategy tuner CLI (STOCKS-HORIZON-T1).

H8 ships only ``--probe``: it times each tuned strategy's signal function on
three symbols' bars and projects the signal-computation time of a full tuning
run for the configured basket (``tuning.basket.per_sector`` x 11 sectors) and
grids (``search_by_horizon``) at ``--workers N``. Signals do not depend on the
horizon, so a combination that appears in several horizons' grids is counted
once per strategy x direction. The other flags land in H10.

The probe reads JSON bar files (default: the test fixtures); it never touches
the database.

Run from repo root:
    python backend/scripts/tune_horizons.py --probe [--workers 8]
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import time
from pathlib import Path

# Allow running from repo root: python backend/scripts/tune_horizons.py
sys.path.insert(0, str(Path(__file__).parent.parent))
from app.services.horizon_profiles import TUNED_HORIZONS  # noqa: E402
from app.services.horizon_tuning.signals import MIN_SIGNAL_BARS, signal_series  # noqa: E402
from app.services.strategy_engine import SIGNAL_WINDOW_BARS, merge_multi_params  # noqa: E402
from app.services.strategy_param_store import (  # noqa: E402
    get_active, get_profile, get_search_by_horizon, get_tuning_config,
)

TUNED_STRATEGIES = ("pullback_ema", "breakout_base", "ma_crossover",
                    "mean_reversion_rsi", "mean_reversion_bb", "mean_reversion_multi")
DIRECTIONS = ("Bullish", "Bearish")
N_SECTORS = 11
# ~2009-10 .. 2026-10 at 252 trading days a year (STOCKS-HORIZON-HISTORY's span).
DEFAULT_BARS_PER_SYMBOL = 4280
FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"


def _baseline_params(strategy: str, direction: str) -> dict:
    if strategy == "mean_reversion_multi":
        return merge_multi_params(direction, get_profile(strategy, direction, None)[0], None)
    return get_active(strategy, direction)


def _unique_combos(strategy: str, direction: str) -> int:
    seen: set[tuple] = set()
    for h in TUNED_HORIZONS:
        grid = get_search_by_horizon(strategy, direction, h)
        keys = sorted(grid)
        for values in itertools.product(*(grid[k] for k in keys)):
            seen.add(tuple(zip(keys, map(repr, values))))
    return len(seen)


def probe(symbols: list[str], bars_dir: Path, workers: int, bars_per_symbol: int) -> None:
    cfg = get_tuning_config()
    basket_n = cfg["basket"]["per_sector"] * N_SECTORS
    series = {s: json.loads((bars_dir / f"{s}_candles.json").read_text(encoding="utf-8")) for s in symbols}
    calls_per_symbol = max(0, bars_per_symbol - (MIN_SIGNAL_BARS - 1))
    windows = [min(len(b), SIGNAL_WINDOW_BARS) for b in series.values()]
    print(f"probe: {', '.join(f'{s} ({len(b)} bars)' for s, b in series.items())} from {bars_dir}")
    print(f"basket {basket_n} symbols ({cfg['basket']['per_sector']} x {N_SECTORS} sectors), "
          f"{bars_per_symbol} bars/symbol, workers {workers}")
    print(f"{'strategy':<22}{'direction':<10}{'ms/call':>9}{'combos':>8}{'projected h':>13}")
    total_s = 0.0
    for strategy in TUNED_STRATEGIES:
        for direction in DIRECTIONS:
            params = _baseline_params(strategy, direction)
            calls, t0 = 0, time.perf_counter()
            for bars in series.values():
                signal_series(bars, strategy, direction, params)
                calls += max(0, len(bars) - (MIN_SIGNAL_BARS - 1))
            ms = (time.perf_counter() - t0) * 1000.0 / max(calls, 1)
            combos = _unique_combos(strategy, direction)
            secs = combos * basket_n * calls_per_symbol * ms / 1000.0 / max(workers, 1)
            total_s += secs
            print(f"{strategy:<22}{direction:<10}{ms:>9.3f}{combos:>8}{secs / 3600:>13.2f}")
    print(f"projected signal time: {total_s / 3600:.2f} h at {workers} workers "
          f"(cached afterwards; simulation and gate masks not included)")
    if max(windows) < SIGNAL_WINDOW_BARS:
        print(f"note: these bars give windows of at most {max(windows)} bars; live and tuned signals "
              f"use {SIGNAL_WINDOW_BARS}, so per-call cost on stored history is higher "
              f"(about x{SIGNAL_WINDOW_BARS / max(windows):.1f} if linear in the window)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--probe", action="store_true", help="time the signal functions and project a full run")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--symbols", default="AAPL,MSFT,NVDA", help="three symbols with <SYMBOL>_candles.json bars")
    ap.add_argument("--bars-dir", type=Path, default=FIXTURES)
    ap.add_argument("--bars-per-symbol", type=int, default=DEFAULT_BARS_PER_SYMBOL)
    args = ap.parse_args(argv)
    if not args.probe:
        ap.error("only --probe exists so far (the tuning run lands in H10)")
    probe([s.strip().upper() for s in args.symbols.split(",") if s.strip()],
          args.bars_dir, args.workers, args.bars_per_symbol)
    return 0


if __name__ == "__main__":
    sys.exit(main())
