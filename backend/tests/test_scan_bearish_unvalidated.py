"""P0B B2: bearish candidates stay visible with a capped, explained verdict."""
import json
from types import SimpleNamespace
from contextlib import ExitStack
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.routers import stock_scan as ss
from app.routers.watchlist import router as watchlist_router
from app.scoring.stock_scorer import RuleResult, StockScoreCard
from app.schemas.stock_scan import RegimeHorizonBlock
from app.services.unvalidated import BEARISH_UNVALIDATED_MESSAGE
from tests.conftest import _override_get_db
from tests.test_scan_stop_cost import _candles, _contract
from tests.test_scan_router_spreads import _make_contract_score, _make_entry, _make_plan, _make_rr
from tests.test_a5c_analysis_scan_drop_flags import _offline
from tests.test_stock_scan_router import _pass_bt
from tests.test_scan_result_vintage import _WatchlistDb
from app.services.strategy_engine import StrategySignal


def _options_scan(client, direction, *, entry_status="PASS"):
    candles = _candles("MSFT")
    price = candles[-1]["close"]
    contract = _contract(price, strike_mult=1.0)
    contract["right"] = "C" if direction == "Bullish" else "P"
    contract["delta"] = 0.55 if direction == "Bullish" else -0.55
    card = StockScoreCard("MSFT", direction, "Swing", 75, "PASS", [
        RuleResult("trend", "PASS", 90, {}),
        RuleResult("event", "PASS", 100, {"earnings_days": 90, "earnings_unknown": False}),
    ])
    entry = _make_entry()
    entry.quality_status = entry_status
    with ExitStack() as stack:
        for target, fake in {
            "app.services.historical_store.get_bars": AsyncMock(return_value=[]),
            "app.routers.scan.fetch_quotes": lambda *a: {},
            "app.data.confidence_cache.get_cached": lambda *a: {"confidence": 70, "sample_size": 50},
            "app.data.confidence_cache.set_cached": AsyncMock(),
            "app.routers.scan.fetch_price_async": AsyncMock(return_value=price),
            "app.routers.scan.fetch_candles_async": AsyncMock(return_value=candles),
            "app.routers.scan.fetch_option_chain_async": AsyncMock(return_value=[contract]),
            "app.routers.scan.fetch_company_name_async": AsyncMock(return_value="Test Co"),
            "app.routers.scan.fetch_fundamentals_calendar": AsyncMock(return_value=None),
            "app.routers.scan.fetch_calendar_dates_async": AsyncMock(return_value=(date.today() + timedelta(days=90), None)),
            "app.routers.scan.score_stock": lambda *a, **kw: card,
            "app.routers.scan.validate_contract": lambda *a, **kw: _make_contract_score(),
            "app.routers.scan.build_trade_plan": lambda *a, **kw: _make_plan(entry, _make_rr()),
            "app.routers.scan._build_spreads": AsyncMock(return_value=(None, None)),
        }.items():
            stack.enter_context(patch(target, fake))
        response = client.post("/api/scan", json={
            "universe": ["MSFT"], "direction": direction, "horizon": "Swing",
        })
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["candidates"]) == 1, data["rejected"]
    assert data["rejected"] == []
    return data


def test_options_bearish_caps_both_statuses_without_changing_the_scorer(client):
    bullish = _options_scan(client, "Bullish")["candidates"][0]
    bearish = _options_scan(client, "Bearish")["candidates"][0]
    assert bullish["status"] == bullish["finalStatus"] == "PASS"
    assert bullish.get("unvalidatedReason") is None
    assert bearish["status"] == "CAUTION"
    assert bearish["finalStatus"] == "CAUTION"
    assert bearish["unvalidatedReason"] == BEARISH_UNVALIDATED_MESSAGE
    assert bearish["stockConfidence"] == bullish["stockConfidence"] == "PASS"
    assert bearish["stockScore"] == bullish["stockScore"] == 75
    assert bearish["stockBreakdown"] == bullish["stockBreakdown"]


def test_options_bearish_never_improves_an_existing_reject(client):
    card = _options_scan(client, "Bearish", entry_status="REJECT")["candidates"][0]
    assert card["finalStatus"] == "REJECT"
    assert card["status"] == "CAUTION"
    assert card["unvalidatedReason"] == BEARISH_UNVALIDATED_MESSAGE


def test_watchlist_stored_bearish_scan_retains_caution(client):
    result = _options_scan(client, "Bearish")
    db = _WatchlistDb(["MSFT"], SimpleNamespace(last_result_json=json.dumps(result)))
    async def stored_db():
        yield db
    app = FastAPI()
    app.include_router(watchlist_router)
    app.dependency_overrides[get_db] = stored_db
    watch_client = TestClient(app)
    response = watch_client.get("/api/watchlist")
    assert response.status_code == 200
    row = next(row for row in response.json() if row["symbol"] == "MSFT")
    assert row["direction"] == "Bearish"
    assert row["status"] == "CAUTION"
    assert row["score"] == 75


@pytest.fixture
def stock_client(monkeypatch):
    _offline(monkeypatch, conviction=70, min_trend=None, bt_passes=True)
    monkeypatch.setattr(ss, "get_cached", lambda *a: {"confidence": 70, "sample_size": 50})
    monkeypatch.setattr(ss, "score_stock", lambda **kw: StockScoreCard(
        kw["symbol"], kw["direction"], kw["horizon"], 75, "PASS",
        [RuleResult("trend", "PASS", 90, {})]))
    monkeypatch.setattr(ss, "_get_backtest_cached", lambda *a: _pass_bt())
    monkeypatch.setitem(ss._SIGNAL_FNS, "pullback_ema", lambda bars, direction, **kw: StrategySignal(
        strategy="pullback_ema", direction=direction, entry_price=130.0,
        stop_price=125.0 if direction == "Bullish" else 135.0,
        target_price=140.0 if direction == "Bullish" else 120.0, atr=1.0))
    monkeypatch.setattr(ss, "_regime_block_for_horizon", lambda symbol, bars, horizon, *a: RegimeHorizonBlock(
        horizon=horizon, timeframe="daily", state="Bull", p_stay=0.8, stability="Stable",
        regime_age_days=5, avg_regime_duration=10, conviction_pct=70, conviction_label="x"))
    monkeypatch.setattr(ss, "_market_backdrop", AsyncMock(return_value=None))
    app = FastAPI()
    app.include_router(ss.router)
    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def _stock_result(client, direction, endpoint):
    body = {"direction": direction, "horizon": "Swing", "strategy": "pullback_ema"}
    body.update({"universe": ["TEST"], "symbols": ["TEST"]} if endpoint == "stock-scan" else {"symbol": "TEST"})
    response = client.post(f"/api/{endpoint}", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    if endpoint == "stock-scan":
        assert len(data["candidates"]) == 1, data["rejected"]
        assert data["rejected"] == []
        return data["candidates"][0], data["pipeline"]
    return data, None


@pytest.mark.parametrize("endpoint", ["stock-scan", "analyze-stock"])
def test_stock_bearish_is_visible_capped_and_explained(stock_client, endpoint):
    bullish, bull_pipeline = _stock_result(stock_client, "Bullish", endpoint)
    bearish, bear_pipeline = _stock_result(stock_client, "Bearish", endpoint)
    assert bullish["stock_status"] == "PASS"
    assert bearish["stock_status"] == "CAUTION"
    assert bearish["gate_flags"] == [{"gate": "unvalidated", "status": "CAUTION",
                                      "detail": BEARISH_UNVALIDATED_MESSAGE}]
    assert not any(g["gate"] == "unvalidated" for g in bullish.get("gate_flags", []))
    assert bearish["stock_score"] == bullish["stock_score"] == 75
    assert bearish["confidence"] == bullish["confidence"] == 70
    assert bearish["backtest"] == bullish["backtest"]
    assert bear_pipeline == bull_pipeline


def test_analysis_bearish_preserves_reject_and_adds_reason(stock_client, monkeypatch):
    monkeypatch.setattr(ss, "score_stock", lambda **kw: StockScoreCard(
        kw["symbol"], kw["direction"], kw["horizon"], 20, "REJECT",
        [RuleResult("trend", "REJECT", 20, {})]))
    card, _ = _stock_result(stock_client, "Bearish", "analyze-stock")
    assert card["stock_status"] == "REJECT"
    assert {"gate": "unvalidated", "status": "CAUTION", "detail": BEARISH_UNVALIDATED_MESSAGE} in card["gate_flags"]
