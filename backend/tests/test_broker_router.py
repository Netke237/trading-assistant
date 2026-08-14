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
    with pytest.raises(ValueError, match="not yet activated"):
        router.execute("ibkr_live", order)


from unittest.mock import patch

from app.services.broker_router import build_router_from_credentials


def test_tastytrade_live_is_blocked():
    # Deliberately register a working adapter under the live key — this proves
    # the _KNOWN_LIVE_BROKERS guard blocks execution unconditionally, before any
    # adapter lookup, rather than merely relying on no live adapter existing.
    # Do not "simplify" this to adapters={}; that would weaken the test to no
    # longer prove the guard runs first.
    router = BrokerRouter(adapters={"tastytrade_live": MagicMock()})
    order = BrokerOrder(symbol="AAPL", action="BUY", quantity=1,
                         order_type="MKT", limit_price=None, sec_type="STK")
    with pytest.raises(ValueError, match="not yet activated"):
        router.execute("tastytrade_live", order)


def test_tradier_live_is_blocked():
    """Regression: _LIVE_BROKERS omitted 'tradier_live' — this proves the
    now-renamed _KNOWN_LIVE_BROKERS guard blocks it too, same as the other
    three live broker keys. Deliberately register a working adapter under the
    live key, same as test_tastytrade_live_is_blocked, so this proves the
    guard runs unconditionally rather than merely relying on no adapter
    existing."""
    router = BrokerRouter(adapters={"tradier_live": MagicMock()})
    order = BrokerOrder(symbol="AAPL", action="BUY", quantity=1,
                         order_type="MKT", limit_price=None, tif="DAY")
    with pytest.raises(ValueError, match="not yet activated"):
        router.execute("tradier_live", order)


def test_unknown_broker_key_is_distinct_from_a_live_broker_key():
    """A genuinely bogus/unrecognized key must still get the 'Unknown broker'
    diagnostic (with the Available: [...] adapter list), not be swallowed by
    the live-broker branch — proving the two branches stay distinct after
    _KNOWN_LIVE_BROKERS was widened to include 'tradier_live'."""
    router = BrokerRouter(adapters={"ibkr_paper": MagicMock()})
    order = BrokerOrder(symbol="X", action="BUY", quantity=1,
                        order_type="MKT", limit_price=None, tif="DAY")
    with pytest.raises(ValueError, match="Unknown broker") as excinfo:
        router.execute("totally_bogus_key", order)
    assert "Available" in str(excinfo.value)


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
async def test_broker_status_lists_tradier_live_as_locked():
    """Regression: broker_status()'s hardcoded live-broker roster (display-only,
    ~broker.py:139-155) also omitted 'tradier_live', same drift pattern as
    _LIVE_BROKERS. Must now list all four live broker keys as locked."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/broker/status")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("ibkr_live", "tradier_live", "alpaca_live", "tastytrade_live"):
        assert key in data, f"broker_status() response missing {key!r}"
        assert data[key]["enabled"] is False
        assert data[key]["note"] == "Locked — not yet activated"


@pytest.mark.asyncio
async def test_stock_order_accepts_tastytrade_paper_broker_key():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/broker/stock-order", json={
            "broker": "tastytrade_paper", "symbol": "AAPL",
            "action": "BUY", "quantity": 1, "order_type": "MKT",
        })
    # No tastytrade credentials configured in this test environment, so the
    # expected failure is 503 (credentials unavailable) or 502 (adapter
    # error) from inside the route — NOT 422, which would mean the Literal
    # still rejects "tastytrade_paper" before the route body even runs.
    assert resp.status_code != 422, (
        f"broker.py's BrokerKey Literal still rejects 'tastytrade_paper' "
        f"(got {resp.status_code}, body: {resp.text})"
    )
