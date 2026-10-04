"""Walk-forward optimization fold construction and utilities."""
from __future__ import annotations

import itertools
import logging
import statistics
from dataclasses import dataclass
from datetime import date

from dateutil.relativedelta import relativedelta

from app.services.strategy_backtest import run_strategy_backtest

logger = logging.getLogger(__name__)

# Largest indicator look-back any strategy uses (trend_sma 200 + BB/RSI period
# headroom; mean_reversion_bb needs ~225) plus margin. Fix #2: test folds used
# to start with cold indicators AND were dropped below 100 bars.
WARMUP_BARS = 260
# Fewest bars inside [start, end) worth scoring. A 3-month fold is ~62 trading
# bars; 40 tolerates holidays and a short final fold.
MIN_SCORED_BARS = 40


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
        - Fold 1: train [2018-04-01, 2019-04-01), test [2019-04-01, 2019-07-01)
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


def commission_for(costs: dict) -> float:
    """Per-leg commission (fee + slippage, as a decimal) for `run_strategy_backtest`.

    TRADING-REVIEW-PHASE-C T4 (review M1): the backtest charges it on every entry
    and exit leg of every trade, so WFO selects and scores folds net of costs that
    scale with turnover (it used to subtract one flat round trip per window).
    """
    return costs.get("fee_pct", 0.001) + costs.get("slippage_pct", 0.001)


def precompute_bar_dates(bars: list[dict]) -> None:
    """Parse and cache each bar's 'time' field as '_date' for O(1) reuse in _slice_bars.

    Call once per symbol before the fold/combo loop to avoid repeated
    string→date conversions inside the triple-nested iteration.
    """
    for b in bars:
        if "_date" not in b:
            b["_date"] = date.fromisoformat(str(b["time"])[:10])


def _slice_bars(bars: list[dict], start: date, end: date) -> list[dict]:
    """Slice a list of bars to [start, end). Uses pre-computed '_date' key if present."""
    return [
        b for b in bars
        if start <= (b.get("_date") or date.fromisoformat(str(b["time"])[:10])) < end
    ]


def slice_with_warmup(
    bars: list[dict], start: date, end: date, warmup: int = WARMUP_BARS,
) -> tuple[list[dict], int]:
    """Warm-up prefix + [start, end). Bars must be ascending; `_date` is used when
    precomputed (see `precompute_bar_dates`), else parsed from `time` like `_slice_bars`.

    Returns (window, n_scored), where n_scored counts the bars inside [start, end).
    The prefix is shorter than `warmup` only when the data starts later.
    """
    def _d(b: dict) -> date:
        return b.get("_date") or date.fromisoformat(str(b["time"])[:10])

    first = next((i for i, b in enumerate(bars) if _d(b) >= start), len(bars))
    lo = max(0, first - warmup)
    window = [b for b in bars[lo:] if _d(b) < end]
    return window, len(window) - (first - lo)


def _complexity_penalty(combo: dict, search_space: dict, *, weight: float = 0.05) -> float:
    """Penalize a param combo for sitting at the edges of its search grid.

    Grid-search selection by raw in-sample Sharpe alone tends to pick extreme
    values that happened to fit this particular training window rather than a
    generalizable regime — the walk-forward eligibility gate (n_trades/
    consistency in strategy_param_optimizer.py) catches this after the fact,
    but doesn't stop the in-sample search itself from reaching for the edge.
    This adds a mild, in-sample regularization: combos near the center of each
    parameter's grid pay no penalty; combos at the edges pay up to `weight`
    Sharpe units per parameter. A genuinely better edge value still wins if its
    Sharpe advantage exceeds the penalty — this discourages marginal curve-fits,
    it doesn't forbid extreme values outright.

    Only numeric parameters (matching the numeric/categorical split `consensus()`
    already uses below) have a meaningful "center" — a categorical grid like
    `ma_type: ["EMA", "SMA"]` has no ordinal distance, so those keys are skipped
    rather than penalized by arbitrary YAML list order.

    Args:
        combo: A single parameter combination (one entry from param_combos()).
        search_space: The full grid the combo was drawn from.
        weight: Max penalty (in Sharpe units) per parameter, at the grid's edge.

    Returns:
        Non-negative penalty to subtract from the combo's pooled Sharpe.
    """
    penalty = 0.0
    for key, values in search_space.items():
        if key not in combo or len(values) < 2:
            continue
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
            continue  # categorical/boolean grid — no ordinal "center" to measure distance from
        try:
            idx = values.index(combo[key])
        except ValueError:
            continue
        center = (len(values) - 1) / 2
        if center > 0:
            penalty += weight * (abs(idx - center) / center)
    return penalty


def train_fold(strategy: str, direction: str, basket_bars: dict[str, list[dict]],
               fold: Fold, search_space: dict, costs: dict) -> tuple[dict, dict[str, object]]:
    """Grid search on the train window, pooled across the basket. Return winning params
    plus the winning combo's own per-symbol backtest results (BacktestResult), so the
    caller can read the IS return directly instead of re-running the identical backtest.

    Combos are ranked by pooled in-sample Sharpe minus a complexity penalty
    (see `_complexity_penalty`) that discourages picking grid-edge values on a
    marginal in-sample advantage.

    Args:
        strategy: Strategy name.
        direction: Directional bias ('bullish', 'bearish', etc.).
        basket_bars: Dict mapping symbol to list of OHLCV bars.
        fold: Fold object with train/test date ranges.
        search_space: Dict mapping parameter names to lists of values.
        costs: Dict with 'fee_pct' and 'slippage_pct' keys, charged per trade leg
            inside the backtest (see `commission_for`), so the ranking is net.

    Returns:
        (winning_params, {symbol: BacktestResult}) for the winning combo. The results map
        only contains symbols that pass the grid search's guard (>= MIN_SCORED_BARS bars inside the
        train window and >= 100 bars including the warm-up prefix).
        Both are ({}, {}) if no combo produced any trades on any symbol.
    """
    best, best_score = None, float("-inf")
    best_results: dict[str, object] = {}
    commission = commission_for(costs)
    for combo in param_combos(search_space):
        sharpes = []
        combo_results: dict[str, object] = {}
        for sym, bars in basket_bars.items():
            train_bars, n_scored = slice_with_warmup(bars, fold.train_start, fold.train_end)
            if n_scored < MIN_SCORED_BARS or len(train_bars) < 100:
                continue
            try:
                res = run_strategy_backtest(train_bars, strategy=strategy, direction=direction,
                                            params=combo, commission=commission,
                                            entry_start=fold.train_start)
            except Exception as exc:
                logger.debug("Train-fold backtest failed for %s: %s", sym, exc)
                continue
            combo_results[sym] = res
            if res.n_trades > 0:
                sharpes.append(res.sharpe)
        pooled = sum(sharpes) / len(sharpes) if sharpes else float("-inf")
        score = pooled - _complexity_penalty(combo, search_space) if sharpes else pooled
        if score > best_score:
            best_score, best, best_results = score, combo, combo_results
    return (best or {}), best_results


def consensus(fold_winners: list[dict]) -> dict:
    """Aggregate winning parameters across folds via median (numeric) or mode (categorical).

    For numeric values (int, float, not bool), computes the median and preserves type.
    For non-numeric values (strings, bools), computes the mode.

    Args:
        fold_winners: List of parameter dicts, one per fold.

    Returns:
        Dict of consensus parameters.
    """
    if not fold_winners:
        return {}
    keys = fold_winners[0].keys()
    out = {}
    for k in keys:
        vals = [w[k] for w in fold_winners if k in w]
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
            med = statistics.median(vals)
            out[k] = int(round(med)) if all(isinstance(v, int) for v in vals) else med
        else:
            out[k] = statistics.mode(vals)
    return out


def consistency(fold_test_returns: list[float]) -> float:
    """Calculate fraction of folds with positive out-of-sample mean return.

    Each element is the mean net return across all basket symbols in that fold's
    test window. A fold counts as positive if its mean return > 0. Folds where
    the basket is mixed (some symbols up, some down) are resolved by sign of the
    mean — not by per-symbol positive counts.

    Args:
        fold_test_returns: List of mean test-period returns per fold (as decimals).

    Returns:
        Ratio of positive-mean folds to total folds (0.0 to 1.0).
    """
    if not fold_test_returns:
        return 0.0
    return sum(1 for r in fold_test_returns if r > 0) / len(fold_test_returns)


def degradation_pct(*, in_sample: float, walk_forward: float) -> float:
    """Calculate curve-fit degradation as 1 - (walk_forward / in_sample).

    High degradation (near 1.0) suggests the strategy was over-fit to training data.
    Low degradation (near 0.0) suggests the edge is robust and translates to OOS.

    Args:
        in_sample: Training (in-sample) return percentage.
        walk_forward: Test (out-of-sample) return percentage.

    Returns:
        Degradation factor (0.0 to 1.0+).
    """
    # Undefined when in_sample <= 0: negative IS makes the ratio flip sign,
    # misclassifying a strategy that improved OOS as severely over-fit.
    if in_sample <= 0:
        return 0.0
    return 1.0 - (walk_forward / in_sample)
