from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.data.ibkr_paper import OrderResult


def _make_app():
    from app.routers.broker import router, _idempotency_cache
    _idempotency_cache.clear()  # tests must not leak state between runs
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
        "broker": "ibkr_paper", "symbol": "AAPL", "action": "BUY",
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
    """A duplicate submitted after the (short) dedup window has elapsed
    represents a deliberate resubmit (e.g. scaling into a position) and must
    NOT be silently absorbed — this is the false-positive bug an earlier
    15s-window design had."""
    client = TestClient(_make_app())
    payload = {
        "broker": "ibkr_paper", "symbol": "AAPL", "action": "BUY",
        "quantity": 10, "order_type": "LMT", "limit_price": 185.0, "tif": "DAY",
    }
    fake_now = [1000.0]
    with patch("app.routers.broker.build_router_from_credentials",
               return_value=_mock_router("ORD1")) as build, \
         patch("app.routers.broker.time.monotonic", side_effect=lambda: fake_now[0]):
        first = client.post("/broker/stock-order", json=payload)
        fake_now[0] += 5.0  # advance past the 3s window
        second = client.post("/broker/stock-order", json=payload)
    assert first.json()["deduped"] is False
    assert second.json()["deduped"] is False
    assert build.call_count == 2, "a duplicate submitted after the window closes must not be deduped"


def test_different_quantity_is_not_deduped():
    client = TestClient(_make_app())
    base = {
        "broker": "ibkr_paper", "symbol": "AAPL", "action": "BUY",
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
        "broker": "ibkr_paper", "symbol": "AAPL", "action": "BUY",
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


def test_option_order_dedup_uses_option_symbol_and_conid():
    client = TestClient(_make_app())
    payload_call = {
        "broker": "ibkr_paper", "symbol": "AAPL", "option_symbol": "AAPL260620C00185000",
        "action": "BUY", "quantity": 1, "order_type": "LMT", "limit_price": 2.50,
        "tif": "DAY", "conid": 111,
    }
    payload_put = {**payload_call, "option_symbol": "AAPL260620P00185000", "conid": 222}
    with patch("app.routers.broker.build_router_from_credentials",
               return_value=_mock_router("O1")) as build:
        client.post("/broker/option-order", json=payload_call)
        client.post("/broker/option-order", json=payload_put)
    assert build.call_count == 2, "different option contracts must not collide as duplicates"
