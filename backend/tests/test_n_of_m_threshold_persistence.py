"""Regression coverage for the N_OF_M threshold bug: ConditionGroupIn never
declared n_of_m_threshold, so FastAPI/Pydantic silently dropped it from every
saved rule, and _deserialize_rule() never read it back even when present.
Net effect: every N_OF_M rule ran as "any 1 condition fires" regardless of
the threshold configured in the UI. See docs/superpowers/plans/
2026-07-30-alert-notification-followups.md for the full root-cause writeup.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import AsyncClient, ASGITransport

from app.routers.chart_alerts import _deserialize_rule


async def _make_app():
    from fastapi import FastAPI
    from app.database import Base, get_db
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.models.alert import AlertRuleModel, AlertHistoryModel  # noqa: F401

    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with Session() as session:
            yield session

    from app.routers.chart_alerts import router as chart_alerts_router

    app = FastAPI()
    app.include_router(chart_alerts_router)
    app.dependency_overrides[get_db] = override_get_db
    return app


def _n_of_m_rule_body(threshold: int = 2):
    return {
        'name': 'N of M test rule', 'symbol': 'AAPL', 'interval': '15min', 'enabled': True,
        'group': {
            'logic': 'N_OF_M',
            'n_of_m_threshold': threshold,
            'conditions': [
                {'kind': 'price', 'operator': '>', 'value': 100},
                {'kind': 'price', 'operator': '<', 'value': 50},
            ],
        },
        'cooldown_minutes': 60, 'expiry_date': None,
    }


@pytest.mark.asyncio
async def test_n_of_m_threshold_round_trips_through_create_and_get():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/alerts/rules', json=_n_of_m_rule_body(threshold=2))
        assert resp.status_code == 201
        rule_id = resp.json()['id']
        assert resp.json()['group']['n_of_m_threshold'] == 2

        resp2 = await client.get(f'/alerts/rules/{rule_id}')
        assert resp2.status_code == 200
        assert resp2.json()['group']['n_of_m_threshold'] == 2


@pytest.mark.asyncio
async def test_n_of_m_threshold_is_enforced_by_test_rule_endpoint():
    """With threshold=2 and only 1 of 2 conditions satisfiable by the test
    candle, the rule must NOT fire. Pre-fix, this fired anyway because the
    threshold was silently coerced to 1 by the time it reached evaluate_rules().
    """
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/alerts/rules', json=_n_of_m_rule_body(threshold=2))
        rule_id = resp.json()['id']

        # close=190 satisfies "price > 100" but not "price < 50" -- 1 of 2 met.
        candle = {'time': '2024-01-05T00:00:00', 'open': 188, 'high': 192, 'low': 187, 'close': 190}
        test_resp = await client.post(f'/alerts/rules/{rule_id}/test', json={'candles': [candle]})
        assert test_resp.status_code == 200
        assert test_resp.json()['matches'] == []


@pytest.mark.asyncio
async def test_n_of_m_threshold_of_one_still_fires_with_one_condition_met():
    """Sanity check the same rule DOES fire once threshold=1 -- proves the
    previous test's empty result is the threshold being enforced, not some
    unrelated evaluation failure.
    """
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/alerts/rules', json=_n_of_m_rule_body(threshold=1))
        rule_id = resp.json()['id']

        candle = {'time': '2024-01-05T00:00:00', 'open': 188, 'high': 192, 'low': 187, 'close': 190}
        test_resp = await client.post(f'/alerts/rules/{rule_id}/test', json={'candles': [candle]})
        assert test_resp.status_code == 200
        assert len(test_resp.json()['matches']) == 1


def test_legacy_rule_without_stored_threshold_still_defaults_to_none():
    """Pins the required backward-compatible behavior: a rule saved before this
    fix has rule_json with no 'n_of_m_threshold' key at all (the value was
    never persisted, so there's nothing to migrate). _deserialize_rule must
    keep producing n_of_m_threshold=None for these rows so evaluate_rules()'s
    `or 1` fallback keeps their existing runtime behavior unchanged.
    """
    row = SimpleNamespace(
        id='legacy-1', name='Legacy rule', symbol='AAPL', interval='15min', enabled=True,
        cooldown_minutes=60, expiry_date=None, created_at='2026-01-01T00:00:00',
        last_triggered_at=None, condition_state='{}',
    )
    legacy_rule_json = (
        '{"logic": "N_OF_M", "conditions": '
        '[{"kind": "price", "operator": ">", "value": 100}, '
        '{"kind": "price", "operator": "<", "value": 50}]}'
    )
    rule_input = _deserialize_rule(legacy_rule_json, row)
    assert rule_input.group.n_of_m_threshold is None
