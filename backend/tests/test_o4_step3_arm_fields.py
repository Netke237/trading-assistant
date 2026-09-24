# backend/tests/test_o4_step3_arm_fields.py
"""O4 step 3 -- the arm request carries the ten booking fields.

Plan: docs/superpowers/plans/2026-09-24-o4-step-3-arm-fields-replan.md (§5).

The ten fields a fired auto-trade will need to book its PortfolioPosition
(step 4) travel `ArmRequest -> ArmedStrategy(**req.model_dump())`. NOTHING
READS THEM YET: these tests pin the carry, the bounds, the name contract with
PortfolioPositionCreate, the vol-sizing carry, and the one consequence of
putting lists/dicts on a frozen dataclass (it stops being hashable).
"""
from __future__ import annotations

import dataclasses
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.database import Base, get_db
from app.routers.auto_trade import ArmRequest, router as auto_trade_router
from app.schemas import PortfolioPositionCreate
from app.services.auto_trader import ArmedStrategy, auto_trader

# Distinct, non-default values: a stock-price stop well away from the stock
# price and the premium, so a field landing in the wrong slot shows up.
TEN = {
    "stop":                181.25,
    "stop_is_user_set":    True,
    "scan_stock_price":    197.50,
    "structural_stop":     179.40,
    "exit_plan":           {"mode": "targets", "trail": False},
    "targets":             [{"price": 205.0, "pct": 0.5}, {"price": 212.0, "pct": 0.5}],
    "dte_total":           45,
    "premium_stop_dollar": 1.35,
    "max_loss_override":   {"dollars": 250.0, "reason": "earnings week"},
    "trade_card_snapshot": {"symbol": "AAPL", "score": 81},
}
OPTIONAL_NINE = [k for k in TEN if k != "targets"]


def _arm_body(**extra) -> dict:
    base = {
        "broker": "tastytrade_paper", "symbol": "AAPL",
        "option_symbol": "AAPL260620C00185000",
        "action": "BUY", "direction": "Bullish", "horizon": "Swing",
        "quantity": 1, "order_type": "LMT", "limit_price": 2.50, "entry_premium": 2.50,
    }
    base.update(extra)
    return base


def _strategy(**extra) -> ArmedStrategy:
    base = dict(
        broker="ibkr_paper", symbol="AAPL", option_symbol="AAPL260620C00185000",
        action="BUY", direction="Bullish", quantity=1, order_type="LMT",
        limit_price=2.50, conid=None, entry_premium=2.50,
    )
    base.update(extra)
    return ArmedStrategy(**base)


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Always disarms on the way out: `auto_trader` is a module singleton."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 connect_args={"check_same_thread": False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _get_db():
        async with Session() as s:
            yield s

    test_app = FastAPI()
    test_app.include_router(auto_trade_router)
    test_app.dependency_overrides[get_db] = _get_db
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://t") as c:
        try:
            yield c
        finally:
            auto_trader.disarm()
            await engine.dispose()


# 1 ────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_all_ten_fields_land_on_the_armed_strategy(client):
    """Asserted on the dataclass, not the response: the response echoes nothing,
    and a silently dropped field would still return 200."""
    resp = await client.post("/auto-trade/arm", json=_arm_body(**TEN))
    assert resp.status_code == 200, resp.text
    armed = auto_trader.get_state().strategy
    assert armed is not None
    for name, value in TEN.items():
        assert getattr(armed, name) == value, name


# 2 ────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_body_without_the_ten_arms_with_the_defaults(client):
    """Today's client sends none of the ten; omitted is a real state."""
    resp = await client.post("/auto-trade/arm", json=_arm_body())
    assert resp.status_code == 200, resp.text
    armed = auto_trader.get_state().strategy
    assert armed is not None
    for name in OPTIONAL_NINE:
        assert getattr(armed, name) is None, name
    assert armed.targets == []


# 3 ────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize("name,bad", [
    ("stop", 0), ("stop", -1), ("scan_stock_price", 0), ("structural_stop", 0),
    ("dte_total", -1), ("premium_stop_dollar", 0),
])
async def test_each_bound_refuses_at_arm_and_only_the_bound(client, name, bad):
    body = _arm_body(**TEN)
    body[name] = bad
    resp = await client.post("/auto-trade/arm", json=body)
    assert resp.status_code == 422, resp.text
    assert name in resp.text
    assert auto_trader.get_state().strategy is None, "a 422 must arm nothing"

    # The same body without the field arms, so the 422 was the bound and not
    # something else in the body.
    del body[name]
    ok = await client.post("/auto-trade/arm", json=body)
    assert ok.status_code == 200, ok.text


# 4 ────────────────────────────────────────────────────────────────────────
def test_every_wire_field_has_a_dataclass_field_of_the_same_name():
    """So `ArmedStrategy(**req.model_dump())` cannot TypeError."""
    dc_names = {f.name for f in dataclasses.fields(ArmedStrategy)}
    missing = set(ArmRequest.model_fields) - dc_names
    assert not missing, f"ArmRequest fields with no ArmedStrategy field: {missing}"


@pytest.mark.parametrize("name", list(TEN))
def test_each_of_the_ten_has_a_counterpart_on_the_create_schema(name):
    """The mapping step 4 writes (by alias) has a target on the other side."""
    assert any(
        n == name or f.alias == name
        for n, f in PortfolioPositionCreate.model_fields.items()
    ), f"{name} has no field or alias on PortfolioPositionCreate"


# 5 ────────────────────────────────────────────────────────────────────────
def test_vol_sizing_carries_the_ten_across_the_resize(mocker):
    """Same stubs as test_phase_g_arm_pick.py's resize test: `_dc_replace`
    carries every field, so a resized strategy keeps all ten."""
    from app.services import auto_trader as at
    mocker.patch.object(at, "_load_scoring_config", return_value={
        "enabled": True, "min_mult": 0.5, "full_conviction_pct": 40,
    })
    mocker.patch.object(at, "_measure_trade_regime", return_value=(0, "Fragile"))

    resized = at._apply_vol_sizing(_strategy(quantity=4, **TEN))
    assert resized.quantity != 4, "the fixture must actually exercise the resize branch"
    for name, value in TEN.items():
        assert getattr(resized, name) == value, name


# 6 ────────────────────────────────────────────────────────────────────────
def test_targets_default_is_not_shared_between_instances():
    a, b = _strategy(), _strategy()
    assert a.targets == [] and b.targets == []
    assert a.targets is not b.targets


# 7 ────────────────────────────────────────────────────────────────────────
def test_armed_strategy_is_unhashable_by_design():
    """frozen=True + eq=True derives __hash__ from every field, and `targets`
    plus the four dicts are unhashable. Nothing hashes an ArmedStrategy today
    (fire() compares by identity). If this goes red because someone made it
    hashable, check that `==` semantics did not change for existing callers;
    if you want one in a set(), key it by something else."""
    with pytest.raises(TypeError):
        hash(_strategy(**TEN))
    # Even with every container empty/None: the default `targets` is a list.
    with pytest.raises(TypeError):
        hash(_strategy())
