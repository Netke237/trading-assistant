import pytest
from unittest.mock import MagicMock
from app.services.broker_router import BrokerRouter
from app.data.ibkr_paper import BrokerOrder, OrderResult


def test_router_routes_to_ibkr_paper():
    mock_adapter = MagicMock()
    mock_adapter.place_order.return_value = OrderResult(
        order_id="ORD1", status="PreSubmitted", broker="ibkr_paper"
    )
    router = BrokerRouter(adapters={"ibkr_paper": mock_adapter})
    order = BrokerOrder(symbol="AAPL", action="BUY", quantity=10,
                        order_type="LMT", limit_price=185.0, tif="DAY")
    result = router.execute("ibkr_paper", order)
    assert result.broker == "ibkr_paper"
    mock_adapter.place_order.assert_called_once_with(order)


def test_router_routes_to_tradier_paper():
    mock_adapter = MagicMock()
    mock_adapter.place_order.return_value = OrderResult(
        order_id="222", status="ok", broker="tradier_paper"
    )
    router = BrokerRouter(adapters={"tradier_paper": mock_adapter})
    order = BrokerOrder(symbol="NVDA", action="BUY", quantity=5,
                        order_type="MKT", limit_price=None, tif="DAY")
    result = router.execute("tradier_paper", order)
    assert result.order_id == "222"


def test_router_raises_for_unknown_broker():
    router = BrokerRouter(adapters={})
    order = BrokerOrder(symbol="X", action="BUY", quantity=1,
                        order_type="MKT", limit_price=None, tif="DAY")
    with pytest.raises(ValueError, match="Unknown broker"):
        router.execute("nonexistent", order)


def test_router_raises_for_inactive_live():
    router = BrokerRouter(adapters={})
    order = BrokerOrder(symbol="X", action="BUY", quantity=1,
                        order_type="MKT", limit_price=None, tif="DAY")
    with pytest.raises(ValueError, match="live IBKR"):
        router.execute("ibkr_live", order)
