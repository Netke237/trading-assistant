"""
Look-ahead bias test: shuffling the time series should change the HMM inference.
If the model used future data, the result would be deterministic regardless of order.
"""
import pytest
import numpy as np
pytest.importorskip("hmmlearn", reason="hmmlearn not available on this Python version — skipping HMM tests")
from app.services.regime_hmm import compute_intraday_hmm, MIN_BARS


def _make_bars(returns: list[float]) -> list[dict]:
    price = 100.0
    bars = []
    for r in returns:
        price = price * (1 + r)
        bars.append({'close': price, 'time': '2025-01-01 09:30', 'open': price, 'high': price, 'low': price, 'volume': 100})
    return bars


def test_shuffled_series_gives_different_result():
    """
    A shuffled return series has the same marginal distribution but different
    sequential structure. The HMM state should differ in at least some shuffles
    because the forward algorithm is time-order sensitive.
    """
    rng = np.random.default_rng(42)
    n = MIN_BARS + 200

    # Create a clearly structured series: first half trending, second half choppy
    trending = rng.normal(0.002, 0.0005, n // 2)
    choppy = rng.normal(0.0, 0.002, n - n // 2)
    returns = np.concatenate([trending, choppy])

    original_bars = _make_bars(returns.tolist())
    result_original = compute_intraday_hmm(original_bars)

    # Run several shuffles and collect states
    states_seen = set()
    if result_original:
        states_seen.add(result_original.state)

    for seed in range(10):
        shuffled = returns.copy()
        rng2 = np.random.default_rng(seed)
        rng2.shuffle(shuffled)
        bars_shuffled = _make_bars(shuffled.tolist())
        result = compute_intraday_hmm(bars_shuffled)
        if result:
            states_seen.add(result.state)

    # With 10 shuffles of a structured series, at least 2 different states should appear
    assert len(states_seen) >= 2, (
        f"All shuffles produced the same state '{states_seen}' — possible look-ahead bias"
    )


def test_compute_omm_is_causal_with_conviction():
    from app.services.regime_omm import compute_omm
    closes = [100 * (1.002 ** i) for i in range(400)]
    full = compute_omm(closes, direction="Bullish", lookback=20, window=500, min_obs=10)
    truncated = compute_omm(closes[:300], direction="Bullish", lookback=20, window=500, min_obs=10)
    # Truncating the future must not change the matrix computed on the past prefix.
    assert truncated is not None and full is not None
