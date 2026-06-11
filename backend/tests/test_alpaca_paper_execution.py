"""Unit tests for AlpacaPaperAdapter — no real network calls."""
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.data.alpaca_paper_execution import AlpacaPaperAdapter
from app.data.ibkr_paper import BrokerOrder, OrderResult


def _alpaca_order_resp(order_id: str = "abc123", status: str = "accepted") -> httpx.Response:
    request = httpx.Request("POST", "https://paper-api.alpaca.markets/v2/orders")
    return httpx.Response(
        200,
        json={"id": order_id, "status": status, "symbol": "AAPL"},
        request=request,
    )


def test_place_market_order_returns_order_result():
    adapter = AlpacaPaperAdapter(key_id="key1", secret_key="secret1")
    order = BrokerOrder(
        symbol="AAPL", action="BUY", quantity=10,
        order_type="MKT", limit_price=None, tif="DAY", sec_type="STK",
    )
    with patch.object(httpx, "post", return_value=_alpaca_order_resp("order-001", "accepted")):
        result = adapter.place_order(order)
    assert isinstance(result, OrderResult)
    assert result.order_id == "order-001"
    assert result.status == "accepted"
    assert result.broker == "alpaca_paper"


def test_place_limit_order_includes_limit_price():
    adapter = AlpacaPaperAdapter(key_id="key1", secret_key="secret1")
    order = BrokerOrder(
        symbol="MSFT", action="BUY", quantity=5,
        order_type="LMT", limit_price=380.50, tif="GTC", sec_type="STK",
    )
    captured = {}

    def mock_post(url, *, json, headers, timeout):
        captured.update(json)
        return _alpaca_order_resp("order-002")

    with patch.object(httpx, "post", side_effect=mock_post):
        adapter.place_order(order)

    assert captured.get("limit_price") == 380.50
    assert captured.get("type") == "limit"
    assert captured.get("time_in_force") == "gtc"


def test_place_order_raises_on_http_error():
    adapter = AlpacaPaperAdapter(key_id="key1", secret_key="secret1")
    order = BrokerOrder(
        symbol="TSLA", action="BUY", quantity=1,
        order_type="MKT", limit_price=None, sec_type="STK",
    )
    request = httpx.Request("POST", "https://paper-api.alpaca.markets/v2/orders")
    bad_resp = httpx.Response(403, json={"message": "forbidden"}, request=request)
    with patch.object(httpx, "post", return_value=bad_resp):
        with pytest.raises(RuntimeError, match="403"):
            adapter.place_order(order)


def test_options_order_raises_not_supported():
    adapter = AlpacaPaperAdapter(key_id="key1", secret_key="secret1")
    order = BrokerOrder(
        symbol="AAPL", action="BUY", quantity=1,
        order_type="MKT", limit_price=None, sec_type="OPT",
        option_symbol="AAPL250117C00200000",
    )
    with pytest.raises(ValueError, match="stock"):
        adapter.place_order(order)
