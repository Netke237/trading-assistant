import pytest
import respx
import httpx
from app.data.tradier_paper import TradierPaperAdapter, BrokerOrder, OrderResult


def _adapter():
    return TradierPaperAdapter(token="sandbox_tok", account_id="VA12345678")


def test_adapter_builds_equity_params():
    adapter = _adapter()
    order = BrokerOrder(
        symbol="NVDA", action="BUY", quantity=20,
        order_type="LMT", limit_price=130.0, tif="DAY"
    )
    params = adapter._build_params(order)
    assert params["class"] == "equity"
    assert params["symbol"] == "NVDA"
    assert params["side"] == "buy"
    assert params["quantity"] == "20"
    assert params["type"] == "limit"
    assert params["price"] == "130.0"


def test_adapter_builds_option_params():
    adapter = _adapter()
    order = BrokerOrder(
        symbol="NVDA", action="BUY", quantity=1,
        order_type="LMT", limit_price=3.50, tif="DAY",
        option_symbol="NVDA260620C00130000",
    )
    params = adapter._build_params(order)
    assert params["class"] == "option"
    assert params["option_symbol"] == "NVDA260620C00130000"
    # Tradier rejects plain "buy"/"sell" on option-class orders — entries open a position.
    assert params["side"] == "buy_to_open"


def test_option_sell_uses_sell_to_open():
    adapter = _adapter()
    order = BrokerOrder(
        symbol="NVDA", action="SELL", quantity=1,
        order_type="LMT", limit_price=3.50, tif="DAY",
        option_symbol="NVDA260620C00130000",
    )
    params = adapter._build_params(order)
    assert params["side"] == "sell_to_open"


@respx.mock
def test_place_order_success():
    respx.post("https://sandbox.tradier.com/v1/accounts/VA12345678/orders").mock(
        return_value=httpx.Response(200, json={"order": {"id": 111222, "status": "ok", "partner_id": "0"}})
    )
    adapter = _adapter()
    order = BrokerOrder(symbol="NVDA", action="BUY", quantity=5,
                        order_type="MKT", limit_price=None, tif="DAY")
    result = adapter.place_order(order)
    assert result.order_id == "111222"
    assert result.broker == "tradier_paper"


@respx.mock
def test_place_order_failure():
    respx.post("https://sandbox.tradier.com/v1/accounts/VA12345678/orders").mock(
        return_value=httpx.Response(400, json={"fault": {"faultstring": "Invalid token"}})
    )
    adapter = _adapter()
    order = BrokerOrder(symbol="NVDA", action="BUY", quantity=1,
                        order_type="MKT", limit_price=None, tif="DAY")
    with pytest.raises(RuntimeError, match="Tradier paper order failed"):
        adapter.place_order(order)


# ── OCC conversion in _build_params ──────────────────────────────────────────

def test_build_params_converts_pipe_to_occ():
    """Adapter converts Bamendjou pipe id to OCC when building option params."""
    adapter = _adapter()
    order = BrokerOrder(
        symbol="AAPL", action="BUY", quantity=1,
        order_type="LMT", limit_price=2.50, tif="DAY",
        option_symbol="AAPL|185|2025-05-16|C",   # pipe format in
    )
    params = adapter._build_params(order)
    assert params["option_symbol"] == "AAPL250516C00185000"  # OCC out
    assert params["class"] == "option"


def test_build_params_passthrough_occ():
    """Adapter passes already-OCC symbols through unchanged."""
    adapter = _adapter()
    order = BrokerOrder(
        symbol="AAPL", action="BUY", quantity=1,
        order_type="LMT", limit_price=2.50, tif="DAY",
        option_symbol="AAPL250516C00185000",   # already OCC
    )
    params = adapter._build_params(order)
    assert params["option_symbol"] == "AAPL250516C00185000"
