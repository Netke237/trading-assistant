# backend/tests/test_alert_generator_sustain.py
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.portfolio import PortfolioPositionModel
from app.services.alert_generator import generate_alerts


async def _make_session_factory():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return Session


def _position(**overrides) -> PortfolioPositionModel:
    base = dict(
        id=uuid.uuid4(), rec_id='rec-1', symbol='AAPL', contract='AAPL|150|2099-01-01|C',
        direction='Bullish', entry_price=5.0, qty=1, entry_date='2024-01-01',
        stop=140.0, targets=[{'stock_price': 200.0}], dte_total=30,
        entry_stock_price=145.0, alert_state={},
    )
    base.update(overrides)
    return PortfolioPositionModel(**base)


@pytest.mark.asyncio
async def test_stop_reached_not_fired_on_first_sustain_check():
    Session = await _make_session_factory()
    async with Session() as db:
        db.add(_position())
        await db.commit()
        alerts = await generate_alerts(db, {'AAPL': 130.0}, sustain_minutes=5)
    assert not any(a.alertType == 'STOP_REACHED' for a in alerts)


@pytest.mark.asyncio
async def test_stop_reached_fires_after_sustain_window_elapses():
    Session = await _make_session_factory()
    async with Session() as db:
        past = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
        db.add(_position(alert_state={'STOP_REACHED': past}))
        await db.commit()
        alerts = await generate_alerts(db, {'AAPL': 130.0}, sustain_minutes=5)
    assert any(a.alertType == 'STOP_REACHED' for a in alerts)


@pytest.mark.asyncio
async def test_stop_reached_clock_resets_when_price_recovers():
    Session = await _make_session_factory()
    async with Session() as db:
        past = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
        pos = _position(alert_state={'STOP_REACHED': past})
        db.add(pos)
        await db.commit()
        # Price back above the stop this check — clock must clear.
        await generate_alerts(db, {'AAPL': 150.0}, sustain_minutes=5)
        await db.commit()
        from sqlalchemy import select
        refreshed = (await db.execute(select(PortfolioPositionModel))).scalar_one()
        assert 'STOP_REACHED' not in (refreshed.alert_state or {})


@pytest.mark.asyncio
async def test_zero_sustain_minutes_fires_instantly_as_before():
    Session = await _make_session_factory()
    async with Session() as db:
        db.add(_position())
        await db.commit()
        alerts = await generate_alerts(db, {'AAPL': 130.0})  # sustain_minutes defaults to 0
    assert any(a.alertType == 'STOP_REACHED' for a in alerts)


@pytest.mark.asyncio
async def test_stop_reached_corrupted_alert_state_does_not_raise_or_fire():
    """A corrupted alert_state entry must restart the clock and suppress the
    fire, not raise -- an unhandled ValueError here would abort alert
    generation for every remaining position in this tick, not just this one.
    Regression test mirroring the composite-path fail-open fix, applied to
    the portfolio position sustain path."""
    Session = await _make_session_factory()
    async with Session() as db:
        db.add(_position(alert_state={'STOP_REACHED': 'not-a-valid-timestamp'}))
        await db.commit()
        alerts = await generate_alerts(db, {'AAPL': 130.0}, sustain_minutes=5)
        await db.commit()
        from sqlalchemy import select
        refreshed = (await db.execute(select(PortfolioPositionModel))).scalar_one()
    assert not any(a.alertType == 'STOP_REACHED' for a in alerts)
    # Clock was restarted (a fresh ISO timestamp), not left corrupted.
    datetime.fromisoformat(refreshed.alert_state['STOP_REACHED'])
