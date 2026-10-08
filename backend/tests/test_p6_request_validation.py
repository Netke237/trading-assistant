# backend/tests/test_p6_request_validation.py
"""P6 unit A -- request validation.

Plan: docs/superpowers/plans/2026-09-30-p6-validation-method-pick-hygiene-plan.md.

  A1  entryPrice / picked prices / resolvedTpPrice refuse NaN and Infinity
      (`gt=0` alone accepted Infinity, and POST committed the row before the
      response failed to encode it).
  A2  the 422 for a non-finite input is a 422, not a 500 (main.py handler).
  A3  pickedAt / picked_at must be a timezone-aware ISO timestamp -- on BOTH the
      create schema and ArmRequest, because a fired trade books through the
      create schema after its order is placed.
  A4  PATCH writes activeTpMethod and resolvedTpPrice together or not at all.
  A5  ArmRequest forbids unknown keys.
  A6  _rr_ratio_for_row: closest row wins; a tie between different ratios is
      unmappable.
"""
from __future__ import annotations

from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.database import Base, get_db
from app.main import request_validation_handler
from app.routers.auto_trade import ArmRequest, router as auto_trade_router
from app.routers.portfolio import router as portfolio_router
from app.schemas import PortfolioPositionCreate
from app.services.auto_trader import auto_trader
from app.services.picked_method import _rr_ratio_for_row

_CREATE = {
    "rec_id": "REC-P6", "symbol": "AAPL", "contract": "AAPL|185|2026-12-18|C",
    "direction": "Bullish", "entry_date": "2026-09-30", "entry_price": 2.5,
}


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Portfolio + auto-trade routers on one app WITH the production 422
    handler, over an in-memory db. Disarms on the way out (auto_trader is a
    module singleton shared with other files)."""
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
    test_app.include_router(auto_trade_router)
    test_app.add_exception_handler(RequestValidationError, request_validation_handler)
    test_app.dependency_overrides[get_db] = _get_db
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://t") as c:
        try:
            yield c
        finally:
            auto_trader.disarm()
    await engine.dispose()


def _raw_create(entry_price_token: str) -> str:
    """A create body with a bare JSON token for entry_price -- NaN/Infinity
    cannot be produced by json.dumps(allow_nan=False) or JSON.stringify, only
    by a hand-written body, which is exactly the caller that reaches this."""
    return (
        '{"rec_id":"REC-RAW","symbol":"AAPL","contract":"AAPL|185|2026-12-18|C",'
        '"direction":"Bullish","entry_date":"2026-09-30","entry_price":%s}' % entry_price_token
    )


async def _add(client, rec="REC-P6"):
    with patch("app.routers.portfolio.fetch_contract_quote_async", new=AsyncMock(return_value=None)):
        r = await client.post("/api/portfolio", json={**_CREATE, "rec_id": rec})
    assert r.status_code == 201, r.text


# ── A1 + A2: non-finite prices ────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
async def test_a_non_finite_entry_price_is_a_422_naming_the_field_and_nothing_is_stored(client, token):
    with patch("app.routers.portfolio.fetch_contract_quote_async", new=AsyncMock(return_value=None)):
        r = await client.post("/api/portfolio", content=_raw_create(token),
                              headers={"content-type": "application/json"})
    assert r.status_code == 422, r.text
    locs = [e["loc"] for e in r.json()["detail"]]
    assert any(loc[-1] in ("entry_price", "entryPrice") for loc in locs), locs
    listed = await client.get("/api/portfolio")
    assert all(p["recId"] != "REC-RAW" for p in listed.json())


@pytest.mark.parametrize("field", ["picked_row_stock_price", "picked_row_option_price"])
def test_the_create_schema_refuses_an_infinite_picked_price(field):
    with pytest.raises(ValidationError):
        PortfolioPositionCreate(**_CREATE, **{field: float("inf")})


@pytest.mark.parametrize("field", ["picked_row_stock_price", "picked_row_option_price"])
def test_arm_refuses_an_infinite_picked_price_the_booking_would_refuse(field):
    body = _arm_body(**{field: float("inf")})
    with pytest.raises(ValidationError):
        ArmRequest(**body)


def test_the_422_body_for_an_ordinary_error_is_what_fastapi_would_have_sent():
    """A2 changes ONLY non-finite values: a missing-field 422 is identical to
    FastAPI's default handler's, which lib/api.ts apiError parses."""
    from fastapi.exception_handlers import request_validation_exception_handler

    def _app(handler):
        a = FastAPI()
        a.include_router(portfolio_router)
        a.add_exception_handler(RequestValidationError, handler)
        return a

    body = {k: v for k, v in _CREATE.items() if k != "symbol"}
    ours = TestClient(_app(request_validation_handler)).post("/api/portfolio", json=body)
    default = TestClient(_app(request_validation_exception_handler)).post("/api/portfolio", json=body)
    assert ours.status_code == default.status_code == 422
    assert ours.json() == default.json()


def test_the_production_app_carries_the_handler():
    from app.main import app
    assert app.exception_handlers[RequestValidationError] is request_validation_handler


# ── A3: pickedAt ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [
    "2026-09-30T12:00:00.000Z",          # what new Date().toISOString() emits
    "2026-09-30T12:00:00Z",
    "2026-09-30T08:00:00-04:00",
])
def test_an_aware_iso_picked_at_is_accepted_and_stored_as_sent(value):
    m = PortfolioPositionCreate(**_CREATE, picked_at=value)
    assert m.pickedAt == value
    assert ArmRequest(**_arm_body(picked_at=value)).picked_at == value


@pytest.mark.parametrize("value", [
    "yesterday",
    "2026-09-30T12:00:00",               # naive: cannot be aged against a clock
    "2026-09-30T12:00:00Z" + "x" * 64,   # over the length cap
    "",
])
def test_a_bad_picked_at_is_refused_on_both_schemas(value):
    with pytest.raises(ValidationError):
        PortfolioPositionCreate(**_CREATE, picked_at=value)
    with pytest.raises(ValidationError):
        ArmRequest(**_arm_body(picked_at=value))


def test_a_null_picked_at_is_still_a_real_state():
    assert PortfolioPositionCreate(**_CREATE, picked_at=None).pickedAt is None
    assert ArmRequest(**_arm_body(picked_at=None)).picked_at is None


# ── A4: the method/price pair on PATCH ───────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("patch_body", [
    {"resolvedTpPrice": 210.5},
    {"activeTpMethod": "monte_carlo"},
    {"activeTpMethod": None, "resolvedTpPrice": 210.5},
    {"activeTpMethod": "monte_carlo", "resolvedTpPrice": -50},
    {"activeTpMethod": "exit_plan_2r", "resolvedTpPrice": None},
    {"activeTpMethod": "monte_carlo", "resolvedTpPrice": 0, "stop": 170.0},
])
async def test_a_half_or_unusable_pair_is_refused_and_nothing_is_written(client, patch_body):
    await _add(client, rec="REC-PAIR")
    before = (await client.get("/api/portfolio")).json()
    r = await client.patch("/api/portfolio/REC-PAIR", json=patch_body)
    assert r.status_code == 422, r.text
    after = (await client.get("/api/portfolio")).json()
    assert after == before


@pytest.mark.asyncio
async def test_what_tpMethodPatch_sends_for_the_ladder_is_accepted(client):
    """EditDrawer's tpMethodPatch('ladder', ...) sends a null price."""
    await _add(client, rec="REC-LADDER")
    r = await client.patch("/api/portfolio/REC-LADDER", json={
        "activeTpMethod": "ladder", "resolvedTpPrice": None,
        "resolvedTpUpdatedAt": "2026-09-30T12:00:00+00:00",
    })
    assert r.status_code == 200, r.text
    assert r.json()["activeTpMethod"] == "ladder"
    assert r.json()["resolvedTpPrice"] is None


@pytest.mark.asyncio
async def test_an_infinite_resolved_tp_price_is_refused(client):
    await _add(client, rec="REC-INFTP")
    r = await client.patch(
        "/api/portfolio/REC-INFTP",
        content='{"activeTpMethod":"monte_carlo","resolvedTpPrice":Infinity}',
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 422, r.text


# ── A5: ArmRequest forbids unknown keys ──────────────────────────────────────

def _arm_body(**extra) -> dict:
    base = {
        "broker": "tastytrade_paper", "symbol": "AAPL",
        "option_symbol": "AAPL260620C00185000",
        "action": "BUY", "direction": "Bullish", "horizon": "Swing", "hold_max_days": 15, "quantity": 1,
        "order_type": "LMT", "limit_price": 2.50, "entry_premium": 2.50,
    }
    base.update(extra)
    return base


@pytest.mark.asyncio
async def test_a_camel_case_pick_key_is_a_422_not_a_silent_drop(client):
    r = await client.post("/auto-trade/arm", json=_arm_body(pickedMethod="monte_carlo"))
    assert r.status_code == 422, r.text
    assert "pickedMethod" in r.text
    assert auto_trader.get_state().armed is False


@pytest.mark.asyncio
async def test_a_snake_case_pick_still_arms(client):
    r = await client.post("/auto-trade/arm", json=_arm_body(
        picked_method="monte_carlo", picked_row_stock_price=197.5,
        picked_row_option_price=6.24, picked_stop_basis="premium",
        picked_at="2026-09-30T12:00:00.000Z",
    ))
    assert r.status_code == 200, r.text
    assert auto_trader.get_state().strategy.picked_method == "monte_carlo"


# ── A6: closest row wins, a tie is unmappable ────────────────────────────────

def _plan(*rows):
    return {"targets": [{"price": p, "rrRatio": r} for r, p in rows]}


def test_the_closest_row_wins_not_the_first_within_tolerance():
    # The entry's reproduction: 197.502 picked, 3.0R listed first at 197.50.
    assert _rr_ratio_for_row(_plan((3.0, 197.50), (2.0, 197.502)), 197.502) == 2.0


def test_a_distance_tie_between_different_ratios_is_unmappable():
    assert _rr_ratio_for_row(_plan((3.0, 197.50), (2.0, 197.50)), 197.50) is None


def test_a_distance_tie_between_equal_ratios_is_not_ambiguous():
    assert _rr_ratio_for_row(_plan((2.0, 197.50), (2.0, 197.50)), 197.50) == 2.0


def test_no_row_within_tolerance_is_still_unmappable():
    assert _rr_ratio_for_row(_plan((2.0, 197.50)), 199.0) is None
