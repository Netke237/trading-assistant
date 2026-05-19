"""Tests for shortlist cap enforcement in POST /api/scan."""

from contextlib import ExitStack
from unittest.mock import patch, AsyncMock
from app.scoring.stock_scorer import StockScoreCard, RuleResult
from app.scoring.contract_validator import ContractScoreCard, ContractScoreBreakdown

_MOCK_CANDLES = [
    {
        "time": f"2026-04-{i + 1:02d}",
        "open": 184.0, "high": 190.0, "low": 182.0, "close": 187.0,
        "volume": 1_000_000,
    }
    for i in range(30)
]

_MOCK_CHAIN = [
    {
        "strike": 190, "expiry": "2026-06-20", "price": 2.50, "spread": 0.20,
        "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 30,
        "right": "C", "volume": 500,
    }
]

_PASS_RULES = [
    RuleResult("trend",    "PASS", 80, {}),
    RuleResult("pullback", "PASS", 75, {}),
    RuleResult("trigger",  "PASS", 70, {}),
    RuleResult("event",    "PASS", 85, {}),
    RuleResult("vol",      "PASS", 80, {}),
]

_PASS_CONTRACT_BREAKDOWN = ContractScoreBreakdown(
    liquidity_score=75, spread_score=75, delta_score=75,
    dte_score=75, iv_rank_score=75, oi_score=75,
)


def _pass_card(symbol, *_, **__) -> StockScoreCard:
    return StockScoreCard(
        symbol=symbol,
        direction="Bullish",
        horizon="Swing",
        score=80,
        status="PASS",
        rules=_PASS_RULES,
    )


def _pass_contract(contract, *_, **__) -> ContractScoreCard:
    sym = contract.get("symbol", "SYM")
    strike = float(contract.get("strike", 190.0))
    expiry = contract.get("expiry", "2026-06-20")
    right = contract.get("right", "C")
    return ContractScoreCard(
        contract_id=f"{sym}|{int(strike)}|{expiry}|{right}",
        symbol=sym,
        strike=strike,
        expiry=expiry,
        is_call=right == "C",
        score=75,
        status="PASS",
        breakdown=_PASS_CONTRACT_BREAKDOWN,
    )


def _enter_shortlist_patches(truncate):
    stack = ExitStack()
    stack.enter_context(patch("app.routers.scan.fetch_price_async",            AsyncMock(return_value=185.0)))
    stack.enter_context(patch("app.routers.scan.fetch_candles_async",           AsyncMock(return_value=_MOCK_CANDLES)))
    stack.enter_context(patch("app.routers.scan.fetch_option_chain_async",      AsyncMock(return_value=_MOCK_CHAIN)))
    stack.enter_context(patch("app.routers.scan.fetch_company_name_async",      AsyncMock(return_value=None)))
    stack.enter_context(patch("app.routers.scan.fetch_fundamentals_calendar",   AsyncMock(return_value=None)))
    stack.enter_context(patch("app.routers.scan.score_stock",                 side_effect=_pass_card))
    stack.enter_context(patch("app.routers.scan.validate_contract",           side_effect=_pass_contract))
    stack.enter_context(patch("app.routers.scan._settings", {"scan": {"shortlist_max_candidates": truncate}}))
    return stack


def test_shortlist_cap_enforced(client):
    """20 symbols all scoring PASS, cap=5 -> <=5 candidates, truncated=True, original_count=20."""
    symbols = [f"SYM{i:02d}" for i in range(20)]

    with _enter_shortlist_patches(truncate=5):
        r = client.post("/api/scan", json={
            "universe": symbols,
            "direction": "Bullish",
            "horizon": "Swing",
        })

    assert r.status_code == 200
    body = r.json()
    assert body["shortlist_truncated"] is True
    assert body["original_count"] == 20
    assert len(body["candidates"]) <= 5


def test_shortlist_not_truncated_when_below_cap(client):
    """2 symbols, cap=10 -> shortlist_truncated=False."""
    with _enter_shortlist_patches(truncate=10):
        r = client.post("/api/scan", json={
            "universe": ["AAPL", "MSFT"],
            "direction": "Bullish",
            "horizon": "Swing",
        })
    assert r.status_code == 200
    body = r.json()
    assert body["shortlist_truncated"] is False
