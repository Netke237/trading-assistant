"""Test that create_rule preserves the client-provided ID."""
from __future__ import annotations

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
    return app


@pytest.mark.asyncio
async def test_create_rule_preserves_client_id():
    app = await _make_app()
    payload = {
        "id": "client-provided-id-abc",
        "name": "Test Rule",
        "symbol": "AAPL",
        "interval": "1D",
        "enabled": True,
        "group": {"logic": "AND", "conditions": [{"kind": "price", "operator": ">", "value": 185}]},
        "cooldown_minutes": 60,
        "expiry_date": None,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        r = await client.post("/alerts/rules", json=payload)
        assert r.status_code == 201
        assert r.json()["id"] == "client-provided-id-abc"


@pytest.mark.asyncio
async def test_create_rule_generates_id_when_not_provided():
    app = await _make_app()
    payload = {
        "name": "Auto ID Rule",
        "symbol": "AAPL",
        "interval": "1D",
        "enabled": True,
        "group": {"logic": "AND", "conditions": [{"kind": "price", "operator": ">", "value": 185}]},
        "cooldown_minutes": 60,
        "expiry_date": None,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        r = await client.post("/alerts/rules", json=payload)
        assert r.status_code == 201
        assert len(r.json()["id"]) > 0
