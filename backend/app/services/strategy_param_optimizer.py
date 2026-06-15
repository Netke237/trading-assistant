"""Strategy parameter optimizer orchestrator — runs walk-forward optimization and builds proposals."""
from __future__ import annotations

import logging
from datetime import date
from typing import Callable

from app.services.walk_forward import (
    consensus, consistency, degradation_pct, build_folds, train_fold, _slice_bars
)

logger = logging.getLogger(__name__)


def build_proposal(
    *,
    strategy: str,
    fold_winners: list[dict],
    fold_test_returns: list[float],
    in_sample_return: float,
    walk_forward_return: float,
    oos_metrics: dict,
    min_trades: int,
) -> dict:
    """Build a proposal record from optimization results.

    Args:
        strategy: Strategy name.
        fold_winners: List of winning parameter dicts, one per fold.
        fold_test_returns: List of test period returns (as decimals).
        in_sample_return: Training (in-sample) return percentage.
        walk_forward_return: Test (out-of-sample) return percentage.
        oos_metrics: Dict with 'sharpe', 'expectancy', 'win_rate', 'total_return',
                     'max_drawdown', 'n_trades' keys.
        min_trades: Minimum trade count required for eligibility.

    Returns:
        Dict with keys: strategy, proposed, consistency, eligible, oos_metrics,
        fold_winners, verdict, recommendation.
    """
    proposed = consensus(fold_winners)
    cons = round(consistency(fold_test_returns), 4)
    eligible = oos_metrics["n_trades"] >= min_trades and cons >= 0.5
    deg = degradation_pct(in_sample=in_sample_return, walk_forward=walk_forward_return)

    if not eligible:
        recommendation = "Edge looks fake — consider dropping."
    elif oos_metrics["sharpe"] > 0.5 and deg < 0.5:
        recommendation = "Proposed beats current — safe to adopt."
    else:
        recommendation = "Marginal — your call."

    return {
        "strategy": strategy,
        "proposed": proposed,
        "consistency": cons,
        "eligible": eligible,
        "oos_metrics": oos_metrics,
        "fold_winners": fold_winners,
        "verdict": {
            "in_sample_return": in_sample_return,
            "walk_forward_return": walk_forward_return,
            "degradation_pct": round(deg, 4),
        },
        "recommendation": recommendation,
    }


async def run_optimization(
    strategies: list[str],
    basket_symbols: list[str],
    windows: dict,
    costs: dict,
    progress_cb: Callable[[int, int], None],
) -> dict:
    """Run walk-forward optimization for all strategies. Returns strategy → proposal dict.

    Args:
        strategies: List of strategy names to optimize.
        basket_symbols: List of symbols to use as the optimization basket.
        windows: Dict with 'train_months', 'test_months', 'type' (rolling|anchored).
        costs: Dict with 'fee_pct' and 'slippage_pct' keys.
        progress_cb: Callable(done, total) for progress reporting.

    Returns:
        Dict mapping strategy name to proposal dict.
        If no bars are available for a strategy, it is skipped.
    """
    from app.services.strategy_param_store import get_search_space
    from app.services.historical_store import get_bars
    from app.services.strategy_backtest import run_strategy_backtest
    from dateutil.relativedelta import relativedelta

    results: dict = {}
    total_work = len(strategies)
    done = 0

    for strategy in strategies:
        search_space = get_search_space(strategy)
        if not search_space:
            logger.warning("No search space for %s, skipping", strategy)
            done += 1
            progress_cb(done, total_work)
            continue

        # Load bars for basket symbols
        basket_bars: dict[str, list[dict]] = {}
        for sym in basket_symbols:
            try:
                # Default to last 3 years if we can determine dates
                end_date = date.today()
                start_date = end_date - relativedelta(years=3)
                bars = await get_bars(sym, start_date, end_date)
                if bars:
                    basket_bars[sym] = bars
            except Exception as exc:
                logger.debug("Failed to load bars for %s: %s", sym, exc)
                pass  # symbol not available in DB

        if not basket_bars:
            logger.warning("No bars available for strategy %s basket, skipping", strategy)
            done += 1
            progress_cb(done, total_work)
            continue

        # Determine date range from available data
        all_dates = [b["time"] for bars in basket_bars.values() for b in bars]
        if not all_dates:
            done += 1
            progress_cb(done, total_work)
            continue

        start_str = min(all_dates)
        end_str = max(all_dates)
        start = date.fromisoformat(str(start_str)[:10])
        end = date.fromisoformat(str(end_str)[:10])

        folds = build_folds(
            start, end,
            train_months=windows.get("train_months", 12),
            test_months=windows.get("test_months", 3),
            anchored=windows.get("type") == "anchored",
        )

        if not folds:
            done += 1
            progress_cb(done, total_work)
            continue

        fold_winners = []
        fold_test_returns = []
        in_sample_sharpes = []
        total_n_trades = 0
        all_sharpes: list[float] = []

        for fold in folds:
            winner = train_fold(strategy, "bullish", basket_bars, fold, search_space, costs)
            fold_winners.append(winner)
            # Score test window with winning params
            test_returns = []
            for sym, bars in basket_bars.items():
                test_bars = _slice_bars(bars, fold.test_start, fold.test_end)
                if len(test_bars) >= 20:
                    try:
                        res = run_strategy_backtest(test_bars, strategy=strategy, direction="bullish")
                        test_returns.append(
                            res.total_return_pct if hasattr(res, "total_return_pct") else 0.0
                        )
                        in_sample_sharpes.append(res.sharpe if hasattr(res, "sharpe") else 0.0)
                        total_n_trades += getattr(res, "n_trades", 0)
                        all_sharpes.append(getattr(res, "sharpe", 0.0))
                    except Exception as exc:
                        logger.debug("Backtest failed for %s: %s", sym, exc)
            fold_test_returns.append(
                sum(test_returns) / len(test_returns) if test_returns else 0.0
            )

        in_sample_return = (
            sum(in_sample_sharpes) / len(in_sample_sharpes) * 100
            if in_sample_sharpes
            else 0.0
        )
        walk_forward_return = (
            sum(fold_test_returns) / len(fold_test_returns) * 100
            if fold_test_returns
            else 0.0
        )
        avg_sharpe = sum(all_sharpes) / len(all_sharpes) if all_sharpes else 0.0

        oos_metrics = {
            "sharpe": round(avg_sharpe, 4),
            "expectancy": 0.0,
            "win_rate": 0.0,
            "total_return": walk_forward_return,
            "max_drawdown": 0.0,
            "n_trades": total_n_trades,
        }

        proposal = build_proposal(
            strategy=strategy,
            fold_winners=fold_winners,
            fold_test_returns=fold_test_returns,
            in_sample_return=in_sample_return,
            walk_forward_return=walk_forward_return,
            oos_metrics=oos_metrics,
            min_trades=20,
        )
        results[strategy] = proposal
        done += 1
        progress_cb(done, total_work)

    return results
