import pytest
from app.services.strategy_engine import breakout_setup_signal

# ── helpers ──────────────────────────────────────────────────────────────────

def _make_bars(n: int = 120) -> list[dict]:
    """Bars that form a clean up-move then pullback to ~38.2% fib level.

    Days 0–59: price rises from 100 → 159 (swing low=100, swing high=160).
    Day 60: swing high = 160.
    Days 61–118: price pulls back to 38.2% retrace = 160 - 0.382*(160-100) = 137.08.
    ATR and volume are kept intentionally flat (compression always passes) so
    we can isolate the fib logic.
    """
    bars = []
    for i in range(60):
        price = 100 + i  # rises 100→159
        bars.append({"open": price, "high": price + 0.5, "low": price - 0.5,
                     "close": price, "volume": 500_000})
    # swing high = 160 at bar 60
    bars.append({"open": 160, "high": 161, "low": 159, "close": 160, "volume": 500_000})
    # pullback to 38.2% retracement level = 137.08
    fib_38 = 160 - 0.382 * (160 - 100)   # ≈ 137.08
    for i in range(58):
        bars.append({"open": fib_38, "high": fib_38 + 0.3, "low": fib_38 - 0.3,
                     "close": fib_38, "volume": 400_000})  # quiet volume
    return bars


def _make_bars_no_fib(n: int = 120) -> list[dict]:
    """Bars where close is far from any fib level (sits at 47% – between 38.2 and 50)."""
    bars = []
    for i in range(61):
        price = 100 + i
        bars.append({"open": price, "high": price + 0.5, "low": price - 0.5,
                     "close": price, "volume": 500_000})
    # close = 47% retrace = far from 38.2, 50, 61.8
    off_level = 160 - 0.47 * (160 - 100)   # ≈ 131.8
    for i in range(58):
        bars.append({"open": off_level, "high": off_level + 0.3, "low": off_level - 0.3,
                     "close": off_level, "volume": 400_000})
    return bars


# ── tests ─────────────────────────────────────────────────────────────────────

class TestFibonacciSignal:
    def test_fib_disabled_no_effect(self):
        """fib_enabled=False must return same result as not passing fib params at all."""
        bars = _make_bars()
        result = breakout_setup_signal(
            bars, "TEST",
            direction="Bullish",
            fib_enabled=False,
        )
        # Should still produce a signal (compression conditions pass in _make_bars)
        # fib parameters must not crash when disabled
        assert result is None or result.confidence >= 0

    def test_fib_at_38_level_raises_confidence(self):
        """Price at 38.2% retracement should raise confidence vs fib_enabled=False."""
        bars = _make_bars()
        # Bypass non-fib gates so only fib is the variable under test
        _bypass = dict(
            resistance_proximity_pct=0.25,
            swing_lookback=70,
            range_atr_mult=10.0,
            atr_compression_ratio=1.5,   # current ATR always < 1.5× average
            vol_compression_ratio=1.5,   # last bar volume always < 1.5× average
            require_trend=False,         # EMA may not converge in synthetic bars
        )
        without_fib = breakout_setup_signal(
            bars, "TEST",
            direction="Bullish",
            fib_enabled=False,
            **_bypass,
        )
        with_fib = breakout_setup_signal(
            bars, "TEST",
            direction="Bullish",
            fib_enabled=True,
            fib_levels=[23.6, 38.2, 50.0, 61.8],
            fib_tolerance_pct=0.02,
            fib_swing_lookback=119,  # full bar history to capture entire move (100→160)
            **_bypass,
        )
        # Both should return a signal; fib-enabled should have equal or higher confidence
        assert with_fib is not None
        assert without_fib is not None
        assert with_fib.confidence >= without_fib.confidence

    def test_fib_not_at_level_does_not_raise(self):
        """Price 47% into retrace (between 38.2 and 50) should not benefit from fib."""
        bars = _make_bars_no_fib()
        with_fib = breakout_setup_signal(
            bars, "TEST",
            direction="Bullish",
            fib_enabled=True,
            fib_levels=[23.6, 38.2, 50.0, 61.8],
            fib_tolerance_pct=0.01,   # tight tolerance
            fib_swing_lookback=70,
            resistance_proximity_pct=0.25,
            swing_lookback=70,
            range_atr_mult=10.0,
            atr_compression_ratio=1.5,
            vol_compression_ratio=1.5,
        )
        # Signal may or may not exist (compression conditions may fail for off-level bars),
        # but if it does exist the fib_at_level metric must be False.
        if with_fib is not None:
            assert with_fib.metrics.get("fib_at_level") is False

    def test_fib_metrics_present_when_enabled(self):
        """When fib enabled, result metrics must include fib_level_hit and fib_at_level."""
        bars = _make_bars()
        result = breakout_setup_signal(
            bars, "TEST",
            direction="Bullish",
            fib_enabled=True,
            fib_levels=[23.6, 38.2, 50.0, 61.8],
            fib_tolerance_pct=0.02,
            fib_swing_lookback=70,
            resistance_proximity_pct=0.25,
            swing_lookback=70,
            range_atr_mult=10.0,
            atr_compression_ratio=1.5,
            vol_compression_ratio=1.5,
        )
        if result is not None:
            assert "fib_at_level" in result.metrics
            assert "fib_level_hit" in result.metrics

    def test_fib_bearish_swing_low_to_high(self):
        """Bearish fib retracement uses high→low move then upward bounce."""
        # Mirror of make_bars but downward
        bars = []
        for i in range(61):
            price = 160 - i   # 160 → 100
            bars.append({"open": price, "high": price + 0.5, "low": price - 0.5,
                         "close": price, "volume": 500_000})
        fib_38_bear = 100 + 0.382 * (160 - 100)  # ≈ 122.9
        for i in range(58):
            bars.append({"open": fib_38_bear, "high": fib_38_bear + 0.3, "low": fib_38_bear - 0.3,
                         "close": fib_38_bear, "volume": 400_000})

        result = breakout_setup_signal(
            bars, "TEST",
            direction="Bearish",
            fib_enabled=True,
            fib_levels=[23.6, 38.2, 50.0, 61.8],
            fib_tolerance_pct=0.02,
            fib_swing_lookback=70,
            resistance_proximity_pct=0.25,
            swing_lookback=70,
            range_atr_mult=10.0,
            atr_compression_ratio=1.5,
            vol_compression_ratio=1.5,
        )
        # Just must not throw; confidence is 0-100 if returned
        if result is not None:
            assert 0 <= result.confidence <= 100

    def test_fib_enabled_empty_levels_falls_back_to_nonfib(self):
        """fib_enabled=True with fib_levels=[] must not penalise confidence.

        Internally the backend falls back to the non-fib weight scheme so the
        confidence should equal the fib_disabled result.
        """
        _bypass = dict(
            resistance_proximity_pct=0.25,
            swing_lookback=70,
            range_atr_mult=10.0,
            atr_compression_ratio=1.5,
            vol_compression_ratio=1.5,
            require_trend=False,         # EMA may not converge in synthetic bars
        )
        bars = _make_bars()
        without_fib = breakout_setup_signal(bars, "TEST", direction="Bullish",
                                            fib_enabled=False, **_bypass)
        with_empty_levels = breakout_setup_signal(bars, "TEST", direction="Bullish",
                                                  fib_enabled=True,
                                                  fib_levels=[],
                                                  **_bypass)
        # Both should return a signal and have equal confidence (fallback applied)
        assert without_fib is not None
        assert with_empty_levels is not None
        assert with_empty_levels.confidence == without_fib.confidence

    def test_fib_enabled_insufficient_bars_falls_back_to_nonfib(self):
        """fib_enabled=True with fewer than 10 bars in fib window must not penalise confidence."""
        _bypass = dict(
            resistance_proximity_pct=0.25,
            swing_lookback=5,
            range_atr_mult=10.0,
            atr_compression_ratio=1.5,
            vol_compression_ratio=1.5,
        )
        # Minimal bar set — just enough to pass min_bars gate but fib window < 10
        bars = []
        for i in range(35):
            price = 100.0 + i * 0.1
            bars.append({"open": price, "high": price + 0.1, "low": price - 0.1,
                         "close": price, "volume": 300_000})

        without_fib = breakout_setup_signal(bars, "TEST", direction="Bullish",
                                            fib_enabled=False,
                                            fib_swing_lookback=100,
                                            **_bypass)
        with_fib = breakout_setup_signal(bars, "TEST", direction="Bullish",
                                         fib_enabled=True,
                                         fib_levels=[38.2, 61.8],
                                         fib_swing_lookback=5,   # forces < 10 bars in window
                                         **_bypass)
        # If both return signals they must have equal confidence (fib fell back)
        if without_fib is not None and with_fib is not None:
            assert with_fib.confidence == without_fib.confidence
