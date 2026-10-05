#!/usr/bin/env python3
"""Gate persistence (TRADING-REVIEW-PHASE-C T12, review H3).

Does a symbol's backtest edge persist? Per strategy and direction, each symbol's stored
history is split at its midpoint (by bar count). ``run_strategy_backtest`` runs on each
half net of the configured cost model (``commission`` = fee + slippage per leg, the
WFO ``commission_for`` rule) with DAY entry limits (T6). Each half places entries only
from its own first bar (``entry_start``); the second half is preceded by WFO's
260-bar warm-up prefix (``slice_with_warmup``), which primes indicators and never trades.

Across the symbols with at least ``--min-trades`` (default 5) trades in BOTH halves, it
reports Spearman's rho between the halves' per-symbol expectancy (mean net trade return,
%), with the noise band +/-1.96/sqrt(n-1). A rho inside the band is indistinguishable
from no persistence: the gate would be picking symbols by luck.

Strategy parameters are the adopted ``active`` block for the direction over the
``exit`` block, the same merge the stock scan uses.

Read-only. Run from the repo root with the backend venv (Python 3.11):
    python scripts/evidence/gate_persistence.py --symbols AAPL MSFT NVDA --out h3.md
"""
from __future__ import annotations

import asyncio
import math
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Mapping, Sequence

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO / "backend", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.services.strategy_backtest import run_strategy_backtest  # noqa: E402
from app.services.walk_forward import WARMUP_BARS, commission_for, slice_with_warmup  # noqa: E402
from evidence._bars import (  # noqa: E402
    common_parser, emit, load_bars, loaded_range, report_header, stored_symbols,
)

# The strategies run_strategy_backtest can replay on daily bars. mean_reversion_vwap
# needs 15-minute bars, which ohlcv_daily does not hold.
DAILY_STRATEGIES = (
    "pullback_ema", "breakout_base", "ma_crossover", "mean_reversion_rsi", "mean_reversion_bb",
)
DIRECTIONS = ("Bullish", "Bearish")
MIN_TRADES_PER_HALF = 5
Z_95 = 1.96


@dataclass(frozen=True)
class PersistenceStat:
    n: int                   # symbols with >= min_trades in both halves
    rho: float | None        # Spearman rho of per-symbol expectancy, half A vs half B
    band: float | None       # noise band half-width, 1.96 / sqrt(n - 1)
    symbols: list[str]       # the symbols counted, sorted

    @property
    def outside_band(self) -> bool:
        return self.rho is not None and self.band is not None and abs(self.rho) > self.band


# ── Pure core ────────────────────────────────────────────────────────────────

def _ranks(values: Sequence[float]) -> list[float]:
    """1-based ranks; tied values share the average of the ranks they span."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Spearman's rho: the Pearson correlation of average ranks. None when it is
    undefined (fewer than 2 pairs, or every value on one side tied)."""
    if len(xs) != len(ys):
        raise ValueError("spearman needs two sequences of equal length")
    n = len(xs)
    if n < 2:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        return None
    return cov / math.sqrt(vx * vy)


def persistence(
    results_a: Mapping[str, object], results_b: Mapping[str, object], min_trades: int,
) -> PersistenceStat:
    """Spearman rho of per-symbol ``expectancy`` between two halves, over the symbols
    present in both with at least ``min_trades`` trades in each half."""
    symbols = sorted(
        s for s in set(results_a) & set(results_b)
        if results_a[s].n_trades >= min_trades and results_b[s].n_trades >= min_trades
    )
    n = len(symbols)
    rho = spearman([results_a[s].expectancy for s in symbols],
                   [results_b[s].expectancy for s in symbols])
    band = Z_95 / math.sqrt(n - 1) if n >= 2 else None
    return PersistenceStat(n=n, rho=rho, band=band, symbols=symbols)


def _bar_date(bar: dict) -> date:
    return date.fromisoformat(str(bar["time"])[:10])


def split_halves(
    bars: list[dict], warmup: int = WARMUP_BARS,
) -> tuple[tuple[list[dict], date], tuple[list[dict], date]] | None:
    """The two halves at the midpoint bar, each as (window, entry_start). The second
    window carries a ``warmup``-bar prefix from the first half (as WFO slices folds).
    None when there are fewer than 2 bars."""
    if len(bars) < 2:
        return None
    mid = len(bars) // 2
    start_a, start_b = _bar_date(bars[0]), _bar_date(bars[mid])
    end_b = _bar_date(bars[-1]) + timedelta(days=1)     # slice_with_warmup's end is exclusive
    window_a, _ = slice_with_warmup(bars, start_a, start_b, warmup)
    window_b, _ = slice_with_warmup(bars, start_b, end_b, warmup)
    return (window_a, start_a), (window_b, start_b)


def run_halves(
    bars_by_symbol: Mapping[str, list[dict]], strategy: str, direction: str, costs: dict,
    *, params: dict | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Backtest every symbol's two halves net of ``costs``. Returns (half A, half B)
    results keyed by symbol; a symbol whose backtest raises is left out of both."""
    commission = commission_for(costs)
    results_a: dict[str, object] = {}
    results_b: dict[str, object] = {}
    for symbol in sorted(bars_by_symbol):
        halves = split_halves(bars_by_symbol[symbol])
        if halves is None:
            continue
        try:
            (window_a, start_a), (window_b, start_b) = halves
            res_a = run_strategy_backtest(window_a, strategy=strategy, direction=direction,
                                          params=params, commission=commission,
                                          entry_start=start_a)
            res_b = run_strategy_backtest(window_b, strategy=strategy, direction=direction,
                                          params=params, commission=commission,
                                          entry_start=start_b)
        except Exception as exc:  # one bad symbol must not sink the whole report
            print(f"warning: {symbol} {strategy} {direction}: {exc}", file=sys.stderr)
            continue
        results_a[symbol], results_b[symbol] = res_a, res_b
    return results_a, results_b


# ── Report ───────────────────────────────────────────────────────────────────

def cost_model(costs: dict) -> str:
    return (f"net: per-leg commission {commission_for(costs):.4%} "
            f"(fee_pct {costs.get('fee_pct', 0.001)} + slippage_pct "
            f"{costs.get('slippage_pct', 0.001)}, strategy_params.yaml `costs`, as WFO), "
            f"charged on entry and exit; DAY entry limits")


def _fmt(x: float | None) -> str:
    return "-" if x is None else f"{x:+.3f}"


def table_row(strategy: str, direction: str, n_run: int, stat: PersistenceStat) -> str:
    verdict = ("-" if stat.rho is None
               else "outside band" if stat.outside_band else "within noise")
    band = "-" if stat.band is None else f"+/-{stat.band:.3f}"
    return (f"| {strategy} | {direction} | {n_run} | {stat.n} | {_fmt(stat.rho)} "
            f"| {band} | {verdict} |")


async def _main(args) -> str:
    from app.services.strategy_param_store import get_active, get_costs

    costs = get_costs()
    symbols = args.symbols or await stored_symbols()
    bars = await load_bars(symbols, args.start, args.end)
    header = report_header(
        "Gate persistence (H3)", symbols=symbols, start=args.start, end=args.end,
        cost_model=cost_model(costs), loaded=loaded_range(bars),
        extra={
            "Split": "each symbol's loaded bars at their midpoint (by bar count)",
            "Warm-up": f"{WARMUP_BARS} bars before the second half (WFO slice_with_warmup)",
            "Min trades per half": str(args.min_trades),
            "Params": "adopted `active` block per direction over the `exit` block",
        },
    )
    lines = [header, "## Spearman rho of per-symbol expectancy, first half vs second half", "",
             "| Strategy | Direction | Symbols run | n (both halves) | rho | Noise band | Verdict |",
             "|---|---|---:|---:|---:|---|---|"]
    for strategy in args.strategies:
        for direction in args.directions:
            res_a, res_b = run_halves(bars, strategy, direction, costs,
                                      params=get_active(strategy, direction))
            stat = persistence(res_a, res_b, args.min_trades)
            lines.append(table_row(strategy, direction, len(res_a), stat))
    lines += ["", f"Noise band: +/-{Z_95}/sqrt(n-1). A rho inside it cannot be told apart "
                  "from zero persistence."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = common_parser(__doc__.splitlines()[0])
    parser.add_argument("--strategies", nargs="+", default=list(DAILY_STRATEGIES),
                        choices=list(DAILY_STRATEGIES), help="strategies (default all daily)")
    parser.add_argument("--directions", nargs="+", default=list(DIRECTIONS),
                        choices=list(DIRECTIONS), help="directions (default both)")
    parser.add_argument("--min-trades", type=int, default=MIN_TRADES_PER_HALF,
                        help=f"trades needed in each half (default {MIN_TRADES_PER_HALF})")
    args = parser.parse_args(argv)
    emit(asyncio.run(_main(args)), args.out)


if __name__ == "__main__":
    main()
