"""
test_contracts_scoring.py — Tests for the scored /api/contracts endpoint.

Covers:
1. _augment() produces non-zero iv_rank and bid_ask_spread_pct from raw dict
2. validate_contract() on an augmented contract returns ContractScoreCard with score > 0
3. Integration: mocked fetch_option_chain + fetch_price → GET /api/contracts returns
   contracts with score > 0, len <= 10, sorted by score desc
4. max_price filter: contracts with ask > max_price are excluded
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from app.data.augment import _augment
from app.scoring.contract_validator import validate_contract
from app.routers.contracts import router as contracts_router


# ── Helpers ───────────────────────────────────────────────────────────────────

def _future_expiry(days: int = 35) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _make_raw_contract(
    symbol: str = "TSLA",
    strike: float = 200.0,
    expiry_days: int = 35,
    price: float = 5.0,
    spread: float = 0.20,
    delta: float = 0.45,
    volume: int = 500,
    open_interest: int = 2000,
    iv: float = 0.35,
    right: str = "C",
) -> dict:
    expiry = _future_expiry(expiry_days)
    return {
        "id": f"{symbol}|{int(strike)}|{expiry}|{right}",
        "symbol": symbol,
        "strike": int(strike),
        "expiry": expiry,
        "right": right,
        "dte": expiry_days,
        "dteTotal": expiry_days,
        "price": price,
        "spread": spread,
        "delta": delta,
        "theta": -0.05,
        "ivRank": int(iv * 100),
        "implied_volatility": iv,
        "ivPercentile": 40,
        "volume": volume,
        "open_interest": open_interest,
        "score": 0,
    }


# ── 1. _augment() tests ───────────────────────────────────────────────────────

def test_augment_produces_nonzero_iv_rank():
    raw = _make_raw_contract(iv=0.35)
    aug = _augment(raw, stock_price=190.0)

    assert aug["iv_rank"] > 0, "iv_rank should be non-zero when ivRank is set in raw contract"
    assert "bid" in aug, "_augment must add 'bid' key"
    assert "ask" in aug, "_augment must add 'ask' key"


def test_augment_bid_ask_spread():
    raw = _make_raw_contract(price=5.0, spread=0.40)
    aug = _augment(raw, stock_price=190.0)

    # bid = max(0.01, price - spread/2), ask = price + spread/2
    assert aug["bid"] == pytest.approx(4.80, abs=0.01)
    assert aug["ask"] == pytest.approx(5.20, abs=0.01)

    mid = (aug["bid"] + aug["ask"]) / 2
    spread_pct = (aug["ask"] - aug["bid"]) / mid
    # spread_pct = 0.40 / 5.0 = 0.08
    assert spread_pct == pytest.approx(0.08, abs=0.005)


def test_augment_computes_bs_delta_when_missing():
    """When delta is 0 but IV and stock price are present, BS delta is computed."""
    raw = _make_raw_contract(delta=0.0, iv=0.35, strike=200.0, expiry_days=35)
    aug = _augment(raw, stock_price=190.0)

    # BS delta for a slightly OTM call should be in (0.2, 0.6)
    assert 0.15 < abs(aug["delta"]) < 0.65, f"Unexpected BS delta: {aug['delta']}"


def test_augment_preserves_original_delta():
    """When delta is already set, _augment must not overwrite it."""
    raw = _make_raw_contract(delta=0.52, iv=0.35)
    aug = _augment(raw, stock_price=190.0)
    assert aug["delta"] == pytest.approx(0.52, abs=1e-6)


# ── 2. validate_contract() on augmented contract ─────────────────────────────

def test_validate_contract_score_positive_for_good_contract():
    raw = _make_raw_contract(
        delta=0.45,
        volume=800,
        open_interest=3000,
        spread=0.20,          # 0.20 / 5.0 = 0.04 → well within preferred
        iv=0.30,
        expiry_days=35,
    )
    aug = _augment(raw, stock_price=200.0)
    card = validate_contract(aug, stock_score=70, overrides=None)

    assert card.score > 0, f"Expected score > 0, got {card.score} (status={card.status}, rejects={card.reject_reasons})"


def test_validate_contract_returns_score_card_type():
    from app.scoring.contract_validator import ContractScoreCard
    raw = _make_raw_contract()
    aug = _augment(raw, stock_price=200.0)
    card = validate_contract(aug, stock_score=70, overrides=None)

    assert isinstance(card, ContractScoreCard)
    assert hasattr(card, "score")
    assert hasattr(card, "status")
    assert hasattr(card, "breakdown")


# ── 3. Integration test via AsyncClient ──────────────────────────────────────

def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(contracts_router)
    return app


SAMPLE_CHAIN = [
    _make_raw_contract(symbol="AAPL", strike=190, delta=0.45, volume=500, open_interest=2000,
                       spread=0.20, iv=0.30, expiry_days=35),
    _make_raw_contract(symbol="AAPL", strike=195, delta=0.38, volume=300, open_interest=1500,
                       spread=0.25, iv=0.32, expiry_days=35),
    _make_raw_contract(symbol="AAPL", strike=200, delta=0.30, volume=200, open_interest=1000,
                       spread=0.30, iv=0.34, expiry_days=42),
]


@pytest.mark.asyncio
async def test_get_contracts_integration():
    app = _build_test_app()

    with (
        patch("app.routers.contracts.fetch_option_chain", return_value=SAMPLE_CHAIN),
        patch("app.routers.contracts.fetch_price", return_value=190.0),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/contracts?symbol=AAPL&right=C&stock_score=70")

    assert response.status_code == 200
    data = response.json()

    assert len(data) <= 10, f"Expected at most 10 results, got {len(data)}"
    assert all(c["score"] > 0 for c in data), (
        f"All contracts should have score > 0; got: {[c['score'] for c in data]}"
    )


@pytest.mark.asyncio
async def test_get_contracts_sorted_by_score_desc():
    app = _build_test_app()

    with (
        patch("app.routers.contracts.fetch_option_chain", return_value=SAMPLE_CHAIN),
        patch("app.routers.contracts.fetch_price", return_value=190.0),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/contracts?symbol=AAPL&right=C&stock_score=70")

    assert response.status_code == 200
    data = response.json()

    scores = [c["score"] for c in data]
    assert scores == sorted(scores, reverse=True), f"Scores not sorted desc: {scores}"


@pytest.mark.asyncio
async def test_get_contracts_respects_limit():
    # Provide more than `limit` contracts in the chain
    chain = [
        _make_raw_contract(symbol="AAPL", strike=180 + i * 5, delta=0.45, volume=500,
                           open_interest=2000, spread=0.20, iv=0.30, expiry_days=35)
        for i in range(15)
    ]
    app = _build_test_app()

    with (
        patch("app.routers.contracts.fetch_option_chain", return_value=chain),
        patch("app.routers.contracts.fetch_price", return_value=190.0),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/contracts?symbol=AAPL&right=C&limit=5")

    assert response.status_code == 200
    data = response.json()
    assert len(data) <= 5, f"Expected at most 5, got {len(data)}"


# ── 4. max_price filter ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_contracts_max_price_filter():
    """Contracts with ask > max_price should be excluded."""
    cheap = _make_raw_contract(symbol="AAPL", strike=200, price=2.0, spread=0.10,
                               delta=0.35, volume=500, open_interest=2000,
                               iv=0.30, expiry_days=35)   # ask ≈ 2.05
    expensive = _make_raw_contract(symbol="AAPL", strike=180, price=20.0, spread=0.50,
                                   delta=0.80, volume=500, open_interest=2000,
                                   iv=0.30, expiry_days=35)  # ask ≈ 20.25

    app = _build_test_app()

    with (
        patch("app.routers.contracts.fetch_option_chain", return_value=[cheap, expensive]),
        patch("app.routers.contracts.fetch_price", return_value=190.0),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/contracts?symbol=AAPL&right=C&max_price=5.0")

    assert response.status_code == 200
    data = response.json()

    # Only the cheap contract should be returned
    assert len(data) == 1, f"Expected 1 contract (cheap only), got {len(data)}: {data}"
    assert data[0]["strike"] == 200


@pytest.mark.asyncio
async def test_get_contracts_empty_chain():
    """Returns empty list when fetch_option_chain returns nothing."""
    app = _build_test_app()

    with (
        patch("app.routers.contracts.fetch_option_chain", return_value=[]),
        patch("app.routers.contracts.fetch_price", return_value=190.0),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/contracts?symbol=AAPL")

    assert response.status_code == 200
    assert response.json() == []
