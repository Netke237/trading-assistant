"""Q3 -- stop bad data being persisted.

Plan: docs/superpowers/plans/2026-09-24-q3-persisted-data-hardening-plan.md
  1. POST /api/portfolio refuses a zero or negative qty (PATCH already did).
  2. alert_dedup.json is written atomically, so a failed write cannot
     truncate the previous dedup / first-seen records.

The config_loader validator hardening was split out of this change at the
round cap (Q3-CAP, option B) and ships as its own change.
"""
from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio


# ── 1. PortfolioPositionCreate.qty ──────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.database import Base, get_db
    from app.main import app
    from app.models import audit_event, portfolio, watchlist  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    db_session = session_factory()

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
    await db_session.close()
    await engine.dispose()


_PAYLOAD = {
    "recId": "REC-Q3-QTY",
    "symbol": "AAPL",
    "contract": "AAPL|190|2026-06-20|C",
    "direction": "Bullish",
    "entryPrice": 4.50,
    "entryDate": "2026-05-08",
    "stop": 2.25,
    "targets": [],
    "dteTotal": 43,
    "portfolioValue": 50_000.0,
}


@pytest.mark.asyncio
@pytest.mark.parametrize("qty", [0, -3])
async def test_create_refuses_a_non_positive_qty_and_saves_nothing(client, qty):
    resp = await client.post("/api/portfolio", json={**_PAYLOAD, "qty": qty})
    assert resp.status_code == 422, resp.text
    assert any(err["loc"][-1] == "qty" for err in resp.json()["detail"])
    listed = await client.get("/api/portfolio")
    assert listed.json() == []


@pytest.mark.asyncio
async def test_create_accepts_qty_one_the_boundary(client):
    resp = await client.post("/api/portfolio", json={**_PAYLOAD, "qty": 1})
    assert resp.status_code == 201, resp.text
    listed = (await client.get("/api/portfolio")).json()
    assert [p["qty"] for p in listed] == [1]


@pytest.mark.asyncio
async def test_create_default_qty_is_still_one(client):
    resp = await client.post("/api/portfolio", json=_PAYLOAD)
    assert resp.status_code == 201, resp.text


# ── 2. alert_dedup.json atomic write ────────────────────────────────────────

@pytest.fixture
def an():
    import app.services.notifications.alert_notifier as module
    return module


def _seed_previous_file(an) -> bytes:
    an._fired["REC-OLD|STOP_REACHED"] = 1000.0
    an._first_seen["REC-OLD|STOP_REACHED"] = "2026-09-01T00:00:00+00:00"
    an._save_dedup()
    return an._DEDUP_PATH.read_bytes()


def _leftover_temp_files(an) -> list[str]:
    return [p.name for p in an._DEDUP_PATH.parent.iterdir()
            if p.name != an._DEDUP_PATH.name and "alert_dedup" in p.name]


def test_save_then_load_round_trips(an):
    _seed_previous_file(an)
    an._fired.clear(); an._first_seen.clear()
    an._load_dedup()
    assert an._fired == {"REC-OLD|STOP_REACHED": 1000.0}
    assert an._first_seen == {"REC-OLD|STOP_REACHED": "2026-09-01T00:00:00+00:00"}
    assert _leftover_temp_files(an) == []


def test_a_write_that_fails_midway_leaves_the_previous_file_intact(an, monkeypatch, caplog):
    """The defect: open(path, 'w') truncates BEFORE the write, so a failure
    part-way left an empty or half-written file, which _load_dedup then
    swallowed -- every dedup hold and first-seen record gone on restart.
    Here the new bytes are already in the temp file when the sync fails."""
    before = _seed_previous_file(an)
    an._fired["REC-NEW|STOP_REACHED"] = 2000.0

    def _sync_fails(fd):
        raise OSError("disk full")

    monkeypatch.setattr(an.os, "fsync", _sync_fails)
    with caplog.at_level(logging.WARNING, logger=an.__name__):
        an._save_dedup()

    assert an._DEDUP_PATH.read_bytes() == before
    assert _leftover_temp_files(an) == []
    assert any("Could not persist dedup state" in r.getMessage()
               and r.levelno == logging.WARNING for r in caplog.records)


def test_a_failed_rename_leaves_the_previous_file_intact(an, monkeypatch):
    before = _seed_previous_file(an)
    an._fired["REC-NEW|STOP_REACHED"] = 2000.0

    def _no_replace(src, dst):
        raise OSError("rename refused")

    monkeypatch.setattr(an.os, "replace", _no_replace)
    an._save_dedup()

    assert an._DEDUP_PATH.read_bytes() == before
    assert _leftover_temp_files(an) == []


def test_an_unserialisable_value_never_touches_the_file(an):
    """The old json.dump streamed straight into the truncated target, so a value
    it could not encode left a half-written file behind."""
    before = _seed_previous_file(an)
    an._first_seen["REC-BAD|STOP_REACHED"] = object()
    an._save_dedup()
    assert an._DEDUP_PATH.read_bytes() == before
    assert _leftover_temp_files(an) == []


def test_a_successful_save_replaces_the_file_with_the_new_state(an):
    _seed_previous_file(an)
    an._fired["REC-NEW|STOP_REACHED"] = 2000.0
    an._save_dedup()
    data = json.loads(an._DEDUP_PATH.read_text(encoding="utf-8"))
    assert data["fired"] == {"REC-OLD|STOP_REACHED": 1000.0, "REC-NEW|STOP_REACHED": 2000.0}
    assert _leftover_temp_files(an) == []


def test_a_corrupt_file_on_load_is_reported_at_warning(an, caplog):
    an._DEDUP_PATH.write_text('{"fired": {"REC-1|STOP', encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger=an.__name__):
        an._load_dedup()
    assert an._fired == {} and an._first_seen == {}
    assert any("Could not load dedup state" in r.getMessage()
               and r.levelno == logging.WARNING for r in caplog.records)
