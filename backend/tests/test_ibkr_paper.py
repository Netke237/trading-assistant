import pytest
import respx
import httpx
from app.data.ibkr_paper import IbkrPaperAdapter, BrokerOrder, OrderResult


def _adapter():
    return IbkrPaperAdapter(
        base_url="https://localhost:7499/v1/api",
        account_id="DU123456",
    )


def test_adapter_builds_order_payload_stock():
    adapter = _adapter()
    order = BrokerOrder(
        symbol="AAPL", action="BUY", effect="OPEN", quantity=10,
        order_type="LMT", limit_price=185.0, tif="DAY"
    )
    payload = adapter._build_payload(order)
    assert payload["orders"][0]["side"] == "BUY"
    assert payload["orders"][0]["quantity"] == 10
    assert payload["orders"][0]["price"] == 185.0
    assert payload["orders"][0]["orderType"] == "LMT"
    assert payload["orders"][0]["symbol"] == "AAPL"


@respx.mock
def test_adapter_place_order_success():
    respx.get("https://localhost:7499/v1/api/iserver/auth/status").mock(
        return_value=httpx.Response(200, json={"authenticated": True})
    )
    respx.post("https://localhost:7499/v1/api/tickle").mock(
        return_value=httpx.Response(200, json={})
    )
    respx.post("https://localhost:7499/v1/api/iserver/account/DU123456/orders").mock(
        return_value=httpx.Response(200, json=[{"order_id": "987654", "order_status": "PreSubmitted"}])
    )
    from app.data import ibkr_paper
    ibkr_paper._auth_cache = None  # avoid cross-test cache leakage
    adapter = _adapter()
    order = BrokerOrder(symbol="AAPL", action="BUY", effect="OPEN", quantity=5,
                        order_type="MKT", limit_price=None, tif="DAY")
    result = adapter.place_order(order)
    assert result.order_id == "987654"
    assert result.status == "PreSubmitted"
    assert result.broker == "ibkr_paper"


@respx.mock
def test_adapter_place_order_failure_raises():
    respx.get("https://localhost:7499/v1/api/iserver/auth/status").mock(
        return_value=httpx.Response(200, json={"authenticated": True})
    )
    respx.post("https://localhost:7499/v1/api/tickle").mock(
        return_value=httpx.Response(200, json={})
    )
    respx.post("https://localhost:7499/v1/api/iserver/account/DU123456/orders").mock(
        return_value=httpx.Response(401, json={"error": "Unauthorized"})
    )
    from app.data import ibkr_paper
    ibkr_paper._auth_cache = None
    adapter = _adapter()
    order = BrokerOrder(symbol="AAPL", action="BUY", effect="OPEN", quantity=1,
                        order_type="MKT", limit_price=None, tif="DAY")
    with pytest.raises(RuntimeError, match="IBKR paper order failed"):
        adapter.place_order(order)


@respx.mock
def test_adapter_place_order_raises_when_not_authenticated():
    respx.get("https://localhost:7499/v1/api/iserver/auth/status").mock(
        return_value=httpx.Response(200, json={"authenticated": False})
    )
    from app.data import ibkr_paper
    ibkr_paper._auth_cache = None
    adapter = _adapter()
    order = BrokerOrder(symbol="AAPL", action="BUY", effect="OPEN", quantity=1,
                        order_type="MKT", limit_price=None, tif="DAY")
    with pytest.raises(RuntimeError, match="gateway session is not authenticated"):
        adapter.place_order(order)
