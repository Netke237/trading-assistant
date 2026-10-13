"""STOCKS-HORIZON-T1 H6 -- a stock position raises TIME_STOP once it has been
held `hold_max_days` (end-of-day rule: days held >= hold). Options TIME_STOP
(<= 3 DTE) is unchanged; a stock row with no hold (NULL) never fires it.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.database import Base
from app.models.portfolio import PortfolioPositionModel
from app.models.position_alert import PositionAlertHistoryModel
from app.schemas import PortfolioPositionCreate, PortfolioPositionSchema

_BACKEND_DIR = Path(__file__).parent.parent


@pytest_asyncio.fixture
async def Session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 connect_args={"check_same_thread": False})
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield maker
    await engine.dispose()


async def _insert(maker, **overrides) -> None:
    row = {
        "rec_id": "REC-H6", "symbol": "AAPL", "contract": "AAPL|STOCK",
        "direction": "Bullish", "entry_price": 100.0, "qty": 10,
        "entry_date": (date.today() - timedelta(days=15)).isoformat(),
        "stop": None, "targets": [], "dte_total": 0,
    }
    row.update(overrides)
    async with maker() as db:
        db.add(PortfolioPositionModel(**row))
        await db.commit()


async def _time_stops(maker):
    from app.services.alert_generator import generate_alerts
    async with maker() as db:
        alerts = await generate_alerts(db, {"AAPL": 100.0})
        await db.commit()
    return [a for a in alerts if a.alertType == "TIME_STOP"]


@pytest.mark.asyncio
async def test_held_for_the_hold_raises_one_time_stop(Session):
    await _insert(Session, hold_max_days=15)
    alerts = await _time_stops(Session)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.referenceValue == 15.0
    assert a.kind == "Action"
    assert a.reason == "Time stop — AAPL held 15d (hold 15d)"
    assert a.recId == "REC-H6"
    async with Session() as db:
        rows = (await db.execute(select(PositionAlertHistoryModel))).scalars().all()
    assert [(r.alert_type, r.reference_value, r.reference_kind) for r in rows] == [
        ("TIME_STOP", 15.0, "days"),
    ]


@pytest.mark.asyncio
async def test_held_past_the_hold_still_raises(Session):
    await _insert(Session, hold_max_days=10)
    alerts = await _time_stops(Session)
    assert len(alerts) == 1
    assert alerts[0].reason == "Time stop — AAPL held 15d (hold 10d)"


@pytest.mark.asyncio
async def test_one_day_short_of_the_hold_raises_nothing(Session):
    await _insert(Session, entry_date=(date.today() - timedelta(days=14)).isoformat(),
                  hold_max_days=15)
    assert await _time_stops(Session) == []


@pytest.mark.asyncio
async def test_no_hold_never_raises(Session):
    await _insert(Session, hold_max_days=None,
                  entry_date=(date.today() - timedelta(days=400)).isoformat())
    assert await _time_stops(Session) == []


@pytest.mark.asyncio
async def test_a_muted_time_stop_raises_nothing(Session):
    await _insert(Session, hold_max_days=15, alert_overrides={"TIME_STOP": False})
    assert await _time_stops(Session) == []


@pytest.mark.asyncio
async def test_options_time_stop_is_unchanged(Session):
    near = (date.today() + timedelta(days=2)).isoformat()
    far = (date.today() + timedelta(days=30)).isoformat()
    await _insert(Session, rec_id="REC-OPT-NEAR", symbol="AAPL",
                  contract=f"AAPL|190|{near}|C", entry_price=4.5)
    await _insert(Session, rec_id="REC-OPT-FAR", symbol="AAPL",
                  contract=f"AAPL|200|{far}|C", entry_price=4.5)
    alerts = await _time_stops(Session)
    assert [(a.recId, a.reason) for a in alerts] == [
        ("REC-OPT-NEAR", "Time stop — AAPL 2 DTE"),
    ]


def test_hold_max_days_survives_a_create_in_both_naming_conventions():
    base = dict(recId="R", symbol="AAPL", contract="AAPL|STOCK", direction="Bullish",
                entryPrice=100.0, qty=1, entryDate="2026-10-01", stop=None, targets=[])
    assert PortfolioPositionCreate(**base, holdMaxDays=185).holdMaxDays == 185
    assert PortfolioPositionCreate(**base, hold_max_days=185).holdMaxDays == 185
    assert PortfolioPositionCreate.model_validate({**base, "hold_max_days": 185}).holdMaxDays == 185
    assert PortfolioPositionCreate(**base).holdMaxDays is None


def test_response_schema_carries_hold_max_days():
    from datetime import datetime, timezone
    import uuid
    row = PortfolioPositionModel(
        id=uuid.uuid4(), rec_id="R", symbol="AAPL", contract="AAPL|STOCK",
        direction="Bullish", entry_price=100.0, qty=1, entry_date="2026-10-01",
        targets=[], created_at=datetime.now(timezone.utc), hold_max_days=45,
    )
    assert PortfolioPositionSchema.from_orm_model(row).holdMaxDays == 45
    row.hold_max_days = None
    assert PortfolioPositionSchema.from_orm_model(row).holdMaxDays is None


@pytest.mark.asyncio
async def test_create_position_stores_the_hold(Session, monkeypatch):
    from copy import deepcopy
    from app.services import portfolio_risk
    from app.services.position_writer import create_position
    config = deepcopy(portfolio_risk._load_config())
    config.setdefault("portfolio", {})["portfolio_value"] = 1_000_000
    monkeypatch.setattr(portfolio_risk, "_load_config", lambda: config)
    body = PortfolioPositionCreate(
        recId="REC-HOLD", symbol="AAPL", contract="AAPL|STOCK", direction="Bullish",
        entryPrice=100.0, qty=1, entryDate="2026-10-01", stop=None, targets=[],
        portfolioValue=1_000_000, hold_max_days=185,
    )
    with patch("app.services.position_writer.fetch_contract_quote_async",
               new=AsyncMock(return_value=None)):
        async with Session() as db:
            await create_position(body, db)
    async with Session() as db:
        rows = (await db.execute(select(PortfolioPositionModel))).scalars().all()
    assert [(r.rec_id, r.hold_max_days) for r in rows] == [("REC-HOLD", 185)]


def test_a_migration_adds_the_nullable_hold_column():
    """The hold migration stays on the single upgrade chain as later revisions land."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    cfg = Config(str(_BACKEND_DIR / "migrations" / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1
    hold_revision = "e7b2d4a91c58"
    ancestry = {revision.revision for revision in script.iterate_revisions(heads[0], "base")}
    assert hold_revision in ancestry
    src = Path(script.get_revision(hold_revision).path).read_text(encoding="utf-8")
    assert "'portfolio_positions'" in src and "'hold_max_days'" in src
    assert "nullable=True" in src
