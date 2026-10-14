"""Invalid historical options requests must not prevent result restoration."""
from datetime import datetime
import json
import logging

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.scan_session import ScanSession, ScanSessionBase
from app.routers import scan
from app.schemas import ScanRequest, ScanResult, SCAN_RESULT_SCHEMA_VERSION


def _request_json(depth):
    overrides = {"private_restore_marker": "do-not-log"}
    for _ in range(depth - 1):
        overrides = {"child": overrides}
    return json.dumps({
        "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing",
        "overrides": overrides,
    })


@pytest.fixture
async def saved_session(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'restore.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(ScanSessionBase.metadata.create_all)
    monkeypatch.setattr(scan, "AsyncSessionLocal", sessions)
    # An invalid restore must also remove a previously populated request.
    monkeypatch.setattr(scan, "_last_request", ScanRequest(
        universe=["STALE"], direction="Bearish", horizon="Swing",
        iv_abs_threshold=75,
    ))
    monkeypatch.setattr(scan, "_last_result", None)
    monkeypatch.setattr(scan, "_last_status", "stopped")
    monkeypatch.setattr(scan, "_last_updated_at", "stale-time")
    try:
        yield sessions
    finally:
        await engine.dispose()


async def _seed(sessions, request_json, *, version=SCAN_RESULT_SCHEMA_VERSION, status="complete"):
    result_json = ScanResult(
        scan_id="REC-RESTORE-TEST", timestamp="2026-10-14T12:00:00",
        schema_version=version, candidates=[], rejected=[],
        contract_rules={"min_open_interest": 123.0},
    ).model_dump_json()
    async with sessions() as db:
        db.add(ScanSession(
            id="current", status=status, last_request_json=request_json,
            last_result_json=result_json, updated_at=datetime(2026, 10, 14, 12),
        ))
        await db.commit()
    return await _snapshot(sessions)


async def _snapshot(sessions):
    async with sessions() as db:
        row = (await db.execute(select(ScanSession))).scalar_one()
        return {column.name: getattr(row, column.name) for column in ScanSession.__table__.columns}


@pytest.mark.parametrize("request_json", [
    pytest.param(_request_json(220), id="jiter-depth220"),
    pytest.param(_request_json(33), id="validator-depth33"),
    pytest.param('{"private_restore_marker": "do-not-log",', id="malformed-json"),
    pytest.param(json.dumps({"universe": ["AAPL"], "direction": "private_restore_marker",
                            "horizon": "Swing"}), id="invalid-direction"),
])
@pytest.mark.parametrize("status", ["complete", "running"])
async def test_invalid_saved_request_preserves_result_and_database(saved_session, caplog, request_json, status):
    before = await _seed(saved_session, request_json, status=status)
    with caplog.at_level(logging.WARNING, logger=scan.__name__):
        assert await scan.restore_from_db() == status

    assert scan._last_request is None
    metadata = await scan.get_last_scan_status()
    assert metadata.status == status
    assert metadata.updated_at == before["updated_at"].isoformat()
    assert metadata.universe is metadata.direction is metadata.horizon is None
    assert metadata.iv_abs_threshold is metadata.iv_rank_threshold is None
    restored = await scan.get_last_scan()
    assert restored.model_dump_json() == before["last_result_json"]
    assert metadata.scan_id == restored.scan_id
    assert await _snapshot(saved_session) == before
    warnings = [record.getMessage() for record in caplog.records if record.name == scan.__name__]
    assert any("saved options request" in message.lower() for message in warnings)
    assert "private_restore_marker" not in caplog.text
    assert "do-not-log" not in caplog.text


async def test_valid_depth32_request_restores_unchanged(saved_session, caplog):
    request_json = _request_json(32)
    before = await _seed(saved_session, request_json)
    assert await scan.restore_from_db() == "complete"
    assert scan._last_request.model_dump() == ScanRequest.model_validate_json(request_json).model_dump()
    assert scan._last_request.overrides == json.loads(request_json)["overrides"]
    assert (await scan.get_last_scan()).model_dump_json() == before["last_result_json"]
    assert (await scan.get_last_scan_status()).universe == ["AAPL"]
    assert await _snapshot(saved_session) == before
    assert not caplog.records


async def test_invalid_request_does_not_bypass_vintage_result_discard(saved_session):
    before = await _seed(saved_session, _request_json(33), version=SCAN_RESULT_SCHEMA_VERSION - 1)
    assert await scan.restore_from_db() == "idle"
    assert scan._last_request is None
    assert await scan.get_last_scan() is None
    metadata = await scan.get_last_scan_status()
    assert metadata.status == "idle"
    assert metadata.updated_at is None
    assert metadata.scan_id is None
    assert metadata.universe is None
    assert await _snapshot(saved_session) == before
