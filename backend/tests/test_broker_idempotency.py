from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.data.ibkr_paper import OrderResult


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


def _make_app():
    from app.routers.broker import router, _idempotency_cache, _idempotency_inflight
    _idempotency_cache.clear()     # tests must not leak state between runs
    _idempotency_inflight.clear()
    _wipe_broker_attempts()
    app = FastAPI()
    app.include_router(router)
    return app


def _mock_router(order_id="ORD1"):
    mock_router = MagicMock()
    mock_router.execute.return_value = OrderResult(
        order_id=order_id, status="PreSubmitted", broker="ibkr_paper"
    )
    return mock_router


def test_duplicate_stock_order_within_window_is_deduped():
    """A rapid (sub-second, back-to-back) duplicate — the only realistic
    signature of a client retry-on-timeout — must be absorbed and clearly
    marked as such via the `deduped` field."""
    client = TestClient(_make_app())
    payload = {
        "broker": "ibkr_paper", "symbol": "AAPL", "action": "BUY", "effect": "OPEN",
        "quantity": 10, "order_type": "LMT", "limit_price": 185.0, "tif": "DAY",
    }
    with patch("app.routers.broker.build_router_from_credentials",
               return_value=_mock_router("ORD1")) as build:
        first = client.post("/broker/stock-order", json=payload)
        second = client.post("/broker/stock-order", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["deduped"] is False
    assert second.json()["deduped"] is True
    assert second.json()["order_id"] == first.json()["order_id"]
    # The broker adapter must only have been reached once — the second call
    # is a cache hit, not a second live order.
    assert build.call_count == 1


def test_stale_duplicate_after_window_is_not_deduped():
    """Time alone never authorizes another POST. A deliberate resubmit needs a
    new explicit attempt id."""
    client = TestClient(_make_app())
    payload = {
        "broker": "ibkr_paper", "symbol": "AAPL", "action": "BUY", "effect": "OPEN",
        "quantity": 10, "order_type": "LMT", "limit_price": 185.0, "tif": "DAY",
    }
    fake_now = [1000.0]
    with patch("app.routers.broker.build_router_from_credentials",
               return_value=_mock_router("ORD1")) as build, \
         patch("app.routers.broker.time.monotonic", side_effect=lambda: fake_now[0]):
        first = client.post("/broker/stock-order", json=payload)
        fake_now[0] += 5.0  # advance past the old 3s window
        second = client.post("/broker/stock-order", json=payload)
        third = client.post("/broker/stock-order", json={**payload, "attempt_id": "deliberate-resubmit"})
    assert first.json()["deduped"] is False
    assert second.json()["deduped"] is True
    assert third.json()["deduped"] is False
    assert build.call_count == 2, "only an explicit new attempt id may dispatch again"


def test_different_quantity_is_not_deduped():
    client = TestClient(_make_app())
    base = {
        "broker": "ibkr_paper", "symbol": "AAPL", "action": "BUY", "effect": "OPEN",
        "order_type": "LMT", "limit_price": 185.0, "tif": "DAY",
    }
    with patch("app.routers.broker.build_router_from_credentials",
               return_value=_mock_router("ORD1")) as build:
        client.post("/broker/stock-order", json={**base, "quantity": 10})
        client.post("/broker/stock-order", json={**base, "quantity": 20})
    assert build.call_count == 2, "distinct quantity must not be treated as a duplicate"


def test_failed_order_is_not_cached_and_can_be_retried():
    client = TestClient(_make_app())
    payload = {
        "broker": "ibkr_paper", "symbol": "AAPL", "action": "BUY", "effect": "OPEN",
        "quantity": 10, "order_type": "LMT", "limit_price": 185.0, "tif": "DAY",
    }
    with patch("app.routers.broker.build_router_from_credentials",
               side_effect=Exception("no creds")):
        resp = client.post("/broker/stock-order", json=payload)
    assert resp.status_code == 503
    with patch("app.routers.broker.build_router_from_credentials",
               return_value=_mock_router("ORD2")) as build:
        resp2 = client.post("/broker/stock-order", json=payload)
    assert resp2.status_code == 200
    assert resp2.json()["order_id"] == "ORD2"
    assert build.call_count == 1, "a failed attempt must not block a subsequent real retry"


def test_different_effect_is_not_deduped():
    """A SELL-to-CLOSE and a SELL-to-OPEN with otherwise-identical fields (same
    symbol/quantity/order_type) must never collide in the dedup cache — closing
    an existing position and immediately opening a new short both look
    identical to a client retry unless `effect` is part of the key, which would
    silently swallow the second, genuinely different order and return the
    first order's cached result instead."""
    client = TestClient(_make_app())
    base = {
        "broker": "ibkr_paper", "symbol": "AAPL", "action": "SELL",
        "quantity": 10, "order_type": "MKT", "limit_price": None, "tif": "DAY",
    }
    with patch("app.routers.broker.build_router_from_credentials",
               return_value=_mock_router("ORD1")) as build:
        client.post("/broker/stock-order", json={**base, "effect": "CLOSE"})
        client.post("/broker/stock-order", json={**base, "effect": "OPEN"})
    assert build.call_count == 2, "OPEN and CLOSE orders must not be treated as duplicates"


def test_option_order_dedup_uses_option_symbol_and_conid():
    client = TestClient(_make_app())
    payload_call = {
        "broker": "ibkr_paper", "symbol": "AAPL", "option_symbol": "AAPL260620C00185000",
        "action": "BUY", "effect": "OPEN", "quantity": 1, "order_type": "LMT", "limit_price": 2.50,
        "tif": "DAY", "conid": 111,
    }
    payload_put = {**payload_call, "option_symbol": "AAPL260620P00185000", "conid": 222}
    with patch("app.routers.broker.build_router_from_credentials",
               return_value=_mock_router("O1")) as build:
        client.post("/broker/option-order", json=payload_call)
        client.post("/broker/option-order", json=payload_put)
    assert build.call_count == 2, "different option contracts must not collide as duplicates"
