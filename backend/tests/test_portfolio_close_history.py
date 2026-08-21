# backend/tests/test_portfolio_close_history.py
"""Integration tests for the portfolio close/history/performance endpoints.

Self-contained: builds a small app with ONLY the portfolio router, backed by an
in-memory SQLite DB with the real Base metadata, and stubs the live Tradier quote
so exit-price auto-fill is deterministic.
"""
from __future__ import annotations

from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.database import Base, get_db
from app.models.portfolio import PortfolioPositionModel
from app.routers.portfolio import router as portfolio_router


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 connect_args={"check_same_thread": False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _get_db():
        async with Session() as s:
            yield s

    test_app = FastAPI()
    test_app.include_router(portfolio_router)
    test_app.dependency_overrides[get_db] = _get_db
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://t") as c:
        yield c
    await engine.dispose()


@pytest_asyncio.fixture
async def client_with_session():
    """Same as `client`, but also yields the sessionmaker so a test can insert a
    row directly — needed to construct portfolio states the risk engine would
    reject via the public POST endpoint (see max_same_symbol_positions: 1)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 connect_args={"check_same_thread": False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _get_db():
        async with Session() as s:
            yield s

    test_app = FastAPI()
    test_app.include_router(portfolio_router)
    test_app.dependency_overrides[get_db] = _get_db
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://t") as c:
        yield c, Session
    await engine.dispose()


async def _add(client, contract="AAPL|185|2026-09-18|C", qty=5, entry=1.00, rec="REC-1"):
    # Avoid the risk-engine 422 by using a large portfolio value.
    body = {"recId": rec, "symbol": "AAPL", "contract": contract, "direction": "Bullish",
            "entryPrice": entry, "qty": qty, "entryDate": "2026-05-01",
            "stop": None, "targets": [], "dteTotal": 140, "portfolioValue": 1_000_000}
    # add_position now re-fetches a live premium at save time to keep entry_price
    # fresh. Stub it to None so these tests use the supplied entryPrice
    # deterministically (the "no live quote available" fallback path).
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value=None)):
        r = await client.post("/api/portfolio", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ── add_position risk check uses the LIVE-refetched price, not the submitted
# entryPrice — this is the actual behavior the fix set out to guarantee, so it
# needs its own direct coverage rather than always mocking the live fetch away.

@pytest.mark.asyncio
async def test_add_position_risk_check_rejects_based_on_live_price(client):
    """A submitted entryPrice that alone would pass the exposure gate must
    still be rejected if the LIVE quote pushes capital-at-risk over the limit —
    proving the risk check evaluates the price that actually gets persisted,
    not the frontend-supplied one."""
    body = {
        "recId": "REC-RISK-LIVE-1", "symbol": "AAPL", "contract": "AAPL|185|2026-09-18|C",
        "direction": "Bullish", "entryPrice": 1.00, "qty": 1, "entryDate": "2026-05-01",
        "stop": None, "targets": [], "dteTotal": 140, "portfolioValue": 10_000.0,
    }
    # max_single_trade_exposure_pct=0.05 * $10,000 = $500 cap.
    # Submitted entryPrice=1.00 -> capital_at_risk=$100 (would pass).
    # Live quote=10.00 -> capital_at_risk=$1000 (must be rejected).
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value={"price": 10.00, "delta": 0.5, "theta": -0.05, "ivRank": 50, "spread": 0.1, "volume": 100})):
        r = await client.post("/api/portfolio", json=body)
    assert r.status_code == 422, r.text
    assert "exposure" in r.text or "reduced" in r.text


@pytest.mark.asyncio
async def test_add_position_persists_and_risk_checks_the_live_price_not_submitted(client):
    """The inverse: a submitted entryPrice that WOULD be rejected must be
    approved (and stored) using a live quote that actually fits the exposure
    limit — proving neither the risk check nor the persisted entry_price uses
    the stale/submitted value once a live quote is available."""
    body = {
        "recId": "REC-RISK-LIVE-2", "symbol": "MSFT", "contract": "MSFT|400|2026-09-18|C",
        "direction": "Bullish", "entryPrice": 10.00, "qty": 1, "entryDate": "2026-05-01",
        "stop": None, "targets": [], "dteTotal": 140, "portfolioValue": 10_000.0,
    }
    # Submitted entryPrice=10.00 -> capital_at_risk=$1000 (would be rejected).
    # Live quote=1.00 -> capital_at_risk=$100 (fits) -> must be approved AND
    # the live 1.00 (not the submitted 10.00) must be what's persisted.
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value={"price": 1.00, "delta": 0.5, "theta": -0.05, "ivRank": 50, "spread": 0.1, "volume": 100})):
        r = await client.post("/api/portfolio", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["entryPrice"] == 1.00


@pytest.mark.asyncio
async def test_full_close_records_history_and_removes_open(client):
    await _add(client, qty=3, entry=1.00)
    r = await client.post("/api/portfolio/REC-1/close",
                          json={"qtyToClose": None, "exitPrice": 1.50, "exitDate": "2026-05-31"})
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["qtyClosed"] == 3
    assert rec["realizedPnlDollar"] == 150.0   # (1.50-1.00)*100*3
    assert rec["realizedPnlPct"] == 50.0
    # open position gone
    assert (await client.get("/api/portfolio")).json() == []  # type: ignore
    # history has the one record
    hist = (await client.get("/api/portfolio/history")).json()
    assert len(hist) == 1 and hist[0]["recId"] == "REC-1"


@pytest.mark.asyncio
async def test_partial_close_reduces_qty_and_keeps_open(client):
    await _add(client, qty=5, entry=1.00)
    r = await client.post("/api/portfolio/REC-1/close",
                          json={"qtyToClose": 2, "exitPrice": 2.00, "exitDate": "2026-05-31"})
    assert r.status_code == 201, r.text
    assert r.json()["qtyClosed"] == 2
    # Non-integer ivRank exercises the int() cast at portfolio.py's enrichment
    # assignment — must round to a plain int, never leak the raw float (which
    # would trip a Pydantic serialization warning against the Optional[int] field).
    with (
        patch("app.routers.portfolio.fetch_contract_quote_async",
              new=AsyncMock(return_value={"price": 1.80, "delta": 0.5, "theta": -0.05, "ivRank": 40.9})),
        patch("app.routers.portfolio.fetch_price_async", new=AsyncMock(return_value=150.0)),
    ):
        open_positions = (await client.get("/api/portfolio")).json()
    assert len(open_positions) == 1
    assert open_positions[0]["qty"] == 3        # 5 - 2 remaining
    assert open_positions[0]["ivRank"] == 41
    assert open_positions[0]["currentStockPrice"] == 150.0
    hist = (await client.get("/api/portfolio/history")).json()
    assert len(hist) == 1 and hist[0]["qtyClosed"] == 2


@pytest.mark.asyncio
async def test_close_auto_fills_exit_price_from_quote(client):
    await _add(client, qty=1, entry=1.00)
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               return_value={"price": 1.80}):
        r = await client.post("/api/portfolio/REC-1/close", json={})
    assert r.status_code == 201, r.text
    assert r.json()["exitPrice"] == 1.80
    assert r.json()["realizedPnlDollar"] == 80.0


@pytest.mark.asyncio
async def test_close_missing_position_404(client):
    r = await client.post("/api/portfolio/NOPE/close", json={"exitPrice": 1.0})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_performance_buckets_and_curve(client):
    await _add(client, qty=4, entry=1.00, rec="REC-A")
    # close 2 today at 1.50 -> +100
    await client.post("/api/portfolio/REC-A/close",
                      json={"qtyToClose": 2, "exitPrice": 1.50, "exitDate": "2026-05-31"})
    perf = (await client.get("/api/portfolio/performance")).json()
    assert perf["realizedYear"] == 100.0
    assert perf["realizedCurve"][-1]["value"] == 100.0


@pytest.mark.asyncio
async def test_get_portfolio_upserts_one_snapshot_per_day(client):
    await _add(client, qty=1, entry=1.00)
    with (
        patch("app.routers.portfolio.fetch_contract_quote_async", return_value={"price": 1.20}),
        patch("app.routers.portfolio.fetch_price_async", return_value=100.0),
    ):
        await client.get("/api/portfolio")
        await client.get("/api/portfolio")  # second call same day must not duplicate
    perf = (await client.get("/api/portfolio/performance")).json()
    # exactly one equity point for today
    assert len(perf["equityCurve"]) == 1
    # total = realized(0) + open(1.20*100*1 = 120)
    assert perf["equityCurve"][0]["value"] == 120.0


@pytest.mark.asyncio
async def test_get_portfolio_dedupes_stock_price_fetch_by_symbol(client_with_session):
    """Two option contracts on the same underlying must fetch the live stock price
    ONCE, not once per contract — proves the option_symbols dedup actually dedupes.
    The second position is inserted directly (see fixture docstring): the risk engine
    blocks creating it via POST, so this specific two-same-symbol-options state can only
    arise from data already in the DB (a pre-existing row, or a risk-config change), not
    from the live add flow — the dedup logic is still real code worth covering directly."""
    client, Session = client_with_session
    with patch("app.routers.portfolio.fetch_contract_quote_async", new=AsyncMock(return_value=None)):
        await _add(client, contract="AAPL|180|2026-09-18|C", rec="REC-A1")

    async with Session() as s:
        s.add(PortfolioPositionModel(
            rec_id="REC-A2", symbol="AAPL", contract="AAPL|190|2026-09-18|C",
            direction="Bullish", entry_price=1.0, qty=1, entry_date="2026-05-01",
            stop=None, targets=[], dte_total=140,
        ))
        await s.commit()

    call_count = {"n": 0}
    async def _fake_price(client, symbol):
        call_count["n"] += 1
        return 175.0

    with (
        patch("app.routers.portfolio.fetch_contract_quote_async",
              new=AsyncMock(return_value={"price": 1.0, "delta": 0.5, "theta": -0.05, "ivRank": 40})),
        patch("app.routers.portfolio.fetch_price_async", new=_fake_price),
    ):
        open_positions = (await client.get("/api/portfolio")).json()

    assert len(open_positions) == 2
    assert call_count["n"] == 1  # one AAPL fetch, not two
    assert {p["currentStockPrice"] for p in open_positions} == {175.0}


@pytest.mark.asyncio
async def test_get_portfolio_stock_leg_mirrors_current_price_not_fetched_separately(client):
    """A |STOCK position's currentStockPrice must equal its own currentPrice, and must
    NOT trigger a separate fetch_price_async call (it's not in option_symbols).

    Uses an explicit call-count (not a raising side_effect) — get_portfolio calls
    fetch_price_async inside `asyncio.gather(..., return_exceptions=True)`, so a raised
    exception would just be swallowed as a captured result rather than failing the test."""
    with patch("app.routers.portfolio.fetch_contract_quote_async", new=AsyncMock(return_value=None)):
        await _add(client, contract="MSFT|STOCK", rec="REC-S1")

    call_count = {"n": 0}
    async def _fake_price(client, symbol):
        call_count["n"] += 1
        return 999.0

    with (
        patch("app.routers.portfolio.fetch_contract_quote_async",
              new=AsyncMock(return_value={"price": 410.5})),
        patch("app.routers.portfolio.fetch_price_async", new=_fake_price),
    ):
        open_positions = (await client.get("/api/portfolio")).json()

    assert call_count["n"] == 0  # not called for a stock-only portfolio
    assert open_positions[0]["currentPrice"] == 410.5
    assert open_positions[0]["currentStockPrice"] == 410.5
