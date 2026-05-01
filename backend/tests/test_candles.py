"""Mulberry32 RNG determinism test — same seed must produce identical output."""

from app.fixtures.candles import make_candles


def test_candles_are_deterministic():
    a = make_candles(seed=11, base=172, bars=5, drift=0.0008)
    b = make_candles(seed=11, base=172, bars=5, drift=0.0008)
    assert a == b, "Same seed must produce identical candle bars"


def test_candles_different_seeds_differ():
    a = make_candles(seed=11, base=172, bars=5, drift=0.0008)
    b = make_candles(seed=22, base=820, bars=5, drift=0.0015)
    assert a != b


def test_candle_bar_shape():
    bars = make_candles(seed=11, base=172, bars=3, drift=0.0008)
    assert len(bars) == 3
    for bar in bars:
        assert set(bar.keys()) == {"time", "open", "high", "low", "close", "volume"}
        assert bar["high"] >= bar["open"]
        assert bar["high"] >= bar["close"]
        assert bar["low"] <= bar["open"]
        assert bar["low"] <= bar["close"]
