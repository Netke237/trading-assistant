"""Strategy parameter optimizer orchestrator — runs walk-forward optimization and builds proposals."""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Callable

from app.services.walk_forward import (
    apply_costs, consensus, consistency, degradation_pct,
    build_folds, train_fold, _slice_bars,
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
    min_consistency: float = 0.5,
) -> dict:
    """Build a proposal record from optimization results.

    Args:
        strategy: Strategy name.
        fold_winners: List of winning parameter dicts, one per fold (empty dicts filtered out).
        fold_test_returns: List of test period returns (as percentages).
        in_sample_return: Training (in-sample) return percentage.
        walk_forward_return: Test (out-of-sample) return percentage.
        oos_metrics: Dict with 'sharpe', 'expectancy', 'win_rate', 'total_return',
                     'max_drawdown', 'n_trades' keys.
        min_trades: Minimum trade count required for eligibility.
        min_consistency: Minimum fraction of folds with positive OOS returns (0–1).

    Returns:
        Dict with keys: strategy, proposed, consistency, eligible, oos_metrics,
        fold_winners, verdict, recommendation.
    """
    proposed = consensus(fold_winners)
    cons = round(consistency(fold_test_returns), 4)
    eligible = oos_metrics["n_trades"] >= min_trades and cons >= min_consistency
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


def _optimize_strategy_sync(
    strategy: str,
    direction: str,
    basket_bars: dict[str, list[dict]],
    folds: list,
    search_space: dict,
    costs: dict,
    min_trades: int,
    min_consistency: float,
) -> dict | None:
    """Synchronous per-strategy fold loop; run via asyncio.to_thread to avoid blocking.

    Returns a proposal dict, or None if all folds produced empty winners (no usable data).
    """
    from app.services.strategy_backtest import run_strategy_backtest

    fold_winners: list[dict] = []
    fold_test_returns: list[float] = []
    in_sample_fold_returns: list[float] = []
    total_n_trades = 0
    contributing_symbols: set[str] = set()
    all_sharpes: list[float] = []
    all_win_rates: list[float] = []
    all_expectancies: list[float] = []
    all_drawdowns: list[float] = []

    for fold in folds:
        winner = train_fold(strategy, direction, basket_bars, fold, search_space, costs)
        fold_winners.append(winner)

        # IS: re-run the train window with winner params using return% to match OOS units
        is_returns: list[float] = []
        for sym, bars in basket_bars.items():
            train_bars_fold = _slice_bars(bars, fold.train_start, fold.train_end)
            if len(train_bars_fold) >= 100:
                try:
                    res = run_strategy_backtest(
                        train_bars_fold, strategy=strategy, direction=direction, params=winner
                    )
                    if res.n_trades > 0:
                        net = apply_costs(
                            gross_return_pct=res.total_return_pct,
                            fee_pct=costs.get("fee_pct", 0.001),
                            slippage_pct=costs.get("slippage_pct", 0.001),
                        )
                        is_returns.append(net)
                except Exception as exc:
                    logger.debug("IS backtest failed for %s: %s", sym, exc)
        in_sample_fold_returns.append(
            sum(is_returns) / len(is_returns) if is_returns else 0.0
        )

        # OOS: score the test window with winner params, net of costs
        test_returns: list[float] = []
        for sym, bars in basket_bars.items():
            test_bars = _slice_bars(bars, fold.test_start, fold.test_end)
            if len(test_bars) >= 100:  # matches IS guard and backtest engine's internal minimum
                try:
                    res = run_strategy_backtest(
                        test_bars, strategy=strategy, direction=direction, params=winner
                    )
                    # Only include windows where the strategy actually traded.
                    # Applying cost drag to a zero-trade window injects a false
                    # negative return (~−0.4%), unfairly suppressing consistency.
                    if res.n_trades > 0:
                        gross = res.total_return_pct if hasattr(res, "total_return_pct") else 0.0
                        net = apply_costs(
                            gross_return_pct=gross,
                            fee_pct=costs.get("fee_pct", 0.001),
                            slippage_pct=costs.get("slippage_pct", 0.001),
                        )
                        test_returns.append(net)
                        total_n_trades += res.n_trades
                        contributing_symbols.add(sym)
                        all_sharpes.append(getattr(res, "sharpe", 0.0))
                        all_win_rates.append(res.win_rate)
                        if getattr(res, "expectancy", None) is not None:
                            all_expectancies.append(res.expectancy)
                        if getattr(res, "max_drawdown_pct", None) is not None:
                            all_drawdowns.append(res.max_drawdown_pct)
                except Exception as exc:
                    logger.debug("OOS backtest failed for %s: %s", sym, exc)
        fold_test_returns.append(
            sum(test_returns) / len(test_returns) if test_returns else 0.0
        )

    # Filter all three parallel lists together so bad folds (empty winner) are
    # excluded from IS return, OOS return, and consistency alike.
    valid_triples = [
        (w, r, isr)
        for w, r, isr in zip(fold_winners, fold_test_returns, in_sample_fold_returns)
        if w
    ]
    valid_winners           = [t[0] for t in valid_triples]
    valid_fold_test_returns = [t[1] for t in valid_triples]
    valid_is_fold_returns   = [t[2] for t in valid_triples]
    if not valid_winners:
        logger.warning("No valid fold winners for %s — all folds empty, skipping", strategy)
        return None

    # apply_costs returns net_return in the same percent units as total_return_pct.
    # No ×100 here — the values are already percent (e.g., 5.0 = 5%).
    in_sample_return = (
        sum(valid_is_fold_returns) / len(valid_is_fold_returns)
        if valid_is_fold_returns
        else 0.0
    )
    walk_forward_return = (
        sum(valid_fold_test_returns) / len(valid_fold_test_returns)
        if valid_fold_test_returns
        else 0.0
    )
    avg_sharpe = sum(all_sharpes) / len(all_sharpes) if all_sharpes else 0.0

    oos_metrics = {
        "sharpe": round(avg_sharpe, 4),
        "expectancy": round(sum(all_expectancies) / len(all_expectancies), 4) if all_expectancies else 0.0,
        "win_rate": round(sum(all_win_rates) / len(all_win_rates), 4) if all_win_rates else 0.0,
        "total_return": walk_forward_return,
        "max_drawdown": round(min(all_drawdowns), 4) if all_drawdowns else 0.0,
        # Divide by symbols that actually contributed (not total basket) so min_trades
        # threshold is not diluted by symbols skipped by the 100-bar OOS guard.
        "n_trades": round(total_n_trades / max(len(contributing_symbols), 1)),
    }

    return build_proposal(
        strategy=strategy,
        fold_winners=valid_winners,
        fold_test_returns=valid_fold_test_returns,
        in_sample_return=in_sample_return,
        walk_forward_return=walk_forward_return,
        oos_metrics=oos_metrics,
        min_trades=min_trades,
        min_consistency=min_consistency,
    )


async def run_optimization(
    strategies: list[str],
    basket_symbols: list[str],
    windows: dict,
    costs: dict,
    progress_cb: Callable[[int, int], None],
    *,
    direction: str = "bullish",
    min_trades: int = 20,
    min_consistency: float = 0.5,
) -> dict:
    """Run walk-forward optimization for all strategies. Returns strategy → proposal dict.

    Args:
        strategies: List of strategy names to optimize.
        basket_symbols: List of symbols to use as the optimization basket.
        windows: Dict with 'train_months', 'test_months', 'type' (rolling|anchored).
        costs: Dict with 'fee_pct' and 'slippage_pct' keys.
        progress_cb: Callable(done, total) for progress reporting.
        direction: Trading direction ('bullish' or 'bearish').
        min_trades: Minimum OOS trades for a proposal to be eligible.
        min_consistency: Minimum fraction of positive OOS folds for eligibility.

    Returns:
        Dict mapping strategy name to proposal dict.
        Strategies with no bars or all-empty folds are omitted.
    """
    from app.services.strategy_param_store import get_search_space
    from app.services.historical_store import get_bars
    from app.services.walk_forward import precompute_bar_dates
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

        basket_bars: dict[str, list[dict]] = {}
        for sym in basket_symbols:
            try:
                end_date = date.today()
                start_date = end_date - relativedelta(years=3)
                bars = await get_bars(sym, start_date, end_date)
                if bars:
                    basket_bars[sym] = bars
            except Exception as exc:
                logger.debug("Failed to load bars for %s: %s", sym, exc)

        if not basket_bars:
            logger.warning("No bars available for strategy %s basket, skipping", strategy)
            done += 1
            progress_cb(done, total_work)
            continue

        # Pre-compute _date fields first — used for the intersection range below
        # and for the fold/combo loop inside _optimize_strategy_sync.
        for bars in basket_bars.values():
            precompute_bar_dates(bars)

        # Intersection of per-symbol date ranges via pre-computed _date (date objects)
        # so the comparison is type-safe regardless of what format get_bars returns.
        symbol_starts = [min(b["_date"] for b in bars) for bars in basket_bars.values()]
        symbol_ends = [max(b["_date"] for b in bars) for bars in basket_bars.values()]
        if not symbol_starts:
            done += 1
            progress_cb(done, total_work)
            continue

        start = max(symbol_starts)  # latest start — intersection
        end = min(symbol_ends)      # earliest end — intersection

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

        proposal = await asyncio.to_thread(
            _optimize_strategy_sync,
            strategy, direction, basket_bars, folds, search_space, costs,
            min_trades, min_consistency,
        )
        if proposal is not None:
            results[strategy] = proposal

        done += 1
        progress_cb(done, total_work)

    return results
