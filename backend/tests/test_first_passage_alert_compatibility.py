# backend/tests/test_first_passage_alert_compatibility.py
"""Alerting groundwork verification for the profit-target/first-passage feature.

The feature adds new configurable T1/T2/T3 profit percentages and an
on-demand Monte Carlo estimate, but deliberately does NOT change the shape
of `targets`/`stop` that a portfolio position stores, or touch
alert_generator.py at all — the claim is that alert_generator's existing
TP_HIT/STOP_REACHED logic already covers a position built from this
feature's numbers, for free. This test verifies that claim against the real
generate_alerts() function rather than leaving it as a docstring assertion.
"""
from __future__ import annotations

import uuid

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
        id=uuid.uuid4(), rec_id='rec-fp-1', symbol='AAPL', contract='AAPL|105|2099-01-01|C',
        direction='Bullish', entry_price=2.50, qty=1, entry_date='2024-01-01',
        stop=95.0, targets=[{'stock_price': 120.0}], dte_total=45,
        entry_stock_price=100.0, alert_state={},
    )
    base.update(overrides)
    return PortfolioPositionModel(**base)


@pytest.mark.asyncio
async def test_bullish_position_using_new_target_shape_still_fires_tp_hit():
    # Stock price shaped as a T1 solved from the new target_t1_pct=0.20 ladder
    # would look like — the exact number doesn't matter to generate_alerts,
    # only that the shape (a JSON list of dicts with stock_price) is honored.
    Session = await _make_session_factory()
    async with Session() as db:
        db.add(_position(direction='Bullish', targets=[{'stock_price': 104.4}], stop=95.0))
        await db.commit()
        alerts = await generate_alerts(db, {'AAPL': 105.0})
    assert any(a.alertType == 'TP_HIT' for a in alerts)


@pytest.mark.asyncio
async def test_bullish_position_using_new_stop_still_fires_stop_reached():
    Session = await _make_session_factory()
    async with Session() as db:
        db.add(_position(direction='Bullish', targets=[{'stock_price': 104.4}], stop=95.0))
        await db.commit()
        alerts = await generate_alerts(db, {'AAPL': 94.0})
    assert any(a.alertType == 'STOP_REACHED' for a in alerts)


@pytest.mark.asyncio
async def test_bearish_position_using_new_target_shape_still_fires_tp_hit():
    # A put's T1 solved from the same ladder sits BELOW entry, per
    # first_passage.py's put/call symmetry — confirm the alert side (which
    # already has its own direction-aware compare) still agrees.
    Session = await _make_session_factory()
    async with Session() as db:
        db.add(_position(
            direction='Bearish', contract='AAPL|95|2099-01-01|P',
            targets=[{'stock_price': 95.8}], stop=105.0,
        ))
        await db.commit()
        alerts = await generate_alerts(db, {'AAPL': 95.0})
    assert any(a.alertType == 'TP_HIT' for a in alerts)


@pytest.mark.asyncio
async def test_bearish_position_using_new_stop_still_fires_stop_reached():
    Session = await _make_session_factory()
    async with Session() as db:
        db.add(_position(
            direction='Bearish', contract='AAPL|95|2099-01-01|P',
            targets=[{'stock_price': 95.8}], stop=105.0,
        ))
        await db.commit()
        alerts = await generate_alerts(db, {'AAPL': 106.0})
    assert any(a.alertType == 'STOP_REACHED' for a in alerts)
