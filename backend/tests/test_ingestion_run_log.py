"""HISTORY-INCREMENTAL-NIGHTLY C1b (#643): the persisted last ingestion run summary.

``ingestion_job._state`` lives in memory only, so after a backend restart the status endpoint
had no run to show. ``run_ingestion`` now writes one ``ingestion_run`` row per run (inserted
``running`` at the start, finished with the state snapshot at the end), and
``GET /api/data/ingest/status`` serves the row with the highest ``id`` as ``last_run``.

Every write is fail-open: no failure, retry or timeout of a run-log write may change the run,
``_state``, its counters or its return value.
"""
from __future__ import annotations

import asyncio
import copy
import dataclasses
import json
import logging
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.ingestion_run import IngestionRun, IngestionRunBase
from app.services import ingestion_job as job
from app.services import ingestion_run_log as run_log
from app.services.history_backfill import HistoryUpdateResult

# Taken at collection, before any test has run an ingestion: the process-start state.
INITIAL_STATE = copy.deepcopy(job._state)
UTC = timezone.utc
FAST_TIMEOUT = 0.2


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def store(monkeypatch):
    """The run log on its own in-memory SQLite table, with a short write timeout."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(IngestionRunBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(run_log, "AsyncSessionLocal", factory)
    monkeypatch.setattr(run_log, "RUN_LOG_WRITE_TIMEOUT_S", FAST_TIMEOUT)
    yield factory
    await engine.dispose()


@pytest.fixture
def fresh_state(monkeypatch):
    """The ingestion state as a freshly started backend has it."""
    monkeypatch.setattr(job, "_state", copy.deepcopy(INITIAL_STATE))


@pytest.fixture
def world(monkeypatch):
    """A two-symbol run with every provider and DB step of the job mocked."""
    monkeypatch.setattr(job, "fetch_daily_bars_batch", AsyncMock(return_value={}))
    monkeypatch.setattr(job, "get_alpaca_client", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(job, "update_history",
                        AsyncMock(return_value=HistoryUpdateResult(1, False, False)))
    monkeypatch.setattr(job, "_prune_old_rows", AsyncMock(return_value=0))


async def run() -> job.IngestionResult:
    return await asyncio.wait_for(job.run_ingestion(["AAA", "BBB"], years=1), 10)


async def rows(factory) -> list[IngestionRun]:
    async with factory() as db:
        return list((await db.execute(select(IngestionRun).order_by(IngestionRun.id))).scalars())


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def without_times(state: dict) -> dict:
    return {k: v for k, v in state.items() if k not in ("started_at", "finished_at")}


async def baseline(monkeypatch) -> tuple[dict, dict]:
    """The same run with the run log switched off: (result, state) to compare against."""
    with patch.object(run_log, "record_start", AsyncMock(return_value=None)), \
         patch.object(run_log, "record_finish", AsyncMock(return_value=None)):
        result = await run()
    state = job.get_ingestion_state()
    monkeypatch.setattr(job, "_state", copy.deepcopy(INITIAL_STATE))
    return dataclasses.asdict(result), without_times(state)


def error_logged(caplog) -> bool:
    return any(r.levelno >= logging.ERROR and r.name == run_log.logger.name for r in caplog.records)


# ── 1. completed run ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_completed_run_writes_one_row_with_the_state_at_finish(store, fresh_state, world,
                                                                      monkeypatch):
    seen = []

    async def update(sym, *args, **kwargs):
        seen.extend((r.status, r.finished_at, r.summary) for r in await rows(store))
        return HistoryUpdateResult(1, False, False)

    monkeypatch.setattr(job, "update_history", update)
    await run()

    assert seen and set(seen) == {("running", None, None)}    # inserted running at start
    [row] = await rows(store)
    state = job.get_ingestion_state()
    assert state["status"] == "completed"
    assert row.status == "completed"
    assert json.loads(row.summary) == state
    assert as_utc(row.started_at) == datetime.fromisoformat(state["started_at"])
    assert as_utc(row.finished_at) == datetime.fromisoformat(state["finished_at"])


# ── 2. error run ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_error_run_writes_status_error_with_the_error_text(store, fresh_state, world,
                                                                  monkeypatch):
    monkeypatch.setattr(job, "get_alpaca_client",
                        AsyncMock(side_effect=RuntimeError("alpaca exploded")))
    result = await run()

    assert job._state["status"] == "error"
    assert result.errors == ["crash: alpaca exploded"]
    [row] = await rows(store)
    assert row.status == "error"
    summary = json.loads(row.summary)
    assert summary["error"] == "alpaca exploded"
    assert summary == job.get_ingestion_state()
    assert as_utc(row.finished_at) == datetime.fromisoformat(job._state["finished_at"])


# ── 3. fail-open writes ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_failing_start_insert_leaves_result_and_state_unchanged(store, fresh_state, world,
                                                                      monkeypatch, caplog):
    expected_result, expected_state = await baseline(monkeypatch)
    monkeypatch.setattr(run_log, "_insert_start", AsyncMock(side_effect=RuntimeError("no table")))
    monkeypatch.setattr(run_log, "_insert_finished",
                        AsyncMock(side_effect=RuntimeError("still no table")))

    with caplog.at_level(logging.ERROR):
        result = await run()

    assert dataclasses.asdict(result) == expected_result
    assert without_times(job.get_ingestion_state()) == expected_state
    assert job._state["status"] == "completed"
    assert error_logged(caplog)
    assert await rows(store) == []      # both writes failed: no row


@pytest.mark.asyncio
async def test_missing_table_leaves_result_and_state_unchanged(fresh_state, world, monkeypatch,
                                                               caplog):
    expected_result, expected_state = await baseline(monkeypatch)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")    # no ingestion_run table
    monkeypatch.setattr(run_log, "AsyncSessionLocal", async_sessionmaker(engine))
    monkeypatch.setattr(run_log, "RUN_LOG_WRITE_TIMEOUT_S", FAST_TIMEOUT)
    with caplog.at_level(logging.ERROR):
        result = await run()
    await engine.dispose()

    assert dataclasses.asdict(result) == expected_result
    assert without_times(job.get_ingestion_state()) == expected_state
    assert job._state["status"] == "completed"
    assert error_logged(caplog)


@pytest.mark.asyncio
async def test_failing_finish_update_both_attempts_leaves_result_and_state_unchanged(
        store, fresh_state, world, monkeypatch, caplog):
    expected_result, expected_state = await baseline(monkeypatch)
    failing = AsyncMock(side_effect=RuntimeError("db went away"))
    monkeypatch.setattr(run_log, "_update_finish", failing)

    with caplog.at_level(logging.ERROR):
        result = await run()

    assert failing.await_count == 2                 # tried twice, then given up
    assert dataclasses.asdict(result) == expected_result
    assert without_times(job.get_ingestion_state()) == expected_state
    assert job._state["status"] == "completed"      # not "error"
    assert error_logged(caplog)
    [row] = await rows(store)                       # the finish was never written
    assert (row.status, row.finished_at, row.summary) == ("running", None, None)


@pytest.mark.asyncio
async def test_failing_finish_update_on_the_error_branch_keeps_the_error_state(
        store, fresh_state, world, monkeypatch):
    monkeypatch.setattr(job, "get_alpaca_client", AsyncMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(run_log, "_update_finish", AsyncMock(side_effect=RuntimeError("db gone")))
    result = await run()
    assert job._state["status"] == "error" and job._state["error"] == "boom"
    assert result.errors == ["crash: boom"]


@pytest.mark.asyncio
async def test_start_insert_failure_then_finish_insert_leaves_one_complete_row(
        store, fresh_state, world, monkeypatch):
    monkeypatch.setattr(run_log, "_insert_start", AsyncMock(side_effect=RuntimeError("blip")))
    await run()
    state = job.get_ingestion_state()

    [row] = await rows(store)
    assert row.status == "completed"
    assert as_utc(row.started_at) == datetime.fromisoformat(state["started_at"])
    assert as_utc(row.finished_at) == datetime.fromisoformat(state["finished_at"])
    assert json.loads(row.summary) == state

    monkeypatch.setattr(job, "_state", copy.deepcopy(INITIAL_STATE))     # restart
    latest = await run_log.latest_run()
    assert latest["id"] == row.id and latest["status"] == "completed"
    assert latest["summary"] == state


@pytest.mark.asyncio
async def test_finish_update_failing_once_succeeds_on_the_retry(store, fresh_state, world,
                                                                 monkeypatch):
    real = run_log._update_finish
    calls = []

    async def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return await real(*args, **kwargs)

    monkeypatch.setattr(run_log, "_update_finish", flaky)
    await run()

    assert len(calls) == 2
    [row] = await rows(store)
    assert row.status == "completed"
    assert json.loads(row.summary) == job.get_ingestion_state()


async def _hang(*args, **kwargs):
    await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_hanging_start_insert_is_abandoned_at_the_timeout(store, fresh_state, world,
                                                                monkeypatch, caplog):
    expected_result, expected_state = await baseline(monkeypatch)
    monkeypatch.setattr(run_log, "_insert_start", _hang)
    with caplog.at_level(logging.ERROR):
        result = await run()

    assert dataclasses.asdict(result) == expected_result
    assert without_times(job.get_ingestion_state()) == expected_state
    assert error_logged(caplog)
    [row] = await rows(store)                  # the finish fell back to one full INSERT
    assert row.status == "completed"


@pytest.mark.asyncio
async def test_hanging_finish_update_is_abandoned_and_the_run_completes(store, fresh_state, world,
                                                                        monkeypatch):
    expected_result, expected_state = await baseline(monkeypatch)
    monkeypatch.setattr(run_log, "_update_finish", _hang)
    result = await run()

    assert dataclasses.asdict(result) == expected_result
    assert without_times(job.get_ingestion_state()) == expected_state
    assert job._state["status"] == "completed"
    [row] = await rows(store)
    assert row.status == "running"


@pytest.mark.asyncio
async def test_non_json_state_fails_the_finish_write_loudly_not_the_run(store, fresh_state, world,
                                                                        monkeypatch, caplog):
    job._state["not_json"] = object()      # json.dumps without default= must refuse it
    with caplog.at_level(logging.ERROR):
        await run()
    assert job._state["status"] == "completed"
    assert error_logged(caplog)
    [row] = await rows(store)
    assert (row.status, row.summary) == ("running", None)


# ── 4. retention and order by id ──────────────────────────────────────────────

async def _seed(factory, n: int) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    async with factory() as db:
        for i in range(n):
            # started_at goes BACKWARDS as id goes up: wall-clock order disagrees with id order.
            when = base - timedelta(days=i)
            db.add(IngestionRun(started_at=when, finished_at=when + timedelta(hours=1),
                                status="completed", summary=json.dumps({"seed": i})))
        await db.commit()


@pytest.mark.asyncio
async def test_start_keeps_the_newest_50_by_id_and_never_prunes_the_new_row(store):
    await _seed(store, 55)
    oldest_clock = datetime(2020, 1, 1, tzinfo=UTC).isoformat()
    run_id = await run_log.record_start(oldest_clock)

    ids = [r.id for r in await rows(store)]
    assert len(ids) == 50
    assert run_id == 56 and run_id in ids
    assert ids == list(range(7, 57))           # the 50 highest ids, whatever their started_at

    latest = await run_log.latest_run()
    assert latest["id"] == run_id and latest["status"] == "running"


@pytest.mark.asyncio
async def test_finish_insert_fallback_keeps_the_newest_50_by_id(store):
    await _seed(store, 60)
    await run_log.record_finish(None, {"status": "completed",
                                       "started_at": "2019-01-01T00:00:00+00:00",
                                       "finished_at": "2019-01-01T00:05:00+00:00"})
    ids = [r.id for r in await rows(store)]
    assert ids == list(range(12, 62))
    latest = await run_log.latest_run()
    assert latest["id"] == 61 and latest["status"] == "completed"
    assert latest["summary"]["started_at"] == "2019-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_latest_run_is_the_highest_id_not_the_latest_started_at(store):
    await _seed(store, 3)                       # id 1 has the latest started_at
    latest = await run_log.latest_run()
    assert latest["id"] == 3
    assert latest["summary"] == {"seed": 2}


# ── 5–7. the status endpoint ──────────────────────────────────────────────────

async def get_status() -> dict:
    from app.main import create_app
    with patch("app.routers.ingestion.single_provider_symbols", AsyncMock(return_value={})), \
         patch("app.data.tiingo_budget.usage_summary", AsyncMock(return_value={})):
        async with AsyncClient(transport=ASGITransport(app=create_app()),
                               base_url="http://test") as ac:
            resp = await ac.get("/api/data/ingest/status")
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.asyncio
async def test_after_a_restart_the_status_returns_the_stored_last_run(store, fresh_state, world,
                                                                      monkeypatch):
    await run()
    finished_state = job.get_ingestion_state()
    [row] = await rows(store)

    monkeypatch.setattr(job, "_state", copy.deepcopy(INITIAL_STATE))     # simulated restart
    body = await get_status()

    assert body["status"] == "idle" and body["started_at"] is None       # live: nothing
    assert body["last_run_error"] is None
    last = body["last_run"]
    assert set(last) == {"id", "status", "started_at", "finished_at", "summary"}
    assert last["id"] == row.id and last["status"] == "completed"
    assert last["summary"] == finished_state
    assert datetime.fromisoformat(last["started_at"]) == datetime.fromisoformat(
        finished_state["started_at"])
    assert datetime.fromisoformat(last["finished_at"]) == datetime.fromisoformat(
        finished_state["finished_at"])


@pytest.mark.asyncio
async def test_empty_table_returns_last_run_null(store, fresh_state):
    body = await get_status()
    assert body["last_run"] is None
    assert body["last_run_error"] is None


@pytest.mark.asyncio
async def test_failing_read_returns_200_with_last_run_error(fresh_state, monkeypatch, caplog):
    monkeypatch.setattr(run_log, "latest_run", AsyncMock(side_effect=RuntimeError("db down")))
    with caplog.at_level(logging.WARNING, logger="app.routers.ingestion"):
        body = await get_status()
    assert body["last_run"] is None
    assert "db down" in body["last_run_error"]
    assert body["status"] == "idle"


@pytest.mark.asyncio
async def test_missing_table_read_returns_200_with_last_run_error(fresh_state, monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(run_log, "AsyncSessionLocal", async_sessionmaker(engine))
    body = await get_status()
    await engine.dispose()
    assert body["last_run"] is None
    assert "ingestion_run" in body["last_run_error"]


# ── 8. a running row, UTC offsets ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_running_row_is_returned_as_is_with_utc_offsets(store):
    run_id = await run_log.record_start("2026-11-12T01:02:03.456789+00:00")
    assert await run_log.latest_run() == {
        "id": run_id, "status": "running", "started_at": "2026-11-12T01:02:03.456789+00:00",
        "finished_at": None, "summary": None,
    }


@pytest.mark.asyncio
async def test_times_come_back_in_utc_with_an_explicit_offset(store):
    run_id = await run_log.record_start("2026-11-12T03:02:03+02:00")
    await run_log.record_finish(run_id, {"status": "completed",
                                         "started_at": "2026-11-12T03:02:03+02:00",
                                         "finished_at": "2026-11-12T03:12:03+02:00"})
    latest = await run_log.latest_run()
    assert latest["started_at"] == "2026-11-12T01:02:03+00:00"
    assert latest["finished_at"] == "2026-11-12T01:12:03+00:00"
    assert latest["status"] == "completed"


# ── 9. the migration ──────────────────────────────────────────────────────────

NEW_REVISION = "d6a2f9c4e017"
PRIOR_HEAD = "b7d4e2a9c816"
COLUMNS = ["id", "started_at", "finished_at", "status", "summary"]


def _alembic_runner(path):
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{path.as_posix()}"}
    cwd = Path(__file__).resolve().parents[1]

    def alembic(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "migrations/alembic.ini", *args],
            cwd=cwd, env=env, check=True, capture_output=True, text=True)

    return alembic


def _tables(db) -> set[str]:
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_ingestion_run_migration_upgrades_and_downgrades(tmp_path):
    path = tmp_path / "ingestion_run.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE keep_me (x INTEGER)")
        db.execute("INSERT INTO keep_me VALUES (1)")
    alembic = _alembic_runner(path)
    alembic("stamp", PRIOR_HEAD)

    alembic("upgrade", NEW_REVISION)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == NEW_REVISION
        info = {r[1]: r for r in db.execute("PRAGMA table_info(ingestion_run)")}
        assert list(info) == COLUMNS
        assert info["id"][5] == 1                                  # primary key
        assert info["started_at"][3] == 1 and info["status"][3] == 1   # NOT NULL
        assert info["finished_at"][3] == 0 and info["summary"][3] == 0
        assert db.execute("SELECT x FROM keep_me").fetchall() == [(1,)]

    alembic("downgrade", "-1")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == PRIOR_HEAD
        assert "ingestion_run" not in _tables(db)
        assert db.execute("SELECT x FROM keep_me").fetchall() == [(1,)]


def test_ingestion_run_revision_stacks_on_the_single_prior_head(tmp_path):
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "migrations"))
    script = ScriptDirectory.from_config(config)
    assert script.get_revision(NEW_REVISION).down_revision == PRIOR_HEAD
    heads = script.get_heads()
    assert heads == [NEW_REVISION]
    out = _alembic_runner(tmp_path / "heads.db")("heads").stdout
    assert [line.split()[0] for line in out.splitlines() if line.strip()] == heads


def test_the_model_is_registered_for_alembic():
    env_py = (Path(__file__).resolve().parents[1] / "migrations" / "env.py").read_text()
    assert "IngestionRunBase.metadata" in env_py
