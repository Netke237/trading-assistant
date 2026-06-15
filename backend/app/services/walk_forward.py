"""Walk-forward optimization fold construction and utilities."""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import date

from dateutil.relativedelta import relativedelta

from app.services.strategy_backtest import run_strategy_backtest


@dataclass
class Fold:
    """A single train/test fold for walk-forward optimization.

    Attributes:
        train_start: Beginning of training period (inclusive).
        train_end: End of training period (exclusive; test_start = train_end).
        test_start: Beginning of test period (inclusive).
        test_end: End of test period (exclusive).
    """

    train_start: date
    train_end: date
    test_start: date
    test_end: date


def build_folds(
    start: date,
    end: date,
    *,
    train_months: int,
    test_months: int,
    anchored: bool = False,
) -> list[Fold]:
    """Build rolling or anchored walk-forward optimization folds.

    Folds partition a date range into training and test windows.

    Args:
        start: First date in the date range.
        end: Last date in the date range.
        train_months: Length of training window in months.
        test_months: Length of test window in months (also the step size for rolling).
        anchored: If False (rolling), train_start slides forward by test_months each fold.
                  If True (anchored), train_start remains fixed at start.

    Returns:
        List of Fold objects. Empty if the range is too short to fit even one fold.

    Examples:
        Rolling (test_months = 3, train_months = 12):
        - Fold 0: train [2018-01-01, 2019-01-01), test [2019-01-01, 2019-04-01)
        - Fold 1: train [2019-04-01, 2020-04-01), test [2020-04-01, 2020-07-01)
        - ...

        Anchored (train_months = 12, test_months = 3):
        - Fold 0: train [2018-01-01, 2019-01-01), test [2019-01-01, 2019-04-01)
        - Fold 1: train [2018-01-01, 2019-04-01), test [2019-04-01, 2019-07-01)
        - ...
    """
    folds: list[Fold] = []

    train_start = start
    train_end = start + relativedelta(months=train_months)

    while train_end + relativedelta(months=test_months) <= end:
        test_start = train_end
        test_end = test_start + relativedelta(months=test_months)

        folds.append(Fold(train_start, train_end, test_start, test_end))

        if not anchored:
            # Rolling: slide both windows forward by test_months
            train_start = train_start + relativedelta(months=test_months)

        # Grow the training window or slide the test window
        train_end = train_end + relativedelta(months=test_months)

    return folds


def param_combos(search_space: dict) -> list[dict]:
    """Generate all parameter combinations from a search space.

    Args:
        search_space: Dict mapping parameter names to lists of values.

    Returns:
        List of dicts, one for each combination of parameter values (Cartesian product).
    """
    keys = list(search_space.keys())
    return [dict(zip(keys, vals)) for vals in itertools.product(*(search_space[k] for k in keys))]


def apply_costs(*, gross_return_pct: float, fee_pct: float, slippage_pct: float) -> float:
    """Subtract round-trip cost (entry + exit legs) as a percentage drag.

    Args:
        gross_return_pct: Gross return percentage.
        fee_pct: Fee per leg (as decimal, e.g., 0.001 = 0.1%).
        slippage_pct: Slippage per leg (as decimal, e.g., 0.001 = 0.1%).

    Returns:
        Net return percentage after subtracting round-trip costs.
    """
    drag_pct = (fee_pct + slippage_pct) * 2 * 100.0
    return gross_return_pct - drag_pct


def _slice_bars(bars: list[dict], start: date, end: date) -> list[dict]:
    """Slice a list of bars to a date range (inclusive start, exclusive end)."""
    return [b for b in bars if start <= date.fromisoformat(str(b["time"])[:10]) < end]


def train_fold(strategy: str, direction: str, basket_bars: dict[str, list[dict]],
               fold: Fold, search_space: dict, costs: dict) -> dict:
    """Grid search on the train window, pooled across the basket. Return winning params.

    Args:
        strategy: Strategy name.
        direction: Directional bias ('bullish', 'bearish', etc.).
        basket_bars: Dict mapping symbol to list of OHLCV bars.
        fold: Fold object with train/test date ranges.
        search_space: Dict mapping parameter names to lists of values.
        costs: Dict with 'fee_pct' and 'slippage_pct' keys.

    Returns:
        Dict of winning parameters, or empty dict if no combo passes.
    """
    best, best_sharpe = None, float("-inf")
    for combo in param_combos(search_space):
        sharpes = []
        for sym, bars in basket_bars.items():
            train_bars = _slice_bars(bars, fold.train_start, fold.train_end)
            if len(train_bars) < 100:
                continue
            res = run_strategy_backtest(train_bars, strategy=strategy, direction=direction)
            if res.n_trades > 0:
                sharpes.append(res.sharpe)
        pooled = sum(sharpes) / len(sharpes) if sharpes else float("-inf")
        if pooled > best_sharpe:
            best_sharpe, best = pooled, combo
    return best or {}
