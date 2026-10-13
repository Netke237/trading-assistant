"""Durable submission attempts: one leader, no time-based redispatch."""
import asyncio
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.broker_attempt import BrokerAttempt, ExposureGuard
from app.services.broker_attempts import (
    BrokerAttemptConflict,
    BrokerAttemptRejected,
    BrokerAttemptService,
    BrokerAttemptStorageError,
)

_BACKEND = Path(__file__).resolve().parents[1]


def payload(**overrides):
    base = {
        "kind": "stock",
        "broker": "ibkr_paper",
        "symbol": "AAPL",
        "instrument": "AAPL|STOCK",
        "action": "BUY",
        "effect": "OPEN",
        "quantity": 10,
        "order_type": "LMT",
        "limit": "185.50",
        "tif": "DAY",
        "conid": None,
    }
    base.update(overrides)
    return base


def _engine(path):
    url = f"sqlite+aiosqlite:///{path.as_posix()}"
    engine = create_async_engine(url, connect_args={"timeout": 30})
    return url, engine


async def _factory(path):
    url, engine = _engine(path)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return url, engine, async_sessionmaker(engine, expire_on_commit=False)


async def _count(factory):
    async with factory() as db:
        return (await db.execute(select(func.count()).select_from(BrokerAttempt))).scalar_one()


@pytest.mark.asyncio
async def test_two_independent_sessions_claim_same_id_once(tmp_path):
    url, engine_a = _engine(tmp_path / "claims.db")
    engine_b = create_async_engine(url, connect_args={"timeout": 30})
    async with engine_a.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factories = [
        async_sessionmaker(engine_a, expire_on_commit=False),
        async_sessionmaker(engine_b, expire_on_commit=False),
    ]
    barrier = asyncio.Barrier(2)

    async def claim(factory):
        await barrier.wait()
        return await BrokerAttemptService(factory).claim("same-id", payload())

    try:
        results = await asyncio.gather(*(claim(factory) for factory in factories))
    finally:
        await engine_a.dispose()
        await engine_b.dispose()
    assert sum(result.leader for result in results) == 1
    assert sum(result.authorized for result in results) == 1
    assert all(result.authorized is result.leader for result in results)
    _, engine, factory = await _factory(tmp_path / "claims.db")
    try:
        assert await _count(factory) == 1
        async with factory() as db:
            row = await db.get(BrokerAttempt, "same-id")
            assert row.state == "dispatching"
            assert row.dispatch_authorized_at is not None
            assert await db.get(ExposureGuard, "global") is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_same_id_different_price_effect_or_instrument_is_409(tmp_path):
    _url, engine, factory = await _factory(tmp_path / "conflict.db")
    service = BrokerAttemptService(factory)
    try:
        first = await service.claim("bound-id", payload())
        assert first.authorized is True
        changes = (
            payload(limit="186.00"),
            payload(effect="CLOSE"),
            payload(instrument="MSFT|STOCK"),
        )
        for changed in changes:
            with pytest.raises(BrokerAttemptConflict) as caught:
                await service.claim("bound-id", changed)
            assert caught.value.status_code == 409
        replay = await service.claim("bound-id", payload(limit="185.5"))
        assert replay.leader is False and replay.authorized is False
        assert replay.payload_canonical == first.payload_canonical
        assert replay.verification_version == first.verification_version
        async with factory() as db:
            row = await db.get(BrokerAttempt, "bound-id")
            assert row.payload_canonical == first.payload_canonical
            assert row.state == "dispatching"
            assert await _count(factory) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_unresolved_fingerprint_does_not_expire(tmp_path):
    _url, engine, factory = await _factory(tmp_path / "expire.db")
    now = [datetime(2026, 10, 13, 23, 59, 58, tzinfo=timezone.utc)]
    service = BrokerAttemptService(factory, clock=lambda: now[0])
    try:
        first = await service.claim("durable-id", payload())
        assert first.leader is True and first.state == "dispatching"
        now[0] += timedelta(seconds=3)
        after_window = await service.claim("durable-id", payload())
        now[0] += timedelta(days=1)
        after_day = await service.claim("durable-id", payload())
        restarted = BrokerAttemptService(factory, clock=lambda: now[0])
        after_restart = await restarted.claim("durable-id", payload())
        for replay in (after_window, after_day, after_restart):
            assert replay.leader is False
            assert replay.authorized is False
            assert replay.state == "dispatching"
            assert replay.attempt_id == "durable-id"
        with pytest.raises(BrokerAttemptConflict) as caught:
            await restarted.claim("other-id", payload())
        assert caught.value.status_code == 409
        legacy = await restarted.legacy_short_success_compatible(payload())
        assert legacy.authorized is False
        assert legacy.expired_known_success is False
        assert await _count(factory) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_crash_while_preparing_blocks_second_dispatch(tmp_path):
    _url, engine, factory = await _factory(tmp_path / "preparing.db")
    try:
        with pytest.raises(BrokerAttemptStorageError):
            await BrokerAttemptService(factory, crash_at="after_preparing").claim("prep-id", payload())
        replay = await BrokerAttemptService(factory).claim("prep-id", payload())
        assert replay.authorized is False and replay.leader is False
        assert replay.state == "preparing"
        assert replay.dispatch_authorized_at is None
        with pytest.raises(BrokerAttemptConflict) as caught:
            await BrokerAttemptService(factory).claim("prep-other", payload())
        assert caught.value.status_code == 409
        assert await _count(factory) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_crash_after_dispatching_blocks_second_dispatch(tmp_path):
    _url, engine, factory = await _factory(tmp_path / "dispatching.db")
    try:
        with pytest.raises(BrokerAttemptStorageError):
            await BrokerAttemptService(factory, crash_at="after_dispatching").claim("disp-id", payload())
        restarted = BrokerAttemptService(factory)
        replay = await restarted.claim("disp-id", payload())
        assert replay.authorized is False and replay.leader is False
        assert replay.state == "dispatching"
        assert replay.dispatch_authorized_at is not None
        with pytest.raises(BrokerAttemptConflict) as caught:
            await restarted.claim("disp-other", payload())
        assert caught.value.status_code == 409
        assert await _count(factory) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_failed_claim_commit_yields_no_dispatch_authorization(tmp_path):
    _url, engine, factory = await _factory(tmp_path / "rollback.db")
    try:
        with pytest.raises(BrokerAttemptStorageError):
            await BrokerAttemptService(factory, crash_at="before_commit").claim("rolled-back", payload())
        assert await _count(factory) == 0
        async with factory() as db:
            row = await db.get(BrokerAttempt, "rolled-back")
            assert row is None
            dispatching = (await db.execute(select(BrokerAttempt).where(BrokerAttempt.state == "dispatching"))).scalars().all()
            assert dispatching == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_missing_storage_fails_closed(tmp_path):
    _url, engine = _engine(tmp_path / "empty.db")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        with pytest.raises(BrokerAttemptStorageError):
            await BrokerAttemptService(factory).claim("missing-table", payload())
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        {"limit": 185.5},
        {"quantity": True},
        {"quantity": 10.0},
        {"quantity": "10"},
        {"order_type": "MKT", "limit": "185.50"},
        {"order_type": "LMT", "limit": None},
        {"effect": "open"},
        {"kind": "stocks"},
        {"instrument": ""},
        {"conid": 111},
        {"extra": "field"},
    ],
)
async def test_inconsistent_payload_is_rejected(tmp_path, bad):
    _url, engine, factory = await _factory(tmp_path / "bad.db")
    try:
        with pytest.raises(BrokerAttemptRejected):
            await BrokerAttemptService(factory).claim("bad-id", payload(**bad))
        assert await _count(factory) == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_outcome_unknown_stays_blocked_and_terminal_states_do_not_redispatch(tmp_path):
    _url, engine, factory = await _factory(tmp_path / "terminal.db")
    service = BrokerAttemptService(factory)
    try:
        claimed = await service.claim("known-id", payload(), saved_rec_id="saved-row")
        recorded = await service.record_outcome(
            "known-id",
            "outcome-unknown",
            expected_version=claimed.verification_version,
            broker_response='{"status":"ambiguous"}',
            broker_status="unknown",
        )
        assert recorded.authorized is False and recorded.leader is False
        assert recorded.state == "outcome-unknown"
        assert recorded.broker_response == '{"status":"ambiguous"}'
        with pytest.raises(BrokerAttemptConflict) as caught:
            await service.claim("new-explicit", payload())
        assert caught.value.status_code == 409
        with pytest.raises(BrokerAttemptConflict) as stale:
            await service.record_outcome(
                "known-id",
                "submitted",
                expected_version=claimed.verification_version,
                broker_order_id="ORD",
                broker_status="Submitted",
            )
        assert stale.value.status_code == 409
        async with factory() as db:
            row = await db.get(BrokerAttempt, "known-id")
            assert row.state == "outcome-unknown"
            assert row.saved_rec_id == "saved-row"
            assert row.payload_canonical == claimed.payload_canonical
            assert row.broker_order_id is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_short_success_never_authorizes_a_second_dispatch(tmp_path):
    _url, engine, factory = await _factory(tmp_path / "legacy.db")
    now = [datetime(2026, 10, 13, 12, tzinfo=timezone.utc)]
    service = BrokerAttemptService(factory, clock=lambda: now[0])
    try:
        claimed = await service.claim("success-id", payload())
        await service.record_outcome(
            "success-id",
            "submitted",
            expected_version=claimed.verification_version,
            broker_order_id="ORD-1",
            broker_status="Submitted",
            broker_response='{"id":"ORD-1"}',
        )
        fresh = await service.legacy_short_success_compatible(payload())
        assert fresh.authorized is False and fresh.expired_known_success is False
        assert fresh.matched_attempt_id == "success-id"
        now[0] += timedelta(seconds=4)
        expired = await BrokerAttemptService(factory, clock=lambda: now[0]).legacy_short_success_compatible(payload())
        assert expired.authorized is False and expired.expired_known_success is True
        assert await _count(factory) == 1
        replay = await service.claim("success-id", payload())
        assert replay.authorized is False and replay.state == "submitted"
    finally:
        await engine.dispose()


def test_committed_attempt_survives_in_a_new_process(tmp_path):
    path = tmp_path / "process.db"
    url = f"sqlite+aiosqlite:///{path.as_posix()}"

    async def plant():
        engine = create_async_engine(url, connect_args={"timeout": 30})
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        result = await BrokerAttemptService(factory).claim("process-id", payload())
        await engine.dispose()
        return result

    planted = asyncio.run(plant())
    assert planted.authorized is True
    script = tmp_path / "read_attempt.py"
    script.write_text(
        "import asyncio, json, sys\n"
        "from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine\n"
        "from app.services.broker_attempts import BrokerAttemptService\n"
        "async def main():\n"
        "    engine = create_async_engine(sys.argv[1], connect_args={'timeout': 30})\n"
        "    factory = async_sessionmaker(engine, expire_on_commit=False)\n"
        "    result = await BrokerAttemptService(factory).claim(sys.argv[2], json.loads(sys.argv[3]))\n"
        "    print(json.dumps({'attempt_id': result.attempt_id, 'state': result.state,"
        " 'leader': result.leader, 'authorized': result.authorized}))\n"
        "    await engine.dispose()\n"
        "asyncio.run(main())\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, str(script), url, "process-id", json.dumps(payload())],
        cwd=_BACKEND,
        env={**__import__("os").environ, "PYTHONPATH": str(_BACKEND)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    body = json.loads(completed.stdout)
    assert body == {
        "attempt_id": "process-id",
        "state": "dispatching",
        "leader": False,
        "authorized": False,
    }
