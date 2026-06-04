import pytest
from app.services.auto_trader import AutoTradeService, ArmedStrategy, AutoTradeState


def test_service_starts_unarmed():
    svc = AutoTradeService()
    state = svc.get_state()
    assert state.armed is False
    assert state.strategy is None


def test_arm_sets_state():
    svc = AutoTradeService()
    armed = ArmedStrategy(
        broker="ibkr_paper",
        symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY",
        quantity=1,
        order_type="LMT",
        limit_price=2.50,
        conid=None,
    )
    svc.arm(armed)
    state = svc.get_state()
    assert state.armed is True
    assert state.strategy.symbol == "AAPL"


def test_disarm_clears_state():
    svc = AutoTradeService()
    armed = ArmedStrategy(
        broker="tradier_paper", symbol="NVDA",
        option_symbol="NVDA260620C00130000",
        action="BUY", quantity=2, order_type="MKT",
        limit_price=None, conid=None,
    )
    svc.arm(armed)
    svc.disarm()
    assert svc.get_state().armed is False


def test_fire_executes_and_disarms(mocker):
    from app.data.ibkr_paper import OrderResult
    svc = AutoTradeService()
    mock_result = OrderResult(order_id="999", status="PreSubmitted", broker="ibkr_paper")
    mock_execute = mocker.patch(
        "app.services.auto_trader.execute_option_order",
        return_value=mock_result
    )
    armed = ArmedStrategy(
        broker="ibkr_paper", symbol="AAPL",
        option_symbol="AAPL260620C00185000",
        action="BUY", quantity=1, order_type="LMT",
        limit_price=2.50, conid=None,
    )
    svc.arm(armed)
    result = svc.fire()
    assert result.order_id == "999"
    mock_execute.assert_called_once()
    assert svc.get_state().armed is False
    assert len(svc.get_state().history) == 1


def test_fire_when_unarmed_raises():
    svc = AutoTradeService()
    with pytest.raises(RuntimeError, match="not armed"):
        svc.fire()
