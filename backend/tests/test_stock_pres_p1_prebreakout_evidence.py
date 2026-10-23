"""STOCK-PRES-P1 Task 2 — Pre-Breakout confidence breakdown and Fib swing low/high.

Send-only: the sub-scores / weights / contributions behind ``confidence`` and the
swing low/high the Fib levels are measured from are already computed inside
``breakout_setup_signal`` / ``_fibonacci_pullback_signal``; these tests pin that
the existing numbers do not move and that the new evidence reproduces them.
"""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.routers.stock_scan import _FIB_DEFAULTS
from app.services.strategy_engine import (
    _atr_series,
    _swing_high,
    breakout_setup_signal,
    fibonacci_pullback_signal,
)
from tests.test_prebreakout_params import _make_bars
from tests.test_strategy_engine_fib import _flat_bars, _impulse_then_retrace

# ── Pinned inputs and numbers (plan "Pinned current numbers") ─────────────────

_BASE_PARAMS = dict(
    atr_compression_ratio=0.85,
    atr_avg_lookback=20,
    range_atr_mult=3.0,
    range_lookback_bars=10,
    vol_compression_ratio=0.9,
    resistance_proximity_pct=0.08,
    swing_lookback=50,
    require_trend=True,
)
_FIB_ON = dict(fib_enabled=True, fib_swing_lookback=50, fib_levels=[23.6, 38.2, 50.0, 61.8])
_FIB_FALLBACK = dict(fib_enabled=True, fib_levels=[])

_METRICS_BASE = {
    "atr_ratio": 0.535,
    "range_ratio": 0.878,
    "vol_ratio": 0.732,
    "proximity_pct": 0.31,
    "swing_level": 104.42,
    "current_atr": 0.4557,
}
_METRICS_FIB = {
    **_METRICS_BASE,
    "fib_at_level": True,
    "fib_level_hit": "23.6",
    "fib_dist_pct": 0.63,
}

# (case id, extra kwargs, pinned confidence, pinned metrics, fib_used)
_CASES = [
    ("fib_off", {}, 59, _METRICS_BASE, False),
    ("fib_on", _FIB_ON, 67, _METRICS_FIB, True),
    ("fib_fallback", _FIB_FALLBACK, 59, _METRICS_BASE, False),
]
_CASE_IDS = [c[0] for c in _CASES]


def _bars() -> list[dict]:
    return _make_bars(60, 100.0, 0.5)


def _signal(extra: dict):
    return breakout_setup_signal(
        _bars(), "TEST", direction="Bullish", **_BASE_PARAMS, **extra,
    )


# ── 1. Numbers unchanged (guard — green before and after the change) ─────────

@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_pinned_confidence_and_metrics_unchanged(case):
    _, extra, confidence, metrics, _ = case
    sig = _signal(extra)
    assert sig is not None
    assert sig.confidence == confidence
    assert sig.metrics == metrics


def test_pinned_fib_tuple_unchanged():
    assert fibonacci_pullback_signal(_impulse_then_retrace(), "Bullish") == (True, 0.07, "61.8")


# ── 2. Breakdown reproduces the confidence ───────────────────────────────────

_W_BASE = {"atr": 0.30, "vol": 0.25, "proximity": 0.45}
_W_FIB = {"atr": 0.24, "vol": 0.20, "proximity": 0.36, "fib": 0.20}


def _independent_scores() -> dict:
    """Recompute atr/vol/proximity scores from the bars, as the engine does."""
    bars = _bars()
    p = _BASE_PARAMS
    atr = _atr_series(bars, period=14)
    current_atr = atr[-1]
    avg_atr = sum(atr[-p["atr_avg_lookback"]:]) / p["atr_avg_lookback"]
    atr_ratio = current_atr / avg_atr
    vols = [b["volume"] for b in bars]
    vol_ratio = vols[-1] / (sum(vols[-21:-1]) / 20)
    swing = _swing_high(bars, lookback=p["swing_lookback"])
    prox = (swing - bars[-1]["close"]) / swing
    return {
        "atr": max(0, 100 * (1 - atr_ratio / p["atr_compression_ratio"])),
        "vol": max(0, 100 * (1 - vol_ratio / p["vol_compression_ratio"])),
        "proximity": max(0, 100 * (1 - prox / p["resistance_proximity_pct"])),
    }


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_breakdown_reproduces_confidence(case):
    _, extra, confidence, _, fib_used = case
    sig = _signal(extra)
    bd = sig.confidence_breakdown
    assert bd["fib_used"] is fib_used
    weights = _W_FIB if fib_used else _W_BASE
    assert bd["weights"] == weights
    assert list(bd["components"]) == list(weights)

    indep = _independent_scores()
    total = 0.0
    for name, w in weights.items():
        comp = bd["components"][name]
        assert comp["weight"] == w
        assert comp["contribution"] == comp["score"] * w
        if name in indep:
            assert comp["score"] == indep[name]
        total += comp["contribution"]  # engine order; 0.0 + x == x exactly
    if fib_used:
        # Pinned case is at a level → full fib score.
        assert bd["components"]["fib"]["score"] == 100
    assert bd["unrounded"] == total
    assert min(100, max(0, int(bd["unrounded"]))) == sig.confidence == confidence
    assert bd["confidence"] == sig.confidence


# ── 3. Fib swing equals the window the levels were measured from ─────────────

def test_fib_swing_matches_measured_window():
    sig = _signal(_FIB_ON)
    window = _bars()[-50:]
    assert sig.fib_swing == {
        "low": min(b["low"] for b in window),
        "high": max(b["high"] for b in window),
    }


@pytest.mark.parametrize("extra", [{}, _FIB_FALLBACK], ids=["fib_off", "fib_fallback"])
def test_fib_swing_none_when_fib_not_used(extra):
    assert _signal(extra).fib_swing is None


# ── 4. Detail helper ──────────────────────────────────────────────────────────

def test_fibonacci_pullback_detail_returns_swing():
    from app.services.strategy_engine import fibonacci_pullback_detail

    bars = _impulse_then_retrace()
    window = bars[-100:]
    assert fibonacci_pullback_detail(bars, "Bullish") == {
        "at_level": True,
        "dist_pct": 0.07,
        "label": "61.8",
        "swing_low": min(b["low"] for b in window),
        "swing_high": max(b["high"] for b in window),
    }


def test_fibonacci_pullback_detail_too_few_bars():
    from app.services.strategy_engine import fibonacci_pullback_detail

    bars = _flat_bars(5)
    assert fibonacci_pullback_signal(bars, "Bullish") == (False, None, None)
    assert fibonacci_pullback_detail(bars, "Bullish") == {
        "at_level": False,
        "dist_pct": None,
        "label": None,
        "swing_low": None,
        "swing_high": None,
    }


# ── 5. Endpoints ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_prebreakout_endpoint_carries_breakdown_and_swing():
    bars = _bars()
    active = {**_BASE_PARAMS, **_FIB_ON}
    expected = breakout_setup_signal(bars, "AAPL", direction="Bullish", **active)
    with patch("app.routers.stock_scan.get_historical_bars",
               new_callable=AsyncMock, return_value=bars), \
         patch("app.routers.stock_scan.get_active", return_value=dict(active)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scan/prebreakout", json={
                "symbols": ["AAPL"], "direction": "Bullish",
            })
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["symbol"] == "AAPL"
    assert row["confidence"] == 67
    assert row["direction"] == "Bullish"
    assert row["metrics"] == _METRICS_FIB
    assert row["confidence_breakdown"] == expected.confidence_breakdown
    assert row["fib_swing"] == expected.fib_swing
    assert set(row) == {"symbol", "confidence", "direction", "metrics",
                        "confidence_breakdown", "fib_swing", "backtest_artifact_status"}


@pytest.mark.asyncio
async def test_fib_pullback_endpoint_carries_swing():
    bars = _impulse_then_retrace()
    window = bars[-_FIB_DEFAULTS["fib_swing_lookback"]:]
    with patch("app.routers.stock_scan.get_historical_bars",
               new_callable=AsyncMock, return_value=bars):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # The default 20-EMA filter drops this retracement (close < EMA);
            # disable it so the row is emitted. All other params are defaults.
            resp = await client.post("/api/scan/fib-pullback", json={
                "symbols": ["AAPL"], "direction": "Bullish",
                "params_override": {"ema_filter_period": 0},
            })
    assert resp.status_code == 200
    assert resp.json() == [{
        # Existing keys/values, as returned before this change (dcc015a5).
        "symbol": "AAPL",
        "direction": "Bullish",
        "fib_level_hit": "61.8",
        "fib_dist_pct": 0.07,
        "at_level": True,
        "confidence": 98,
        # New.
        "fib_swing": {
            "low": min(b["low"] for b in window),
            "high": max(b["high"] for b in window),
        },
        "backtest_artifact_status": "original_unavailable",
    }]
