"""Manual verification reads durable attempts and never places another order."""
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.models.broker_attempt import BrokerAttempt
from app.models.daily_risk import DailyRiskAttempt, DailyRiskBudget
from app.models.portfolio import PortfolioPositionModel
from app.routers import broker as broker_routes
from app.services.broker_attempts import BrokerAttemptConflict, BrokerAttemptService
from app.services.broker_router import BrokerRouter
from app.services.daily_risk import DailyRiskService


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


class _Posts:
    def __init__(self, result):
        self.calls = 0
        self.result = result

    def place_order(self, order):
        del order
        self.calls += 1
        outcome = self.result
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
async def env(tmp_path, monkeypatch):
    import app.models  # noqa: F401

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'reconciliation.db').as_posix()}",
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
    broker_routes._attempt_waiters.clear()
    real_monotonic = time.monotonic
    clock = {"extra": 0.0}

    def _monotonic():
        return real_monotonic() + clock["extra"]

    monkeypatch.setattr(time, "monotonic", _monotonic)
    monkeypatch.setattr("app.services.portfolio_risk.account_value", lambda *args, **kwargs: 100_000.0)
    monkeypatch.setattr("app.services.daily_risk_hooks.capture_daily_risk_hooks", lambda: MagicMock())
    events = []
    monkeypatch.setattr(broker_routes, "log_event", lambda *args: events.append(args))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield SimpleNamespace(client=client, factory=factory, clock=clock, events=events)
    broker_routes._idempotency_cache.clear()
    broker_routes._idempotency_inflight.clear()
    broker_routes._attempt_waiters.clear()
    await engine.dispose()


def _use(env, adapter):
    router = BrokerRouter({"alpaca_paper": adapter})
    return patch.object(broker_routes, "build_router_from_credentials", return_value=router)


def _forget_process():
    broker_routes._idempotency_cache.clear()
    broker_routes._idempotency_inflight.clear()
    broker_routes._attempt_waiters.clear()


async def _rows(env):
    async with env.factory() as db:
        return (await db.execute(select(BrokerAttempt).order_by(BrokerAttempt.created_at))).scalars().all()


def _prepared(symbol="AAPL", rec_id="REC-DEL", contract="AAPL|STOCK|DEL"):
    return PortfolioPositionModel(
        rec_id=rec_id,
        symbol=symbol,
        contract=contract,
        direction="Bullish",
        entry_price=150,
        qty=1,
        entry_date="2026-10-13",
        prepared_order={
            "instrument": f"{symbol}|STOCK",
            "symbol": symbol,
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
    )


async def test_reload_lists_open_and_close_unknowns_and_verify_does_not_order(env, monkeypatch):
    posts = _Posts(RuntimeError("timed out after POST"))
    opened = _stock(symbol="AAPL", effect="OPEN", action="BUY")
    closed = _stock(symbol="MSFT", effect="CLOSE", action="SELL", quantity=3, order_type="MKT", limit_price=None)
    with _use(env, posts):
        first_open = await env.client.post("/broker/stock-order", json=opened)
        first_close = await env.client.post("/broker/stock-order", json=closed)
        env.clock["extra"] += 4
        _forget_process()
        BrokerAttemptService(env.factory)
        listed = await env.client.get("/broker/attempts")
        assert listed.status_code == 200, listed.text
        body = listed.json()["attempts"]
        effects = sorted(row["payload"]["effect"] for row in body)
        assert effects == ["CLOSE", "OPEN"]
        assert all(row["state"] == "outcome-unknown" for row in body)
        assert any(row["saved_rec_id"] is None for row in body)
        open_row = next(row for row in body if row["payload"]["effect"] == "OPEN")
        close_row = next(row for row in body if row["payload"]["effect"] == "CLOSE")
        assert open_row["payload"]["quantity"] == 1
        assert open_row["payload"]["limit"] == "150"
        assert close_row["payload"]["quantity"] == 3
        assert close_row["payload"]["limit"] is None
        assert "filled" not in open_row["outcome_label"].lower()
        again_open = await env.client.post("/broker/stock-order", json=opened)
        again_close = await env.client.post("/broker/stock-order", json=closed)
        assert again_open.status_code >= 400 or again_open.json().get("deduped") is True
        assert posts.calls == 2
        changed = await env.client.post(
            "/broker/stock-order",
            json={**opened, "attempt_id": open_row["attempt_id"], "limit_price": 151},
        )
        bypass = await env.client.post("/broker/stock-order", json={**opened, "attempt_id": "other-id"})
        assert changed.status_code == 409
        assert bypass.status_code == 409
        assert posts.calls == 2

        day = datetime.now(timezone.utc).date().isoformat()
        risk = DailyRiskService(
            env.factory,
            history_provider=lambda: [],
            config_provider=lambda: {"portfolio": {"portfolio_value": 100000}, "auto_trade": {"max_daily_loss_pct": 0.02}},
        )
        calls = []

        async def _resolve(*args, **kwargs):
            calls.append(kwargs)
            await risk.resolve(*args, **kwargs)

        monkeypatch.setattr("app.services.daily_risk.resolve", _resolve)
        async with env.factory() as db:
            async with db.begin():
                db.add(DailyRiskBudget(day=day, reserved_cents=800, loss_cents=0))
                db.add(DailyRiskAttempt(
                    id=open_row["attempt_id"], day=day, reserved_cents=500, state="retained",
                    outcome="", instrument="AAPL|STOCK", source="manual", quantity=1,
                    price="150", multiplier=1,
                ))
                db.add(DailyRiskAttempt(
                    id=close_row["attempt_id"], day=day, reserved_cents=300, state="retained",
                    outcome="", instrument="MSFT|STOCK", source="manual", quantity=3,
                    price="1", multiplier=1,
                ))
        submitted = await env.client.post(
            f"/broker/attempts/{open_row['attempt_id']}/verify",
            json={"outcome": "submitted", "note": "broker shows the open order working", "expected_version": open_row["verification_version"]},
        )
        missing = await env.client.post(
            f"/broker/attempts/{close_row['attempt_id']}/verify",
            json={"outcome": "definitely-not-submitted", "note": "broker shows no close order", "expected_version": close_row["verification_version"]},
        )
    assert first_open.status_code >= 400
    assert first_close.status_code >= 400
    assert again_close.status_code >= 400 or again_close.json().get("deduped") is True
    assert submitted.status_code == 200, submitted.text
    assert missing.status_code == 200, missing.text
    assert posts.calls == 2
    assert submitted.json()["outcome_label"] == "submitted"
    assert "filled" not in submitted.json()["outcome_label"].lower()
    assert missing.json()["state"] == "proven-not-submitted"
    assert [call["definitely_not_submitted"] for call in calls] == [True]
    assert calls[0]["outcome"]
    async with env.factory() as db:
        kept = await db.get(DailyRiskAttempt, open_row["attempt_id"])
        released = await db.get(DailyRiskAttempt, close_row["attempt_id"])
        budget = await db.get(DailyRiskBudget, day)
    assert kept.state == "retained" and kept.outcome == ""
    assert released.state == "released"
    assert budget.reserved_cents == 500
    remaining = await env.client.get("/broker/attempts")
    assert remaining.status_code == 200
    assert remaining.json()["attempts"] == []
    detail = await env.client.get(f"/broker/attempts/{open_row['attempt_id']}")
    assert detail.status_code == 200
    assert detail.json()["verification_note"] == "broker shows the open order working"
    stale = await env.client.post(
        f"/broker/attempts/{open_row['attempt_id']}/verify",
        json={"outcome": "definitely-not-submitted", "note": "too late", "expected_version": open_row["verification_version"]},
    )
    assert stale.status_code == 409
    assert len(await _rows(env)) == 2


async def test_deleted_row_does_not_erase_the_attempt(env):
    async with env.factory() as db:
        async with db.begin():
            db.add(_prepared())
    posts = _Posts(RuntimeError("timed out after POST"))
    with _use(env, posts):
        first = await env.client.post("/broker/stock-order", json={**_stock(), "savedRecId": "REC-DEL"})
        async with env.factory() as db:
            async with db.begin():
                row = (await db.execute(
                    select(PortfolioPositionModel).where(PortfolioPositionModel.rec_id == "REC-DEL")
                )).scalar_one()
                await db.delete(row)
        _forget_process()
        listed = await env.client.get("/broker/attempts")
    assert first.status_code >= 400
    assert posts.calls == 1
    assert listed.status_code == 200, listed.text
    attempts = listed.json()["attempts"]
    assert len(attempts) == 1
    assert attempts[0]["saved_rec_id"] == "REC-DEL"
    assert attempts[0]["state"] == "outcome-unknown"
    stored = await _rows(env)
    assert len(stored) == 1


async def test_accepted_detail_says_submitted_not_filled(env):
    from app.data.ibkr_paper import OrderResult

    posts = _Posts(OrderResult(order_id="ORD-A", status="accepted", broker="alpaca_paper"))
    with _use(env, posts):
        first = await env.client.post("/broker/stock-order", json={**_stock(symbol="HD"), "attempt_id": "acc-1"})
        detail = await env.client.get("/broker/attempts/acc-1")
    assert first.status_code == 200, first.text
    assert posts.calls == 1
    assert detail.status_code == 200, detail.text
    assert detail.json()["state"] == "submitted"
    assert detail.json()["broker_status"] == "accepted"
    assert detail.json()["outcome_label"] == "submitted"
    assert "filled" not in detail.json()["outcome_label"].lower()


async def test_partial_verification_keeps_spend_and_a_late_worker_cannot_overwrite(env, monkeypatch):
    posts = _Posts(RuntimeError("timed out after POST"))
    with _use(env, posts):
        first = await env.client.post("/broker/stock-order", json={**_stock(symbol="IBM"), "attempt_id": "part-1"})
    assert first.status_code >= 400
    rows = await _rows(env)
    assert len(rows) == 1 and rows[0].state == "outcome-unknown"
    calls = []

    async def _resolve(*args, **kwargs):
        del args
        calls.append(kwargs)

    monkeypatch.setattr("app.services.daily_risk.resolve", _resolve)
    verified = await env.client.post(
        "/broker/attempts/part-1/verify",
        json={
            "outcome": "partial",
            "note": "broker shows 1 of 1 shares filled and the rest working",
            "expected_version": rows[0].verification_version,
        },
    )
    assert verified.status_code == 200, verified.text
    assert posts.calls == 1
    assert calls == []
    assert verified.json()["verification_outcome"] == "partial"
    assert "deferred" in verified.json()["coverage_note"].lower()
    assert verified.json()["state"] != "outcome-unknown"
    service = BrokerAttemptService(env.factory)
    with pytest.raises(BrokerAttemptConflict):
        await service.record_outcome(
            "part-1", "filled", expected_version=rows[0].verification_version,
            broker_order_id="LATE", broker_status="filled",
        )
    stored = await _rows(env)
    assert stored[0].state != "filled"
    assert stored[0].verification_outcome == "partial"
    reset = await env.client.post(
        "/broker/attempts/part-1/verify",
        json={"outcome": "reset", "note": "clear it", "expected_version": stored[0].verification_version},
    )
    assert reset.status_code == 422
