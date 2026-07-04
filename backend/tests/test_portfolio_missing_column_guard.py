import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import get_db
from app.routers.portfolio import router as portfolio_router


@pytest_asyncio.fixture
async def client_drifted():
    # portfolio_positions table intentionally MISSING entry_stock_price (pre-migration shape).
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE portfolio_positions ("
            "id TEXT PRIMARY KEY, rec_id TEXT, symbol TEXT, contract TEXT, "
            "direction TEXT, entry_price FLOAT, qty INTEGER, entry_date TEXT, "
            "stop FLOAT, targets JSON, dte_total INTEGER, created_at TIMESTAMP)"
        ))
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_get_db():
        async with Session() as s:
            yield s

    app = FastAPI()
    app.include_router(portfolio_router)  # prefix '/api'
    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await engine.dispose()


async def test_get_portfolio_degrades_to_empty_on_missing_column(client_drifted):
    resp = await client_drifted.get("/api/portfolio")
    assert resp.status_code == 200
    assert resp.json() == []
