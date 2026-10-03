"""Audit round 1, F1: the D5 premium cap is judged at the price the order can
actually fill at, not the mid.

LMT  -> max(mid, limit)
MKT  -> the ask when known, else mid + half the spread when the spread is
        known, else the mid
none -> the mid (no order is placed: a tracked basket row)

The auditor's example: account 100k, live mid $3.00, limit typed at $3.60,
12 contracts. Judged at the mid that is $3,600 (3.6%, under the 3.75% cap);
judged at the limit it is $4,320 (4.32%), over it.
"""
from __future__ import annotations

from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.database import Base, get_db
from app.routers.auto_trade import ArmRequest
from app.routers.portfolio import router as portfolio_router
from app.services import portfolio_risk as pr
from app.services.auto_trader import ArmedStrategy, AutoTradeService

CONTRACT = "AAPL|185|2026-12-18|C"


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    cfg = {
        "portfolio": {"max_total_exposure_pct": 0.25, "max_concurrent_positions": 10,
                      "max_daily_recommendations": 5, "max_same_symbol_positions": 1,
                      "min_portfolio_value": 5000.0, "max_single_position_pct": 0.05,
                      "max_loss_per_trade_pct": 0.0375},
        # 50, not the shipped 5: this file tests the premium cap, not the
        # contract cap, and 12 contracts must reach the premium cap.
        "sizing": {"max_contracts_per_trade": 50},
    }
    monkeypatch.setattr(pr, "_load_config", lambda: cfg)


# ── The pure basis ──────────────────────────────────────────────────────────

def test_limit_above_mid_is_judged_at_the_limit():
    assert pr.premium_cap_basis(3.00, "LMT", 3.60) == pytest.approx(3.60)


def test_limit_below_mid_is_judged_at_the_mid():
    assert pr.premium_cap_basis(3.00, "LMT", 2.80) == pytest.approx(3.00)


def test_market_uses_the_ask_when_known():
    assert pr.premium_cap_basis(3.00, "MKT", None, ask=3.25, spread=0.40) == pytest.approx(3.25)


def test_market_without_ask_uses_mid_plus_half_spread():
    assert pr.premium_cap_basis(3.00, "MKT", None, spread=0.40) == pytest.approx(3.20)


def test_market_without_ask_or_spread_falls_back_to_mid():
    assert pr.premium_cap_basis(3.00, "MKT", None) == pytest.approx(3.00)


def test_no_order_is_judged_at_the_mid():
    assert pr.premium_cap_basis(3.00, None, 3.60) == pytest.approx(3.00)


def test_auditor_example_at_the_basis_is_not_approved_at_twelve():
    basis = pr.premium_cap_basis(3.00, "LMT", 3.60)
    r = pr.check_position_risk("AAPL", CONTRACT, 12, basis, basis, [], 100_000)
    assert "size_reduced_to_fit_exposure_limit" in r.reasons
    assert r.adjusted_size == 10          # 10 x 360 = 3,600 <= 3,750


# ── The auto-trade fire check ───────────────────────────────────────────────

def _strategy(**over) -> ArmedStrategy:
    body = {
        "broker": "ibkr_paper", "symbol": "AAPL", "option_symbol": CONTRACT,
        "action": "BUY", "direction": "Bullish", "horizon": "Swing",
        "quantity": 12, "order_type": "LMT", "limit_price": 3.60, "entry_premium": 3.00,
        "stop": 180.0, "conid": None,
    }
    body.update(over)
    return ArmedStrategy(**ArmRequest(**body).model_dump())


def test_fire_check_refuses_the_auditor_example():
    with pytest.raises(RuntimeError) as exc:
        AutoTradeService._check_exposure(_strategy(), [], 100_000.0)
    assert "re-arm with 10" in str(exc.value)


def test_fire_check_passes_when_the_limit_is_at_the_mid():
    AutoTradeService._check_exposure(_strategy(limit_price=3.00), [], 100_000.0)


# ── The direct send: POST /api/portfolio ────────────────────────────────────

@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 connect_args={"check_same_thread": False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _get_db():
        async with Session() as s:
            yield s

    test_app = FastAPI()
    test_app.include_router(portfolio_router)
    test_app.dependency_overrides[get_db] = _get_db
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://t") as c:
        yield c
    await engine.dispose()


def _body(**over) -> dict:
    body = {"recId": "REC-F1", "symbol": "AAPL", "contract": CONTRACT,
            "direction": "Bullish", "entryPrice": 3.00, "qty": 12, "entryDate": "2026-10-03",
            "stop": 170.0, "targets": [], "dteTotal": 70, "portfolioValue": 100_000}
    body.update(over)
    return body


_QUOTE = {"price": 3.00, "spread": 0.40, "delta": 0.5, "theta": -0.05, "ivRank": None}


async def _post(client, body):
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value=dict(_QUOTE))):
        return await client.post("/api/portfolio", json=body)


@pytest.mark.asyncio
async def test_direct_limit_send_is_resized_at_the_limit(client):
    r = await _post(client, _body(orderType="LMT", orderLimitPrice=3.60))
    assert r.status_code == 201, r.text
    assert r.json()["adjustedQty"] == 10
    # The STORED entry is still the live mid: the basis judges the cap only.
    assert r.json()["entryPrice"] == pytest.approx(3.00)


@pytest.mark.asyncio
async def test_direct_market_send_is_judged_at_mid_plus_half_spread(client):
    # 12 x 320 = 3,840 > 3,750 -> 11 x 320 = 3,520
    r = await _post(client, _body(orderType="MKT"))
    assert r.status_code == 201, r.text
    assert r.json()["adjustedQty"] == 11


@pytest.mark.asyncio
async def test_no_order_fields_keep_the_mid_basis(client):
    # A tracked basket row places no order: judged at the mid, 3,600 fits.
    r = await _post(client, _body())
    assert r.status_code == 201, r.text
    assert r.json().get("adjustedQty") is None


@pytest.mark.asyncio
async def test_one_contract_over_the_cap_at_the_limit_is_refused(client):
    # mid 30 fits one contract (3,000); a limit of 40 does not (4,000 > 3,750).
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value={**_QUOTE, "price": 30.0})):
        r = await client.post("/api/portfolio",
                              json=_body(qty=1, entryPrice=30.0, orderType="LMT", orderLimitPrice=40.0))
    assert r.status_code == 422, r.text
    assert "single_trade_exposure_too_high" in r.text


# ── The auto-trade booking (gates off) reports over-exposure on the same basis ─

def test_booking_body_carries_the_armed_order():
    from app.services import auto_trade_booking
    from app.services.auto_trader import FiredOrder
    body = auto_trade_booking._build_body(
        FiredOrder(result=None, strategy=_strategy(), attempt_id="A1"), "REC-AT-1",
    )
    assert body.orderType == "LMT"
    assert body.orderLimitPrice == pytest.approx(3.60)
