# backend/tests/test_alert_rule_disabled_cannot_fire.py
"""Formalizes the ghost-alert audit finding: evaluate_and_notify_for_symbol's
query (chart_alerts.py:502) filters AlertRuleModel.enabled == True at the SQL
level, so a disabled rule is excluded before any condition matching happens --
not filtered out afterward. This plants an enabled and a disabled rule with
IDENTICAL matching conditions on the same symbol/interval and asserts only
the enabled one ever fires, and that no AlertHistoryModel row is ever created
for the disabled one. Live data audited 2026-07-17: alert_history had zero
rows ever, and the one real alert_rules row (enabled) had never triggered --
no evidence of a disabled rule having fired historically either."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.alert import AlertHistoryModel, AlertRuleModel


async def _make_session_factory():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return Session


def _rule(rule_id: str, enabled: bool) -> AlertRuleModel:
    # Condition is always true (price > -1) so if the disabled rule were ever
    # evaluated, it would trigger -- this isolates "does enabled=False get
    # respected" from "does the condition happen to be false right now".
    rule_json = json.dumps({'logic': 'AND', 'conditions': [{'kind': 'price', 'operator': '>', 'value': -1}]})
    return AlertRuleModel(
        id=rule_id, user_id='default', name=f'Rule {rule_id}', symbol='AAPL', interval='15min',
        enabled=enabled, rule_json=rule_json, cooldown_minutes=0, expiry_date=None,
        created_at='2024-01-01T00:00:00Z', last_triggered_at=None, condition_state='{}',
    )


_CANDLES = [
    {'time': f't{i}', 'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 103.0, 'volume': 1000}
    for i in range(3)
]


@pytest.mark.asyncio
async def test_disabled_rule_never_fires_even_with_matching_conditions(monkeypatch):
    import app.routers.chart_alerts as chart_alerts

    Session = await _make_session_factory()
    async with Session() as db:
        db.add(_rule('enabled-rule', enabled=True))
        db.add(_rule('disabled-rule', enabled=False))
        await db.commit()

    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    monkeypatch.setattr(chart_alerts, 'build_regime_snapshot', lambda *a, **kw: None)
    monkeypatch.setattr(chart_alerts, 'compute_indicators_for_conditions', lambda *a, **kw: {})
    monkeypatch.setattr(chart_alerts, '_load_notification_config', lambda: {})

    triggered = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '15min', _CANDLES[-1], _CANDLES, [],
    )

    triggered_rule_ids = {t['rule_id'] for t in triggered}
    assert 'enabled-rule' in triggered_rule_ids
    assert 'disabled-rule' not in triggered_rule_ids

    async with Session() as db:
        history = (await db.execute(select(AlertHistoryModel))).scalars().all()
        history_rule_ids = {h.rule_id for h in history}
        assert 'enabled-rule' in history_rule_ids
        assert 'disabled-rule' not in history_rule_ids
