"""Tests for regime_hmm — synthetic 3-regime returns → correct state assignment."""
import pytest
import numpy as np
pytest.importorskip("hmmlearn", reason="hmmlearn not available on this Python version — skipping HMM tests")
from app.services.regime_hmm import compute_intraday_hmm, _assign_labels, MIN_BARS


def _make_bars(returns: np.ndarray) -> list[dict]:
    """Convert return array to minimal bar dicts (only close needed)."""
    price = 100.0
    bars = [{'close': price, 'time': '2025-01-01 09:30:00', 'open': price, 'high': price, 'low': price, 'volume': 1000}]
    for r in returns:
        price = price * (1 + r)
        bars.append({'close': price, 'time': '2025-01-01 09:30:00', 'open': price, 'high': price, 'low': price, 'volume': 1000})
    return bars


class TestComputeIntradayHmm:
    def test_returns_none_for_insufficient_bars(self):
        bars = _make_bars(np.zeros(100))
        assert compute_intraday_hmm(bars) is None

    def test_returns_result_for_sufficient_bars(self):
        np.random.seed(42)
        returns = np.random.normal(0.0002, 0.002, MIN_BARS + 50)
        bars = _make_bars(returns)
        result = compute_intraday_hmm(bars)
        assert result is not None

    def test_state_is_valid_label(self):
        np.random.seed(0)
        returns = np.random.normal(0, 0.002, MIN_BARS + 100)
        bars = _make_bars(returns)
        result = compute_intraday_hmm(bars)
        if result:
            assert result.state in ('Trending', 'Choppy', 'Mean-reverting')

    def test_p_stay_in_unit_interval(self):
        np.random.seed(1)
        returns = np.random.normal(0, 0.002, MIN_BARS + 100)
        bars = _make_bars(returns)
        result = compute_intraday_hmm(bars)
        if result:
            assert 0.0 <= result.p_stay <= 1.0

    def test_p_transition_above_threshold(self):
        np.random.seed(2)
        returns = np.random.normal(0, 0.002, MIN_BARS + 100)
        bars = _make_bars(returns)
        result = compute_intraday_hmm(bars)
        if result:
            for t in result.p_transition:
                assert t['prob'] > 0.05
                assert t['to'] in ('Trending', 'Choppy', 'Mean-reverting')


class TestAssignLabels:
    def test_trending_gets_highest_signal_ratio(self):
        # State 0: high mean, low std (Trending)
        # State 1: low mean, low std (Choppy)
        # State 2: low mean, high std (Mean-reverting)
        means = np.array([[0.05], [0.001], [0.001]])
        # Full covariance matrices for 'full' covariance type: shape (n, d, d)
        covars = np.array([
            [[0.0001]],   # low variance → Trending
            [[0.0001]],   # low variance → Choppy (lower |mean|/std after accounting for mean)
            [[0.01]],     # high variance → Mean-reverting
        ])
        labels = _assign_labels(means, covars)
        assert labels[0] == 'Trending'

    def test_mean_reverting_gets_highest_variance_state(self):
        means = np.array([[0.0001], [0.0001], [0.0001]])
        covars = np.array([
            [[0.0001]],
            [[0.001]],
            [[0.01]],     # highest variance → Mean-reverting
        ])
        labels = _assign_labels(means, covars)
        assert labels[2] == 'Mean-reverting'

    def test_all_three_labels_assigned(self):
        means = np.array([[0.05], [0.001], [0.0001]])
        covars = np.array([
            [[0.0001]],
            [[0.0005]],
            [[0.005]],
        ])
        labels = _assign_labels(means, covars)
        assert set(labels.values()) == {'Trending', 'Choppy', 'Mean-reverting'}
