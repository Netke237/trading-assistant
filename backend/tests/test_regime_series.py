"""Tests for compute_regime_series and compute_intraday_hmm_series."""
from __future__ import annotations

import pytest


def _daily_candles(n: int = 100, start_price: float = 100.0) -> list[dict]:
    candles = []
    price = start_price
    for i in range(n):
        price += 0.3
        candles.append({
            "time": f"2024-{(i // 21 + 1):02d}-{(i % 21 + 1):02d}",
            "open": price - 0.1,
            "high": price + 0.5,
            "low": price - 0.5,
            "close": price,
            "volume": 1_000_000,
        })
    return candles


def _intraday_candles(n: int = 100) -> list[dict]:
    candles = []
    price = 100.0
    for i in range(n):
        candles.append({
            "time": f"2024-01-02T{(9 + i // 4):02d}:{(i % 4) * 15:02d}:00",
            "open": price - 0.05,
            "high": price + 0.1,
            "low": price - 0.1,
            "close": price,
            "volume": 50_000,
        })
        price += 0.01
    return candles


class TestComputeRegimeSeries:
    def test_empty_input(self):
        from app.services.regime_omm import compute_regime_series
        assert compute_regime_series([]) == []

    def test_output_length_matches_input(self):
        from app.services.regime_omm import compute_regime_series
        candles = _daily_candles(100)
        result = compute_regime_series(candles)
        # Result may be shorter due to warm-up period, but must not be longer
        assert len(result) <= len(candles)
        assert len(result) > 0

    def test_output_has_required_keys(self):
        from app.services.regime_omm import compute_regime_series
        candles = _daily_candles(100)
        result = compute_regime_series(candles)
        if result:
            assert "time" in result[0]
            assert "state" in result[0]

    def test_state_values_are_valid(self):
        from app.services.regime_omm import compute_regime_series
        candles = _daily_candles(100)
        result = compute_regime_series(candles)
        valid_states = {"Bull", "Bear", "Choppy"}
        for entry in result:
            assert entry["state"] in valid_states, f"Invalid state: {entry['state']}"


class TestComputeIntradayHmmSeries:
    def test_returns_list(self):
        pytest.importorskip("hmmlearn", reason="hmmlearn not available — skipping HMM series tests")
        from app.services.regime_hmm import compute_intraday_hmm_series
        candles = _intraday_candles(100)
        result = compute_intraday_hmm_series(candles)
        assert isinstance(result, list)

    def test_insufficient_bars_returns_empty(self):
        pytest.importorskip("hmmlearn", reason="hmmlearn not available — skipping HMM series tests")
        from app.services.regime_hmm import compute_intraday_hmm_series, MIN_BARS
        candles = _intraday_candles(MIN_BARS - 1)
        result = compute_intraday_hmm_series(candles)
        assert result == []

    def test_truncates_to_max_bars(self):
        pytest.importorskip("hmmlearn", reason="hmmlearn not available — skipping HMM series tests")
        from app.services.regime_hmm import compute_intraday_hmm_series
        candles = _intraday_candles(400)
        result = compute_intraday_hmm_series(candles, max_bars=100)
        assert len(result) <= 100

    def test_output_has_required_keys(self):
        pytest.importorskip("hmmlearn", reason="hmmlearn not available — skipping HMM series tests")
        from app.services.regime_hmm import compute_intraday_hmm_series
        candles = _intraday_candles(250)
        result = compute_intraday_hmm_series(candles)
        if result:
            assert "time" in result[0]
            assert "state" in result[0]
            assert "conviction" in result[0]

    def test_conviction_is_probability(self):
        pytest.importorskip("hmmlearn", reason="hmmlearn not available — skipping HMM series tests")
        from app.services.regime_hmm import compute_intraday_hmm_series
        candles = _intraday_candles(250)
        result = compute_intraday_hmm_series(candles)
        for entry in result:
            assert 0.0 <= entry["conviction"] <= 1.0
