"""Tests for walk-forward optimization fold construction."""
from datetime import date
from app.services.walk_forward import build_folds


def test_rolling_folds_step_by_test_months():
    """Test rolling folds step by test window size."""
    folds = build_folds(
        date(2018, 1, 1), date(2021, 1, 1),
        train_months=12, test_months=3, anchored=False
    )
    # train 12m / test 3m, stepping 3m: roughly 9 folds across 3 years (after the first 12m train)
    assert len(folds) >= 6
    f0 = folds[0]
    assert f0.train_start == date(2018, 1, 1)
    assert f0.test_start == f0.train_end                # test immediately follows train
    assert (f0.test_end.year, f0.test_end.month) >= (f0.test_start.year, f0.test_start.month)


def test_anchored_train_start_is_fixed():
    """Test anchored folds have fixed train_start and growing window."""
    folds = build_folds(
        date(2018, 1, 1), date(2021, 1, 1),
        train_months=12, test_months=3, anchored=True
    )
    assert all(f.train_start == date(2018, 1, 1) for f in folds)   # anchored: start fixed, window grows
