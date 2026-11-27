# backend/tests/test_target_first_hit.py
"""PORTFOLIO-ALERT-ACTION T3: the History flag "Reached target, closed at a
loss" reads `target_first_hit_at`, a server-only stamp.

- Stamp: the first TP_HIT fire (backend generate_alerts or the browser's
  POST /api/alerts/notify) sets it on the open position; it is never
  overwritten afterwards.
- Close: close_position copies the locked position's value into every closed
  row (partial closes too).
- Migration: adds the column to portfolio_positions and closed_positions and
  back-fills it from the surviving position_alert_history TP_HIT rows (for a
  closed row only fires at or before closed_at count).

Migration cases run Alembic against a temp SQLite file (the test_exit_record.py
pattern); the PostgreSQL variant runs only against the explicitly supplied
TARGET_HIT_TEST_POSTGRES_URL (a throwaway database) and skips otherwise.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import patch

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (registers all tables on Base.metadata)
import app.routers.portfolio as portfolio_router_module
from app.config import get_settings
from app.database import Base, get_db
from app.models.closed_position import ClosedPositionModel
from app.models.portfolio import PortfolioPositionModel
from app.models.position_alert import PositionAlertHistoryModel
from app.routers.alerts import router as alerts_router
from app.routers.portfolio import router as portfolio_router
from app.schemas import ClosedPositionSchema
from app.services.alert_generator import generate_alerts

_BACKEND = Path(__file__).resolve().parents[1]
_PREV_HEAD = "e3c7a1f5b209"
_REVISION = "a7f3c2d9e1b4"

_STAMP = datetime(2026, 10, 20, 14, 30, tzinfo=timezone.utc)


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def env(monkeypatch) -> AsyncGenerator[tuple[AsyncClient, async_sessionmaker], None]:
    monkeypatch.setattr(portfolio_router_module, "_global_premium_stop_pct", lambda: 0.6)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 connect_args={"check_same_thread": False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _get_db():
        async with Session() as s:
            yield s

    test_app = FastAPI()
    test_app.include_router(portfolio_router)
    test_app.include_router(alerts_router)
    test_app.dependency_overrides[get_db] = _get_db
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://t") as c:
        yield c, Session
    await engine.dispose()


async def _seed(Session, *, rec="REC-T", qty=5, target_first_hit_at=None, targets=None):
    async with Session() as s:
        s.add(PortfolioPositionModel(
            rec_id=rec, symbol="FTNT", contract=f"FTNT|100|2027-01-15|C-{rec}",
            direction="Bullish", entry_price=2.0, qty=qty, entry_date="2026-10-01",
            stop=1.2, targets=targets if targets is not None else [{"stock_price": 110.0}],
            dte_total=140, alert_state={}, target_first_hit_at=target_first_hit_at,
        ))
        await s.commit()


async def _stamp_of(Session, rec="REC-T"):
    async with Session() as s:
        pos = (await s.execute(select(PortfolioPositionModel).where(
            PortfolioPositionModel.rec_id == rec))).scalar_one()
        return _utc(pos.target_first_hit_at)


# ── Model / schema ───────────────────────────────────────────────────────────

def test_columns_are_nullable_without_a_default():
    for model in (PortfolioPositionModel, ClosedPositionModel):
        col = model.__table__.columns["target_first_hit_at"]
        assert col.nullable is True
        assert col.server_default is None
        assert col.default is None


def test_column_is_not_writable_through_the_create_or_patch_schemas():
    from app.schemas import PortfolioPositionCreate, PortfolioPositionUpdate
    for schema in (PortfolioPositionCreate, PortfolioPositionUpdate):
        names = set(schema.model_fields)
        assert "targetFirstHitAt" not in names
        assert "target_first_hit_at" not in names


def _closed_row(**over) -> ClosedPositionModel:
    base = dict(
        id="c1", rec_id="REC-1", symbol="FTNT", contract="FTNT|100|2027-01-15|C",
        direction="Bullish", entry_price=2.0, entry_date="2026-10-01", exit_price=1.0,
        exit_date="2026-11-01", qty_closed=1, realized_pnl_dollar=-100.0,
        realized_pnl_pct=-50.0, source=None,
        closed_at=datetime(2026, 11, 1, 15, 0, tzinfo=timezone.utc),
    )
    base.update(over)
    return ClosedPositionModel(**base)


def test_schema_field_is_iso_utc_with_offset():
    aware = ClosedPositionSchema.from_orm_model(_closed_row(target_first_hit_at=_STAMP))
    assert aware.targetFirstHitAt == "2026-10-20T14:30:00+00:00"
    # SQLite hands DateTime(timezone=True) back naive; naive values are UTC.
    naive = ClosedPositionSchema.from_orm_model(
        _closed_row(target_first_hit_at=datetime(2026, 10, 20, 14, 30)))
    assert naive.targetFirstHitAt == "2026-10-20T14:30:00+00:00"
    berlin = timezone(timedelta(hours=2))
    shifted = ClosedPositionSchema.from_orm_model(
        _closed_row(target_first_hit_at=datetime(2026, 10, 20, 16, 30, tzinfo=berlin)))
    assert shifted.targetFirstHitAt == "2026-10-20T14:30:00+00:00"
    assert ClosedPositionSchema.from_orm_model(_closed_row()).targetFirstHitAt is None


# ── Stamp: generate_alerts ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_alerts_stamps_the_first_tp_hit(env):
    _client, Session = env
    await _seed(Session)
    before = datetime.now(timezone.utc)
    async with Session() as db:
        alerts = await generate_alerts(db, {"FTNT": 111.0})
        await db.commit()
    after = datetime.now(timezone.utc)
    assert any(a.alertType == "TP_HIT" for a in alerts)
    stamp = await _stamp_of(Session)
    assert stamp is not None and before <= stamp <= after


@pytest.mark.asyncio
async def test_generate_alerts_never_overwrites_the_stamp(env):
    _client, Session = env
    await _seed(Session, target_first_hit_at=_STAMP)
    async with Session() as db:
        alerts = await generate_alerts(db, {"FTNT": 115.0})
        await db.commit()
    assert any(a.alertType == "TP_HIT" for a in alerts)
    assert await _stamp_of(Session) == _STAMP


@pytest.mark.asyncio
async def test_generate_alerts_does_not_stamp_without_a_tp_hit(env):
    _client, Session = env
    await _seed(Session)
    async with Session() as db:
        alerts = await generate_alerts(db, {"FTNT": 100.0})  # below target, above stop
        await db.commit()
    assert not any(a.alertType == "TP_HIT" for a in alerts)
    assert await _stamp_of(Session) is None


@pytest.mark.asyncio
async def test_generate_alerts_does_not_stamp_a_muted_tp_hit(env):
    _client, Session = env
    await _seed(Session)
    async with Session() as db:
        pos = (await db.execute(select(PortfolioPositionModel))).scalar_one()
        pos.alert_overrides = {"TP_HIT": False}
        await db.commit()
    async with Session() as db:
        alerts = await generate_alerts(db, {"FTNT": 111.0})
        await db.commit()
    assert not any(a.alertType == "TP_HIT" for a in alerts)
    assert await _stamp_of(Session) is None


@pytest.mark.asyncio
async def test_generate_alerts_does_not_stamp_before_the_sustain_window(env):
    _client, Session = env
    await _seed(Session)
    async with Session() as db:
        alerts = await generate_alerts(db, {"FTNT": 111.0}, sustain_minutes=5)
        await db.commit()
    assert not any(a.alertType == "TP_HIT" for a in alerts)
    assert await _stamp_of(Session) is None


# ── Stamp: POST /api/alerts/notify ───────────────────────────────────────────

async def _notify(client, alert_type="TP_HIT", rec="REC-T"):
    with patch("app.routers.alerts.notify_alert", return_value=True):
        r = await client.post("/api/alerts/notify", json={
            "symbol": "FTNT", "alertType": alert_type, "reason": "Target reached",
            "recId": rec, "price": 111.0, "referenceValue": 110.0,
        })
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_notify_stamps_the_first_tp_hit(env):
    client, Session = env
    await _seed(Session)
    before = datetime.now(timezone.utc)
    await _notify(client)
    after = datetime.now(timezone.utc)
    stamp = await _stamp_of(Session)
    assert stamp is not None and before <= stamp <= after


@pytest.mark.asyncio
async def test_notify_never_overwrites_the_stamp(env):
    client, Session = env
    await _seed(Session, target_first_hit_at=_STAMP)
    await _notify(client)
    assert await _stamp_of(Session) == _STAMP


@pytest.mark.asyncio
async def test_notify_second_tp_hit_keeps_the_first_stamp(env):
    client, Session = env
    await _seed(Session)
    await _notify(client)
    first = await _stamp_of(Session)
    await _notify(client)
    assert await _stamp_of(Session) == first


@pytest.mark.asyncio
async def test_notify_other_types_do_not_stamp(env):
    client, Session = env
    await _seed(Session)
    await _notify(client, alert_type="STOP_REACHED")
    assert await _stamp_of(Session) is None


@pytest.mark.asyncio
async def test_notify_unknown_position_writes_nothing(env):
    client, Session = env
    await _seed(Session)
    body = await _notify(client, rec="REC-GONE")
    assert body == {"sent": False, "reason": "position_not_found"}
    assert await _stamp_of(Session) is None


# ── Copy on close ────────────────────────────────────────────────────────────

async def _close(client, rec="REC-T", **body):
    body.setdefault("exitPrice", 1.0)
    body.setdefault("exitDate", "2026-11-01")
    return await client.post(f"/api/portfolio/{rec}/close", json=body)


@pytest.mark.asyncio
async def test_full_close_copies_the_stamp(env):
    client, Session = env
    await _seed(Session, target_first_hit_at=_STAMP)
    r = await _close(client)
    assert r.status_code == 201, r.text
    assert r.json()["targetFirstHitAt"] == "2026-10-20T14:30:00+00:00"
    async with Session() as s:
        row = (await s.execute(select(ClosedPositionModel))).scalar_one()
    assert _utc(row.target_first_hit_at) == _STAMP
    hist = (await client.get("/api/portfolio/history")).json()
    assert [h["targetFirstHitAt"] for h in hist] == ["2026-10-20T14:30:00+00:00"]


@pytest.mark.asyncio
async def test_close_without_a_stamp_stores_null(env):
    client, Session = env
    await _seed(Session)
    r = await _close(client)
    assert r.status_code == 201, r.text
    assert r.json()["targetFirstHitAt"] is None
    async with Session() as s:
        row = (await s.execute(select(ClosedPositionModel))).scalar_one()
    assert row.target_first_hit_at is None


@pytest.mark.asyncio
async def test_partial_closes_each_copy_the_stamp_in_force(env):
    client, Session = env
    await _seed(Session, qty=5)
    r1 = await _close(client, qtyToClose=2)
    assert r1.status_code == 201, r1.text
    assert r1.json()["targetFirstHitAt"] is None
    # The remaining position reaches its target after the first partial close.
    async with Session() as s:
        pos = (await s.execute(select(PortfolioPositionModel))).scalar_one()
        assert pos.qty == 3 and pos.target_first_hit_at is None
        pos.target_first_hit_at = _STAMP
        await s.commit()
    r2 = await _close(client, qtyToClose=1)
    r3 = await _close(client)
    assert (r2.status_code, r3.status_code) == (201, 201)
    assert r2.json()["targetFirstHitAt"] == "2026-10-20T14:30:00+00:00"
    assert r3.json()["targetFirstHitAt"] == "2026-10-20T14:30:00+00:00"
    async with Session() as s:
        rows = {r.id: r for r in (await s.execute(select(ClosedPositionModel))).scalars()}
        assert (await s.execute(select(PortfolioPositionModel))).scalar_one_or_none() is None
    assert rows[r1.json()["id"]].target_first_hit_at is None
    assert _utc(rows[r2.json()["id"]].target_first_hit_at) == _STAMP
    assert _utc(rows[r3.json()["id"]].target_first_hit_at) == _STAMP


@pytest.mark.asyncio
async def test_patch_keeps_the_stamp(env):
    client, Session = env
    await _seed(Session, target_first_hit_at=_STAMP)
    r = await client.patch("/api/portfolio/REC-T", json={"stop": 1.1})
    assert r.status_code == 200, r.text
    assert await _stamp_of(Session) == _STAMP


# ── Migration ────────────────────────────────────────────────────────────────

# Minimal prior-head shapes: only the columns the migration reads or writes,
# plus the NOT NULL ones the rows need.
_CREATE_SQL = (
    "CREATE TABLE portfolio_positions ("
    "id VARCHAR(36) PRIMARY KEY, rec_id VARCHAR NOT NULL, symbol VARCHAR NOT NULL)",
    "CREATE TABLE closed_positions ("
    "id VARCHAR(36) PRIMARY KEY, rec_id VARCHAR NOT NULL, symbol VARCHAR NOT NULL,"
    "realized_pnl_dollar FLOAT NOT NULL, closed_at TIMESTAMP WITH TIME ZONE)",
    "CREATE TABLE position_alert_history ("
    "id VARCHAR(36) PRIMARY KEY, rec_id VARCHAR NOT NULL, alert_type VARCHAR NOT NULL,"
    "source VARCHAR NOT NULL, triggered_at TIMESTAMP WITH TIME ZONE)",
)

# Times as UTC wall-clock strings in SQLAlchemy's SQLite DateTime format.
_T = {
    "d1": "2026-10-18 09:00:00.000000",
    "d2": "2026-10-20 14:30:00.000000",
    "d3": "2026-10-25 08:00:00.000000",
    "close": "2026-10-28 15:00:00.000000",
    "d4": "2026-10-29 10:00:00.000000",
}

_INSERT_SQL = (
    # Open: two TP_HITs (MIN wins) plus an earlier STOP_REACHED that must not count.
    "INSERT INTO portfolio_positions VALUES ('p1', 'OPEN-TP', 'NFLX')",
    # Open: only a stop fire -> NULL.
    "INSERT INTO portfolio_positions VALUES ('p2', 'OPEN-STOP', 'BAC')",
    # Open: no history at all -> NULL.
    "INSERT INTO portfolio_positions VALUES ('p3', 'OPEN-NONE', 'HPE')",
    # Closed: TP_HIT before the close and one after -> the pre-close MIN.
    f"INSERT INTO closed_positions VALUES ('c1', 'CLOSED-TP', 'FTNT', -500.0, '{_T['close']}')",
    # Closed: TP_HIT only after the close -> ignored -> NULL.
    f"INSERT INTO closed_positions VALUES ('c2', 'CLOSED-LATE', 'COP', -300.0, '{_T['close']}')",
    # Closed: no history -> NULL.
    f"INSERT INTO closed_positions VALUES ('c3', 'CLOSED-NONE', 'BMY', -200.0, '{_T['close']}')",
    # Closed: TP_HIT exactly at closed_at counts (<=).
    f"INSERT INTO closed_positions VALUES ('c4', 'CLOSED-EDGE', 'AAPL', -50.0, '{_T['close']}')",
    # Closed: no closed_at recorded -> cannot prove it was pre-close -> NULL.
    "INSERT INTO closed_positions VALUES ('c5', 'CLOSED-NOAT', 'MSFT', -10.0, NULL)",
    f"INSERT INTO position_alert_history VALUES ('h1', 'OPEN-TP', 'TP_HIT', 'backend', '{_T['d3']}')",
    f"INSERT INTO position_alert_history VALUES ('h2', 'OPEN-TP', 'TP_HIT', 'frontend', '{_T['d2']}')",
    f"INSERT INTO position_alert_history VALUES ('h3', 'OPEN-TP', 'STOP_REACHED', 'backend', '{_T['d1']}')",
    f"INSERT INTO position_alert_history VALUES ('h4', 'OPEN-STOP', 'STOP_REACHED', 'backend', '{_T['d2']}')",
    f"INSERT INTO position_alert_history VALUES ('h5', 'CLOSED-TP', 'TP_HIT', 'backend', '{_T['d4']}')",
    f"INSERT INTO position_alert_history VALUES ('h6', 'CLOSED-TP', 'TP_HIT', 'backend', '{_T['d2']}')",
    f"INSERT INTO position_alert_history VALUES ('h7', 'CLOSED-TP', 'TP_HIT', 'backend', '{_T['d3']}')",
    f"INSERT INTO position_alert_history VALUES ('h8', 'CLOSED-LATE', 'TP_HIT', 'backend', '{_T['d4']}')",
    f"INSERT INTO position_alert_history VALUES ('h9', 'CLOSED-EDGE', 'TP_HIT', 'backend', '{_T['close']}')",
    f"INSERT INTO position_alert_history VALUES ('h10', 'CLOSED-NOAT', 'TP_HIT', 'backend', '{_T['d1']}')",
)

_EXPECTED_OPEN = {"OPEN-TP": _T["d2"], "OPEN-STOP": None, "OPEN-NONE": None}
_EXPECTED_CLOSED = {
    "CLOSED-TP": _T["d2"], "CLOSED-LATE": None, "CLOSED-NONE": None,
    "CLOSED-EDGE": _T["close"], "CLOSED-NOAT": None,
}


def _parse(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _utc(value).astimezone(timezone.utc)
    return _utc(datetime.fromisoformat(value))


def _expected(mapping):
    return {k: _parse(v) for k, v in mapping.items()}


def _alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_BACKEND / "migrations"))
    return cfg


class _DatabaseUrl:
    def __init__(self, url: str):
        self.url = url

    def __enter__(self):
        self.previous = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = self.url
        get_settings.cache_clear()
        return self

    def __exit__(self, *exc):
        if self.previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = self.previous
        get_settings.cache_clear()


def test_migration_is_the_single_head_above_the_exit_record():
    from alembic.script import ScriptDirectory
    script = ScriptDirectory.from_config(_alembic_config())
    heads = script.get_heads()
    assert len(heads) == 1
    ancestors = {rev.revision for rev in script.iterate_revisions(heads[0], "base")}
    assert _REVISION in ancestors
    assert script.get_revision(_REVISION).down_revision == _PREV_HEAD


def _sqlite_stamps(db, table):
    return {rec: _parse(v) for rec, v in db.execute(
        f"SELECT rec_id, target_first_hit_at FROM {table}")}


def test_sqlite_upgrade_backfills_and_downgrade_drops(tmp_path):
    db_path = tmp_path / "existing.db"
    with sqlite3.connect(db_path) as db:
        for sql in _CREATE_SQL + _INSERT_SQL:
            db.execute(sql)

    cfg = _alembic_config()
    with _DatabaseUrl(f"sqlite+aiosqlite:///{db_path.as_posix()}"):
        command.stamp(cfg, _PREV_HEAD)
        get_settings.cache_clear()
        command.upgrade(cfg, _REVISION)
        with sqlite3.connect(db_path) as db:
            assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == _REVISION
            for table in ("portfolio_positions", "closed_positions"):
                cols = {row[1]: row for row in db.execute(f"PRAGMA table_info({table})")}
                _cid, _name, _type, notnull, default, _pk = cols["target_first_hit_at"]
                assert notnull == 0 and default is None
            assert _sqlite_stamps(db, "portfolio_positions") == _expected(_EXPECTED_OPEN)
            assert _sqlite_stamps(db, "closed_positions") == _expected(_EXPECTED_CLOSED)
            assert db.execute("SELECT COUNT(*) FROM position_alert_history").fetchone()[0] == 10

        get_settings.cache_clear()
        command.downgrade(cfg, _PREV_HEAD)
        with sqlite3.connect(db_path) as db:
            assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == _PREV_HEAD
            for table in ("portfolio_positions", "closed_positions"):
                cols = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                assert "target_first_hit_at" not in cols
            assert db.execute("SELECT COUNT(*) FROM portfolio_positions").fetchone()[0] == 3
            assert db.execute("SELECT COUNT(*) FROM closed_positions").fetchone()[0] == 5
            assert db.execute(
                "SELECT rec_id, realized_pnl_dollar FROM closed_positions WHERE id = 'c1'"
            ).fetchone() == ("CLOSED-TP", -500.0)


def test_postgres_upgrade_backfills_and_downgrade_drops():
    """Runs only against TARGET_HIT_TEST_POSTGRES_URL, which must name a
    throwaway database (postgresql+asyncpg://...). The test creates the three
    tables and alembic_version there and drops them afterwards; it refuses to
    run if any already exists."""
    url = os.getenv("TARGET_HIT_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("TARGET_HIT_TEST_POSTGRES_URL not supplied")
    tables = ("portfolio_positions", "closed_positions", "position_alert_history", "alembic_version")

    async def run(sql_list, fetch=None):
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                for sql in sql_list:
                    await conn.execute(text(sql))
                if fetch:
                    return [tuple(r) for r in (await conn.execute(text(fetch))).all()]
        finally:
            await engine.dispose()
        return None

    names = ", ".join(f"'{t}'" for t in tables)
    existing = asyncio.run(run([], fetch=(
        "SELECT table_name FROM information_schema.tables "
        f"WHERE table_schema = current_schema() AND table_name IN ({names})")))
    if existing:
        pytest.fail(f"TARGET_HIT_TEST_POSTGRES_URL is not a throwaway database: {existing}")

    # Postgres stores the strings as timestamptz in the session zone; pin UTC
    # so the literals mean the same instants as on SQLite.
    inserts = ["SET TIME ZONE 'UTC'", *_INSERT_SQL]
    columns_sql = ("SELECT table_name, is_nullable, column_default FROM information_schema.columns "
                   "WHERE table_schema = current_schema() AND column_name = 'target_first_hit_at'")
    cfg = _alembic_config()
    try:
        asyncio.run(run([*_CREATE_SQL, *inserts]))
        with _DatabaseUrl(url):
            command.stamp(cfg, _PREV_HEAD)
            get_settings.cache_clear()
            command.upgrade(cfg, _REVISION)
            cols = {c[0]: c for c in asyncio.run(run([], fetch=columns_sql))}
            assert set(cols) == {"portfolio_positions", "closed_positions"}
            assert all(c[1] == "YES" and c[2] is None for c in cols.values())
            open_rows = asyncio.run(run([], fetch="SELECT rec_id, target_first_hit_at FROM portfolio_positions"))
            closed_rows = asyncio.run(run([], fetch="SELECT rec_id, target_first_hit_at FROM closed_positions"))
            assert {r: _parse(v) for r, v in open_rows} == _expected(_EXPECTED_OPEN)
            assert {r: _parse(v) for r, v in closed_rows} == _expected(_EXPECTED_CLOSED)

            get_settings.cache_clear()
            command.downgrade(cfg, _PREV_HEAD)
            assert asyncio.run(run([], fetch=columns_sql)) == []
            assert asyncio.run(run([], fetch="SELECT COUNT(*) FROM closed_positions")) == [(5,)]
    finally:
        asyncio.run(run([f"DROP TABLE IF EXISTS {t}" for t in tables]))
