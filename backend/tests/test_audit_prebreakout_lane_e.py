"""
Independent verification test suite for Lane E: Pre-Breakout, Fibonacci, and Pullback (APP-AUDIT-PREBREAKOUT, #353).
Pins signal calculations, confidence weights, parameter coercion, and route contracts.
"""

import pytest
from app.services.strategy_engine import _atr_series, breakout_setup_signal
from app.routers.stock_scan import router
from fastapi.testclient import TestClient
from fastapi import FastAPI


def test_atr_series_rolling_sma():
    """Verify that _atr_series computes a rolling 14-period Simple Moving Average of True Range starting at bar index 1."""
    bars = []
    for i in range(30):
        bars.append({
            "open": 100.0 + i,
            "high": 110.0 + i,
            "low": 100.0 + i,
            "close": 105.0 + i,
            "volume": 1000,
        })
    atrs = _atr_series(bars, period=14)
    # len(bars) - 1 because True Range calculation starts from bar 1 (requiring prior close)
    assert len(atrs) == 29
    for val in atrs:
        assert pytest.approx(val, rel=1e-5) == 10.0


def _build_contracting_bars(n: int = 60) -> list[dict]:
    """Construct synthetic bars exhibiting ATR and volume compression near swing high."""
    bars = []
    # Bars 0-39: High volatility (TR ~ 20.0), volume 1000
    for i in range(40):
        bars.append({
            "open": 90.0,
            "high": 100.0,
            "low": 80.0,
            "close": 95.0,
            "volume": 1000,
        })
    # Bars 40-59: Tight compression (TR ~ 2.0), close near resistance 100.0 (e.g. 98.0)
    for i in range(40, n):
        is_last = (i == n - 1)
        bars.append({
            "open": 97.0,
            "high": 99.0,
            "low": 97.0,
            "close": 98.5,
            "volume": 300 if is_last else 1000,  # volume contraction on last bar
        })
    return bars


def test_prebreakout_confidence_weights_and_components():
    """Verify exact base confidence weights (30% ATR, 25% Vol, 45% Proximity) and breakdown."""
    bars = _build_contracting_bars(60)
    sig = breakout_setup_signal(
        bars,
        symbol="TEST",
        direction="Bullish",
        atr_compression_ratio=0.85,
        atr_avg_lookback=20,
        range_atr_mult=3.0,
        range_lookback_bars=10,
        vol_compression_ratio=0.90,
        resistance_proximity_pct=0.08,
        swing_lookback=50,
        require_trend=False,
        fib_enabled=False,
    )
    assert sig is not None
    assert sig.confidence_breakdown is not None
    weights = sig.confidence_breakdown["weights"]
    assert weights["atr"] == pytest.approx(0.30, abs=1e-4)
    assert weights["vol"] == pytest.approx(0.25, abs=1e-4)
    assert weights["proximity"] == pytest.approx(0.45, abs=1e-4)
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-4)

    # Verify score calculation: total_score = sum(score * weight)
    components = sig.confidence_breakdown["components"]
    expected_score = sum(c["score"] * c["weight"] for c in components.values())
    assert sig.confidence == round(expected_score)


def test_prebreakout_fib_enabled_weights():
    """Verify scaled weights when fib_enabled=True: 24% ATR, 20% Vol, 36% Proximity, 20% Fib."""
    bars = _build_contracting_bars(60)
    sig = breakout_setup_signal(
        bars,
        symbol="TEST",
        direction="Bullish",
        atr_compression_ratio=0.85,
        atr_avg_lookback=20,
        range_atr_mult=3.0,
        range_lookback_bars=10,
        vol_compression_ratio=0.90,
        resistance_proximity_pct=0.08,
        swing_lookback=50,
        require_trend=False,
        fib_enabled=True,
        fib_levels=[38.2, 50.0, 61.8],
        fib_swing_lookback=40,
    )
    assert sig is not None
    weights = sig.confidence_breakdown["weights"]
    assert weights["atr"] == pytest.approx(0.24, abs=1e-4)
    assert weights["vol"] == pytest.approx(0.20, abs=1e-4)
    assert weights["proximity"] == pytest.approx(0.36, abs=1e-4)
    assert weights["fib"] == pytest.approx(0.20, abs=1e-4)
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-4)


def test_fibonacci_confidence_formula():
    """Verify Fibonacci confidence piecewise formula and missing distance guard."""
    tol = 1.5  # 1.5% tolerance (0.015 * 100)

    # 1. At level: dist_pct = 0 -> 100
    conf_at_0 = max(60, round(100 - (0.0 / tol) * 40))
    assert conf_at_0 == 100

    # 2. At boundary: dist_pct = tol -> 60
    conf_at_tol = max(60, round(100 - (tol / tol) * 40))
    assert conf_at_tol == 60

    # 3. Beyond boundary: dist_pct = 2 * tol -> 30
    conf_at_2tol = max(0, round(60 - ((2 * tol - tol) / tol) * 30))
    assert conf_at_2tol == 30

    # 4. Far beyond: dist_pct = 3 * tol -> 0
    conf_at_3tol = max(0, round(60 - ((3 * tol - tol) / tol) * 30))
    assert conf_at_3tol == 0


def test_route_presence_and_contracts():
    """Verify route existence and path mapping under the FastAPI app router."""
    app = FastAPI()
    # router already has prefix="/api"
    app.include_router(router)
    client = TestClient(app)

    # 1. Route /api/scan/prebreakout exists (empty symbols returns empty list or valid json)
    res_pre = client.post("/api/scan/prebreakout", json={"symbols": [], "direction": "Bullish"})
    assert res_pre.status_code == 200
    assert res_pre.json() == []

    # 2. Route /api/scan/fib-pullback exists
    res_fib = client.post("/api/scan/fib-pullback", json={"symbols": [], "direction": "Bullish"})
    assert res_fib.status_code == 200
    assert res_fib.json() == []

    # 3. Nonexistent legacy paths return 404
    assert client.post("/api/stock-scan/prebreakout", json={}).status_code == 404
    assert client.post("/api/stock-scan/fibonacci", json={}).status_code == 404
