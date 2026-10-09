#!/usr/bin/env python3
"""Strategy matrix (TRADING-REVIEW-PHASE-C T12, review M5, M6).

Strategy x direction x symbol over each symbol's full loaded history:
``run_strategy_backtest`` net of the configured cost model (``commission`` = fee +
slippage per leg, the WFO ``commission_for`` rule) with DAY entry limits (T6).

Per strategy and direction it pools the symbols: pooled trade count, pooled mean net
trade return (trade-weighted: each symbol's ``expectancy`` times its trade count), the
share of symbols reaching the backtest gate's ``_MIN_TRADES``, and a bootstrap 95% CI
on the pooled mean (2,000 resamples, seed 7, as T11).

The CI resamples symbols, not single trades: ``BacktestResult`` carries each symbol's
trade count and mean trade return but not its trade list, and trades of one symbol are
not independent of each other, so the symbol is the resampling unit. Each resample
draws the traded symbols with replacement and recomputes the trade-weighted mean.

Strategy parameters are the adopted ``active`` block for the direction over the
``exit`` block, the same merge the stock scan uses.

Read-only. Run from the repo root with the backend venv (Python 3.11):
    python scripts/evidence/strategy_matrix.py --symbols AAPL MSFT NVDA --out m5.md
"""
from __future__ import annotations

import asyncio
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO / "backend", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.services.strategy_backtest import _MIN_TRADES, run_strategy_backtest  # noqa: E402
from app.services.walk_forward import commission_for  # noqa: E402
from evidence._bars import (  # noqa: E402
    common_parser, emit, load_bars, loaded_range, report_header, evidence_symbols,
)
from evidence.gate_persistence import DAILY_STRATEGIES, DIRECTIONS, cost_model  # noqa: E402

BOOTSTRAP_RESAMPLES = 2_000
BOOTSTRAP_SEED = 7


@dataclass(frozen=True)
class MatrixRow:
    strategy: str
    direction: str
    n_symbols: int                        # symbols backtested
    n_traded: int                         # symbols with at least one trade
    n_trades: int                         # pooled trade count
    mean_trade_return_pct: float | None   # trade-weighted mean net trade return, %
    share_min_trades: float               # share of symbols with >= _MIN_TRADES trades
    ci_low: float | None                  # bootstrap 95% CI of the pooled mean
    ci_high: float | None


# ── Pure core ────────────────────────────────────────────────────────────────

def _weighted_mean(pairs: list[tuple[int, float]]) -> float | None:
    n = sum(k for k, _ in pairs)
    return (sum(k * e for k, e in pairs) / n) if n else None


def pooled_ci(
    pairs: list[tuple[int, float]], resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float | None, float | None]:
    """Percentile bootstrap 95% CI of the trade-weighted mean, resampling the
    (n_trades, expectancy) pairs of traded symbols with a fixed seed."""
    if not pairs:
        return None, None
    rng = random.Random(seed)
    means = sorted(_weighted_mean(rng.choices(pairs, k=len(pairs))) for _ in range(resamples))
    return means[round(0.025 * (resamples - 1))], means[round(0.975 * (resamples - 1))]


def pool(
    results: Mapping[str, object] | Iterable[object], *, strategy: str = "",
    direction: str = "", min_trades: int = _MIN_TRADES,
) -> MatrixRow:
    """Pool per-symbol backtest results (by symbol, or a plain iterable) into one row.
    The pooled mean weights each symbol's ``expectancy`` by its ``n_trades``."""
    items = list(results.values()) if isinstance(results, Mapping) else list(results)
    pairs = [(int(r.n_trades), float(r.expectancy)) for r in items if r.n_trades > 0]
    lo, hi = pooled_ci(pairs)
    return MatrixRow(
        strategy=strategy, direction=direction, n_symbols=len(items), n_traded=len(pairs),
        n_trades=sum(k for k, _ in pairs), mean_trade_return_pct=_weighted_mean(pairs),
        share_min_trades=(sum(r.n_trades >= min_trades for r in items) / len(items))
        if items else 0.0,
        ci_low=lo, ci_high=hi,
    )


def run_cell(
    bars_by_symbol: Mapping[str, list[dict]], strategy: str, direction: str, costs: dict,
    *, params: dict | None = None,
) -> dict[str, object]:
    """Backtest every symbol's full history net of ``costs``, keyed by symbol; a symbol
    whose backtest raises is left out."""
    commission = commission_for(costs)
    out: dict[str, object] = {}
    for symbol in sorted(bars_by_symbol):
        try:
            out[symbol] = run_strategy_backtest(
                bars_by_symbol[symbol], strategy=strategy, direction=direction,
                params=params, commission=commission,
            )
        except Exception as exc:  # one bad symbol must not sink the whole report
            print(f"warning: {symbol} {strategy} {direction}: {exc}", file=sys.stderr)
    return out


# ── Report ───────────────────────────────────────────────────────────────────

def _fmt(x: float | None) -> str:
    return "-" if x is None else f"{x:+.3f}"


def table_row(row: MatrixRow) -> str:
    ci = "-" if row.ci_low is None else f"[{_fmt(row.ci_low)}, {_fmt(row.ci_high)}]"
    return (f"| {row.strategy} | {row.direction} | {row.n_symbols} | {row.n_traded} "
            f"| {row.n_trades} | {_fmt(row.mean_trade_return_pct)} | {ci} "
            f"| {row.share_min_trades:.1%} |")


async def _main(args) -> str:
    from app.services.strategy_param_store import get_active, get_costs

    costs = get_costs()
    symbols, excluded = await evidence_symbols(
        args.symbols, include_excluded=args.include_excluded)
    bars = await load_bars(symbols, args.start, args.end)
    header = report_header(
        "Strategy matrix (M5, M6)", symbols=symbols, start=args.start, end=args.end,
        cost_model=cost_model(costs), loaded=loaded_range(bars), excluded=excluded,
        extra={
            "History": "each symbol's full loaded history, no warm-up exclusion beyond the "
                       "backtest's own 60 bars",
            "Min trades (gate)": f"{_MIN_TRADES} (strategy_backtest._MIN_TRADES)",
            "Bootstrap": f"{BOOTSTRAP_RESAMPLES} resamples over symbols, seed {BOOTSTRAP_SEED}",
            "Params": "adopted `active` block per direction over the `exit` block",
        },
    )
    lines = [header, "## Pooled net trade return per strategy and direction", "",
             "| Strategy | Direction | Symbols | Traded | Trades | Mean trade return % "
             "| 95% CI | Symbols >= min trades |",
             "|---|---|---:|---:|---:|---:|---|---:|"]
    for strategy in args.strategies:
        for direction in args.directions:
            results = run_cell(bars, strategy, direction, costs,
                               params=get_active(strategy, direction))
            lines.append(table_row(pool(results, strategy=strategy, direction=direction)))
    lines += ["", "Mean trade return is net of costs and trade-weighted across symbols "
                  "(each symbol's expectancy times its trade count)."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = common_parser(__doc__.splitlines()[0])
    parser.add_argument("--strategies", nargs="+", default=list(DAILY_STRATEGIES),
                        choices=list(DAILY_STRATEGIES), help="strategies (default all daily)")
    parser.add_argument("--directions", nargs="+", default=list(DIRECTIONS),
                        choices=list(DIRECTIONS), help="directions (default both)")
    args = parser.parse_args(argv)
    emit(asyncio.run(_main(args)), args.out)


if __name__ == "__main__":
    main()
