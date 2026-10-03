"""Audit round 2, R2-F2: the fire-time D5 cap check cannot be skipped by
omitting `entry_premium`.

Before: `ArmRequest.entry_premium` defaulted to 0.0 ("exposure check is
skipped if 0"), and `fire()` ran `_check_exposure` only when
`entry_premium > 0`. `AutoTradeService.arm()` already raised on a zero
premium, but as an unhandled ValueError (a 500), and the fire-side condition
meant any strategy that reached the armed slot with a zero premium went to the
broker unchecked -- and then could not be booked ("no entry premium was
armed"), so the live order was untracked too.

Ruling (R2-F2): REQUIRE it. `entry_premium` is required and `gt=0` on the
schema (a 422 naming the field, at arm), and `fire()` runs the cap check
whatever the premium says, refusing outright -- before any broker call -- a
strategy with no positive premium. Judging at max(entry_premium, limit) instead
would still fire an order the booking then refuses.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.data.ibkr_paper import OrderResult
from app.routers.auto_trade import router as auto_trade_router
from app.services import portfolio_risk as pr
from app.services.auto_trader import ArmedStrategy, AutoTradeService, auto_trader

CONTRACT = "AAPL|185|2026-12-18|C"


def _arm_body(**over) -> dict:
    body = {
        "broker": "tastytrade_paper", "symbol": "AAPL", "option_symbol": CONTRACT,
        "action": "BUY", "direction": "Bullish", "horizon": "Swing",
        "quantity": 1, "order_type": "LMT", "limit_price": 2.50, "entry_premium": 2.50,
    }
    body.update(over)
    return {k: v for k, v in body.items() if v is not ...}


async def _post_arm(body):
    app = FastAPI()
    app.include_router(auto_trade_router)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            return await c.post("/auto-trade/arm", json=body)
    finally:
        auto_trader.disarm()


# ── at arm: a 422 naming the field, nothing armed ───────────────────────────

@pytest.mark.asyncio
async def test_an_arm_without_entry_premium_is_a_422_naming_it():
    resp = await _post_arm(_arm_body(entry_premium=...))
    assert resp.status_code == 422, resp.text
    assert "entry_premium" in resp.text
    assert auto_trader.get_state().armed is False


@pytest.mark.asyncio
@pytest.mark.parametrize("premium", [0, 0.0, -1.5])
async def test_an_arm_with_a_non_positive_entry_premium_is_a_422(premium):
    resp = await _post_arm(_arm_body(entry_premium=premium))
    assert resp.status_code == 422, resp.text
    assert "entry_premium" in resp.text
    assert auto_trader.get_state().armed is False


@pytest.mark.asyncio
@pytest.mark.parametrize("order_type", ["MKT", "LMT"])
@pytest.mark.parametrize("token", ["Infinity", "NaN"])
async def test_r5f1_a_non_finite_limit_price_is_a_422(order_type, token):
    """Audit round 5, R5-F1: the JSON parser accepts `Infinity`/`NaN`, and the
    arm schema let a non-finite limit through; on a MKT arm it reached the
    broker and then failed the booking's schema (`allow_inf_nan=False` there)."""
    import json as _json
    raw = _json.dumps(_arm_body(order_type=order_type, limit_price="__LIMIT__"))
    raw = raw.replace('"__LIMIT__"', token)
    # The app's own 422 handler (main.py): FastAPI's default one echoes the
    # non-finite input and its encoder then raises, turning the refusal into a 500.
    from fastapi.exceptions import RequestValidationError
    from app.main import request_validation_handler
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.include_router(auto_trade_router)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post("/auto-trade/arm", content=raw,
                                headers={"content-type": "application/json"})
        assert resp.status_code == 422, resp.text
        assert "limit_price" in resp.text
        assert auto_trader.get_state().armed is False
    finally:
        auto_trader.disarm()


@pytest.mark.asyncio
async def test_a_positive_entry_premium_still_arms():
    app = FastAPI()
    app.include_router(auto_trade_router)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post("/auto-trade/arm", json=_arm_body())
            assert resp.status_code == 200, resp.text
            assert auto_trader.get_state().armed is True
    finally:
        auto_trader.disarm()


# ── at fire: no premium can skip the cap ────────────────────────────────────

@pytest.fixture
def _cfg(monkeypatch):
    cfg = {
        "portfolio": {"max_total_exposure_pct": 0.25, "max_concurrent_positions": 10,
                      "max_daily_recommendations": 5, "max_same_symbol_positions": 1,
                      "min_portfolio_value": 5000.0, "max_single_position_pct": 0.05,
                      "max_loss_per_trade_pct": 0.0375},
        "sizing": {"max_contracts_per_trade": 50},
    }
    monkeypatch.setattr(pr, "_load_config", lambda: cfg)


def _slipped_in(**over) -> ArmedStrategy:
    """A strategy in the armed slot WITHOUT going through `arm()` -- the only
    way a non-positive premium can get there now, and exactly the state the old
    `entry_premium > 0` condition let past the cap."""
    body = dict(
        broker="ibkr_paper", symbol="AAPL", option_symbol=CONTRACT,
        action="BUY", direction="Bullish", horizon="Swing", quantity=1,
        order_type="LMT", limit_price=40.0, conid=None,
        entry_premium=0.0, portfolio_value=100_000.0,
    )
    body.update(over)
    return ArmedStrategy(**body)


@pytest.mark.parametrize("over", [
    {},                                                     # LMT at 40: $4,000 > $3,750
    {"order_type": "MKT", "limit_price": None},              # nothing to judge at all
    {"limit_price": 1.00},                                  # would fit the cap at the limit
])
def test_a_zero_premium_strategy_cannot_fire(mocker, _cfg, over):
    svc = AutoTradeService()
    mocker.patch("app.services.auto_trader._market_is_open", return_value=True)
    mocker.patch("app.services.auto_trader._apply_vol_sizing", lambda s: s)
    execute = mocker.patch(
        "app.services.auto_trader.execute_option_order",
        return_value=OrderResult(order_id="x", status="PreSubmitted", broker="ibkr_paper"),
    )
    with svc._lock:
        svc._state.armed = True
        svc._state.strategy = _slipped_in(**over)
    with pytest.raises(RuntimeError, match="entry premium"):
        svc.fire(portfolio_snapshot=[])
    execute.assert_not_called()
    [row] = svc.get_state().history
    assert row["status"] == "cap_blocked" and row["order_id"] is None
    assert svc.get_state().armed is False
