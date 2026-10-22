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
from unittest.mock import patch, AsyncMock

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
        patch("app.routers.contracts.fetch_option_chain_async", new_callable=AsyncMock, return_value=SAMPLE_CHAIN),
        patch("app.routers.contracts.fetch_price_async", new_callable=AsyncMock, return_value=190.0),
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
        patch("app.routers.contracts.fetch_option_chain_async", new_callable=AsyncMock, return_value=SAMPLE_CHAIN),
        patch("app.routers.contracts.fetch_price_async", new_callable=AsyncMock, return_value=190.0),
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
        patch("app.routers.contracts.fetch_option_chain_async", new_callable=AsyncMock, return_value=chain),
        patch("app.routers.contracts.fetch_price_async", new_callable=AsyncMock, return_value=190.0),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/contracts?symbol=AAPL&right=C&limit=5")

    assert response.status_code == 200
    data = response.json()
    assert len(data) <= 5, f"Expected at most 5, got {len(data)}"


@pytest.mark.asyncio
async def test_get_contracts_forwards_backend_contractConfidence_not_stock_scale():
    """Regression: /api/contracts must forward validate_contract()'s own status
    (contract-scale thresholds from contract_rules.yaml: pass>=65/caution>=45),
    not one a client would derive from stock-scale thresholds (pass>=55/
    caution>=35). score=60 is PASS under stock-scale but CAUTION under
    contract-scale — mock validate_contract to return exactly that pair and
    assert the response carries the real CAUTION status through untouched.
    """
    from app.scoring.contract_validator import ContractScoreCard, ContractScoreBreakdown

    app = _build_test_app()

    fake_card = ContractScoreCard(
        contract_id="AAPL|190|2099-01-01|C", symbol="AAPL", strike=190, expiry="2099-01-01",
        is_call=True, score=60, status="CAUTION",
        breakdown=ContractScoreBreakdown(0, 0, 0, 0, 0, 0),
    )

    with (
        patch("app.routers.contracts.fetch_option_chain_async", new_callable=AsyncMock, return_value=SAMPLE_CHAIN[:1]),
        patch("app.routers.contracts.fetch_price_async", new_callable=AsyncMock, return_value=190.0),
        patch("app.routers.contracts.validate_contract", return_value=fake_card),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/contracts?symbol=AAPL&right=C&stock_score=70")

    assert response.status_code == 200
    data = response.json()
    assert data[0]["score"] == 60
    assert data[0]["contractConfidence"] == "CAUTION", (
        f"Expected backend status 'CAUTION' to pass through untouched, got {data[0]['contractConfidence']!r}"
    )


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
        patch("app.routers.contracts.fetch_option_chain_async", new_callable=AsyncMock, return_value=[cheap, expensive]),
        patch("app.routers.contracts.fetch_price_async", new_callable=AsyncMock, return_value=190.0),
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


def test_oi_score_is_populated():
    """oi_score in the breakdown should reflect open interest, not always be 0."""
    contract = {
        'symbol': 'AAPL', 'strike': 185.0, 'expiry': '2025-09-19',
        'is_call': True, 'bid': 3.50, 'ask': 3.60,
        'delta': 0.45, 'volume': 500, 'open_interest': 2000,
    }
    card = validate_contract(contract, stock_score=70)
    assert card.breakdown.oi_score > 0, 'oi_score should reflect open interest'


def test_oi_score_populated_on_pass_path():
    """oi_score must be populated even when contract passes all gates."""
    import datetime
    expiry = (datetime.date.today() + datetime.timedelta(days=45)).isoformat()
    contract = {
        'symbol': 'SPY', 'strike': 500.0, 'expiry': expiry,
        'is_call': True,
        'bid': 4.90, 'ask': 5.10,       # tight spread
        'delta': 0.50,                   # centre of preferred range
        'volume': 5000,                  # well above preferred_volume_min (200)
        'open_interest': 10000,          # well above preferred_oi_min (1000)
        'iv_rank': 30,                   # within preferred range
    }
    card = validate_contract(contract, stock_score=80)
    assert card.status != 'REJECT', f'Expected PASS/CAUTION, got REJECT: {card.reject_reasons}'
    assert card.breakdown.oi_score > 0, f'oi_score is 0 on PASS path: {card.breakdown}'


@pytest.mark.asyncio
async def test_get_contracts_empty_chain():
    """Returns empty list when fetch_option_chain returns nothing."""
    app = _build_test_app()

    with (
        patch("app.routers.contracts.fetch_option_chain_async", new_callable=AsyncMock, return_value=[]),
        patch("app.routers.contracts.fetch_price_async", new_callable=AsyncMock, return_value=190.0),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/contracts?symbol=AAPL")

    assert response.status_code == 200
    assert response.json() == []


# ── DTE hard-reject tests (min_dte: 14 → 21) ────────────────────────────────

def test_contract_rejected_at_dte_18():
    """DTE=18 must be hard-rejected after raising min_dte from 14 to 21."""
    from datetime import date, timedelta
    expiry = (date.today() + timedelta(days=18)).isoformat()
    contract = {
        "symbol": "AAPL", "strike": 185.0, "expiry": expiry, "is_call": True,
        "bid": 2.00, "ask": 2.10, "delta": 0.45,
        "volume": 500, "open_interest": 1500, "iv_rank": 30,
    }
    card = validate_contract(contract, stock_score=70)
    assert card.status == "REJECT"
    assert "dte_too_short" in card.reject_reasons


def test_contract_passes_at_dte_22():
    """DTE=22 must not be rejected for DTE reasons."""
    from datetime import date, timedelta
    expiry = (date.today() + timedelta(days=22)).isoformat()
    contract = {
        "symbol": "AAPL", "strike": 185.0, "expiry": expiry, "is_call": True,
        "bid": 2.00, "ask": 2.10, "delta": 0.45,
        "volume": 500, "open_interest": 1500, "iv_rank": 30,
    }
    card = validate_contract(contract, stock_score=70)
    assert "dte_too_short" not in card.reject_reasons


@pytest.mark.asyncio
async def test_recompute_plan_rr_target_r_multiple_override_changes_target():
    """Same override key set as the scan endpoint (rr_target_r_multiple) must
    also move Step 6's recompute-plan target, or a user who overrides the
    contract after tuning R/R params would silently lose their tuning."""
    app = FastAPI()
    app.include_router(contracts_router)
    payload_base = {
        "symbol": "AAPL", "direction": "Bullish", "stock_price": 185.0,
        "strike": 190.0, "dte": 30, "premium": 2.50, "delta": 0.45, "spread": 0.10,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r_default = await ac.post("/api/contracts/recompute-plan", json=payload_base)
        r_override = await ac.post("/api/contracts/recompute-plan", json={
            **payload_base, "rr_target_r_multiple": 3,
        })
    assert r_default.status_code == 200
    assert r_override.status_code == 200
    default_target = r_default.json()["exit"]["target"]
    override_target = r_override.json()["exit"]["target"]
    assert override_target > default_target
    assert round(override_target, 2) == round(185.0 * (1 + 3 * .03), 2)


# ── NO-LIVE-QUOTE (plan 3c, test T7): Step 6 labels, the quote reports ───────

async def _get_contracts(chain):
    app = _build_test_app()
    with (
        patch("app.routers.contracts.fetch_option_chain_async", new_callable=AsyncMock, return_value=chain),
        patch("app.routers.contracts.fetch_price_async", new_callable=AsyncMock, return_value=190.0),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/contracts?symbol=AAPL&right=C&stock_score=70")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_step6_contracts_label_a_non_live_row_caution_with_no_live_quote():
    """/api/contracts grades in LABEL mode: the off-hours row comes back listed,
    capped at CAUTION and flagged, where the scan's reject mode would drop it."""
    live_row = {**SAMPLE_CHAIN[0], "quoteState": "live", "quoteLive": True, "quoteAgeS": 4.0}
    [live] = await _get_contracts([live_row])
    assert live["contractConfidence"] == "PASS"
    assert live["noLiveQuote"] is False
    assert live["quoteState"] is None

    closed_row = {**live_row, "quoteState": "session_closed", "quoteLive": False, "quoteAgeS": 61200.0}
    [closed] = await _get_contracts([closed_row])
    assert closed["contractConfidence"] == "CAUTION"
    assert closed["score"] == live["score"]
    assert closed["noLiveQuote"] is True
    assert closed["quoteState"] == "session_closed"
    assert "no_live_quote" in closed["explanation"]["soft_flags"]


@pytest.mark.asyncio
async def test_step6_contracts_pass_quote_mode_label():
    import app.routers.contracts as contracts_mod
    seen = []
    real = contracts_mod.validate_contract

    def _spy(*a, **k):
        seen.append(k.get("quote_mode"))
        return real(*a, **k)

    with patch("app.routers.contracts.validate_contract", _spy):
        await _get_contracts(SAMPLE_CHAIN)
    assert seen and set(seen) == {"label"}


@pytest.mark.asyncio
async def test_option_quote_returns_quote_live_and_state():
    app = _build_test_app()
    expiry = _future_expiry(35)
    row = {
        "price": 2.1, "delta": 0.45, "theta": -0.04, "ivRank": None, "iv": 30.0,
        "spread": 0.2, "volume": 500, "expiry": expiry, "strike": 190,
        "quoteState": "stale", "quoteLive": False, "quoteAgeS": 5400.0,
    }
    with patch("app.routers.contracts.fetch_contract_quote_async", new_callable=AsyncMock, return_value=row):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/api/quote/option?symbol=AAPL&strike=190&expiry={expiry}&right=C")
    assert r.status_code == 200, r.text
    assert r.json()["quoteLive"] is False
    assert r.json()["quoteState"] == "stale"

    with patch("app.routers.contracts.fetch_contract_quote_async", new_callable=AsyncMock,
               return_value={**row, "quoteState": "live", "quoteLive": True}):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/api/quote/option?symbol=AAPL&strike=190&expiry={expiry}&right=C")
    assert r.json()["quoteLive"] is True
    assert r.json()["quoteState"] == "live"

    # A row with no state (only a fixture) reports None, never a guess.
    bare = {k: v for k, v in row.items() if k not in ("quoteState", "quoteLive", "quoteAgeS")}
    with patch("app.routers.contracts.fetch_contract_quote_async", new_callable=AsyncMock, return_value=bare):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/api/quote/option?symbol=AAPL&strike=190&expiry={expiry}&right=C")
    assert r.json()["quoteLive"] is None
    assert r.json()["quoteState"] is None
