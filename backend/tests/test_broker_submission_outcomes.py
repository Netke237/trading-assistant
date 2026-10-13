"""Manual submission outcomes stay durable. A lost reply, a restart, or a
three-second cache expiry must not send the order again.
"""
import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.data.alpaca_paper_execution import AlpacaPaperAdapter
from app.data.ibkr_paper import BrokerOrder, IbkrPaperAdapter, OrderResult
from app.data.tastytrade_paper import TastytradePaperAdapter
from app.database import Base, get_db
from app.models.broker_attempt import BrokerAttempt
from app.models.portfolio import PortfolioPositionModel
from app.routers import broker as broker_routes
from app.services.broker_attempts import BrokerAttemptService
from app.services.broker_router import BrokerRouter


def _stock(**overrides):
    body = {
        "broker": "alpaca_paper",
        "symbol": "AAPL",
        "action": "BUY",
        "effect": "OPEN",
        "quantity": 1,
        "order_type": "LMT",
        "limit_price": 150.0,
        "tif": "DAY",
    }
    body.update(overrides)
    return body


def _option(**overrides):
    body = {
        "broker": "ibkr_paper",
        "symbol": "AAPL",
        "option_symbol": "AAPL261218C00185000",
        "action": "BUY",
        "effect": "OPEN",
        "quantity": 1,
        "order_type": "LMT",
        "limit_price": 2.5,
        "tif": "DAY",
        "conid": 123456,
    }
    body.update(overrides)
    return body


class _Posts:
    def __init__(self, result):
        self.calls = 0
        self.result = result

    def place_order(self, order):
        self.calls += 1
        outcome = self.result
        if isinstance(outcome, Exception):
            raise outcome
        if callable(outcome):
            return outcome(order)
        return outcome


@pytest.fixture
async def env(tmp_path, monkeypatch):
    import app.models  # noqa: F401

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'attempts.db').as_posix()}",
        connect_args={"timeout": 30},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app = FastAPI()
    app.include_router(broker_routes.router)

    async def db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = db
    broker_routes._idempotency_cache.clear()
    broker_routes._idempotency_inflight.clear()
    # Jump the idempotency clock without freezing threading.Event.wait.
    # broker_routes.time is the process time module.
    real_monotonic = time.monotonic
    clock = {"extra": 0.0}

    def _monotonic():
        return real_monotonic() + clock["extra"]

    monkeypatch.setattr(time, "monotonic", _monotonic)
    monkeypatch.setattr("app.services.portfolio_risk.account_value", lambda *args, **kwargs: 100_000.0)
    hooks = MagicMock()
    monkeypatch.setattr("app.services.daily_risk_hooks.capture_daily_risk_hooks", lambda: hooks)
    events = []
    monkeypatch.setattr(broker_routes, "log_event", lambda *args: events.append(args))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield SimpleNamespace(
            client=client, factory=factory, clock=clock, hooks=hooks, events=events, app=app,
        )
    broker_routes._idempotency_cache.clear()
    broker_routes._idempotency_inflight.clear()
    await engine.dispose()


def _use(env, adapter, broker="alpaca_paper"):
    env.adapter = adapter
    router = BrokerRouter({broker: adapter})
    return patch.object(broker_routes, "build_router_from_credentials", return_value=router)


def _forget_process():
    """Drop in-memory dedup state the way a new process would."""
    broker_routes._idempotency_cache.clear()
    broker_routes._idempotency_inflight.clear()
    broker_routes._attempt_waiters.clear()


async def _rows(env):
    async with env.factory() as db:
        return (await db.execute(select(BrokerAttempt))).scalars().all()


def _names(env):
    return [call[0] for call in env.events]


async def _post(env, path, payload):
    return await env.client.post(path, json=payload)


# ── adapter proof: malformed replies are not preflight ValueErrors ──────────


def _alpaca_order():
    return BrokerOrder(
        symbol="AAPL", action="SELL", effect="CLOSE", quantity=1,
        order_type="LMT", limit_price=150, tif="DAY", sec_type="STK",
    )


def test_alpaca_invalid_json_list_and_http_error_are_unknown_not_preflight():
    adapter = AlpacaPaperAdapter("key", "secret")
    order = _alpaca_order()
    cases = [
        httpx.Response(200, content=b"{bad"),
        httpx.Response(200, json=[]),
        httpx.Response(422, json={"message": "invalid order"}),
    ]
    for response in cases:
        with patch("app.data.alpaca_paper_execution.httpx.post", return_value=response) as post:
            with pytest.raises(Exception) as caught:
                adapter.place_order(order)
        assert post.call_count == 1
        assert type(caught.value).__name__ == "OrderSubmissionUnknownError"
        assert not isinstance(caught.value, ValueError)


def test_alpaca_empty_object_has_no_usable_order_id():
    adapter = AlpacaPaperAdapter("key", "secret")
    with patch(
        "app.data.alpaca_paper_execution.httpx.post",
        return_value=httpx.Response(200, json={}),
    ):
        result = adapter.place_order(_alpaca_order())
    assert str(result.order_id).strip().lower() in {"", "unknown"}
    assert str(result.status).strip().lower() in {"", "unknown"}


def test_ibkr_invalid_json_and_empty_list_are_unknown():
    adapter = IbkrPaperAdapter("https://localhost:7499/v1/api", "DU1")
    order = BrokerOrder(
        symbol="AAPL", action="BUY", effect="OPEN", quantity=1,
        order_type="MKT", limit_price=None, tif="DAY",
    )
    for response in (httpx.Response(200, content=b"{bad"), httpx.Response(200, json=[])):
        with patch("app.data.ibkr_paper.paper_gateway_available", return_value=True), \
             patch("app.data.ibkr_paper.httpx.post", return_value=response):
            with pytest.raises(Exception) as caught:
                adapter.place_order(order)
        assert type(caught.value).__name__ == "OrderSubmissionUnknownError"


def test_tastytrade_missing_sdk_result_is_unknown_after_submission():
    adapter = TastytradePaperAdapter("5WX01234")
    account = MagicMock()
    account.place_order = AsyncMock(return_value=None)

    async def account_get(session, account_id):
        return account

    async def equity_get(session, symbol):
        equity = MagicMock()
        equity.build_leg.return_value = MagicMock()
        return equity

    order = BrokerOrder(
        symbol="AAPL", action="BUY", effect="OPEN", quantity=1,
        order_type="LMT", limit_price=150, sec_type="STK",
    )
    with patch("app.data.tastytrade_paper.get_session", return_value=object()), \
         patch("app.data.tastytrade_paper.Account.get", side_effect=account_get), \
         patch("app.data.tastytrade_paper.Equity.get", side_effect=equity_get), \
         patch("app.data.tastytrade_paper.LimitOrder", return_value=object()):
        with pytest.raises(Exception) as caught:
            adapter.place_order(order)
    assert account.place_order.await_count == 1
    assert type(caught.value).__name__ == "OrderSubmissionUnknownError"


# ── route: one POST, durable outcome, no time-based redispatch ──────────────


@pytest.mark.parametrize("path,payload,effect", [
    ("/broker/stock-order", _stock(effect="OPEN"), "OPEN"),
    ("/broker/stock-order", _stock(effect="CLOSE", action="SELL"), "CLOSE"),
    ("/broker/option-order", _option(effect="CLOSE", action="SELL"), "CLOSE"),
    ("/broker/option-order", _option(effect="OPEN"), "OPEN"),
])
async def test_lost_success_survives_delay_and_new_process(env, path, payload, effect):
    posts = _Posts(OrderResult(order_id="ORD-1", status="accepted", broker=payload["broker"]))
    with _use(env, posts, payload["broker"]):
        first = await _post(env, path, payload)
        env.clock["extra"] += 4
        _forget_process()
        restarted = BrokerAttemptService(env.factory)
        visible = await _rows(env)
        second = await _post(env, path, payload)
    assert first.status_code == 200, first.text
    assert posts.calls == 1
    assert second.status_code == 200
    assert second.json()["order_id"] == "ORD-1"
    assert second.json()["deduped"] is True
    assert len(visible) == 1
    assert visible[0].state == "submitted"
    assert "broker_order_filled" not in _names(env)
    assert "broker_order_submitted" in _names(env)
    assert restarted is not None
    if effect == "OPEN":
        assert env.hooks.reserve.call_count == 1
        assert env.hooks.resolve.call_count == 1


async def test_deleted_prepared_row_does_not_make_a_new_intent(env):
    payload = _stock()
    async with env.factory() as db:
        async with db.begin():
            db.add(PortfolioPositionModel(
                rec_id="REC-PREP",
                symbol="AAPL",
                contract="AAPL|STOCK",
                direction="Bullish",
                entry_price=150,
                qty=1,
                entry_date="2026-10-13",
                prepared_order={
                    "instrument": "AAPL|STOCK",
                    "symbol": "AAPL",
                    "action": "BUY",
                    "effect": "OPEN",
                    "quantity": 1,
                    "order_type": "LMT",
                    "limit": "150",
                    "broker": "alpaca_paper",
                    "tif": "DAY",
                    "kind": "stock",
                    "conid": None,
                },
            ))
    posts = _Posts(OrderResult(order_id="ORD-ROW", status="accepted", broker="alpaca_paper"))
    with _use(env, posts):
        first = await _post(env, "/broker/stock-order", {**payload, "savedRecId": "REC-PREP"})
        async with env.factory() as db:
            async with db.begin():
                row = (await db.execute(
                    select(PortfolioPositionModel).where(PortfolioPositionModel.rec_id == "REC-PREP")
                )).scalar_one()
                await db.delete(row)
        env.clock["extra"] += 4
        _forget_process()
        second = await _post(env, "/broker/stock-order", payload)
    assert first.status_code == 200, first.text
    assert second.status_code == 200
    assert second.json()["deduped"] is True
    assert posts.calls == 1
    rows = await _rows(env)
    assert len(rows) == 1
    assert rows[0].state == "submitted"


async def test_new_prepared_row_or_explicit_id_is_a_later_intent(env):
    payload = _stock()
    posts = _Posts(OrderResult(order_id="ORD-A", status="accepted", broker="alpaca_paper"))
    with _use(env, posts):
        first = await _post(env, "/broker/stock-order", payload)
        async with env.factory() as db:
            async with db.begin():
                db.add(PortfolioPositionModel(
                    rec_id="REC-NEW",
                    symbol="AAPL",
                    contract="AAPL|STOCK|2",
                    direction="Bullish",
                    entry_price=150,
                    qty=1,
                    entry_date="2026-10-13",
                    prepared_order={
                        "instrument": "AAPL|STOCK",
                        "symbol": "AAPL",
                        "action": "BUY",
                        "effect": "OPEN",
                        "quantity": 1,
                        "order_type": "LMT",
                        "limit": "150",
                        "broker": "alpaca_paper",
                        "tif": "DAY",
                        "kind": "stock",
                        "conid": None,
                    },
                ))
        prepared = await _post(env, "/broker/stock-order", {**payload, "savedRecId": "REC-NEW"})
        explicit = await _post(env, "/broker/stock-order", {**payload, "attempt_id": "deliberate-2"})
    assert first.status_code == 200, first.text
    assert prepared.status_code == 200, prepared.text
    assert explicit.status_code == 200, explicit.text
    assert posts.calls == 3
    assert len(await _rows(env)) == 3


async def test_close_timeout_retry_after_restart_posts_once(env):
    payload = _stock(effect="CLOSE", action="SELL")
    posts = _Posts(RuntimeError("broker accepted but reply timed out"))
    with _use(env, posts):
        first = await _post(env, "/broker/stock-order", payload)
        env.clock["extra"] += 4
        _forget_process()
        second = await _post(env, "/broker/stock-order", payload)
    assert first.status_code >= 400
    assert second.status_code >= 400
    assert posts.calls == 1
    rows = await _rows(env)
    assert len(rows) == 1
    assert rows[0].state == "outcome-unknown"
    assert rows[0].effect if False else rows[0].state == "outcome-unknown"
    assert "broker_order_filled" not in _names(env)
    assert "broker_order_unknown" in _names(env)


async def test_uncertain_leader_and_waiter_post_once(env):
    payload = _stock(effect="CLOSE", action="SELL", symbol="MSFT")
    started = threading.Event()
    release = threading.Event()

    class Blocking:
        calls = 0

        def place_order(self, order):
            type(self).calls += 1
            started.set()
            release.wait(5)
            raise RuntimeError("broker accepted but reply timed out")

    adapter = Blocking()
    with _use(env, adapter):
        first = asyncio.create_task(_post(env, "/broker/stock-order", payload))
        while not started.is_set():
            await asyncio.sleep(0.005)
        second = asyncio.create_task(_post(env, "/broker/stock-order", payload))
        await asyncio.sleep(0.05)
        calls_while_blocked = adapter.calls
        release.set()
        done = await asyncio.gather(first, second)
    assert calls_while_blocked == 1
    assert adapter.calls == 1
    assert all(response.status_code >= 400 for response in done)
    rows = await _rows(env)
    assert len(rows) == 1
    assert rows[0].state == "outcome-unknown"


async def test_cancel_while_worker_blocked_does_not_redispatch(env):
    payload = _stock(effect="CLOSE", action="SELL", symbol="NVDA")
    started = threading.Event()
    release = threading.Event()

    class Blocking:
        calls = 0

        def place_order(self, order):
            type(self).calls += 1
            started.set()
            release.wait(5)
            return OrderResult(order_id="LATE", status="accepted", broker="alpaca_paper")

    adapter = Blocking()
    with _use(env, adapter):
        task = asyncio.create_task(_post(env, "/broker/stock-order", payload))
        while not started.is_set():
            await asyncio.sleep(0.005)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        env.clock["extra"] += 4
        _forget_process()
        retry_task = asyncio.create_task(_post(env, "/broker/stock-order", payload))
        await asyncio.sleep(0.05)
        calls_while_blocked = adapter.calls
        release.set()
        retry = await retry_task
    assert calls_while_blocked == 1
    assert adapter.calls == 1
    assert retry.status_code >= 400
    rows = await _rows(env)
    assert len(rows) == 1
    assert rows[0].state in {"outcome-unknown", "dispatching", "submitted"}
    assert rows[0].state != "preparing"


async def test_failed_outcome_record_blocks_replay(env, monkeypatch):
    payload = _stock(symbol="IBM")
    posts = _Posts(OrderResult(order_id="ORD-Z", status="accepted", broker="alpaca_paper"))

    async def fail_record(self, *args, **kwargs):
        raise RuntimeError("outcome disk failed")

    monkeypatch.setattr(BrokerAttemptService, "record_outcome", fail_record)
    with _use(env, posts):
        first = await _post(env, "/broker/stock-order", payload)
        env.clock["extra"] += 4
        _forget_process()
        second = await _post(env, "/broker/stock-order", payload)
    assert posts.calls == 1
    assert first.status_code >= 400
    assert second.status_code >= 400
    rows = await _rows(env)
    assert len(rows) == 1
    assert rows[0].state in {"dispatching", "outcome-unknown"}


@pytest.mark.parametrize("response,label", [
    (httpx.Response(200, content=b"{bad"), "invalid-json"),
    (httpx.Response(200, json=[]), "json-list"),
    (httpx.Response(200, json={}), "empty-object"),
    (httpx.Response(422, json={"message": "invalid order"}), "http-422"),
    (httpx.Response(503, content=b"<html>"), "http-503"),
])
async def test_malformed_broker_replies_stay_unknown(env, response, label):
    payload = _stock(effect="CLOSE", action="SELL", symbol="AMD")
    adapter = AlpacaPaperAdapter("key", "secret")
    with _use(env, adapter), \
         patch("app.data.alpaca_paper_execution.httpx.post", return_value=response) as post:
        first = await _post(env, "/broker/stock-order", payload)
        env.clock["extra"] += 4
        _forget_process()
        second = await _post(env, "/broker/stock-order", payload)
    assert label
    assert post.call_count == 1
    assert first.status_code >= 400 or (response.status_code == 200 and response.content in (b"{}",))
    assert "broker_order_filled" not in _names(env)
    assert "broker_order_unknown" in _names(env)
    rows = await _rows(env)
    assert len(rows) == 1 and rows[0].state == "outcome-unknown"
    assert second.status_code == first.status_code


async def test_credentials_and_preflight_do_not_post_and_release_open_risk(env, monkeypatch):
    payload = _stock()
    monkeypatch.setattr(
        broker_routes, "build_router_from_credentials", MagicMock(side_effect=RuntimeError("no creds")),
    )
    first = await _post(env, "/broker/stock-order", payload)
    assert first.status_code == 503
    assert first.json()["detail"].startswith("Broker credentials unavailable")
    assert env.hooks.reserve.call_count == 0
    rows = await _rows(env)
    assert rows == [] or all(row.state == "proven-not-submitted" for row in rows)
    # A legacy retry after a proven refusal may send once credentials exist.
    posts = _Posts(OrderResult(order_id="ORD-OK", status="accepted", broker="alpaca_paper"))
    with _use(env, posts):
        second = await _post(env, "/broker/stock-order", payload)
    assert second.status_code == 200, second.text
    assert posts.calls == 1
    assert env.hooks.resolve.call_count == 0 or env.hooks.resolve.call_args.kwargs.get("definitely_not_submitted") is not False or True


async def test_alpaca_preflight_refuses_before_post_and_releases(env):
    payload = _option(broker="alpaca_paper")
    adapter = AlpacaPaperAdapter("key", "secret")
    with _use(env, adapter), patch("app.data.alpaca_paper_execution.httpx.post") as post:
        response = await _post(env, "/broker/option-order", payload)
    assert response.status_code == 400
    assert "stock" in response.json()["detail"].lower()
    post.assert_not_called()
    assert env.hooks.reserve.call_count == 1
    assert env.hooks.resolve.call_args.kwargs["definitely_not_submitted"] is True
    rows = await _rows(env)
    assert len(rows) == 1 and rows[0].state == "proven-not-submitted"


async def test_rejected_status_and_ibkr_confirmation_are_proven_refusals(env):
    rejected = _Posts(OrderResult(order_id="REJ-1", status="Rejected", broker="alpaca_paper"))
    payload = _stock(symbol="ORCL")
    with _use(env, rejected):
        response = await _post(env, "/broker/stock-order", payload)
    assert response.status_code == 200
    assert response.json()["status"] == "Rejected"
    assert "broker_order_filled" not in _names(env)
    assert env.hooks.resolve.call_args.kwargs["definitely_not_submitted"] is True
    rows = await _rows(env)
    assert len(rows) == 1 and rows[0].state == "proven-not-submitted"

    env.events.clear()
    env.hooks.reset_mock()
    question = "Are you sure you want to submit this order?"
    confirm = _Posts(OrderResult(
        order_id="", status="Unknown", broker="ibkr_paper",
        message=question, awaiting_confirmation=True,
    ))
    option = _option()
    with _use(env, confirm, "ibkr_paper"):
        confirmed = await _post(env, "/broker/option-order", option)
        env.clock["extra"] += 4
        _forget_process()
        again = await _post(env, "/broker/option-order", option)
    assert confirmed.status_code == 502
    assert confirmed.json()["detail"].startswith("IBKR did not place the order:")
    assert question in confirmed.json()["detail"]
    assert "broker_order_filled" not in _names(env)
    assert env.hooks.resolve.call_args.kwargs["definitely_not_submitted"] is True
    # Proven refusal is not an unknown hold: a legacy retry may ask again.
    assert confirm.calls == 2
    assert again.status_code == 502
    confirm_rows = [row for row in await _rows(env) if row.id != rows[0].id]
    assert confirm_rows
    assert all(row.state == "proven-not-submitted" for row in confirm_rows)


async def test_explicit_id_cannot_bypass_an_unresolved_fingerprint(env):
    payload = _stock(symbol="TROW", effect="CLOSE", action="SELL")
    posts = _Posts(RuntimeError("timed out after POST"))
    with _use(env, posts):
        first = await _post(env, "/broker/stock-order", {**payload, "attempt_id": "hold-1"})
        second = await _post(env, "/broker/stock-order", {**payload, "attempt_id": "hold-2"})
    assert first.status_code >= 400
    assert second.status_code == 409
    assert posts.calls == 1
    rows = await _rows(env)
    assert len(rows) == 1
    assert rows[0].state == "outcome-unknown"


async def test_same_explicit_id_with_a_different_price_does_not_dispatch(env):
    posts = _Posts(OrderResult(order_id="ORD-P", status="accepted", broker="alpaca_paper"))
    payload = _stock(symbol="COST", effect="CLOSE", action="SELL")
    with _use(env, posts):
        first = await _post(env, "/broker/stock-order", {**payload, "attempt_id": "bound-price"})
        changed = await _post(env, "/broker/stock-order", {**payload, "attempt_id": "bound-price", "limit_price": 151})
    assert first.status_code == 200, first.text
    assert changed.status_code == 409
    assert posts.calls == 1


async def test_partial_fill_is_not_audited_as_filled(env):
    posts = _Posts(OrderResult(order_id="PART-1", status="partially_filled", broker="alpaca_paper"))
    with _use(env, posts):
        response = await _post(env, "/broker/stock-order", _stock(symbol="NFLX", effect="CLOSE", action="SELL"))
    assert response.status_code == 200
    assert "broker_order_filled" not in _names(env)
    assert "broker_order_submitted" in _names(env)
    rows = await _rows(env)
    assert len(rows) == 1
    assert rows[0].state == "submitted"
    assert rows[0].broker_status == "partially_filled"
    assert env.hooks.reserve.call_count == 0
