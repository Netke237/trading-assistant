"""Walk-forward optimization fold construction and utilities."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from dateutil.relativedelta import relativedelta


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
