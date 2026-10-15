"""
WS-34 persistence tests.

Uses an in-memory SQLite async engine so no PostgreSQL is needed.
The get_db dependency is overridden for each test to use a fresh session
against the in-memory database.
"""
from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

# ── In-memory SQLite engine ───────────────────────────────────────────────────

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_db():
    """Create all tables before each test; drop them after."""
    from app.database import Base
    from app.models.scan_session import ScanSessionBase
    # Import models so their metadata is registered on Base.
    # log_approval takes the exposure guard, so that table has to exist too.
    import app.models  # noqa: F401
    from app.models import portfolio, watchlist, audit_event  # noqa: F401

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(ScanSessionBase.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session():
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session):
    """AsyncClient with get_db overridden to use the test SQLite session.

    add_position() re-fetches a live quote at save time (see portfolio.py) to
    keep entry_price fresh — that value now also feeds the risk check. These
    fixtures use synthetic/expired test contracts (e.g. expiry 2026-06-20 with
    a fabricated $4.50 premium), so an unmocked live fetch would substitute a
    real market quote for an unrelated live expiry and make the risk check
    (and any assertion on entry_price) nondeterministic. Mock it to "no live
    quote available" so add_position falls back to the payload's entryPrice,
    matching these tests' intent of exercising persistence/CRUD, not live data.
    """
    from app.main import app
    from app.database import get_db

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with (
        patch("app.routers.portfolio.fetch_contract_quote_async", new=AsyncMock(return_value=None)),
        patch("app.routers.portfolio.fetch_price_async", new=AsyncMock(return_value=None)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────

_POSITION_PAYLOAD = {
    "recId": "REC-20260508-AABBCCDD",
    "symbol": "AAPL",
    "contract": "AAPL|190|2026-06-20|C",
    "direction": "Bullish",
    "entryPrice": 4.50,
    "qty": 2,
    "entryDate": "2026-05-08",
    "stop": 2.25,
    "targets": [{"id": "tp1", "stockPrice": 200.0, "contractsToSell": 1, "status": "PENDING"}],
    "dteTotal": 43,
    "portfolioValue": 50_000.0,
}


# ── Test 1: Portfolio add / list ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_portfolio_add_and_list(client):
    """POST a position → GET /api/portfolio returns it."""
    post_resp = await client.post("/api/portfolio", json=_POSITION_PAYLOAD)
    assert post_resp.status_code == 201, post_resp.text

    get_resp = await client.get("/api/portfolio")
    assert get_resp.status_code == 200
    positions = get_resp.json()
    assert len(positions) == 1
    assert positions[0]["recId"] == _POSITION_PAYLOAD["recId"]
    assert positions[0]["contract"] == _POSITION_PAYLOAD["contract"]


@pytest.mark.asyncio
async def test_portfolio_create_rejects_missing_rec_id(client):
    """recId/entryPrice/entryDate are required fields — omitting one must return
    a 422 validation error, not silently construct with None and fail later as
    an opaque 500 on the database write (Critical finding #11, 2026-07-15 audit)."""
    bad_payload = {k: v for k, v in _POSITION_PAYLOAD.items() if k != "recId"}
    resp = await client.post("/api/portfolio", json=bad_payload)
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_portfolio_create_rejects_invalid_direction(client):
    """direction is now Literal["Bullish","Bearish"] (was plain str) — a wrong-cased
    or wrong-value direction must 422, not be silently persisted."""
    bad_payload = {**_POSITION_PAYLOAD, "recId": "REC-BAD-DIRECTION-1", "direction": "bullish"}
    resp = await client.post("/api/portfolio", json=bad_payload)
    assert resp.status_code == 422, resp.text

    bad_payload2 = {**_POSITION_PAYLOAD, "recId": "REC-BAD-DIRECTION-2", "direction": "Long"}
    resp2 = await client.post("/api/portfolio", json=bad_payload2)
    assert resp2.status_code == 422, resp2.text


@pytest.mark.asyncio
async def test_portfolio_add_reanchors_stop_and_structural_stop_to_live_price(client):
    """add_position() re-anchors stop/structuralStop/targets by the delta between
    scanStockPrice and the live-fetched underlying price at save time (see the
    "Two live fetches at save time" comment in portfolio.py). Untested before —
    exercise it explicitly for both stop AND structuralStop, since they must
    shift by the same delta."""
    payload = {
        **_POSITION_PAYLOAD,
        "recId": "REC-REANCHOR-001",
        "scanStockPrice": 190.0,
        "stop": 178.0,
        "structuralStop": 182.0,
        "targets": [{"id": "tp1", "stockPrice": 200.0, "contractsToSell": 1, "status": "PENDING"}],
    }
    # Live price is $2 above the scan-time price -> every level shifts +2.00.
    with (
        patch("app.routers.portfolio.fetch_contract_quote_async", new=AsyncMock(return_value=None)),
        patch("app.routers.portfolio.fetch_price_async", new=AsyncMock(return_value=192.0)),
    ):
        resp = await client.post("/api/portfolio", json=payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["stop"] == 180.0
    assert body["structuralStop"] == 184.0
    assert body["targets"][0]["stockPrice"] == 202.0


# ── Test 2: Portfolio delete ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_portfolio_add_persists_exit_plan(client):
    """POST /api/portfolio must persist exitPlan (the exit-plan pipeline result
    a user attached via TradeCard's "Compute Exit Plan" button before sending
    to broker), not silently drop it — regression guard for a round-2
    adversarial-audit finding where the create path had no exitPlan field at
    all (only the later PATCH-update path did), so a plan computed pre-trade
    was erased by the very next backend sync."""
    exit_plan = {
        "computedAt": "2026-08-26T12:00:00.000Z",
        "stop": {"price": 178.0, "source": "structural", "contractPrice": 1.2, "rrModel": "Heston repriced",
                  "structuralSource": "order_block", "structuralConfidence": 80},
        "targets": [
            {"rrRatio": 2.0, "arithmeticPrice": 195.0, "price": 195.0, "tpSource": "arithmetic",
             "structuralPrice": None, "contractPrice": 4.5, "rrModel": "Heston repriced",
             "probability": 0.6, "expectedDays": 8, "qualityGood": True, "qualityReasons": []},
        ],
        "atr": 3.5,
    }
    payload = {**_POSITION_PAYLOAD, "recId": "REC-EXITPLAN-001", "exitPlan": exit_plan}
    resp = await client.post("/api/portfolio", json=payload)
    assert resp.status_code == 201, resp.text
    assert resp.json()["exitPlan"] == exit_plan

    get_resp = await client.get("/api/portfolio")
    assert get_resp.status_code == 200
    saved = next(p for p in get_resp.json() if p["recId"] == "REC-EXITPLAN-001")
    assert saved["exitPlan"] == exit_plan


@pytest.mark.asyncio
async def test_portfolio_add_persists_max_loss_override(client):
    """POST /api/portfolio must persist maxLossOverride (Feature 5 — the
    pre-trade override set on TradeCard's Arithmetic Profit Target card, sent
    once at creation time), not silently drop it — same regression class as
    the exitPlan create-path fix above: PortfolioPositionCreate previously had
    no such field, so a pre-trade override appeared to work in the client's
    optimistic local UI state but the backend never received it, and the next
    sync silently overwrote it with null."""
    override = {"mode": "percent", "value": 0.05}
    payload = {**_POSITION_PAYLOAD, "recId": "REC-MAXLOSS-001", "maxLossOverride": override}
    resp = await client.post("/api/portfolio", json=payload)
    assert resp.status_code == 201, resp.text
    assert resp.json()["maxLossOverride"] == override

    get_resp = await client.get("/api/portfolio")
    assert get_resp.status_code == 200
    saved = next(p for p in get_resp.json() if p["recId"] == "REC-MAXLOSS-001")
    assert saved["maxLossOverride"] == override


@pytest.mark.asyncio
async def test_portfolio_add_max_loss_override_defaults_to_none(client):
    """A position created with no maxLossOverride key at all must persist as
    null, not error or silently default to some other shape."""
    payload = {**_POSITION_PAYLOAD, "recId": "REC-MAXLOSS-002"}
    resp = await client.post("/api/portfolio", json=payload)
    assert resp.status_code == 201, resp.text
    assert resp.json()["maxLossOverride"] is None


@pytest.mark.asyncio
async def test_portfolio_delete(client):
    """POST then DELETE by rec_id → GET returns empty list."""
    await client.post("/api/portfolio", json=_POSITION_PAYLOAD)

    del_resp = await client.delete(f"/api/portfolio/{_POSITION_PAYLOAD['recId']}")
    assert del_resp.status_code == 204, del_resp.text

    get_resp = await client.get("/api/portfolio")
    assert get_resp.json() == []


@pytest.mark.asyncio
async def test_portfolio_hard_delete_also_removes_audit_event(client, db_session):
    """A hard DELETE never creates a closed_positions row, so prune_old_history's
    audit_events cascade (which only discovers rec_ids via closed_positions)
    can never reach it — delete_position must clean up audit_events itself,
    or the buy-decision snapshot orphans forever."""
    from app.models.audit_event import AuditEventModel

    payload = {**_POSITION_PAYLOAD, "tradeCardSnapshot": {"stockScore": 77}}
    post_resp = await client.post("/api/portfolio", json=payload)
    assert post_resp.status_code == 201, post_resp.text

    existing = await db_session.execute(
        select(AuditEventModel).where(AuditEventModel.rec_id == payload["recId"])
    )
    assert existing.scalar_one_or_none() is not None, "log_approval should have written an audit_events row"

    del_resp = await client.delete(f"/api/portfolio/{payload['recId']}")
    assert del_resp.status_code == 204, del_resp.text

    after = await db_session.execute(
        select(AuditEventModel).where(AuditEventModel.rec_id == payload["recId"])
    )
    assert after.scalar_one_or_none() is None, "audit_events row must be cleaned up on hard delete"


# ── Test 3: Portfolio persistence across sessions ─────────────────────────────

@pytest.mark.asyncio
async def test_portfolio_persistence(db_session):
    """Data written in one session is readable in a new session (same in-memory DB)."""
    from app.models.portfolio import PortfolioPositionModel

    pos = PortfolioPositionModel(
        rec_id="REC-20260508-PERSIST01",
        symbol="MSFT",
        contract="MSFT|400|2026-06-20|C",
        direction="Bullish",
        entry_price=3.00,
        qty=1,
        entry_date="2026-05-08",
    )
    db_session.add(pos)
    await db_session.commit()

    # Open a second session against the same engine
    async with TestSessionLocal() as session2:
        result = await session2.execute(
            select(PortfolioPositionModel).where(
                PortfolioPositionModel.rec_id == "REC-20260508-PERSIST01"
            )
        )
        fetched = result.scalar_one_or_none()
        assert fetched is not None
        assert fetched.symbol == "MSFT"


# ── Test 4: Duplicate prevention (409) ───────────────────────────────────────

@pytest.mark.asyncio
async def test_portfolio_duplicate_contract_returns_409(client):
    """POST same contract string twice → second returns 409."""
    resp1 = await client.post("/api/portfolio", json=_POSITION_PAYLOAD)
    assert resp1.status_code == 201

    dup_payload = dict(_POSITION_PAYLOAD)
    dup_payload["recId"] = "REC-20260508-DUPLICATE"  # different rec_id, same contract
    resp2 = await client.post("/api/portfolio", json=dup_payload)
    assert resp2.status_code == 409, resp2.text


# ── Test 5: Watchlist add / list / delete ────────────────────────────────────

@pytest.mark.asyncio
async def test_watchlist_add_list_delete(client):
    """POST symbol → GET returns it → DELETE → GET returns empty."""
    # Add
    add_resp = await client.post("/api/watchlist", json={"symbol": "NVDA"})
    assert add_resp.status_code == 201, add_resp.text

    # List — endpoint returns list[WatchlistRow] objects
    list_resp = await client.get("/api/watchlist")
    assert list_resp.status_code == 200
    rows = list_resp.json()
    assert any(r["symbol"] == "NVDA" for r in rows), f"NVDA not in watchlist: {rows}"

    # Delete
    del_resp = await client.delete("/api/watchlist/NVDA")
    assert del_resp.status_code == 204, del_resp.text

    # Verify empty
    list_resp2 = await client.get("/api/watchlist")
    assert list_resp2.json() == []


# ── Test 6: Audit log write ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_log_approval_creates_db_row(db_session):
    """call log_approval() → AuditEvent row exists with correct rec_id."""
    from app.services.audit import log_approval
    from app.models.audit_event import AuditEventModel
    from app.models.portfolio import PortfolioPositionModel

    rec_id = "REC-20260508-AUDITROW"
    trade_data = {"symbol": "AAPL", "contract": "AAPL|190|2026-06-20|C"}
    db_session.add(PortfolioPositionModel(
        rec_id=rec_id, symbol="AAPL", contract="AAPL|190|2026-06-20|C",
        direction="Bullish", entry_price=1.0, qty=1, entry_date="2026-05-08",
    ))
    await db_session.commit()
    await log_approval(rec_id, trade_data, db_session)

    result = await db_session.execute(
        select(AuditEventModel).where(AuditEventModel.rec_id == rec_id)
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.event_type == "approval"
    assert row.rec_id == rec_id
    assert row.recommendation_id == rec_id


# ── Test 7: rec_id dual-system match ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_rec_id_dual_system_match(db_session, tmp_path, monkeypatch):
    """After log_approval(), same rec_id appears in AuditEvent table and JSONL log."""
    import app.services.audit as audit_module
    from app.services.audit import log_approval
    from app.models.audit_event import AuditEventModel
    from app.models.portfolio import PortfolioPositionModel

    # Redirect the JSONL log to a temp file
    log_file = tmp_path / "test_audit.log"
    monkeypatch.setattr(audit_module, "_LOG_PATH", str(log_file))

    rec_id = "REC-20260508-DUALSYS"
    trade_data = {"symbol": "TSLA", "action": "BUY"}
    db_session.add(PortfolioPositionModel(
        rec_id=rec_id, symbol="TSLA", contract="TSLA|200|2026-06-20|C",
        direction="Bullish", entry_price=1.0, qty=1, entry_date="2026-05-08",
    ))
    await db_session.commit()
    await log_approval(rec_id, trade_data, db_session)

    # Check DB row
    result = await db_session.execute(
        select(AuditEventModel).where(AuditEventModel.rec_id == rec_id)
    )
    db_row = result.scalar_one_or_none()
    assert db_row is not None, "rec_id not found in AuditEvent table"

    # Check JSONL log
    assert log_file.exists(), "audit.log was not created"
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1, "audit.log has no entries"
    parsed = json.loads(lines[-1])
    assert parsed["rec_id"] == rec_id, f"JSONL rec_id mismatch: {parsed}"
    assert parsed["event"] == "approval"


# -- Test 8: Risk gate rejects with 422 when portfolio too small ---------------

@pytest.mark.asyncio
async def test_portfolio_risk_gate_rejects_422(client, monkeypatch):
    """The server account below min_portfolio_value refuses the position."""
    from copy import deepcopy
    from app.services import portfolio_risk
    config = deepcopy(portfolio_risk._load_config())
    config.setdefault("portfolio", {})["portfolio_value"] = 1000.0
    monkeypatch.setattr(portfolio_risk, "_load_config", lambda: config)

    payload = dict(_POSITION_PAYLOAD)
    payload["recId"] = "REC-20260508-RISK01"
    payload["portfolioValue"] = 1000.0  # below 5000 min
    resp = await client.post("/api/portfolio", json=payload)
    assert resp.status_code == 422, resp.text
    data = resp.json()
    assert "detail" in data
    assert "portfolio_too_small" in data["detail"]
