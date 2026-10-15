"""Alembic upgrade installs the attempt ledger without inventing history."""
import asyncio
import os
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.broker_attempt import BrokerAttempt, ExposureGuard, ExposureHold
from app.models.portfolio import PortfolioPositionModel
from app.services.broker_attempts import BrokerAttemptService

_BACKEND = Path(__file__).resolve().parents[1]
_HEAD = "a93b8d24f760"
_REVISION = "bpr001"


def _payload():
    return {
        "kind": "option",
        "broker": "tradier_paper",
        "symbol": "AAPL",
        "instrument": "AAPL260620C00185000",
        "action": "BUY",
        "effect": "OPEN",
        "quantity": 1,
        "order_type": "LMT",
        "limit": "2.50",
        "tif": "DAY",
        "conid": 111,
    }


def test_upgrade_preserves_daily_risk_and_restart_reads_attempt(tmp_path):
    db_path = tmp_path / "existing.db"
    with sqlite3.connect(db_path) as db:
        db.execute(
            "CREATE TABLE portfolio_positions ("
            "id TEXT PRIMARY KEY, rec_id TEXT NOT NULL, symbol TEXT NOT NULL,"
            "contract TEXT NOT NULL, direction TEXT NOT NULL,"
            "entry_price FLOAT NOT NULL, qty INTEGER NOT NULL, entry_date TEXT NOT NULL)"
        )
        db.execute(
            "INSERT INTO portfolio_positions "
            "(id, rec_id, symbol, contract, direction, entry_price, qty, entry_date) "
            "VALUES ('pos-1', 'rec-1', 'AAPL', 'AAPL|STOCK', 'Bullish', 10.5, 2, '2026-10-01')"
        )
        db.execute(
            "CREATE TABLE daily_risk_budgets ("
            "day TEXT PRIMARY KEY, reserved_cents INTEGER NOT NULL, loss_cents INTEGER NOT NULL)"
        )
        db.execute("INSERT INTO daily_risk_budgets VALUES ('2026-10-13', 4200, 15)")
        db.execute(
            "CREATE TABLE daily_risk_attempts ("
            "id TEXT PRIMARY KEY, day TEXT NOT NULL, reserved_cents INTEGER NOT NULL,"
            "state TEXT NOT NULL, outcome TEXT NOT NULL, instrument TEXT NOT NULL,"
            "source TEXT NOT NULL, quantity INTEGER NOT NULL, price TEXT NOT NULL,"
            "multiplier INTEGER NOT NULL)"
        )
        db.execute(
            "INSERT INTO daily_risk_attempts VALUES "
            "('legacy-risk', '2026-10-13', 4200, 'retained', '', 'AAPL|STOCK', 'manual', 2, '10.5', 1)"
        )
        db.execute(
            "CREATE TABLE daily_risk_losses ("
            "closed_id TEXT PRIMARY KEY, day TEXT NOT NULL, loss_cents INTEGER NOT NULL)"
        )
        db.execute("INSERT INTO daily_risk_losses VALUES ('closed-1', '2026-10-13', 15)")

    cfg = Config()
    cfg.set_main_option("script_location", str(_BACKEND / "migrations"))
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    get_settings.cache_clear()
    try:
        command.stamp(cfg, _HEAD)
        get_settings.cache_clear()
        command.upgrade(cfg, _REVISION)
        with sqlite3.connect(db_path) as db:
            assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == _REVISION
            assert db.execute("SELECT COUNT(*) FROM broker_attempts").fetchone()[0] == 0
            assert db.execute("SELECT prepared_order, order_attempt_id FROM portfolio_positions").fetchone() == (None, None)
            assert db.execute("SELECT reserved_cents, loss_cents FROM daily_risk_budgets").fetchone() == (4200, 15)
            assert db.execute("SELECT id, state FROM daily_risk_attempts").fetchone() == ("legacy-risk", "retained")
            assert db.execute("SELECT loss_cents FROM daily_risk_losses").fetchone() == (15,)
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert {"broker_attempts", "exposure_guards", "exposure_holds"} <= tables
            attempt_cols = {row[1] for row in db.execute("PRAGMA table_info(broker_attempts)")}
            hold_cols = {row[1] for row in db.execute("PRAGMA table_info(exposure_holds)")}
            guard_cols = {row[1] for row in db.execute("PRAGMA table_info(exposure_guards)")}
            assert attempt_cols == {column.name for column in BrokerAttempt.__table__.columns}
            assert hold_cols == {column.name for column in ExposureHold.__table__.columns}
            assert guard_cols == {column.name for column in ExposureGuard.__table__.columns}
            ddl = " ".join(row[0] or "" for row in db.execute(
                "SELECT sql FROM sqlite_master WHERE name IN ('broker_attempts', 'exposure_holds', 'exposure_guards')"
            ))
            assert "ON DELETE CASCADE" not in ddl.upper()

        url = f"sqlite+aiosqlite:///{db_path.as_posix()}"

        async def plant_and_reread():
            engine = create_async_engine(url, connect_args={"timeout": 30})
            factory = async_sessionmaker(engine, expire_on_commit=False)
            planted = await BrokerAttemptService(factory).claim("migrated-id", _payload(), saved_rec_id="rec-1")
            await engine.dispose()
            restarted_engine = create_async_engine(url, connect_args={"timeout": 30})
            restarted = async_sessionmaker(restarted_engine, expire_on_commit=False)
            seen = await BrokerAttemptService(restarted).claim("migrated-id", _payload())
            count = None
            async with restarted() as db:
                count = (await db.execute(select(func.count()).select_from(BrokerAttempt))).scalar_one()
            await restarted_engine.dispose()
            return planted, seen, count

        planted, seen, count = asyncio.run(plant_and_reread())
        assert planted.authorized is True and planted.state == "dispatching"
        assert seen.authorized is False and seen.leader is False
        assert seen.state == "dispatching" and seen.attempt_id == "migrated-id"
        assert count == 1

        get_settings.cache_clear()
        command.downgrade(cfg, _HEAD)
        with sqlite3.connect(db_path) as db:
            assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == _HEAD
            names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert "broker_attempts" not in names
            assert "exposure_guards" not in names
            assert "exposure_holds" not in names
            columns = {row[1] for row in db.execute("PRAGMA table_info(portfolio_positions)")}
            assert "prepared_order" not in columns
            assert "order_attempt_id" not in columns
            assert db.execute("SELECT rec_id, qty FROM portfolio_positions").fetchone() == ("rec-1", 2)
            assert db.execute("SELECT reserved_cents FROM daily_risk_budgets").fetchone() == (4200,)
            assert db.execute("SELECT id FROM daily_risk_attempts").fetchone() == ("legacy-risk",)
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


def test_portfolio_prepared_order_columns_are_nullable_without_a_default():
    prepared = PortfolioPositionModel.__table__.columns["prepared_order"]
    owner = PortfolioPositionModel.__table__.columns["order_attempt_id"]
    assert prepared.nullable is True and prepared.server_default is None
    assert owner.nullable is True and owner.server_default is None
    assert not BrokerAttempt.__table__.foreign_keys
    assert not ExposureHold.__table__.foreign_keys
