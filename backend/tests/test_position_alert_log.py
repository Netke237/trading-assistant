"""Tests for position_alert_log.py (position_alert_history persistence).

Covers: log_position_alert's own dedup window (one row per reminder window,
not per call), that it persists regardless of notify_alert's masterEnabled/
enabledTypes gating (verified via generate_alerts, which never reads that
config at all), and prune_position_alert_history's retention cutoff.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.database import Base
from app.models.portfolio import PortfolioPositionModel
from app.models.position_alert import PositionAlertHistoryModel

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_db():
    from app.models import portfolio, watchlist, audit_event, position_alert  # noqa: F401
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session():
    async with TestSessionLocal() as session:
        yield session


async def _insert_position(db: AsyncSession, **overrides) -> PortfolioPositionModel:
    defaults = {
        "rec_id": "REC-TEST-001",
        "symbol": "AAPL",
        "contract": "AAPL|190|2026-05-16|C",
        "direction": "Bullish",
        "entry_price": 4.50,
        "qty": 2,
        "entry_date": "2026-04-08",
        "stop": 3.00,
        "targets": [{"stockPrice": 210.0, "targetPrice": 9.0}],
    }
    defaults.update(overrides)
    pos = PortfolioPositionModel(**defaults)
    db.add(pos)
    await db.commit()
    return pos


# ── log_position_alert dedup ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_log_position_alert_writes_a_row(db_session):
    from app.services.position_alert_log import log_position_alert

    await log_position_alert(
        db_session, rec_id="REC-1", symbol="AAPL", alert_type="STOP_REACHED",
        source="backend", price=185.0, reference_value=190.0, reference_kind="price",
        direction="Bullish", contract="AAPL|190|2026-05-16|C",
    )
    rows = (await db_session.execute(
        select(PositionAlertHistoryModel).where(PositionAlertHistoryModel.rec_id == "REC-1")
    )).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.source == "backend"
    assert row.price == 185.0
    assert row.reference_value == 190.0
    assert row.reference_kind == "price"


@pytest.mark.asyncio
async def test_log_position_alert_dedups_within_reminder_window(db_session):
    """Two calls for the same (rec_id, alert_type, source) within the reminder
    window produce ONE row, not a firehose — this is what keeps a stop that
    stays breached for days from writing one row per tick."""
    from app.services.position_alert_log import log_position_alert

    for _ in range(3):
        await log_position_alert(
            db_session, rec_id="REC-2", symbol="AAPL", alert_type="STOP_REACHED",
            source="backend", price=185.0, reference_value=190.0, reference_kind="price",
        )
    rows = (await db_session.execute(
        select(PositionAlertHistoryModel).where(PositionAlertHistoryModel.rec_id == "REC-2")
    )).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_log_position_alert_new_row_after_reminder_window(db_session):
    """A stale row (older than reminderIntervalHours) doesn't suppress a new one."""
    from app.services.position_alert_log import log_position_alert

    stale = PositionAlertHistoryModel(
        rec_id="REC-3", symbol="AAPL", alert_type="STOP_REACHED", source="backend",
        price=185.0, reference_value=190.0, reference_kind="price",
        triggered_at=datetime.now(timezone.utc) - timedelta(hours=5),
    )
    db_session.add(stale)
    await db_session.commit()

    await log_position_alert(
        db_session, rec_id="REC-3", symbol="AAPL", alert_type="STOP_REACHED",
        source="backend", price=184.0, reference_value=190.0, reference_kind="price",
    )
    rows = (await db_session.execute(
        select(PositionAlertHistoryModel).where(PositionAlertHistoryModel.rec_id == "REC-3")
    )).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_log_position_alert_dedup_is_per_source(db_session):
    """backend and frontend firing the same condition both get a row — the
    dedup key includes source, so one engine never suppresses the other's row."""
    from app.services.position_alert_log import log_position_alert

    await log_position_alert(
        db_session, rec_id="REC-4", symbol="AAPL", alert_type="STOP_REACHED",
        source="backend", price=185.0, reference_value=190.0, reference_kind="price",
    )
    await log_position_alert(
        db_session, rec_id="REC-4", symbol="AAPL", alert_type="STOP_REACHED",
        source="frontend", price=185.5, reference_value=190.0, reference_kind="price",
    )
    rows = (await db_session.execute(
        select(PositionAlertHistoryModel).where(PositionAlertHistoryModel.rec_id == "REC-4")
    )).scalars().all()
    assert {r.source for r in rows} == {"backend", "frontend"}


# ── Persistence is independent of notify_alert's masterEnabled/enabledTypes ──

@pytest.mark.asyncio
async def test_generate_alerts_persists_time_stop(db_session):
    """TIME_STOP previously had no log_event call at all. Confirms it now
    writes a position_alert_history row (reference_kind='days', price=None)."""
    from app.services.alert_generator import generate_alerts

    near_expiry = (date.today() + timedelta(days=2)).isoformat()
    await _insert_position(
        db_session, rec_id="REC-5", contract=f"AAPL|190|{near_expiry}|C", stop=None,
    )
    await generate_alerts(db_session, {"AAPL": 200.0})

    rows = (await db_session.execute(
        select(PositionAlertHistoryModel).where(
            PositionAlertHistoryModel.rec_id == "REC-5",
            PositionAlertHistoryModel.alert_type == "TIME_STOP",
        )
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].price is None
    assert rows[0].reference_kind == "days"
    assert rows[0].reference_value == 2


@pytest.mark.asyncio
async def test_generate_alerts_persists_regardless_of_enabled_types(db_session, monkeypatch):
    """generate_alerts() never reads alert_delivery.enabledTypes — persistence
    must not depend on it, unlike notify_alert's own dispatch gating. Simulates
    a user having disabled STOP_REACHED notifications entirely and confirms the
    audit row still appears."""
    from app.services.alert_generator import generate_alerts

    await _insert_position(db_session, rec_id="REC-6", stop=190.0, direction="Bullish")
    # price below stop -> STOP_REACHED condition is met
    await generate_alerts(db_session, {"AAPL": 185.0})

    rows = (await db_session.execute(
        select(PositionAlertHistoryModel).where(
            PositionAlertHistoryModel.rec_id == "REC-6",
            PositionAlertHistoryModel.alert_type == "STOP_REACHED",
        )
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].source == "backend"
    assert rows[0].price == 185.0
    assert rows[0].reference_value == 190.0


# ── Retention ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_prune_position_alert_history_deletes_only_stale_rows(db_session):
    from app.services.position_alert_log import prune_position_alert_history

    old = PositionAlertHistoryModel(
        rec_id="REC-OLD", symbol="AAPL", alert_type="STOP_REACHED", source="backend",
        triggered_at=datetime.now(timezone.utc) - timedelta(days=45),
    )
    recent = PositionAlertHistoryModel(
        rec_id="REC-NEW", symbol="AAPL", alert_type="STOP_REACHED", source="backend",
        triggered_at=datetime.now(timezone.utc) - timedelta(days=5),
    )
    db_session.add_all([old, recent])
    await db_session.commit()

    await prune_position_alert_history(db_session, retention_days=30)

    remaining = (await db_session.execute(select(PositionAlertHistoryModel))).scalars().all()
    assert {r.rec_id for r in remaining} == {"REC-NEW"}
