"""Save-first option holds and verified misses.

File-backed SQLite. The broker adapter is mocked. A prepared option row
submitted without savedRecId must offset that row once. Verifying a miss
drops only that attempt's hold.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.data.ibkr_paper import OrderResult
from app.database import Base, get_db
from app.models.broker_attempt import ExposureHold
from app.models.portfolio import PortfolioPositionModel
from app.routers import broker, portfolio
from app.services.portfolio_exposure import capacity_positions


CONTRACT = "AAPL|185|2026-12-18|C"
QTY = 2
LIMIT = 1.25


class _Router:
    def __init__(self, adapter):
        self.adapter = adapter

    def resolve(self, _broker):
        return self.adapter


def _engine(path):
    url = f"sqlite+aiosqlite:///{path.as_posix()}"
    engine = create_async_engine(url, connect_args={"timeout": 30, "check_same_thread": False})
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _option_order(symbol="AAPL", contract=CONTRACT, attempt_id=None):
    body = {
        "broker": "ibkr_paper",
        "symbol": symbol,
        "option_symbol": contract,
        "action": "BUY",
        "effect": "OPEN",
        "quantity": QTY,
        "order_type": "LMT",
        "limit_price": LIMIT,
        "tif": "DAY",
    }
    if attempt_id is not None:
        body["attempt_id"] = attempt_id
    return body


def _save_body(rec_id="OPT-PREP", symbol="AAPL", contract=CONTRACT):
    return {
        "recId": rec_id,
        "symbol": symbol,
        "contract": contract,
        "direction": "Bullish",
        "entryPrice": LIMIT,
        "qty": QTY,
        "entryDate": "2026-10-13",
        "orderType": "LMT",
        "orderLimitPrice": LIMIT,
    }


async def _exposure(factory):
    async with factory() as db:
        rows = list((await db.execute(select(PortfolioPositionModel))).scalars().all())
        holds = list((await db.execute(select(ExposureHold))).scalars().all())
        positions = capacity_positions(rows, holds)
        return sum(p.capital_at_risk for p in positions), holds, rows


@pytest.fixture(autouse=True)
def _clear_broker_process():
    broker._idempotency_cache.clear()
    broker._idempotency_inflight.clear()
    broker._attempt_waiters.clear()
    yield
    broker._idempotency_cache.clear()
    broker._idempotency_inflight.clear()
    broker._attempt_waiters.clear()


@pytest.fixture
async def rig(tmp_path, monkeypatch):
    path = tmp_path / "save-first.db"
    engine, sessions = _engine(path)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _no_quote(*_args, **_kwargs):
        return None

    monkeypatch.setattr(portfolio, "fetch_contract_quote_async", _no_quote)
    monkeypatch.setattr(portfolio, "fetch_price_async", _no_quote)
    adapter = MagicMock()
    adapter.place_order.return_value = OrderResult(
        order_id="opt-1", status="PreSubmitted", broker="ibkr_paper",
    )
    monkeypatch.setattr(broker, "build_router_from_credentials", lambda: _Router(adapter))
    monkeypatch.setattr("app.services.daily_risk_hooks.capture_daily_risk_hooks", lambda: MagicMock())

    async def _resolve(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.daily_risk.resolve", _resolve)
    app = FastAPI()
    app.include_router(portfolio.router)
    app.include_router(broker.router)

    async def _db():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = _db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield SimpleNamespace(client=client, sessions=sessions, adapter=adapter)
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("attempt_id", [None, "explicit-opt"])
async def test_save_first_option_without_saved_rec_offsets_the_row_once(rig, attempt_id):
    saved = await rig.client.post("/api/portfolio", json=_save_body())
    assert saved.status_code == 201, saved.text
    _total, _holds, rows = await _exposure(rig.sessions)
    prepared = rows[0].prepared_order
    assert prepared["instrument"] == CONTRACT
    assert prepared["quantity"] == QTY
    assert prepared["limit"] == "1.25"
    assert int(rows[0].qty) == QTY

    sent = await rig.client.post("/broker/option-order", json=_option_order(attempt_id=attempt_id))
    assert sent.status_code == 200, sent.text
    assert "savedRecId" not in _option_order(attempt_id=attempt_id)
    total, holds, rows = await _exposure(rig.sessions)
    assert len(holds) == 1
    row = rows[0]
    hold = holds[0]
    assert hold.saved_rec_id == row.rec_id
    assert int(hold.coverage_quantity or 0) == int(row.qty)
    row_capital = float(row.entry_price) * int(row.qty) * 100
    combined = row_capital + float(hold.notional)
    assert combined > row_capital
    assert total == pytest.approx(row_capital)
    assert total != pytest.approx(combined)


@pytest.mark.asyncio
async def test_verified_miss_drops_its_hold_and_other_outcomes_keep_theirs(rig):
    rig.adapter.place_order.side_effect = RuntimeError("timed out after POST")
    cases = {
        "miss-opt": ("definitely-not-submitted", "AAPL", "AAPL|185|2026-12-18|C"),
        "kept-submitted": ("submitted", "MSFT", "MSFT|400|2026-12-18|C"),
        "kept-filled": ("filled", "NVDA", "NVDA|900|2026-12-18|C"),
        "kept-partial": ("partial", "QQQ", "QQQ|500|2026-12-18|C"),
        "kept-canceled": ("canceled-after-submission", "SPY", "SPY|550|2026-12-18|C"),
    }
    for attempt_id, (_outcome, symbol, contract) in cases.items():
        response = await rig.client.post(
            "/broker/option-order",
            json=_option_order(symbol=symbol, contract=contract, attempt_id=attempt_id),
        )
        assert response.status_code >= 400, response.text
    _total, holds, _rows = await _exposure(rig.sessions)
    assert {hold.attempt_id for hold in holds} == set(cases)

    for attempt_id, (outcome, _symbol, _contract) in cases.items():
        detail = await rig.client.get(f"/broker/attempts/{attempt_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["state"] == "outcome-unknown"
        verified = await rig.client.post(
            f"/broker/attempts/{attempt_id}/verify",
            json={
                "outcome": outcome,
                "note": f"broker evidence for {outcome}",
                "expected_version": detail.json()["verification_version"],
            },
        )
        assert verified.status_code == 200, verified.text

    _total, holds, _rows = await _exposure(rig.sessions)
    remaining = {hold.attempt_id for hold in holds}
    assert "miss-opt" not in remaining
    assert remaining == {"kept-submitted", "kept-filled", "kept-partial", "kept-canceled"}
