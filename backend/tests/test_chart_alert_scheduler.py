# backend/tests/test_chart_alert_scheduler.py
"""Background scheduler that evaluates chart-drawn alert rules even when no
chart is open, mirroring what chart.py's websocket does on candle-close."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.alert import AlertRuleModel, AlertHistoryModel  # noqa: F401


async def _make_session_factory():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return Session


def _rule_row():
    rule_json = json.dumps({'logic': 'AND', 'conditions': [{'kind': 'price', 'operator': '>', 'value': 100}]})
    return AlertRuleModel(
        id='rule-1', user_id='default', name='Rule', symbol='AAPL', interval='15min',
        enabled=True, rule_json=rule_json, cooldown_minutes=0, expiry_date=None,
        created_at='2024-01-01T00:00:00Z', last_triggered_at=None, condition_state='{}',
    )


_CANDLES_V1 = [
    {'time': f't{i}', 'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 103.0, 'volume': 1000}
    for i in range(5)
]


@pytest.mark.asyncio
async def test_tick_evaluates_each_enabled_symbol_interval_once_per_new_candle(monkeypatch):
    import app.services.chart_alert_scheduler as sched

    Session = await _make_session_factory()
    async with Session() as db:
        db.add(_rule_row())
        await db.commit()

    monkeypatch.setattr(sched, 'AsyncSessionLocal', Session)
    monkeypatch.setattr(sched, 'get_intraday', AsyncMock(return_value=_CANDLES_V1))
    monkeypatch.setattr(sched, 'compute_structure', lambda *a, **kw: [])
    mock_evaluate = AsyncMock(return_value=[])
    monkeypatch.setattr('app.routers.chart_alerts.evaluate_and_notify_for_symbol', mock_evaluate)
    sched._last_seen_candle.clear()

    await sched._tick()
    assert mock_evaluate.await_count == 1
    assert mock_evaluate.await_args.args[0] == 'AAPL'
    assert mock_evaluate.await_args.args[1] == '15min'

    # Same candles again (no new close) — must NOT re-evaluate.
    await sched._tick()
    assert mock_evaluate.await_count == 1


@pytest.mark.asyncio
async def test_tick_skips_when_no_enabled_rules(monkeypatch):
    import app.services.chart_alert_scheduler as sched

    Session = await _make_session_factory()
    monkeypatch.setattr(sched, 'AsyncSessionLocal', Session)
    get_intraday_mock = AsyncMock(return_value=_CANDLES_V1)
    monkeypatch.setattr(sched, 'get_intraday', get_intraday_mock)
    sched._last_seen_candle.clear()

    await sched._tick()
    get_intraday_mock.assert_not_awaited()
