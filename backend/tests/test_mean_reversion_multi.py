"""Tests for mean_reversion_vwap_daily_signal and mean_reversion_multi scan path."""

import pytest
from app.services.strategy_engine import (
    mean_reversion_vwap_daily_signal,
    StrategySignal,
)


def make_bars(n: int, base_price: float = 100.0, base_volume: float = 1_000_000) -> list[dict]:
    """Build synthetic daily bars with slight noise.

    Args:
        n: number of bars
        base_price: starting price
        base_volume: base volume (bars will have volume ± 10%)

    Returns:
        List of bar dicts with OHLCV + date
    """
    bars = []
    price = base_price
    for i in range(n):
        # Slight random drift (±0.2% per bar)
        drift = 1 + (i % 7 - 3) * 0.002
        price *= drift

        vol = base_volume * (0.9 + (i % 3) * 0.1)
        bars.append({
            "open": price - 0.3,
            "high": price + 0.5,
            "low": price - 0.5,
            "close": price,
            "volume": vol,
            "date": f"2025-01-{(i % 31) + 1:02d}",
        })
    return bars


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: vwap_daily fires on snap-back (Bullish)
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_daily_bullish_snap_back():
    """bar[-2] closes 5% below rolling VWAP, bar[-1] snaps back above VWAP."""
    bars = make_bars(25, base_price=100.0, base_volume=1_000_000)

    # Keep VWAP stable by using consistent prices
    for i in range(len(bars)):
        bars[i]["close"] = 100.0
        bars[i]["high"] = 100.5
        bars[i]["low"] = 99.5
        bars[i]["volume"] = 1_000_000

    # bar[-2]: close = 95 (5% below rolling VWAP of ~100)
    bars[-2]["close"] = 95.0
    bars[-2]["low"] = 94.5

    # bar[-1]: close = 101 (back above VWAP)
    bars[-1]["close"] = 101.0
    bars[-1]["high"] = 101.5

    signal = mean_reversion_vwap_daily_signal(bars, direction="Bullish")

    assert signal is not None, "Expected signal on Bullish snap-back"
    assert signal.direction == "Bullish"
    assert signal.entry_price > 0
    assert signal.strategy == "mean_reversion_vwap_daily"


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: vwap_daily does NOT fire when bar[-1] still below VWAP
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_daily_bullish_no_snap_back():
    """bar[-2] closes below VWAP, but bar[-1] still below VWAP."""
    bars = make_bars(25, base_price=100.0, base_volume=1_000_000)

    # Keep VWAP stable
    for i in range(len(bars)):
        bars[i]["close"] = 100.0
        bars[i]["high"] = 100.5
        bars[i]["low"] = 99.5
        bars[i]["volume"] = 1_000_000

    # bar[-2]: close = 95 (5% below VWAP)
    bars[-2]["close"] = 95.0
    bars[-2]["low"] = 94.5

    # bar[-1]: close = 97 (still below VWAP of ~100)
    bars[-1]["close"] = 97.0
    bars[-1]["low"] = 96.5

    signal = mean_reversion_vwap_daily_signal(bars, direction="Bullish")

    assert signal is None, "Expected None when bar[-1] still below VWAP"


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: vwap_daily does NOT fire when deviation is insufficient
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_daily_bullish_insufficient_deviation():
    """bar[-2] closes only 0.5% below VWAP (threshold is 2%), bar[-1] above VWAP."""
    bars = make_bars(25, base_price=100.0, base_volume=1_000_000)

    # Keep VWAP stable
    for i in range(len(bars)):
        bars[i]["close"] = 100.0
        bars[i]["high"] = 100.5
        bars[i]["low"] = 99.5
        bars[i]["volume"] = 1_000_000

    # bar[-2]: close = 99.5 (0.5% below VWAP of ~100, below threshold)
    bars[-2]["close"] = 99.5
    bars[-2]["low"] = 99.0

    # bar[-1]: close = 101 (back above VWAP)
    bars[-1]["close"] = 101.0
    bars[-1]["high"] = 101.5

    signal = mean_reversion_vwap_daily_signal(
        bars,
        direction="Bullish",
        vwap_deviation_pct=0.02  # 2% threshold
    )

    assert signal is None, "Expected None when deviation is below 2% threshold"


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: vwap_daily fires for Bearish direction
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_daily_bearish_snap_back():
    """bar[-2] closes 5% above rolling VWAP, bar[-1] snaps back below VWAP."""
    bars = make_bars(25, base_price=100.0, base_volume=1_000_000)

    # Keep VWAP stable
    for i in range(len(bars)):
        bars[i]["close"] = 100.0
        bars[i]["high"] = 100.5
        bars[i]["low"] = 99.5
        bars[i]["volume"] = 1_000_000

    # bar[-2]: close = 105 (5% above rolling VWAP of ~100)
    bars[-2]["close"] = 105.0
    bars[-2]["high"] = 105.5

    # bar[-1]: close = 99 (snaps back below VWAP)
    bars[-1]["close"] = 99.0
    bars[-1]["low"] = 98.5

    signal = mean_reversion_vwap_daily_signal(bars, direction="Bearish")

    assert signal is not None, "Expected signal on Bearish snap-back"
    assert signal.direction == "Bearish"


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: vwap_daily insufficient bars returns None
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_daily_insufficient_bars():
    """Only 10 bars (less than vwap_lookback=20 + 2 required)."""
    bars = make_bars(10, base_price=100.0, base_volume=1_000_000)

    signal = mean_reversion_vwap_daily_signal(
        bars,
        direction="Bullish",
        vwap_lookback=20
    )

    assert signal is None, "Expected None with insufficient bars"


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: vwap_daily detail contains rolling_vwap and deviation_pct
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_daily_detail_fields():
    """Verify detail dict contains rolling_vwap and deviation_pct."""
    bars = make_bars(25, base_price=100.0, base_volume=1_000_000)

    # Keep VWAP stable
    for i in range(len(bars)):
        bars[i]["close"] = 100.0
        bars[i]["high"] = 100.5
        bars[i]["low"] = 99.5
        bars[i]["volume"] = 1_000_000

    # bar[-2]: close = 95 (5% below VWAP)
    bars[-2]["close"] = 95.0
    bars[-2]["low"] = 94.5

    # bar[-1]: close = 101 (back above VWAP)
    bars[-1]["close"] = 101.0
    bars[-1]["high"] = 101.5

    signal = mean_reversion_vwap_daily_signal(bars, direction="Bullish")

    assert signal is not None
    assert "rolling_vwap" in signal.detail
    assert "deviation_pct" in signal.detail
    assert signal.detail["rolling_vwap"] > 0
    assert signal.detail["deviation_pct"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: StrategySignal structure and risk/reward/rr_ratio properties
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_daily_signal_structure():
    """Verify StrategySignal has all required fields and properties."""
    bars = make_bars(25, base_price=100.0, base_volume=1_000_000)

    # Setup for successful signal
    for i in range(len(bars)):
        bars[i]["close"] = 100.0
        bars[i]["high"] = 100.5
        bars[i]["low"] = 99.5
        bars[i]["volume"] = 1_000_000

    bars[-2]["close"] = 95.0
    bars[-2]["low"] = 94.5
    bars[-1]["close"] = 101.0
    bars[-1]["high"] = 101.5

    signal = mean_reversion_vwap_daily_signal(bars, direction="Bullish")

    assert signal is not None
    assert isinstance(signal, StrategySignal)
    assert signal.strategy == "mean_reversion_vwap_daily"
    assert signal.direction == "Bullish"
    assert signal.entry_price > 0
    assert signal.stop_price > 0
    assert signal.target_price > 0
    assert signal.atr > 0
    # For Bullish: stop < entry < target
    assert signal.stop_price < signal.entry_price < signal.target_price
    assert signal.risk > 0
    assert signal.reward > 0
    assert signal.rr_ratio > 0


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: Bearish signal structure
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_daily_bearish_signal_structure():
    """Bearish signal: target < entry < stop."""
    bars = make_bars(25, base_price=100.0, base_volume=1_000_000)

    for i in range(len(bars)):
        bars[i]["close"] = 100.0
        bars[i]["high"] = 100.5
        bars[i]["low"] = 99.5
        bars[i]["volume"] = 1_000_000

    bars[-2]["close"] = 105.0
    bars[-2]["high"] = 105.5
    bars[-1]["close"] = 99.0
    bars[-1]["low"] = 98.5

    signal = mean_reversion_vwap_daily_signal(bars, direction="Bearish")

    assert signal is not None
    assert signal.direction == "Bearish"
    # For Bearish: target < entry < stop
    assert signal.target_price < signal.entry_price < signal.stop_price


# ─────────────────────────────────────────────────────────────────────────────
# Test 9: Edge case — just above boundary (> 2% deviation)
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_daily_just_above_2pct_deviation():
    """bar[-2] at 2.1% below VWAP (just above threshold)."""
    bars = make_bars(25, base_price=100.0, base_volume=1_000_000)

    # Keep VWAP stable
    for i in range(len(bars)):
        bars[i]["close"] = 100.0
        bars[i]["high"] = 100.5
        bars[i]["low"] = 99.5
        bars[i]["volume"] = 1_000_000

    # bar[-2]: close = 97.9 (2.1% below VWAP of 100)
    bars[-2]["close"] = 97.9
    bars[-2]["low"] = 97.4

    # bar[-1]: close = 101 (back above)
    bars[-1]["close"] = 101.0
    bars[-1]["high"] = 101.5

    signal = mean_reversion_vwap_daily_signal(
        bars,
        direction="Bullish",
        vwap_deviation_pct=0.02
    )

    # Just above threshold should fire (< comparison with 0.021)
    assert signal is not None, "Expected signal at 2.1% deviation (> 2% threshold)"


# ─────────────────────────────────────────────────────────────────────────────
# Test 10: Customizable stop and target multipliers
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_daily_custom_atr_multipliers():
    """Custom stop_atr_mult and rr_target_mult.

    UPDATED by the 2026-08-22 exit-targets rework. This test used to assert that
    a higher `rr_target_mult` produced a larger `signal.reward`, which was only
    true because `target_price` WAS `entry + risk * rr_target_mult`. It is now
    the mirror of the entry deviation off the rolling VWAP (a reclaim-and-
    overshoot — VWAP itself sits BEHIND entry for this variant, since its gate is
    `close > vwap`), so `rr_target_mult` no longer touches rung 1 at all: it
    scales the outward extension rungs, which are dropped entirely when they land
    inside the thesis rung.

    So the contract asserted here is the new one: rung 1 is invariant under
    rr_target_mult, and the multiplier's real effect is how far the LADDER
    reaches.
    """
    bars = make_bars(25, base_price=100.0, base_volume=1_000_000)

    for i in range(len(bars)):
        bars[i]["close"] = 100.0
        bars[i]["high"] = 100.5
        bars[i]["low"] = 99.5
        bars[i]["volume"] = 1_000_000

    bars[-2]["close"] = 95.0
    bars[-2]["low"] = 94.5
    bars[-1]["close"] = 101.0
    bars[-1]["high"] = 101.5

    # Custom multipliers
    signal = mean_reversion_vwap_daily_signal(
        bars,
        direction="Bullish",
        stop_atr_mult=1.0,  # wider stop
        rr_target_mult=3.0,  # higher reward target
    )

    assert signal is not None

    # Compare to default (0.5, 2.0)
    signal_default = mean_reversion_vwap_daily_signal(
        bars,
        direction="Bullish",
        stop_atr_mult=0.5,
        rr_target_mult=2.0,
    )
    assert signal_default is not None

    # Rung 1 is the thesis level and is identical under both multipliers.
    assert signal.target_price == signal_default.target_price
    assert signal.target_price == signal.targets[0]

    # The wider stop genuinely widens the risk...
    assert signal.risk > signal_default.risk
    # ...and the higher rr_target_mult pushes the extension rungs out past the
    # thesis rung, so the ladder reaches further than the default's does.
    assert signal.targets[-1] > signal_default.targets[-1]
    assert len(signal.targets) > len(signal_default.targets)


# ─────────────────────────────────────────────────────────────────────────────
# Test 11: No signal when zero ATR (degenerate case)
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_daily_zero_atr():
    """All bars identical — ATR = 0, should return None."""
    bars = []
    for i in range(25):
        bars.append({
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1_000_000,
        })

    signal = mean_reversion_vwap_daily_signal(bars, direction="Bullish")

    # With zero ATR, stop calculation would fail (risk <= 0)
    assert signal is None


# ─────────────────────────────────────────────────────────────────────────────
# Test 12: Real-world-like bars with volume variation
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_daily_with_realistic_bars():
    """Use make_bars() helper to generate realistic synthetic data."""
    bars = make_bars(30, base_price=150.0, base_volume=2_500_000)

    # Manually set up snap-back
    # First 28 bars will have slight variation from make_bars
    # Adjust last 2 bars for our test
    for i in range(len(bars) - 2):
        bars[i]["close"] = 150.0
        bars[i]["high"] = 150.5
        bars[i]["low"] = 149.5
        bars[i]["volume"] = 2_500_000

    # bar[-2]: down 3% from 150
    bars[-2]["close"] = 145.5
    bars[-2]["low"] = 145.0
    bars[-2]["high"] = 146.0

    # bar[-1]: back up to 151
    bars[-1]["close"] = 151.0
    bars[-1]["high"] = 151.5
    bars[-1]["low"] = 150.0

    signal = mean_reversion_vwap_daily_signal(bars, direction="Bullish")

    assert signal is not None, "Expected signal with realistic bars"
    assert signal.entry_price == pytest.approx(151.0, abs=0.01)


# --- Integration tests for multi-signal scan endpoint ---

from unittest.mock import patch, AsyncMock, MagicMock
import pytest


@pytest.mark.asyncio
async def test_multi_signal_rejects_empty_variants():
    """min_confirmations=2 with zero variants should return 422 from model_validator."""
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/stock-scan", json={
            "universe": ["SP500"],
            "direction": "Bullish",
            "horizon": "Swing",
            "strategy": "mean_reversion_multi",
            "mean_reversion_variants": [],
            "mean_reversion_min_confirmations": 2,
        })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_multi_signal_rejects_when_min_exceeds_variants():
    """3 confirmations with 1 variant should return 422."""
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/stock-scan", json={
            "universe": ["SP500"],
            "direction": "Bullish",
            "horizon": "Swing",
            "strategy": "mean_reversion_multi",
            "mean_reversion_variants": ["mean_reversion_rsi"],
            "mean_reversion_min_confirmations": 3,
        })
    assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# resolve_multi_signal — order-independent variant resolution
# ─────────────────────────────────────────────────────────────────────────────

def test_resolve_multi_signal_is_order_independent():
    """The bug this replaces: fired[0] made the answer depend on the order the
    caller listed the variants in."""
    from app.services.strategy_engine import StrategySignal, resolve_multi_signal

    a = StrategySignal(strategy="mean_reversion_bb", direction="Bullish",
                       entry_price=100.0, stop_price=96.0, target_price=108.0,
                       atr=2.0, targets=[108.0, 114.0])
    b = StrategySignal(strategy="mean_reversion_rsi", direction="Bullish",
                       entry_price=100.0, stop_price=94.0, target_price=105.0,
                       atr=2.0, targets=[105.0, 111.0])

    first = resolve_multi_signal([a, b])
    second = resolve_multi_signal([b, a])
    assert first == second
    # Widest stop wins (94, not 96).
    assert first.stop_price == 94.0
    # Tightest surviving rung leads. risk = 6, floor = entry + 0.5R = 103.
    assert first.target_price == 105.0
    assert first.targets[0] == first.target_price
    assert first.detail["fired"] == ["mean_reversion_bb", "mean_reversion_rsi"]
    assert first.detail["resolution"] == "widest_stop_tightest_target"


def test_resolve_multi_signal_bearish_widest_stop_is_the_highest():
    from app.services.strategy_engine import StrategySignal, resolve_multi_signal

    a = StrategySignal(strategy="mean_reversion_bb", direction="Bearish",
                       entry_price=100.0, stop_price=104.0, target_price=92.0,
                       atr=2.0, targets=[92.0])
    b = StrategySignal(strategy="mean_reversion_rsi", direction="Bearish",
                       entry_price=100.0, stop_price=106.0, target_price=95.0,
                       atr=2.0, targets=[95.0])
    out = resolve_multi_signal([a, b])
    assert out.stop_price == 106.0
    assert out.target_price == 95.0     # tightest, and outside the 0.5R floor (97)
    assert all(t < out.entry_price for t in out.targets)


def test_resolve_multi_signal_drops_rungs_inside_the_widened_floor():
    """Widening the stop widens the 0.5R floor this caller passes, which can
    invalidate a rung that was fine against a variant's own tighter stop. That
    must not produce a target at or behind entry, and must not let a rung no
    variant ever proposed against THIS stop become the target."""
    from app.services.strategy_engine import StrategySignal, resolve_multi_signal
    from app.services.strategy_backtest import _entry_side

    a = StrategySignal(strategy="mean_reversion_bb", direction="Bullish",
                       entry_price=100.0, stop_price=99.0, target_price=100.6,
                       atr=1.0, targets=[100.6])
    b = StrategySignal(strategy="mean_reversion_rsi", direction="Bullish",
                       entry_price=100.0, stop_price=90.0, target_price=112.0,
                       atr=1.0, targets=[112.0])
    out = resolve_multi_signal([a, b])
    assert out.stop_price == 90.0
    assert out.target_price == 112.0    # 100.6 is inside the 5.0 floor, dropped
    assert _entry_side("Bullish", entry=out.entry_price,
                       sl=out.stop_price, tp=out.target_price) == "buy"


def test_resolve_multi_signal_with_a_single_variant_keeps_its_own_target():
    """mean_reversion_min_confirmations is user-configurable down to 1, so a
    single fired variant is a real, reachable call — not just a degenerate
    edge case. With nothing to merge, the 0.5R floor (there to stop a rung
    surviving a transplant onto a WIDER stop from another variant) must not
    apply against the variant's OWN stop and silently discard its own thesis
    rung. 100.4 is 0.08R from entry/stop (100/95, risk 5) — well inside 0.5R,
    and exactly the kind of rung mean_reversion_bb's tight (0.5-ATR) stop
    routinely produces, per its own module docstring."""
    from app.services.strategy_engine import StrategySignal, resolve_multi_signal

    a = StrategySignal(strategy="mean_reversion_bb", direction="Bullish",
                       entry_price=100.0, stop_price=95.0, target_price=100.4,
                       atr=1.0, targets=[100.4, 112.0])
    out = resolve_multi_signal([a])
    assert out.target_price == 100.4, "must not fall back to the 2R extension"
    assert out.targets == [100.4, 112.0]
    assert out.stop_price == 95.0
    assert out.detail["confirmations"] == 1
    assert out.detail["resolution"] == "single_variant_passthrough"


def test_resolve_multi_signal_with_a_single_variant_and_no_targets_list():
    """Mirrors the targets-is-empty fallback test above, for the single-variant
    passthrough path specifically."""
    from app.services.strategy_engine import StrategySignal, resolve_multi_signal

    a = StrategySignal(strategy="mean_reversion_bb", direction="Bullish",
                       entry_price=100.0, stop_price=95.0, target_price=100.4, atr=1.0)
    out = resolve_multi_signal([a])
    assert out.targets == [100.4]
    assert out.target_price == 100.4


def test_resolve_multi_signal_returns_none_on_empty():
    from app.services.strategy_engine import resolve_multi_signal
    assert resolve_multi_signal([]) is None


def test_resolve_multi_signal_falls_back_to_target_price_when_targets_is_empty():
    """A variant constructed without the additive `targets` field (several older
    tests do exactly this) must still contribute its rung."""
    from app.services.strategy_engine import StrategySignal, resolve_multi_signal

    a = StrategySignal(strategy="mean_reversion_bb", direction="Bullish",
                       entry_price=100.0, stop_price=96.0, target_price=108.0, atr=2.0)
    b = StrategySignal(strategy="mean_reversion_rsi", direction="Bullish",
                       entry_price=100.0, stop_price=95.0, target_price=106.0, atr=2.0)
    out = resolve_multi_signal([a, b])
    assert out.targets == [106.0, 108.0]
    assert out.stop_price == 95.0
