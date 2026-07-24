"""Unit tests for /api/stock-scan endpoint — schema and routing logic only (no live API calls)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.schemas.stock_scan import StockScanRequest
from app.routers.stock_scan import router as stock_scan_router
from tests.conftest import _override_get_db


# ── Schema tests ──────────────────────────────────────────────────────────────

def test_stock_scan_request_accepts_symbols():
    req = StockScanRequest(
        universe=["SP500"],
        symbols=["AAPL", "MSFT"],
        direction="Bullish",
        horizon="Swing",
        strategy="pullback_ema",
    )
    assert req.symbols == ["AAPL", "MSFT"]


def test_stock_scan_request_symbols_defaults_none():
    req = StockScanRequest(
        universe=["SP500"],
        direction="Bullish",
        horizon="Swing",
        strategy="pullback_ema",
    )
    assert req.symbols is None


# ── Endpoint fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def stock_client():
    """Minimal TestClient wiring only the stock-scan router."""
    app = FastAPI()
    app.include_router(stock_scan_router)
    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


_BARS = [
    {"time": f"2024-01-{d:02d}", "open": 150.0, "high": 155.0,
     "low": 148.0, "close": 152.0, "volume": 1_000_000}
    for d in range(1, 62)   # 61 bars — enough for scoring but below signal threshold
]


def _reject_card():
    card = MagicMock()
    card.status = "REJECT"
    card.score = 20
    card.rules = []
    return card


# ── Regression: stock scan uses universe, not options candidates ───────────────

def test_stock_scan_expands_universe_when_no_symbols_given(stock_client):
    """Without symbols the router must call expand_universe and use its result."""
    # expand_universe is a lazy import inside run_stock_scan — patch the source module
    with (
        patch("app.data.universe_presets.expand_universe", return_value=["AAPL", "MSFT"]) as mock_expand,
        patch("app.routers.stock_scan.fetch_quotes", return_value={}),
        patch("app.routers.stock_scan.get_historical_bars", AsyncMock(return_value=_BARS)),
        patch("app.routers.stock_scan.score_stock", return_value=_reject_card()),
        patch("app.routers.stock_scan.fetch_company_name_async", AsyncMock(return_value="Test")),
        patch("app.routers.stock_scan.fetch_price_async", AsyncMock(return_value=152.0)),
    ):
        r = stock_client.post("/api/stock-scan", json={
            "universe": ["SP500"],
            "direction": "Bullish",
            "horizon": "Swing",
            "strategy": "pullback_ema",
        })

    assert r.status_code == 200
    mock_expand.assert_called_once_with(["SP500"])
    data = r.json()
    # Both symbols go through the pipeline (end up in rejected due to score, not silently dropped)
    all_symbols = {c["symbol"] for c in data["candidates"]} | {r["symbol"] for r in data["rejected"]}
    assert all_symbols == {"AAPL", "MSFT"}


def test_stock_scan_uses_symbols_directly_when_provided(stock_client):
    """When symbols is given the router must skip expand_universe entirely."""
    with (
        patch("app.data.universe_presets.expand_universe") as mock_expand,
        patch("app.routers.stock_scan.fetch_quotes", return_value={}),
        patch("app.routers.stock_scan.get_historical_bars", AsyncMock(return_value=_BARS)),
        patch("app.routers.stock_scan.score_stock", return_value=_reject_card()),
        patch("app.routers.stock_scan.fetch_company_name_async", AsyncMock(return_value="Test")),
        patch("app.routers.stock_scan.fetch_price_async", AsyncMock(return_value=152.0)),
    ):
        r = stock_client.post("/api/stock-scan", json={
            "universe": ["SP500"],
            "symbols": ["NVDA"],
            "direction": "Bullish",
            "horizon": "Swing",
            "strategy": "pullback_ema",
        })

    assert r.status_code == 200
    mock_expand.assert_not_called()
    data = r.json()
    all_symbols = {c["symbol"] for c in data["candidates"]} | {r["symbol"] for r in data["rejected"]}
    assert all_symbols == {"NVDA"}


def test_stock_scan_response_shape(stock_client):
    """Response must always contain scan_id, timestamp, candidates, rejected, pipeline."""
    with (
        patch("app.data.universe_presets.expand_universe", return_value=[]),
        patch("app.routers.stock_scan.fetch_quotes", return_value={}),
    ):
        r = stock_client.post("/api/stock-scan", json={
            "universe": ["SP500"],
            "direction": "Bullish",
            "horizon": "Swing",
            "strategy": "pullback_ema",
        })

    assert r.status_code == 200
    data = r.json()
    for field in ("scan_id", "timestamp", "candidates", "rejected", "pipeline"):
        assert field in data, f"Missing field: {field}"


# ── Regression: options scan pipeline is unaffected ───────────────────────────

def test_options_scan_returns_200(client):
    """POST /api/scan must still return 200 after the stock-scan decoupling."""
    r = client.post("/api/scan", json={
        "universe": [], "direction": "Bullish", "horizon": "Swing", "overrides": {},
    })
    assert r.status_code == 200


def test_options_scan_response_has_required_fields(client):
    """Options scan response shape must be unaffected by stock-scan changes."""
    r = client.post("/api/scan", json={
        "universe": [], "direction": "Bullish", "horizon": "Swing", "overrides": {},
    })
    data = r.json()
    for field in ("scan_id", "timestamp", "candidates", "rejected"):
        assert field in data, f"Missing field: {field}"


def test_options_scan_empty_universe(client):
    """Options scan with empty universe must return empty candidates and rejected."""
    r = client.post("/api/scan", json={
        "universe": [], "direction": "Bullish", "horizon": "Swing", "overrides": {},
    })
    data = r.json()
    assert data["candidates"] == []
    assert data["rejected"] == []


def test_options_scan_invalid_direction_422(client):
    """Options scan must still reject invalid direction with 422."""
    r = client.post("/api/scan", json={
        "universe": ["AAPL"], "direction": "Sideways", "horizon": "Swing", "overrides": {},
    })
    assert r.status_code == 422


# ── Bearish direction threading ────────────────────────────────────────────────

def _make_bearish_bars(n: int = 130) -> list[dict]:
    """Return `n` daily bars in a clear downtrend that triggers pullback_ema bearish.

    Structure: 110 trend bars (200 → 115) + 20 bounce bars (115 → 118).
    With default params (ema_period=50, trend_ema=100) over bars[-120:]:
    - 100-EMA ≈ 141  (high, reflecting the deep downtrend)
    - 50-EMA  ≈ 125  (lower than 100-EMA → downtrend stack confirmed)
    - Last close ≈ 118  (below 50-EMA, ratio ≈ 0.05 well within 8% tolerance)
    This satisfies all three bearish gates in pullback_ema_signal.
    """
    bars = []
    trend_n = 110
    for i in range(trend_n):
        price = 200.0 - (85.0 * i / max(trend_n - 1, 1))
        bars.append({
            "time": f"2024-{(i // 28 + 1):02d}-{(i % 28 + 1):02d}",
            "open": price + 0.5,
            "high": price + 1.0,
            "low":  price - 1.0,
            "close": price,
            "volume": 1_500_000,
        })
    # Bear-rally bounce toward EMA — still stays well below the 50-EMA
    bounce_n = n - trend_n  # 20 bars
    for j in range(bounce_n):
        price = 115.0 + (3.0 * j / max(bounce_n - 1, 1))
        # Last 4 bars at low volume so volume contraction gate passes
        vol = 450_000 if j >= bounce_n - 4 else 1_500_000
        bars.append({
            "time": f"2025-01-{(j % 28 + 1):02d}",
            "open": price - 0.3,
            "high": price + 0.5,
            "low":  price - 0.5,
            "close": price,
            "volume": vol,
        })
    return bars


def _pass_card(symbol: str = "TSLA"):
    from app.scoring.stock_scorer import StockScoreCard
    return StockScoreCard(
        symbol=symbol, direction="Bearish", horizon="Swing",
        score=72, status="PASS", rules=[],
    )


def _pass_bt():
    from app.services.strategy_backtest import BacktestResult
    return BacktestResult(
        strategy="pullback_ema", direction="Bearish",
        n_trades=12, win_rate=0.58, total_return_pct=14.0,
        max_drawdown_pct=6.0, expectancy=0.45, sharpe=1.0,
        confidence=58, passes_gate=True, summary_text="PASS",
    )


def test_stock_scan_bearish_direction_threads_to_signal(stock_client):
    """Bearish direction must be passed to the signal fn and produce stop>entry>target."""
    import time
    from app.routers.stock_scan import (
        _BACKTEST_CACHE, _BACKTEST_TTL, _backtest_key,
    )

    bearish_bars = _make_bearish_bars(130)

    # Pre-populate backtest cache so the ProcessPoolExecutor is never invoked.
    # Key must match exactly what the router will compute for this symbol+strategy+direction+params.
    # _merge_strategy_params is patched below to return this exact fixed dict,
    # so the router's real key computation can't drift from what we pre-compute
    # here regardless of what get_active()'s persisted tuning state actually
    # holds for pullback_ema/Bearish at test-run time. This dict is a synthetic,
    # arbitrary-but-plausible params set for the fixture (tolerance=0.08 matches
    # StockScanRequest's schema default, not the signal function's own internal
    # fallback of 0.04) — it is NOT asserted to equal get_active()'s real
    # config values (which can and do change independently in strategy_params.yaml).
    _fixed_params = {
        "ema_period": 50, "trend_ema": 100, "atr_stop_mult": 1.5, "rr_target_mult": 2.0,
        "tolerance": 0.08, "ma_type": "EMA", "require_reversal": False,
    }
    bt_key = _backtest_key("TSLA", "pullback_ema", "Bearish", bearish_bars, _fixed_params)
    _BACKTEST_CACHE[bt_key] = (_pass_bt(), time.time() + _BACKTEST_TTL)

    try:
        with (
            patch("app.data.universe_presets.expand_universe", return_value=["TSLA"]),
            patch("app.routers.stock_scan.fetch_quotes", return_value={}),
            patch("app.routers.stock_scan.get_historical_bars", AsyncMock(return_value=bearish_bars)),
            patch("app.routers.stock_scan.score_stock", return_value=_pass_card()),
            patch("app.routers.stock_scan.fetch_company_name_async", AsyncMock(return_value="Tesla")),
            patch("app.routers.stock_scan.fetch_price_async", AsyncMock(return_value=118.0)),
            patch("app.routers.stock_scan.get_cached", return_value={"confidence": 60, "sample_size": 30}),
            patch("app.routers.stock_scan._merge_strategy_params", return_value=_fixed_params),
        ):
            r = stock_client.post("/api/stock-scan", json={
                "universe": ["SP500"],
                "symbols": ["TSLA"],
                "direction": "Bearish",
                "horizon": "Swing",
                "strategy": "pullback_ema",
            })
    finally:
        _BACKTEST_CACHE.pop(bt_key, None)

    assert r.status_code == 200, r.text
    data = r.json()
    # The symbol must appear as a candidate (not rejected)
    assert len(data["candidates"]) == 1, (
        f"Expected 1 candidate, got rejected: {data['rejected']}"
    )
    card = data["candidates"][0]
    assert card["direction"] == "Bearish"
    sig = card["strategy"]
    # Bearish shape: stop_price > entry_price > target_price
    assert sig["stop_price"] > sig["entry_price"], (
        f"Bearish stop must be above entry: stop={sig['stop_price']} entry={sig['entry_price']}"
    )
    assert sig["entry_price"] > sig["target_price"], (
        f"Bearish entry must be above target: entry={sig['entry_price']} target={sig['target_price']}"
    )
