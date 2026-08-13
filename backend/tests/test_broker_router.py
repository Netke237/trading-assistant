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
    order = BrokerOrder(symbol="AAPL", action="BUY", effect="OPEN", quantity=10,
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
    order = BrokerOrder(symbol="NVDA", action="BUY", effect="OPEN", quantity=5,
                        order_type="MKT", limit_price=None, tif="DAY")
    result = router.execute("tradier_paper", order)
    assert result.order_id == "222"


def test_router_raises_for_unknown_broker():
    router = BrokerRouter(adapters={})
    order = BrokerOrder(symbol="X", action="BUY", effect="OPEN", quantity=1,
                        order_type="MKT", limit_price=None, tif="DAY")
    with pytest.raises(ValueError, match="Unknown broker"):
        router.execute("nonexistent", order)


def test_router_raises_for_inactive_live():
    router = BrokerRouter(adapters={})
    order = BrokerOrder(symbol="X", action="BUY", effect="OPEN", quantity=1,
                        order_type="MKT", limit_price=None, tif="DAY")
    with pytest.raises(ValueError, match="not yet activated"):
        router.execute("ibkr_live", order)


from unittest.mock import patch

from app.services.broker_router import build_router_from_credentials


def test_tastytrade_live_is_blocked():
    # Deliberately register a working adapter under the live key — this proves
    # the _LIVE_BROKERS guard blocks execution unconditionally, before any
    # adapter lookup, rather than merely relying on no live adapter existing.
    # Do not "simplify" this to adapters={}; that would weaken the test to no
    # longer prove the guard runs first.
    router = BrokerRouter(adapters={"tastytrade_live": MagicMock()})
    order = BrokerOrder(symbol="AAPL", action="BUY", effect="OPEN", quantity=1,
                         order_type="MKT", limit_price=None, sec_type="STK")
    with pytest.raises(ValueError, match="not yet activated"):
        router.execute("tastytrade_live", order)


def test_build_router_from_credentials_includes_tastytrade_paper_when_configured():
    fake_creds = {
        "ibkr_paper": None,
        "tradier_paper": {},
        "alpaca_paper": None,
        "tastytrade_paper": {"client_secret": "x", "refresh_token": "y", "account_id": "5WX01234"},
    }
    with patch("app.services.credential_store.credential_store.load"), \
         patch("app.services.credential_store.credential_store.get",
               side_effect=lambda k: fake_creds.get(k)):
        router = build_router_from_credentials()
    assert "tastytrade_paper" in router._adapters


from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_stock_order_accepts_tastytrade_paper_broker_key():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/broker/stock-order", json={
            "broker": "tastytrade_paper", "symbol": "AAPL",
            "action": "BUY", "effect": "OPEN", "quantity": 1, "order_type": "MKT",
        })
    # No tastytrade credentials configured in this test environment, so the
    # expected failure is 503 (credentials unavailable) or 502 (adapter
    # error) from inside the route — NOT 422, which would mean the Literal
    # still rejects "tastytrade_paper" before the route body even runs.
    assert resp.status_code != 422, (
        f"broker.py's BrokerKey Literal still rejects 'tastytrade_paper' "
        f"(got {resp.status_code}, body: {resp.text})"
    )


@pytest.mark.asyncio
async def test_stock_order_requires_effect_field():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/broker/stock-order", json={
            "broker": "ibkr_paper", "symbol": "AAPL",
            "action": "BUY", "quantity": 1, "order_type": "MKT",
        })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_option_order_requires_effect_field():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/broker/option-order", json={
            "broker": "ibkr_paper", "symbol": "AAPL", "option_symbol": "AAPL250117C00200000",
            "action": "BUY", "quantity": 1, "order_type": "MKT",
        })
    assert resp.status_code == 422


# ── effect propagation: broker.py's route handlers -> BrokerOrder ───────────
# The plan's own stated reason for these tests: "this exact combination is the
# gap that let the original bug ship untested." These go through the real HTTP
# route (not BrokerRouter.execute() directly), which is the layer that actually
# reads req.effect and builds BrokerOrder — a route handler silently hardcoding
# effect="OPEN" instead of using req.effect would pass every other existing
# test in this file but fail these.

def _mock_router_with_capture():
    """A BrokerRouter-shaped mock whose adapter records the BrokerOrder it received."""
    captured = {}
    mock_adapter = MagicMock()

    def capture_and_respond(order):
        captured["order"] = order
        return OrderResult(order_id="CAP1", status="ok", broker="ibkr_paper")

    mock_adapter.place_order.side_effect = capture_and_respond
    router = BrokerRouter(adapters={"ibkr_paper": mock_adapter})
    return router, captured


@pytest.mark.asyncio
async def test_stock_order_propagates_close_effect_to_broker_order():
    router, captured = _mock_router_with_capture()
    with patch("app.routers.broker.build_router_from_credentials", return_value=router):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/broker/stock-order", json={
                "broker": "ibkr_paper", "symbol": "AAPL",
                "action": "SELL", "effect": "CLOSE", "quantity": 1, "order_type": "MKT",
            })
    assert resp.status_code == 200
    assert captured["order"].effect == "CLOSE"
    assert captured["order"].action == "SELL"


@pytest.mark.asyncio
async def test_stock_order_propagates_open_effect_to_broker_order():
    router, captured = _mock_router_with_capture()
    with patch("app.routers.broker.build_router_from_credentials", return_value=router):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/broker/stock-order", json={
                "broker": "ibkr_paper", "symbol": "AAPL",
                "action": "SELL", "effect": "OPEN", "quantity": 1, "order_type": "MKT",
            })
    assert resp.status_code == 200
    assert captured["order"].effect == "OPEN"


@pytest.mark.asyncio
async def test_option_order_propagates_close_effect_to_broker_order():
    router, captured = _mock_router_with_capture()
    with patch("app.routers.broker.build_router_from_credentials", return_value=router):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/broker/option-order", json={
                "broker": "ibkr_paper", "symbol": "AAPL", "option_symbol": "AAPL250117C00200000",
                "action": "SELL", "effect": "CLOSE", "quantity": 1, "order_type": "MKT",
            })
    assert resp.status_code == 200
    assert captured["order"].effect == "CLOSE"
    assert captured["order"].action == "SELL"


# ── IBKR/Alpaca accept `effect` but their payload is unaffected by it ───────
# (auto-inferred from account state) — see ibkr_paper.py/alpaca_paper_execution.py.

def test_ibkr_payload_unaffected_by_effect():
    from app.data.ibkr_paper import IbkrPaperAdapter
    adapter = IbkrPaperAdapter(base_url="https://localhost:7499/v1/api", account_id="DU123456")
    open_order = BrokerOrder(symbol="AAPL", action="SELL", effect="OPEN", quantity=1,
                              order_type="MKT", limit_price=None)
    close_order = BrokerOrder(symbol="AAPL", action="SELL", effect="CLOSE", quantity=1,
                               order_type="MKT", limit_price=None)
    assert adapter._build_payload(open_order) == adapter._build_payload(close_order)


def test_alpaca_payload_unaffected_by_effect():
    from app.data.alpaca_paper_execution import AlpacaPaperAdapter
    adapter = AlpacaPaperAdapter(key_id="key1", secret_key="secret1")
    open_order = BrokerOrder(symbol="AAPL", action="SELL", effect="OPEN", quantity=1,
                              order_type="MKT", limit_price=None, sec_type="STK")
    close_order = BrokerOrder(symbol="AAPL", action="SELL", effect="CLOSE", quantity=1,
                               order_type="MKT", limit_price=None, sec_type="STK")
    assert adapter._build_payload(open_order) == adapter._build_payload(close_order)
