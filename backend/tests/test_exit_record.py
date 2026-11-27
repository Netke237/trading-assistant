# backend/tests/test_exit_record.py
"""PORTFOLIO-EXIT-RECORD T1: every close row records why the trade was closed
and the stop it had at that moment, read from the LOCKED re-read position.

Close-flow cases build a small app with only the portfolio router on an
in-memory SQLite DB (the test_portfolio_close_history.py pattern) and insert
the open position directly so stop / structural_stop / premium_stop_pct are
exact. The migration cases run Alembic against a temp SQLite file (the
test_broker_attempts_migration.py pattern); the PostgreSQL variant runs only
against the explicitly supplied EXIT_RECORD_TEST_POSTGRES_URL (a throwaway
database) and skips otherwise.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path
from typing import AsyncGenerator

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
from app.routers.portfolio import router as portfolio_router

_BACKEND = Path(__file__).resolve().parents[1]
_PREV_HEAD = "d6a2f9c4e017"
_REVISION = "e3c7a1f5b209"
_NEW_COLUMNS = {
    "exit_reason", "stop_at_close", "structural_stop_at_close",
    "premium_stop_pct_at_close", "premium_stop_price_at_close",
}
_FIELDS = ("exitReason", "stopAtClose", "structuralStopAtClose",
           "premiumStopPctAtClose", "premiumStopPriceAtClose")


@pytest_asyncio.fixture
async def env(monkeypatch) -> AsyncGenerator[tuple[AsyncClient, async_sessionmaker], None]:
    # Default global premium stop for these tests; individual tests override it.
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
    test_app.dependency_overrides[get_db] = _get_db
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://t") as c:
        yield c, Session
    await engine.dispose()


async def _seed(Session, *, rec="REC-X", symbol="AAPL", contract="AAPL|185|2026-09-18|C",
                direction="Bullish", entry=2.0, qty=5, stop=1.2, structural=1.5,
                premium_stop_pct=None):
    async with Session() as s:
        s.add(PortfolioPositionModel(
            rec_id=rec, symbol=symbol, contract=contract, direction=direction,
            entry_price=entry, qty=qty, entry_date="2026-05-01",
            stop=stop, structural_stop=structural, premium_stop_pct=premium_stop_pct,
            targets=[], dte_total=140,
        ))
        await s.commit()


async def _close(client, rec="REC-X", **body):
    body.setdefault("exitPrice", 1.0)
    body.setdefault("exitDate", "2026-06-01")
    return await client.post(f"/api/portfolio/{rec}/close", json=body)


async def _rows(Session):
    async with Session() as s:
        return (await s.execute(select(ClosedPositionModel))).scalars().all()


@pytest.mark.asyncio
async def test_option_with_explicit_pct_stores_snapshot_and_reason(env):
    client, Session = env
    await _seed(Session, entry=2.0, stop=1.2, structural=1.5, premium_stop_pct=0.4)
    r = await _close(client, exitReason="premium_stop")
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["exitReason"] == "premium_stop"
    assert data["stopAtClose"] == 1.2
    assert data["structuralStopAtClose"] == 1.5
    assert data["premiumStopPctAtClose"] == pytest.approx(0.4)
    assert data["premiumStopPriceAtClose"] == pytest.approx(2.0 * (1 - 0.4))
    [row] = await _rows(Session)
    assert row.exit_reason == "premium_stop"
    assert (row.stop_at_close, row.structural_stop_at_close) == (1.2, 1.5)
    assert row.premium_stop_pct_at_close == pytest.approx(0.4)
    assert row.premium_stop_price_at_close == pytest.approx(1.2)


@pytest.mark.asyncio
async def test_option_inheriting_the_global_stores_the_global(env, monkeypatch):
    client, Session = env
    monkeypatch.setattr(portfolio_router_module, "_global_premium_stop_pct", lambda: 0.5)
    await _seed(Session, entry=2.0, premium_stop_pct=None)
    r = await _close(client, exitReason="manual")
    assert r.status_code == 201, r.text
    [row] = await _rows(Session)
    assert row.premium_stop_pct_at_close == pytest.approx(0.5)
    assert row.premium_stop_price_at_close == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_inheriting_with_no_global_stores_null_never_the_fallback(env, monkeypatch):
    client, Session = env
    monkeypatch.setattr(portfolio_router_module, "_global_premium_stop_pct", lambda: None)
    await _seed(Session, entry=2.0, premium_stop_pct=None)
    r = await _close(client, exitReason="manual")
    assert r.status_code == 201, r.text
    assert r.json()["premiumStopPctAtClose"] is None
    assert r.json()["premiumStopPriceAtClose"] is None
    [row] = await _rows(Session)
    assert row.premium_stop_pct_at_close is None
    assert row.premium_stop_price_at_close is None
    # The stops themselves are still copied.
    assert (row.stop_at_close, row.structural_stop_at_close) == (1.2, 1.5)


@pytest.mark.asyncio
async def test_explicit_pct_is_stored_even_when_the_global_is_unavailable(env, monkeypatch):
    client, Session = env
    monkeypatch.setattr(portfolio_router_module, "_global_premium_stop_pct", lambda: None)
    await _seed(Session, entry=2.0, premium_stop_pct=0.3)
    r = await _close(client, exitReason="stop")
    assert r.status_code == 201, r.text
    [row] = await _rows(Session)
    assert row.premium_stop_pct_at_close == pytest.approx(0.3)
    assert row.premium_stop_price_at_close == pytest.approx(1.4)


@pytest.mark.asyncio
async def test_long_stock_close_stores_pct_price_and_stops(env):
    client, Session = env
    await _seed(Session, rec="REC-S", symbol="MSFT", contract="MSFT|STOCK", direction="Bullish",
                entry=400.0, qty=10, stop=380.0, structural=370.0, premium_stop_pct=0.1)
    r = await _close(client, rec="REC-S", exitPrice=390.0, exitReason="stop")
    assert r.status_code == 201, r.text
    [row] = await _rows(Session)
    assert row.exit_reason == "stop"
    assert (row.stop_at_close, row.structural_stop_at_close) == (380.0, 370.0)
    assert row.premium_stop_pct_at_close == pytest.approx(0.1)
    assert row.premium_stop_price_at_close == pytest.approx(400.0 * (1 - 0.1))


@pytest.mark.asyncio
async def test_short_stock_close_stores_price_above_entry(env):
    client, Session = env
    await _seed(Session, rec="REC-SH", symbol="TSLA", contract="TSLA|STOCK", direction="Bearish",
                entry=200.0, qty=10, stop=215.0, structural=None, premium_stop_pct=0.1)
    r = await _close(client, rec="REC-SH", exitPrice=210.0, exitReason="structural_stop")
    assert r.status_code == 201, r.text
    [row] = await _rows(Session)
    assert row.exit_reason == "structural_stop"
    assert row.stop_at_close == 215.0
    assert row.structural_stop_at_close is None
    assert row.premium_stop_pct_at_close == pytest.approx(0.1)
    assert row.premium_stop_price_at_close == pytest.approx(200.0 * (1 + 0.1))


@pytest.mark.asyncio
async def test_partial_then_full_close_each_row_holds_its_own_snapshot(env):
    client, Session = env
    await _seed(Session, entry=2.0, qty=5, stop=1.2, structural=1.5, premium_stop_pct=0.4)
    r1 = await _close(client, qtyToClose=2, exitReason="target")
    assert r1.status_code == 201, r1.text

    # Move the stops and the percent stop on the remaining position.
    async with Session() as s:
        pos = (await s.execute(select(PortfolioPositionModel))).scalar_one()
        assert pos.qty == 3
        pos.stop = 1.6
        pos.structural_stop = 1.7
        pos.premium_stop_pct = 0.25
        await s.commit()

    r2 = await _close(client, exitReason="manual")
    assert r2.status_code == 201, r2.text

    first, second = r1.json(), r2.json()
    assert (first["qtyClosed"], second["qtyClosed"]) == (2, 3)
    assert first["exitReason"] == "target"
    assert (first["stopAtClose"], first["structuralStopAtClose"]) == (1.2, 1.5)
    assert first["premiumStopPctAtClose"] == pytest.approx(0.4)
    assert first["premiumStopPriceAtClose"] == pytest.approx(1.2)
    assert second["exitReason"] == "manual"
    assert (second["stopAtClose"], second["structuralStopAtClose"]) == (1.6, 1.7)
    assert second["premiumStopPctAtClose"] == pytest.approx(0.25)
    assert second["premiumStopPriceAtClose"] == pytest.approx(1.5)

    rows = {r.id: r for r in await _rows(Session)}
    assert rows[first["id"]].stop_at_close == 1.2
    assert rows[second["id"]].stop_at_close == 1.6
    async with Session() as s:
        assert (await s.execute(select(PortfolioPositionModel))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_omitted_reason_stores_null(env):
    client, Session = env
    await _seed(Session, premium_stop_pct=0.4)
    r = await _close(client)
    assert r.status_code == 201, r.text
    assert r.json()["exitReason"] is None
    [row] = await _rows(Session)
    assert row.exit_reason is None


@pytest.mark.asyncio
async def test_explicit_null_reason_stores_null(env):
    client, Session = env
    await _seed(Session, premium_stop_pct=0.4)
    r = await _close(client, exitReason=None)
    assert r.status_code == 201, r.text
    [row] = await _rows(Session)
    assert row.exit_reason is None


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["panic", "STOP", "", 3])
async def test_invalid_reason_is_422_with_no_row_and_position_unchanged(env, bad):
    client, Session = env
    await _seed(Session, qty=5, stop=1.2, premium_stop_pct=0.4)
    r = await _close(client, exitReason=bad)
    assert r.status_code == 422, r.text
    assert await _rows(Session) == []
    async with Session() as s:
        pos = (await s.execute(select(PortfolioPositionModel))).scalar_one()
        assert (pos.qty, pos.stop, pos.premium_stop_pct) == (5, 1.2, 0.4)


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", [
    "stop", "structural_stop", "premium_stop", "target", "time_stop", "expiry", "manual", "unknown",
])
async def test_every_allowed_reason_is_stored(env, reason):
    client, Session = env
    await _seed(Session, premium_stop_pct=0.4)
    r = await _close(client, exitReason=reason)
    assert r.status_code == 201, r.text
    [row] = await _rows(Session)
    assert row.exit_reason == reason


@pytest.mark.asyncio
async def test_history_returns_the_five_fields(env):
    client, Session = env
    await _seed(Session, entry=2.0, stop=1.2, structural=1.5, premium_stop_pct=0.4)
    assert (await _close(client, exitReason="expiry")).status_code == 201
    # An old-style row (written before this change) reads NULL for all five.
    async with Session() as s:
        s.add(ClosedPositionModel(
            id="old-row", rec_id="REC-OLD", symbol="AAPL", contract="AAPL|190|2026-09-18|C",
            direction="Bullish", entry_price=1.0, entry_date="2026-01-01", exit_price=1.1,
            exit_date="2026-02-01", qty_closed=1, realized_pnl_dollar=10.0,
            realized_pnl_pct=10.0, source=None,
        ))
        await s.commit()
    hist = {h["id"]: h for h in (await client.get("/api/portfolio/history")).json()}
    assert len(hist) == 2
    new = next(h for i, h in hist.items() if i != "old-row")
    assert new["exitReason"] == "expiry"
    assert new["stopAtClose"] == 1.2
    assert new["structuralStopAtClose"] == 1.5
    assert new["premiumStopPctAtClose"] == pytest.approx(0.4)
    assert new["premiumStopPriceAtClose"] == pytest.approx(1.2)
    assert all(hist["old-row"][f] is None for f in _FIELDS)


def test_new_columns_are_nullable_without_a_server_default():
    cols = ClosedPositionModel.__table__.columns
    for name in _NEW_COLUMNS:
        assert cols[name].nullable is True
        assert cols[name].server_default is None
        assert cols[name].default is None


# ── Migration ────────────────────────────────────────────────────────────────

_CREATE_CLOSED_AT_PREV_HEAD = (
    "CREATE TABLE closed_positions ("
    "id VARCHAR(36) PRIMARY KEY, rec_id VARCHAR NOT NULL, symbol VARCHAR NOT NULL,"
    "contract VARCHAR NOT NULL, direction VARCHAR NOT NULL, entry_price FLOAT NOT NULL,"
    "entry_date VARCHAR, exit_price FLOAT NOT NULL, exit_date VARCHAR NOT NULL,"
    "qty_closed INTEGER NOT NULL, realized_pnl_dollar FLOAT NOT NULL,"
    "realized_pnl_pct FLOAT NOT NULL, source VARCHAR, closed_at TIMESTAMP)"
)
_INSERT_OLD_ROW = (
    "INSERT INTO closed_positions (id, rec_id, symbol, contract, direction, entry_price, "
    "entry_date, exit_price, exit_date, qty_closed, realized_pnl_dollar, realized_pnl_pct, source) "
    "VALUES ('old-1', 'REC-1', 'AAPL', 'AAPL|185|2026-09-18|C', 'Bullish', 2.0, '2026-05-01', "
    "1.5, '2026-06-01', 3, -150.0, -25.0, 'manual')"
)
_OLD_COLS = ("id, rec_id, symbol, contract, direction, entry_price, entry_date, exit_price, "
             "exit_date, qty_closed, realized_pnl_dollar, realized_pnl_pct, source")
_OLD_ROW = ("old-1", "REC-1", "AAPL", "AAPL|185|2026-09-18|C", "Bullish", 2.0, "2026-05-01",
            1.5, "2026-06-01", 3, -150.0, -25.0, "manual")


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


def test_migration_head_is_the_exit_record_revision():
    from alembic.script import ScriptDirectory
    script = ScriptDirectory.from_config(_alembic_config())
    assert script.get_heads() == [_REVISION]
    assert script.get_revision(_REVISION).down_revision == _PREV_HEAD


def test_sqlite_upgrade_adds_null_columns_and_downgrade_keeps_the_row(tmp_path):
    db_path = tmp_path / "existing.db"
    with sqlite3.connect(db_path) as db:
        db.execute(_CREATE_CLOSED_AT_PREV_HEAD)
        db.execute(_INSERT_OLD_ROW)

    cfg = _alembic_config()
    with _DatabaseUrl(f"sqlite+aiosqlite:///{db_path.as_posix()}"):
        command.stamp(cfg, _PREV_HEAD)
        get_settings.cache_clear()
        command.upgrade(cfg, _REVISION)
        with sqlite3.connect(db_path) as db:
            assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == _REVISION
            cols = {row[1]: row for row in db.execute("PRAGMA table_info(closed_positions)")}
            assert _NEW_COLUMNS <= set(cols)
            for name in _NEW_COLUMNS:
                _cid, _name, _type, notnull, default, _pk = cols[name]
                assert notnull == 0 and default is None
            assert set(cols) == {c.name for c in ClosedPositionModel.__table__.columns}
            assert db.execute(f"SELECT {_OLD_COLS} FROM closed_positions").fetchone() == _OLD_ROW
            assert db.execute(
                "SELECT exit_reason, stop_at_close, structural_stop_at_close, "
                "premium_stop_pct_at_close, premium_stop_price_at_close FROM closed_positions"
            ).fetchone() == (None, None, None, None, None)

        get_settings.cache_clear()
        command.downgrade(cfg, _PREV_HEAD)
        with sqlite3.connect(db_path) as db:
            assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == _PREV_HEAD
            cols = {row[1] for row in db.execute("PRAGMA table_info(closed_positions)")}
            assert not (_NEW_COLUMNS & cols)
            assert db.execute(f"SELECT {_OLD_COLS} FROM closed_positions").fetchone() == _OLD_ROW
            assert db.execute("SELECT COUNT(*) FROM closed_positions").fetchone()[0] == 1


def test_postgres_upgrade_and_downgrade_keep_the_row():
    """Runs only against EXIT_RECORD_TEST_POSTGRES_URL, which must name a
    throwaway database (postgresql+asyncpg://...). The test creates
    closed_positions and alembic_version there and drops both afterwards; it
    refuses to run if either already exists."""
    url = os.getenv("EXIT_RECORD_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("EXIT_RECORD_TEST_POSTGRES_URL not supplied")

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

    existing = asyncio.run(run([], fetch=(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = current_schema() "
        "AND table_name IN ('closed_positions', 'alembic_version')")))
    if existing:
        pytest.fail(f"EXIT_RECORD_TEST_POSTGRES_URL is not a throwaway database: {existing}")

    columns_sql = ("SELECT column_name, is_nullable, column_default FROM information_schema.columns "
                   "WHERE table_schema = current_schema() AND table_name = 'closed_positions'")
    cfg = _alembic_config()
    try:
        asyncio.run(run([_CREATE_CLOSED_AT_PREV_HEAD, _INSERT_OLD_ROW]))
        with _DatabaseUrl(url):
            command.stamp(cfg, _PREV_HEAD)
            get_settings.cache_clear()
            command.upgrade(cfg, _REVISION)
            cols = {c[0]: c for c in asyncio.run(run([], fetch=columns_sql))}
            assert _NEW_COLUMNS <= set(cols)
            for name in _NEW_COLUMNS:
                assert cols[name][1] == "YES" and cols[name][2] is None
            assert asyncio.run(run([], fetch=f"SELECT {_OLD_COLS} FROM closed_positions")) == [_OLD_ROW]
            assert asyncio.run(run([], fetch=(
                "SELECT exit_reason, stop_at_close, structural_stop_at_close, "
                "premium_stop_pct_at_close, premium_stop_price_at_close FROM closed_positions"
            ))) == [(None, None, None, None, None)]

            get_settings.cache_clear()
            command.downgrade(cfg, _PREV_HEAD)
            cols = {c[0] for c in asyncio.run(run([], fetch=columns_sql))}
            assert not (_NEW_COLUMNS & cols)
            assert asyncio.run(run([], fetch=f"SELECT {_OLD_COLS} FROM closed_positions")) == [_OLD_ROW]
    finally:
        asyncio.run(run(["DROP TABLE IF EXISTS closed_positions",
                         "DROP TABLE IF EXISTS alembic_version"]))
