"""Editing a rule's conditions via PUT must reset condition_state -- otherwise
a stale sustain-clock entry left over from the OLD condition list gets
misapplied to whatever condition now sits at that same positional index,
letting it fire instantly instead of respecting its own sustain window."""
from __future__ import annotations

import json

import pytest
from httpx import AsyncClient, ASGITransport


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
    return app, Session


@pytest.mark.asyncio
async def test_replace_rule_resets_condition_state():
    app, Session = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        create_payload = {
            "id": "rule-edit-test",
            "name": "Original",
            "symbol": "AAPL",
            "interval": "1D",
            "enabled": True,
            "group": {"logic": "AND", "conditions": [
                {"kind": "price", "operator": ">", "value": 185, "sustain_minutes": 5},
            ]},
            "cooldown_minutes": 0,
            "expiry_date": None,
        }
        r = await client.post("/alerts/rules", json=create_payload)
        assert r.status_code == 201

    # Simulate the sustain clock having accumulated pending state for the OLD
    # condition-0 (as evaluate_and_notify_for_symbol would persist mid-window).
    from app.models.alert import AlertRuleModel
    from sqlalchemy import select
    async with Session() as db:
        row = (await db.execute(
            select(AlertRuleModel).where(AlertRuleModel.id == "rule-edit-test")
        )).scalar_one()
        row.condition_state = json.dumps({"0": "2020-01-01T00:00:00"})  # ancient pending_since
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        replace_payload = {
            "name": "Edited",
            "symbol": "AAPL",
            "interval": "1D",
            "enabled": True,
            "group": {"logic": "AND", "conditions": [
                {"kind": "indicator", "indicator": "RSI", "operator": ">", "value": 70, "sustain_minutes": 10},
            ]},
            "cooldown_minutes": 0,
            "expiry_date": None,
        }
        r = await client.put("/alerts/rules/rule-edit-test", json=replace_payload)
        assert r.status_code == 200

    async with Session() as db:
        row = (await db.execute(
            select(AlertRuleModel).where(AlertRuleModel.id == "rule-edit-test")
        )).scalar_one()
        assert json.loads(row.condition_state) == {}
