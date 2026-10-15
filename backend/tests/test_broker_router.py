import asyncio

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
    mock_adapter.place_order.assert_called_once_with(order)


def test_router_forwards_all_order_fields_for_options():
    """An OPT order's conid/option_symbol/sec_type must reach the adapter
    unchanged — call_args inspection, not just call-count, per T2."""
    mock_adapter = MagicMock()
    mock_adapter.place_order.return_value = OrderResult(
        order_id="OPT1", status="ok", broker="tradier_paper"
    )
    router = BrokerRouter(adapters={"tradier_paper": mock_adapter})
    order = BrokerOrder(
        symbol="AAPL", action="BUY", effect="OPEN", quantity=2, order_type="LMT",
        limit_price=2.50, tif="DAY", conid=12345, sec_type="OPT",
        option_symbol="AAPL260620C00185000",
    )
    router.execute("tradier_paper", order)
    forwarded = mock_adapter.place_order.call_args.args[0]
    assert forwarded.conid == 12345
    assert forwarded.option_symbol == "AAPL260620C00185000"
    assert forwarded.sec_type == "OPT"
    assert forwarded.quantity == 2


def test_live_broker_keys_shared_with_credential_store():
    """broker_router's live-block set must be the same object credential_store
    exposes — this is the fix for H8's 'enforced only in broker_router.py' gap.
    A regression here means someone redefined a second, driftable list."""
    from app.services.broker_router import _LIVE_BROKERS
    from app.services.credential_store import LIVE_BROKER_KEYS
    assert _LIVE_BROKERS is LIVE_BROKER_KEYS


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
    # the _KNOWN_LIVE_BROKERS guard blocks execution unconditionally, before any
    # adapter lookup, rather than merely relying on no live adapter existing.
    # Do not "simplify" this to adapters={}; that would weaken the test to no
    # longer prove the guard runs first.
    router = BrokerRouter(adapters={"tastytrade_live": MagicMock()})
    order = BrokerOrder(symbol="AAPL", action="BUY", effect="OPEN", quantity=1,
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
    order = BrokerOrder(symbol="AAPL", action="BUY", effect="OPEN", quantity=1,
                         order_type="MKT", limit_price=None, tif="DAY")
    with pytest.raises(ValueError, match="not yet activated"):
        router.execute("tradier_live", order)


def test_unknown_broker_key_is_distinct_from_a_live_broker_key():
    """A genuinely bogus/unrecognized key must still get the 'Unknown broker'
    diagnostic (with the Available: [...] adapter list), not be swallowed by
    the live-broker branch — proving the two branches stay distinct after
    _KNOWN_LIVE_BROKERS was widened to include 'tradier_live'."""
    router = BrokerRouter(adapters={"ibkr_paper": MagicMock()})
    order = BrokerOrder(symbol="X", action="BUY", effect="OPEN", quantity=1,
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


def _wipe_broker_attempts():
    from app.database import engine
    import sqlite3
    if engine.url.get_backend_name() != "sqlite":
        return
    database = engine.url.database
    if not database or database == ":memory:":
        return
    conn = sqlite3.connect(database, timeout=30)
    try:
        conn.execute("delete from broker_attempts")
        conn.commit()
    except sqlite3.OperationalError:
        conn.rollback()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _clear_durable_attempts():
    _wipe_broker_attempts()
    yield
    _wipe_broker_attempts()


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
                "action": "BUY", "effect": "OPEN", "quantity": 1, "order_type": "MKT",
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


@pytest.mark.asyncio
async def test_stock_order_does_not_block_event_loop():
    """Regression for the High finding: router_.execute() ran straight on the
    event loop with no to_thread hop, so a slow synchronous adapter call (e.g.
    IBKR/Tradier/Alpaca's blocking httpx.post) froze every other coroutine —
    scans, price fetches, websocket alerts — for the whole round trip.

    Deterministic, no wall-clock threshold (the previous version asserted a
    concurrent 0.05s tick resolved in < 0.2s, which failed intermittently in
    full-suite runs): the adapter blocks its thread until a coroutine on the
    event loop has run AFTER the adapter started. On a worker thread that
    coroutine runs at once; on the loop thread it cannot run until the adapter
    returns, so the adapter's wait times out and reports it."""
    import threading as _threading
    from app.routers.broker import _idempotency_cache, _idempotency_inflight
    # An identical order cached by an earlier test would be answered from the
    # dedup cache without ever reaching the adapter.
    _idempotency_cache.clear()
    _idempotency_inflight.clear()

    adapter_started = _threading.Event()
    loop_ran_during_adapter = _threading.Event()
    seen: dict[str, bool] = {}

    class BlockingAdapter:
        def place_order(self, order):
            adapter_started.set()
            # Blocks its thread like a synchronous httpx.post would.
            seen["loop_ran"] = loop_ran_during_adapter.wait(timeout=5.0)
            return OrderResult(order_id="SLOW1", status="ok", broker="ibkr_paper")

    router = BrokerRouter(adapters={"ibkr_paper": BlockingAdapter()})

    async def other_coroutine():
        # Polls asynchronously, so it only makes progress while the loop is free.
        while not adapter_started.is_set():
            await asyncio.sleep(0.005)
        loop_ran_during_adapter.set()

    with patch("app.routers.broker.build_router_from_credentials", return_value=router):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            order_task = asyncio.create_task(client.post("/broker/stock-order", json={
                "broker": "ibkr_paper", "symbol": "AAPL",
                "action": "BUY", "effect": "OPEN", "quantity": 1, "order_type": "MKT",
            }))
            other_task = asyncio.create_task(other_coroutine())
            resp = await order_task
            other_task.cancel()
    assert resp.status_code == 200
    assert resp.json()["deduped"] is False
    assert seen.get("loop_ran") is True, (
        "no event-loop coroutine ran while the adapter was blocking — "
        "the order handler is still running the broker call on the event loop"
    )


@pytest.mark.asyncio
async def test_concurrent_duplicate_orders_are_deduped_not_both_executed():
    """Regression: once router_.execute() moved to a worker thread
    (asyncio.to_thread), the event loop yields between the idempotency check
    and the idempotency record, so two near-simultaneous identical requests
    (e.g. a client retry racing the original submission) could both pass the
    check before either recorded a result -- placing two real orders instead
    of deduping to one, defeating the whole point of the idempotency guard."""
    import time as _time
    from app.routers.broker import _idempotency_cache, _idempotency_inflight
    _idempotency_cache.clear()
    _idempotency_inflight.clear()
    call_count = {"n": 0}

    class SlowAdapter:
        def place_order(self, order):
            call_count["n"] += 1
            _time.sleep(0.2)
            return OrderResult(order_id="ONLY1", status="ok", broker="ibkr_paper")

    router = BrokerRouter(adapters={"ibkr_paper": SlowAdapter()})
    payload = {
        "broker": "ibkr_paper", "symbol": "AAPL",
        "action": "BUY", "effect": "OPEN", "quantity": 1, "order_type": "MKT",
    }
    with patch("app.routers.broker.build_router_from_credentials", return_value=router):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp1_task = asyncio.create_task(client.post("/broker/stock-order", json=payload))
            resp2_task = asyncio.create_task(client.post("/broker/stock-order", json=payload))
            resp1, resp2 = await asyncio.gather(resp1_task, resp2_task)

    assert call_count["n"] == 1, (
        f"place_order was called {call_count['n']} times for the same natural "
        f"key within the dedup window -- a duplicate order was placed"
    )
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["order_id"] == "ONLY1"
    assert resp2.json()["order_id"] == "ONLY1"
    deduped_flags = {resp1.json()["deduped"], resp2.json()["deduped"]}
    assert deduped_flags == {False, True}, (
        "exactly one of the two concurrent requests should be the 'leader' "
        "(deduped=False) and the other should get the deduped result"
    )


@pytest.mark.asyncio
async def test_unexpected_exception_releases_the_idempotency_claim():
    """Regression: _release_claim() was only being called from inside the
    enumerated ValueError/RuntimeError except blocks. Any OTHER exception
    escaping router_.execute() (e.g. a malformed broker response raising
    AttributeError, or asyncio.CancelledError on client disconnect) left the
    asyncio.Event reservation in _idempotency_inflight permanently
    unreleased -- every future request for that exact natural key would then
    hang in `await event.wait()` forever, since nothing ever calls
    event.set() or removes the stale reservation. Proven here with a bounded
    asyncio.wait_for: if the claim leaked, the second identical request times
    out instead of raising the adapter's own exception again."""
    from app.routers.broker import _idempotency_cache, _idempotency_inflight
    _idempotency_cache.clear()
    _idempotency_inflight.clear()

    class BrokenAdapter:
        calls = 0

        def place_order(self, order):
            type(self).calls += 1
            raise AttributeError("malformed broker response")

    router = BrokerRouter(adapters={"ibkr_paper": BrokenAdapter()})
    payload = {
        "broker": "ibkr_paper", "symbol": "AAPL",
        "action": "BUY", "effect": "OPEN", "quantity": 1, "order_type": "MKT",
    }
    with patch("app.routers.broker.build_router_from_credentials", return_value=router):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await asyncio.wait_for(client.post("/broker/stock-order", json=payload), timeout=2.0)
            # The malformed response is an unknown outcome. A retry must not
            # dispatch again or hang on the old in-memory claim.
            second = await asyncio.wait_for(client.post("/broker/stock-order", json=payload), timeout=2.0)
    assert first.status_code >= 400
    assert second.status_code >= 400
    assert BrokenAdapter.calls == 1
