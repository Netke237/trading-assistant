"""
Tests for the intraday HMM pipeline and fetch_intraday_candles reliability fixes.
"""
from __future__ import annotations

import random
from unittest.mock import patch

import pytest

from app.services.regime_hmm import compute_intraday_hmm, HmmResult, MIN_BARS


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_synthetic_bars(n: int, seed: int = 42) -> list[dict]:
    """Generate n plausible 15-min OHLCV bar dicts using a seeded RNG."""
    rng = random.Random(seed)
    base = 450.0
    bars = []
    for i in range(n):
        close = base + rng.gauss(0, 2)
        bars.append({
            "time": f"2026-01-{i % 28 + 1:02d} 09:30",
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 100_000,
        })
        base = close
    return bars


# ── HMM tests ────────────────────────────────────────────────────────────────


def test_hmm_returns_none_on_empty_bars():
    """compute_intraday_hmm([]) must return None without raising."""
    result = compute_intraday_hmm([])
    assert result is None


def test_hmm_returns_none_below_min_bars():
    """Any bar count below MIN_BARS must return None."""
    bars = _make_synthetic_bars(MIN_BARS - 1)
    result = compute_intraday_hmm(bars)
    assert result is None


def test_hmm_succeeds_with_200_synthetic_bars():
    """200 bars is exactly MIN_BARS — HMM should return a valid HmmResult."""
    assert MIN_BARS == 200, "MIN_BARS should be 200 after the fix"
    bars = _make_synthetic_bars(200)
    result = compute_intraday_hmm(bars)
    assert result is not None, "Expected HmmResult with 200 bars (== MIN_BARS)"
    assert isinstance(result, HmmResult)
    assert result.state in ('Trending', 'Choppy', 'Mean-reverting')
    assert 0.0 <= result.p_stay <= 1.0


def test_hmm_succeeds_with_1000_bars():
    """1000 bars (well above MIN_BARS) must produce a valid HmmResult."""
    bars = _make_synthetic_bars(1000)
    result = compute_intraday_hmm(bars)
    assert result is not None
    assert isinstance(result, HmmResult)
    assert result.state in ('Trending', 'Choppy', 'Mean-reverting')
    assert 0.0 <= result.p_stay <= 1.0
    for t in result.p_transition:
        assert t['prob'] > 0.05
        assert t['to'] in ('Trending', 'Choppy', 'Mean-reverting')


# ── fetch_intraday_candles tests ──────────────────────────────────────────────


def test_fetch_intraday_logs_on_failure():
    """
    When Tradier raises and yfinance returns empty, fetch_intraday_candles
    should return [] without raising an exception itself.
    """
    from app.data.market import fetch_intraday_candles

    def _tradier_raise(*args, **kwargs):
        raise RuntimeError("simulated Tradier network error")

    def _yf_empty(*args, **kwargs):
        return []

    with (
        patch("app.data.market.httpx.get", side_effect=_tradier_raise),
        patch("app.data.market._fetch_intraday_yf", side_effect=_yf_empty),
        patch("app.data.market.TRADIER_TOKEN", "fake-token"),
    ):
        result = fetch_intraday_candles("SPY")

    assert result == [], f"Expected [] on total failure, got {len(result)} bars"


def test_fetch_intraday_returns_partial_yf_bars_on_tradier_failure():
    """
    If Tradier fails but yfinance returns some bars, the function should
    return those bars rather than [].
    """
    from app.data.market import fetch_intraday_candles

    fake_bars = _make_synthetic_bars(300)

    def _tradier_raise(*args, **kwargs):
        raise RuntimeError("simulated Tradier failure")

    def _yf_returns_bars(*args, **kwargs):
        return fake_bars

    with (
        patch("app.data.market.httpx.get", side_effect=_tradier_raise),
        patch("app.data.market._fetch_intraday_yf", side_effect=_yf_returns_bars),
        patch("app.data.market.TRADIER_TOKEN", "fake-token"),
    ):
        result = fetch_intraday_candles("SPY")

    assert len(result) == 300
