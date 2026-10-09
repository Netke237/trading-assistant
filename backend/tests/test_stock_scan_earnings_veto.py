"""P0B B6: the stocks path vetoes earnings inside the hold window.

veto_days = max(reject_days, hold_max_days) (`effective_veto_days`); a stock
card with a KNOWN earnings date inside it is capped at CAUTION, flagged and
marked `earnings_veto`. An unknown date (None, or a failed lookup) is not a
veto on stocks. No candidate is dropped.

The earnings date comes from `auto_trader._fetch_earnings_date` (the fire
path's Tradier-then-yfinance chain), the module-level seam conftest stubs for
the whole suite -- never from the batch quote, which carries no date.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.data.market as market
import app.services.auto_trader as at
from app.database import get_db
from app.routers import stock_scan as ss
from app.schemas.stock_scan import RegimeHorizonBlock
from app.scoring.stock_scorer import RuleResult, StockScoreCard
from app.services.strategy_engine import StrategySignal
from tests.conftest import _override_get_db
from tests.test_a5c_analysis_scan_drop_flags import _offline
from tests.test_earnings_lookup_fire import _install_tradier, _install_yf
from tests.test_stock_scan_router import _pass_bt


def _in(days: int) -> date:
    return date.today() + timedelta(days=days)


def _signal(bars, direction, **kw):
    return StrategySignal(
        strategy="pullback_ema", direction=direction, entry_price=130.0,
        stop_price=125.0 if direction == "Bullish" else 135.0,
        target_price=140.0 if direction == "Bullish" else 120.0, atr=1.0)


@pytest.fixture
def lookups(monkeypatch):
    """Every symbol the earnings lookup was asked about; the answer is set per test."""
    calls: list[str] = []
    state = {"answer": _in(365)}

    def _fetch(symbol):
        calls.append(symbol)
        ans = state["answer"]
        if isinstance(ans, Exception):
            raise ans
        return ans

    monkeypatch.setattr(at, "_fetch_earnings_date", _fetch)
    return calls, state


@pytest.fixture
def client(monkeypatch):
    _offline(monkeypatch, conviction=70, min_trend=None, bt_passes=True)
    monkeypatch.setattr(ss, "get_cached", lambda *a: {"confidence": 70, "sample_size": 50})
    monkeypatch.setattr(ss, "score_stock", lambda **kw: StockScoreCard(
        kw["symbol"], kw["direction"], kw["horizon"], 75, "PASS",
        [RuleResult("trend", "PASS", 90, {})]))
    monkeypatch.setattr(ss, "_get_backtest_cached", lambda *a: _pass_bt())
    monkeypatch.setitem(ss._SIGNAL_FNS, "pullback_ema", _signal)
    monkeypatch.setattr(ss, "_regime_block_for_horizon", lambda symbol, bars, horizon, *a: RegimeHorizonBlock(
        horizon=horizon, timeframe="daily", state="Bull", p_stay=0.8, stability="Stable",
        regime_age_days=5, avg_regime_duration=10, conviction_pct=70, conviction_label="x"))
    monkeypatch.setattr(ss, "_market_backdrop", AsyncMock(return_value=None))
    app = FastAPI()
    app.include_router(ss.router)
    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def _post(client, endpoint, **extra):
    body = {"direction": "Bullish", "horizon": "Position", "strategy": "pullback_ema", **extra}
    body.update({"universe": ["TEST"], "symbols": ["TEST"]} if endpoint == "stock-scan" else {"symbol": "TEST"})
    response = client.post(f"/api/{endpoint}", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    if endpoint == "stock-scan":
        assert data["rejected"] == []
        assert len(data["candidates"]) == 1
        return data["candidates"][0], data
    return data, data


def _earnings_flags(card):
    return [g for g in card.get("gate_flags", []) if g["gate"] == "earnings"]


ENDPOINTS = ["stock-scan", "analyze-stock"]


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_earnings_inside_the_hold_caps_at_caution_and_flags(client, lookups, endpoint):
    _, state = lookups
    state["answer"] = _in(40)
    card, data = _post(client, endpoint, hold_max_days=60)
    assert card["stock_status"] == "CAUTION"
    assert card["earnings_veto"] is True
    assert card["earnings_days"] == 40
    assert _earnings_flags(card) == [{
        "gate": "earnings", "status": "CAUTION",
        "detail": "earnings in 40d is inside the hold window (<60d)",
    }]
    assert card["stock_score"] == 75
    if endpoint == "stock-scan":
        assert data["veto_days"] == 60
        assert data["pipeline"]["candidates"] == 1
        assert data["pipeline"]["scanned"] == 1


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_earnings_beyond_the_hold_leaves_the_card_alone(client, lookups, endpoint):
    _, state = lookups
    state["answer"] = _in(70)
    card, data = _post(client, endpoint, hold_max_days=60)
    assert card["stock_status"] == "PASS"
    assert card["earnings_veto"] is False
    assert card["earnings_days"] == 70
    assert _earnings_flags(card) == []
    if endpoint == "stock-scan":
        assert data["veto_days"] == 60


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("answer", [None, market.EarningsLookupError("tradier down; yfinance down"),
                                    RuntimeError("boom")])
def test_unknown_earnings_is_not_a_stocks_veto(client, lookups, endpoint, answer):
    _, state = lookups
    state["answer"] = answer
    card, _ = _post(client, endpoint, hold_max_days=60)
    assert card["stock_status"] == "PASS"
    assert card["earnings_veto"] is False
    assert card["earnings_days"] is None
    assert _earnings_flags(card) == []


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_a_past_earnings_date_is_unknown(client, lookups, endpoint):
    _, state = lookups
    state["answer"] = _in(-3)
    card, _ = _post(client, endpoint, hold_max_days=60)
    assert card["stock_status"] == "PASS"
    assert card["earnings_veto"] is False
    assert card["earnings_days"] is None


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_no_hold_falls_back_to_the_horizon_preset_hold(client, lookups, endpoint):
    """Position: reject 30, preset hold 45 -> window 45."""
    _, state = lookups
    state["answer"] = _in(40)
    card, data = _post(client, endpoint)
    assert card["earnings_veto"] is True
    assert _earnings_flags(card)[0]["detail"] == "earnings in 40d is inside the hold window (<45d)"
    if endpoint == "stock-scan":
        assert data["veto_days"] == 45
    state["answer"] = _in(50)
    card, _ = _post(client, endpoint)
    assert card["earnings_veto"] is False
    assert card["stock_status"] == "PASS"


def test_a_symbol_dropped_by_an_earlier_gate_never_triggers_the_lookup(client, lookups, monkeypatch):
    calls, state = lookups
    state["answer"] = _in(40)
    monkeypatch.setitem(ss._SIGNAL_FNS, "pullback_ema", lambda bars, direction, **kw: None)
    response = client.post("/api/stock-scan", json={
        "universe": ["TEST"], "symbols": ["TEST"], "direction": "Bullish",
        "horizon": "Position", "strategy": "pullback_ema", "hold_max_days": 60,
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["candidates"] == []
    assert len(data["rejected"]) == 1
    assert calls == []


def test_the_scan_looks_up_each_surviving_symbol_once(client, lookups):
    calls, _ = lookups
    _post(client, "stock-scan", hold_max_days=60)
    assert calls == ["TEST"]


def test_analysis_never_lifts_a_reject(client, lookups, monkeypatch):
    _, state = lookups
    state["answer"] = _in(10)
    monkeypatch.setattr(ss, "score_stock", lambda **kw: StockScoreCard(
        kw["symbol"], kw["direction"], kw["horizon"], 20, "REJECT",
        [RuleResult("trend", "REJECT", 20, {})]))
    card, _ = _post(client, "analyze-stock", hold_max_days=60)
    assert card["stock_status"] == "REJECT"
    assert card["earnings_veto"] is True
    assert _earnings_flags(card)[0]["status"] == "CAUTION"


def test_a_bearish_card_keeps_both_reasons(client, lookups):
    _, state = lookups
    state["answer"] = _in(40)
    card, _ = _post(client, "stock-scan", direction="Bearish", hold_max_days=60)
    assert card["stock_status"] == "CAUTION"
    assert [g["gate"] for g in card["gate_flags"]] == ["unvalidated", "earnings"]


def test_hold_max_days_is_bounded():
    from app.schemas.stock_scan import StockScanRequest
    from pydantic import ValidationError
    base = {"universe": ["TEST"], "direction": "Bullish", "horizon": "Swing", "strategy": "pullback_ema"}
    assert StockScanRequest(**base).hold_max_days is None
    assert StockScanRequest(**base, hold_max_days=185).hold_max_days == 185
    for bad in (-1, 3651):
        with pytest.raises(ValidationError):
            StockScanRequest(**base, hold_max_days=bad)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_the_real_lookup_chain_feeds_the_veto(client, monkeypatch, endpoint):
    """Drives the real `_lookup_earnings_date` (Tradier fundamentals first),
    stubbing only the HTTP edge, as tests/test_earnings_lookup_fire.py does."""
    monkeypatch.setattr(at, "_fetch_earnings_date", at._lookup_earnings_date)
    monkeypatch.setattr(market, "_fundamentals_calendar_cache", {})
    monkeypatch.setattr(market, "_yf_cal_cache", {})
    monkeypatch.setattr(market, "_yf_cal_cache_date", "")
    monkeypatch.setattr(market, "_yf_cal_fail_until", {})
    monkeypatch.setattr(market, "get_tradier_creds", lambda: ("tok", "https://tradier.test"))
    _install_tradier(monkeypatch, report_date=_in(40))
    _install_yf(monkeypatch, [{}])
    card, _ = _post(client, endpoint, hold_max_days=60)
    assert card["earnings_days"] == 40
    assert card["earnings_veto"] is True
    assert card["stock_status"] == "CAUTION"
