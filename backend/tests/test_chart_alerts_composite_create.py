import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.models.alert import AlertRuleModel, AlertHistoryModel  # noqa: F401  (register tables)
from app.routers.chart_alerts import router as chart_alerts_router


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _override_get_db():
        async with Session() as session:
            yield session

    app = FastAPI()
    app.include_router(chart_alerts_router)          # prefix '/alerts' is on the router
    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await engine.dispose()


async def test_create_composite_rule_stores_typed_rule_json(client):
    body = {
        "name": "AAPL composite",
        "symbol": "aapl",
        "interval": "15m",
        "rule_type": "composite",
        "composite_def": {
            "primary": {"model": "OMM", "to_state": "Bull", "conviction_min": 60,
                        "p_stay_min": 0.7, "p_transition_min": 0.3},
            "confirmations": [], "min_confirmations": 0,
            "strategy_confirmations": [], "min_strategy_confirmations": 0,
            "horizon": "swing", "direction": "Bullish",
        },
    }
    resp = await client.post("/alerts/rules", json=body)
    assert resp.status_code == 201
    data = resp.json()
    assert data["symbol"] == "AAPL"
    assert data["rule_type"] == "composite"
    assert data["composite_def"]["primary"]["model"] == "OMM"
    # standard-shape consumers must still see an (empty) group, not the composite dict
    assert data["group"] == {"logic": "AND", "conditions": []}


async def test_replace_composite_rule_preserves_type(client):
    create = {
        "id": "cmp-put-1", "name": "n", "symbol": "MSFT", "interval": "1h",
        "rule_type": "composite",
        "composite_def": {"primary": {"model": "OMM", "to_state": "Bull"},
                          "confirmations": [], "strategy_confirmations": [],
                          "direction": "Bullish"},
    }
    await client.post("/alerts/rules", json=create)
    create["name"] = "renamed"
    resp = await client.put("/alerts/rules/cmp-put-1", json=create)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "renamed"
    assert data["rule_type"] == "composite"
    assert data["group"] == {"logic": "AND", "conditions": []}
