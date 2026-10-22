"""MANUAL-IBKR-CONFIRM-AS-ERROR (Kenneth 2026-09-25).

IBKR can answer an order submission with a confirmation QUESTION (the "order
reply message": 2xx, `id` + `message`, no `order_id`). Nothing in this app
sends the confirming reply, so the order is not placed. ibkr_paper.place_order
flags that reply (OrderResult.awaiting_confirmation). The manual routes
/broker/stock-order and /broker/option-order used to answer it as an empty-id
200 "success" -- which every frontend send path turns into a Portfolio
position -- and cached that success for the dedup window. They now answer a
502 carrying IBKR's question, log it as a failed order, and cache nothing.
"""
import asyncio
import threading
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.data.ibkr_paper import OrderResult
from app.routers import broker as broker_mod
from app.routers.broker import (
    _confirmation_question,
    _idempotency_cache,
    _idempotency_inflight,
    router,
)
from app.services.broker_router import BrokerRouter

QUESTION = (
    "You are about to submit an order outside regular trading hours. "
    "Are you sure you want to submit this order?"
)

STOCK = {
    "broker": "ibkr_paper", "symbol": "AAPL", "action": "BUY", "effect": "OPEN",
    "quantity": 10, "order_type": "LMT", "limit_price": 185.0, "tif": "DAY",
}
OPTION = {
    "broker": "ibkr_paper", "symbol": "AAPL", "option_symbol": "AAPL251017C00185000",
    "action": "BUY", "effect": "OPEN", "quantity": 1, "order_type": "LMT",
    "limit_price": 2.5, "tif": "DAY", "conid": 123456,
}
ROUTES = [("/broker/stock-order", STOCK, "stock"), ("/broker/option-order", OPTION, "option")]


def _confirm_result(message=QUESTION) -> OrderResult:
    return OrderResult(
        order_id="", status="Unknown", broker="ibkr_paper",
        message=message, awaiting_confirmation=True,
    )


def _ok_result(order_id="987") -> OrderResult:
    return OrderResult(order_id=order_id, status="PreSubmitted", broker="ibkr_paper")


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
def _clean_idempotency():
    _idempotency_cache.clear()
    _idempotency_inflight.clear()
    _wipe_broker_attempts()
    yield
    _idempotency_cache.clear()
    _idempotency_inflight.clear()
    _wipe_broker_attempts()


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _router_returning(*results):
    r = MagicMock()
    r.execute.side_effect = list(results)
    return r


# ── 1-2: the reply is a 502 carrying the question, on both routes ─────────────

@pytest.mark.parametrize("path,payload,kind", ROUTES)
def test_confirmation_reply_is_a_502_with_the_question(path, payload, kind):
    client = TestClient(_app())
    with patch("app.routers.broker.build_router_from_credentials",
               return_value=_router_returning(_confirm_result())):
        resp = client.post(path, json=payload)
    assert resp.status_code == 502
    body = resp.json()
    assert set(body) == {"detail"}
    assert "IBKR did not place the order" in body["detail"]
    assert body["detail"].endswith(f"IBKR said: {QUESTION}")


# ── 3: audit trail says failed, never filled ──────────────────────────────────

@pytest.mark.parametrize("path,payload,kind", ROUTES)
def test_confirmation_reply_logs_failed_never_filled(path, payload, kind):
    client = TestClient(_app())
    with patch("app.routers.broker.build_router_from_credentials",
               return_value=_router_returning(_confirm_result())), \
         patch("app.routers.broker.log_event") as log:
        client.post(path, json=payload)
    events = [c.args[0] for c in log.call_args_list]
    assert "broker_order_filled" not in events
    failed = [c.args[2] for c in log.call_args_list if c.args[0] == "broker_order_failed"]
    assert len(failed) == 1
    assert failed[0]["kind"] == kind
    assert failed[0]["http_status"] == 502
    assert failed[0]["awaiting_confirmation"] is True
    assert failed[0]["error"] == QUESTION


# ── 4: nothing is cached (sequential) ─────────────────────────────────────────

@pytest.mark.parametrize("path,payload,kind", ROUTES)
def test_confirmation_reply_is_not_cached(path, payload, kind):
    client = TestClient(_app())
    r = _router_returning(_confirm_result(), _confirm_result())
    with patch("app.routers.broker.build_router_from_credentials", return_value=r):
        first = client.post(path, json=payload)
        second = client.post(path, json=payload)
    assert first.status_code == 502
    assert second.status_code == 502
    assert "deduped" not in first.json() and "deduped" not in second.json()
    assert r.execute.call_count == 2, "a retry must ask IBKR again, not replay a cached answer"
    assert _idempotency_cache == {}
    assert _idempotency_inflight == {}


# ── 4b: nothing is cached (concurrent) -- the parked waiter re-leads ──────────

@pytest.mark.asyncio
async def test_concurrent_duplicate_during_confirmation_reply_re_asks_ibkr():
    started = threading.Event()
    release = threading.Event()
    calls: list[dict] = []

    class BlockingConfirmAdapter:
        def place_order(self, order):
            calls.append({"release_was_set_at_start": release.is_set()})
            started.set()
            assert release.wait(timeout=5.0), "test never released the adapter"
            return _confirm_result()

    fake_router = BrokerRouter(adapters={"ibkr_paper": BlockingConfirmAdapter()})

    async def scenario():
        with patch("app.routers.broker.build_router_from_credentials", return_value=fake_router):
            transport = ASGITransport(app=_app())
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                t1 = asyncio.create_task(client.post("/broker/stock-order", json=STOCK))
                while not started.is_set():
                    await asyncio.sleep(0.005)
                t2 = asyncio.create_task(client.post("/broker/stock-order", json=STOCK))
                await asyncio.sleep(0.05)
                assert len(calls) == 1, "the duplicate must wait, not run beside the leader"
                release.set()
                return await asyncio.gather(t1, t2)

    r1, r2 = await asyncio.wait_for(scenario(), timeout=10.0)
    assert r1.status_code == 502 and r2.status_code == 502
    assert len(calls) == 1, "a parked waiter must not ask IBKR again"
    assert _idempotency_cache == {}
    assert _idempotency_inflight == {}


# ── 5: a question, then a real order for the same order shape ─────────────────

@pytest.mark.parametrize("path,payload,kind", ROUTES)
def test_confirmation_then_real_order_is_a_normal_success(path, payload, kind):
    client = TestClient(_app())
    with patch("app.routers.broker.build_router_from_credentials",
               return_value=_router_returning(_confirm_result(), _ok_result("987"))):
        first = client.post(path, json=payload)
        second = client.post(path, json=payload)
    assert first.status_code == 502
    assert second.status_code == 200
    assert second.json() == {
        "order_id": "987", "status": "PreSubmitted", "broker": "ibkr_paper", "deduped": False,
    }


# ── 6: unchanged paths ────────────────────────────────────────────────────────

@dataclass
class _TradierShapedResult:
    """No awaiting_confirmation attribute, like tradier_paper's own OrderResult."""
    order_id: str
    status: str
    broker: str


@pytest.mark.parametrize("path,payload,kind", ROUTES)
@pytest.mark.parametrize("result,expected_id", [
    (_ok_result("123"), "123"),
    # Empty id WITHOUT the flag: shape unchanged (NO-ORDER-ID-BOOKS-FULL-PREMIUM, out of scope).
    (OrderResult(order_id="", status="Unknown", broker="ibkr_paper"), ""),
    (_TradierShapedResult(order_id="T1", status="ok", broker="ibkr_paper"), "T1"),
    (SimpleNamespace(order_id="N1", status="ok", broker="ibkr_paper"), "N1"),
])
def test_results_without_the_flag_are_unchanged(path, payload, kind, result, expected_id):
    client = TestClient(_app())
    with patch("app.routers.broker.build_router_from_credentials",
               return_value=_router_returning(result)):
        resp = client.post(path, json=payload)
    assert resp.status_code == 200
    assert resp.json()["order_id"] == expected_id
    assert resp.json()["deduped"] is False


# ── 7: message edge cases ─────────────────────────────────────────────────────

@pytest.mark.parametrize("message", ["", "   ", "<br><b></b>"])
def test_empty_or_tag_only_question_uses_the_fallback(message):
    client = TestClient(_app())
    with patch("app.routers.broker.build_router_from_credentials",
               return_value=_router_returning(_confirm_result(message))):
        resp = client.post("/broker/stock-order", json=STOCK)
    assert resp.status_code == 502
    assert resp.json()["detail"].endswith("IBKR said: IBKR asked for a confirmation")


def test_long_question_is_capped_at_500_chars():
    client = TestClient(_app())
    with patch("app.routers.broker.build_router_from_credentials",
               return_value=_router_returning(_confirm_result("Q" * 600))):
        resp = client.post("/broker/stock-order", json=STOCK)
    assert resp.status_code == 502
    detail = resp.json()["detail"]
    # The fixed prefix has no "Q", so every "Q" in the detail is the question's.
    assert detail.count("Q") == 500


@pytest.mark.parametrize("message,expected", [
    ("Line one<br>Line two", "Line one Line two"),
    ("<p>Price exceeds <b>the</b> cap.</p>", "Price exceeds the cap."),
    ("price < 5 and qty > 3", "price < 5 and qty > 3"),
    ("a lone < stays", "a lone < stays"),
    ("Tom &amp; Jerry&nbsp;&lt;3", "Tom & Jerry <3"),
    ("Confirm&lt;br&gt;please", "Confirm please"),
])
def test_question_text_is_cleaned(message, expected):
    assert _confirmation_question(_confirm_result(message)) == expected


# ── 8: the helper ─────────────────────────────────────────────────────────────

def test_helper_reads_only_a_real_true_flag():
    assert _confirmation_question(_confirm_result()) == QUESTION
    assert _confirmation_question(_ok_result()) is None
    assert _confirmation_question(SimpleNamespace(order_id="", message=QUESTION)) is None
    # A mock's attribute reads truthy but is not True -- must not be taken for the reply.
    assert _confirmation_question(MagicMock()) is None
    assert _confirmation_question(SimpleNamespace(awaiting_confirmation=1, message=QUESTION)) is None

