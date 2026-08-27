"""POST /api/alerts/notify must only dispatch for a recId that is an open
portfolio position in the DB — otherwise the browser could email alerts for
positions the backend does not hold (phantom-alert guard)."""
from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from httpx import AsyncClient, ASGITransport

from app.database import Base
from app.models.portfolio import PortfolioPositionModel

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
_engine = create_async_engine(TEST_DB_URL, echo=False)
_Session = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False,
                              autoflush=False, autocommit=False)


@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    from app.models import portfolio, watchlist, audit_event  # noqa: F401
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session():
    async with _Session() as s:
        yield s


@pytest_asyncio.fixture
async def client(db_session):
    from app.main import app
    from app.database import get_db

    async def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _insert(db: AsyncSession, rec_id: str, alert_overrides: dict | None = None) -> None:
    db.add(PortfolioPositionModel(
        rec_id=rec_id, symbol="ABT", contract="ABT|97|2027-01-15|C",
        direction="Bullish", entry_price=10.45, qty=1, entry_date="2026-07-17",
        stop=89.89, targets=[], dte_total=547, alert_overrides=alert_overrides,
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_notify_dispatches_when_position_exists(client, db_session):
    await _insert(db_session, "REC-REAL-1")
    with patch("app.routers.alerts.notify_alert", return_value=True) as mock_notify:
        resp = await client.post("/api/alerts/notify", json={
            "symbol": "ABT", "alertType": "STOP_REACHED",
            "reason": "Stop breached", "recId": "REC-REAL-1",
        })
    assert resp.status_code == 200
    assert resp.json()["sent"] is True
    mock_notify.assert_called_once()


@pytest.mark.asyncio
async def test_notify_passes_explicit_true_override_as_type_enabled(client, db_session):
    # Feature D: an explicit per-position override must reach notify_alert as
    # type_enabled so it can bypass a globally-disabled type — this is the one
    # path (browser POST) the unit tests on effective_enabled/notify_alert in
    # isolation don't cover, since it's the router that wires the two together.
    await _insert(db_session, "REC-OVERRIDE-TRUE", alert_overrides={"STOP_REACHED": True})
    with patch("app.routers.alerts.notify_alert", return_value=True) as mock_notify:
        resp = await client.post("/api/alerts/notify", json={
            "symbol": "ABT", "alertType": "STOP_REACHED",
            "reason": "Stop breached", "recId": "REC-OVERRIDE-TRUE",
        })
    assert resp.status_code == 200
    assert mock_notify.call_args.kwargs["type_enabled"] is True


@pytest.mark.asyncio
async def test_notify_passes_explicit_false_override_as_type_enabled(client, db_session):
    await _insert(db_session, "REC-OVERRIDE-FALSE", alert_overrides={"STOP_REACHED": False})
    with patch("app.routers.alerts.notify_alert", return_value=False) as mock_notify:
        resp = await client.post("/api/alerts/notify", json={
            "symbol": "ABT", "alertType": "STOP_REACHED",
            "reason": "Stop breached", "recId": "REC-OVERRIDE-FALSE",
        })
    assert resp.status_code == 200
    assert mock_notify.call_args.kwargs["type_enabled"] is False


@pytest.mark.asyncio
async def test_notify_passes_none_when_no_override_present(client, db_session):
    # No override on the position (and a stray key for an account-wide type
    # would be ignored the same way) -> notify_alert must fall back to the
    # global enabledTypes list, signalled by type_enabled=None.
    await _insert(db_session, "REC-NO-OVERRIDE")
    with patch("app.routers.alerts.notify_alert", return_value=True) as mock_notify:
        resp = await client.post("/api/alerts/notify", json={
            "symbol": "ABT", "alertType": "STOP_REACHED",
            "reason": "Stop breached", "recId": "REC-NO-OVERRIDE",
        })
    assert resp.status_code == 200
    assert mock_notify.call_args.kwargs["type_enabled"] is None


@pytest.mark.asyncio
async def test_notify_suppressed_when_position_absent(client):
    with patch("app.routers.alerts.notify_alert", return_value=True) as mock_notify:
        resp = await client.post("/api/alerts/notify", json={
            "symbol": "ABT", "alertType": "STOP_REACHED",
            "reason": "Stop breached", "recId": "REC-GHOST-1",
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body["sent"] is False
    assert body.get("reason") == "position_not_found"
    mock_notify.assert_not_called()
