"""P0B B3: bearish arms/fires refuse; the arm carries the actual scan hold."""
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.routers.auto_trade as router_module
import app.services.auto_trader as at
from app.database import get_db
from app.data.ibkr_paper import OrderResult
from app.services.unvalidated import BEARISH_UNVALIDATED_MESSAGE


def _body(**overrides):
    return {
        "broker": "ibkr_paper", "symbol": "AAPL",
        "option_symbol": "AAPL|185|2026-12-18|C", "action": "BUY",
        "direction": "Bullish", "horizon": "Position", "hold_max_days": 185,
        "quantity": 1, "order_type": "LMT", "limit_price": 2.5,
        "entry_premium": 2.5, **overrides,
    }


def _legacy_bearish():
    body = _body(direction="Bearish", option_symbol="AAPL|185|2026-12-18|P")
    body.pop("hold_max_days")
    return at.ArmedStrategy(**body, conid=None)


@pytest.fixture
def env(monkeypatch):
    service = at.AutoTradeService()
    monkeypatch.setattr(router_module, "auto_trader", service)
    booking = AsyncMock(return_value={})
    monkeypatch.setattr(router_module, "book_fired_order", booking)
    market = Mock(return_value=True)
    sizing = Mock(side_effect=lambda strategy: strategy)
    regime = Mock()
    broker = Mock(return_value=OrderResult("fake", "Submitted", "ibkr_paper"))
    earnings = Mock(return_value=date.today() + timedelta(days=400))
    monkeypatch.setattr(at, "_market_is_open", market)
    monkeypatch.setattr(at, "_apply_vol_sizing", sizing)
    monkeypatch.setattr(at, "_apply_regime_gate", regime)
    monkeypatch.setattr(at, "execute_option_order", broker)
    monkeypatch.setattr(at, "_fetch_earnings_date", earnings)
    notify = AsyncMock(return_value=True)
    forget = Mock()
    monkeypatch.setattr("app.services.notifications.alert_notifier.notify_alert", notify)
    monkeypatch.setattr("app.services.notifications.alert_notifier.forget_alerts", forget)
    return SimpleNamespace(service=service, booking=booking, market=market, sizing=sizing, regime=regime,
                           broker=broker, earnings=earnings, notify=notify, forget=forget)


@pytest_asyncio.fixture
async def client(env):
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

    async def database():
        yield db

    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[get_db] = database
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_bearish_arm_refuses_with_policy_detail_and_leaves_unarmed(client, env):
    response = await client.post("/auto-trade/arm", json=_body(direction="Bearish"))
    assert response.status_code == 422
    assert response.json()["detail"] == BEARISH_UNVALIDATED_MESSAGE
    assert env.service.get_state().armed is False
    assert env.service.get_state().strategy is None
    env.broker.assert_not_called()


@pytest.mark.asyncio
async def test_bullish_arm_requires_hold_max_days(client, env):
    body = _body()
    body.pop("hold_max_days")
    response = await client.post("/auto-trade/arm", json=body)
    assert response.status_code == 422
    assert any(error["loc"] == ["body", "hold_max_days"] for error in response.json()["detail"])
    assert not env.service.get_state().armed


@pytest.mark.asyncio
@pytest.mark.parametrize("hold", [0, 185, 3650])
async def test_bullish_arm_stores_actual_hold(client, env, hold):
    response = await client.post("/auto-trade/arm", json=_body(hold_max_days=hold))
    assert response.status_code == 200, response.text
    assert env.service.get_state().strategy.hold_max_days == hold
    env.broker.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("hold", [-1, 3651])
async def test_arm_rejects_hold_outside_bounds(client, env, hold):
    response = await client.post("/auto-trade/arm", json=_body(hold_max_days=hold))
    assert response.status_code == 422
    assert any(error["loc"] == ["body", "hold_max_days"] for error in response.json()["detail"])
    assert not env.service.get_state().armed


def test_legacy_bearish_fire_disarms_records_refusal_before_sizing_or_broker(env):
    env.service.arm(_legacy_bearish())
    with pytest.raises(RuntimeError) as error:
        env.service.fire(attempt_id="bearish-before-deploy")
    assert type(error.value).__name__ == "UnvalidatedDirectionError"
    assert str(error.value) == BEARISH_UNVALIDATED_MESSAGE
    state = env.service.get_state()
    assert not state.armed and state.strategy is None
    assert len(state.history) == 1
    row = state.history[0]
    assert row["status"] == "unvalidated_blocked"
    assert row["attempt_id"] == "bearish-before-deploy"
    assert row["error"] == BEARISH_UNVALIDATED_MESSAGE
    assert row["premium_at_risk"] == 0.0 and row["order_id"] is None
    env.sizing.assert_not_called()
    env.regime.assert_not_called()
    env.broker.assert_not_called()
    env.earnings.assert_not_called()


@pytest.mark.asyncio
async def test_legacy_bearish_fire_maps_refusal_to_400(client, env):
    env.service.arm(_legacy_bearish())
    response = await client.post("/auto-trade/fire")
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == BEARISH_UNVALIDATED_MESSAGE
    assert env.service.get_state().history[-1]["status"] == "unvalidated_blocked"
    assert not env.service.get_state().armed
    env.booking.assert_not_called()
    env.sizing.assert_not_called()
    env.regime.assert_not_called()
    env.broker.assert_not_called()


def test_bearish_scan_trigger_delivers_its_own_discrete_refusal_alert(env):
    env.service.arm(_legacy_bearish())
    assert env.service.maybe_fire_on_scan() is None
    env.notify.assert_awaited_once()
    payload = env.notify.await_args.kwargs
    assert payload["alert_type"] == "AUTO_TRADE_UNVALIDATED"
    assert payload["symbol"] == "AAPL"
    assert BEARISH_UNVALIDATED_MESSAGE in payload["reason"]
    assert "Nothing was sent" in payload["reason"] and "disarmed" in payload["reason"]
    assert payload["rec_id"] == "auto-trade-unvalidated:AAPL"
    env.forget.assert_called_once()
    env.sizing.assert_not_called()
    env.regime.assert_not_called()
    env.broker.assert_not_called()


def test_closed_market_bearish_arm_is_consumed_and_refused_as_unvalidated(env):
    env.market.return_value = False
    env.service.arm(_legacy_bearish())
    with pytest.raises(RuntimeError) as error:
        env.service.fire(attempt_id="bearish-market-closed")
    assert type(error.value).__name__ == "UnvalidatedDirectionError"
    assert str(error.value) == BEARISH_UNVALIDATED_MESSAGE
    assert not env.service.get_state().armed
    assert env.service.get_state().history[-1]["status"] == "unvalidated_blocked"
    env.market.assert_not_called()
    env.broker.assert_not_called()
    env.sizing.assert_not_called()
    env.regime.assert_not_called()


def test_closed_market_bullish_arm_is_preserved_for_retry(env):
    env.market.return_value = False
    body = _body()
    body.pop("hold_max_days")
    strategy = at.ArmedStrategy(**body, conid=None)
    env.service.arm(strategy)
    with pytest.raises(at.ArmPreservedError):
        env.service.fire()
    assert env.service.get_state().strategy is strategy
    assert env.service.get_state().armed
    assert env.service.get_state().history == []
    env.broker.assert_not_called()
    env.sizing.assert_not_called()
