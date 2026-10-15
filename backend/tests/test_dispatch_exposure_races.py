"""Dispatch exposure races against the real routes, workers, and ORM.

File-backed SQLite. The broker adapter is mocked. A barrier holds the one
worker so a PATCH can grow the book after the route snapshot and before
admission. Coverage that is not a committed ExposureHold fails these tests.
"""
from __future__ import annotations

import asyncio
import sqlite3
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
import app.services.auto_trader as at
from app.data.ibkr_paper import OrderResult
from app.data.order_errors import OrderAdmissionRefusedError
from app.database import Base, get_db
from app.models.broker_attempt import ExposureHold
from app.models.daily_risk import DailyRiskBudget
from app.models.portfolio import PortfolioPositionModel
from app.routers import auto_trade, broker, portfolio, scan
from app.schemas import PortfolioPositionCreate
from app.services import daily_risk, daily_risk_hooks, portfolio_risk
from app.services.auto_trade_booking import BookingOutcome
from app.services.auto_trader import ArmedStrategy, auto_trader
from app.services.portfolio_exposure import book, capacity_positions
from app.routers.portfolio import update_position
from app.schemas import PortfolioPositionUpdate


def _engine(path):
    url = f"sqlite+aiosqlite:///{path.as_posix()}"
    engine = create_async_engine(url, connect_args={"timeout": 30, "check_same_thread": False})
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _hold_count(path) -> int:
    con = sqlite3.connect(path)
    try:
        return con.execute("select count(*) from exposure_holds").fetchone()[0]
    finally:
        con.close()


def _option(rec, symbol, qty, entry):
    return PortfolioPositionModel(
        rec_id=rec, symbol=symbol, contract=f"{symbol}|200|2026-12-18|C",
        direction="Bullish", entry_price=entry, qty=qty, entry_date="2026-10-13",
        stop=100, targets=[],
    )


def _stock(rec, symbol, qty, entry, prepared=None):
    return PortfolioPositionModel(
        rec_id=rec, symbol=symbol, contract=f"{symbol}|STOCK", direction="Bullish",
        entry_price=entry, qty=qty, entry_date="2026-10-13", targets=[],
        prepared_order=prepared,
    )


def _prepared(symbol, qty, limit):
    return {
        "instrument": f"{symbol}|STOCK",
        "symbol": symbol,
        "action": "BUY",
        "effect": "OPEN",
        "quantity": qty,
        "order_type": "LMT",
        "limit": limit,
    }


def _arm_body(symbol, premium, qty=1):
    return {
        "broker": "ibkr_paper",
        "symbol": symbol,
        "option_symbol": f"{symbol}|200|2026-12-18|C",
        "action": "BUY",
        "direction": "Bullish",
        "quantity": qty,
        "order_type": "LMT",
        "limit_price": premium,
        "entry_premium": premium,
        "horizon": "Swing",
        "hold_max_days": 20,
        "stop": 100,
        "scan_stock_price": 200,
    }


def _stock_order(symbol="AAPL", qty=1, limit=100, attempt_id=None, saved_rec_id=None):
    body = {
        "broker": "ibkr_paper", "symbol": symbol, "action": "BUY", "effect": "OPEN",
        "quantity": qty, "order_type": "LMT", "limit_price": limit, "tif": "DAY",
    }
    if attempt_id is not None:
        body["attempt_id"] = attempt_id
    if saved_rec_id is not None:
        body["savedRecId"] = saved_rec_id
    return body


def _option_order(symbol="AAPL", qty=1, limit=1.0, attempt_id=None, saved_rec_id=None):
    body = {
        "broker": "ibkr_paper", "symbol": symbol,
        "option_symbol": "AAPL261218C00185000",
        "action": "BUY", "effect": "OPEN", "quantity": qty, "order_type": "LMT",
        "limit_price": limit, "tif": "DAY",
    }
    if attempt_id is not None:
        body["attempt_id"] = attempt_id
    if saved_rec_id is not None:
        body["savedRecId"] = saved_rec_id
    return body


async def _seed(factory, rows):
    async with factory() as db:
        for row in rows:
            db.add(row)
        await db.commit()


async def _exposure(factory):
    async with factory() as db:
        rows = (await db.execute(select(PortfolioPositionModel))).scalars().all()
        holds = (await db.execute(select(ExposureHold))).scalars().all()
        positions = capacity_positions(list(rows), list(holds))
        return sum(p.capital_at_risk for p in positions), list(holds), list(rows)


async def _reserved(factory):
    async with factory() as db:
        rows = (await db.execute(select(DailyRiskBudget))).scalars().all()
        return sum(row.reserved_cents for row in rows)


def _bound_to(fn, method):
    return getattr(fn, "__func__", None) is method and getattr(fn, "__self__", None) is auto_trader


def _occupy(executor):
    started = threading.Event()
    release = threading.Event()

    def _block():
        started.set()
        release.wait(15)

    future = executor.submit(_block)
    assert started.wait(5), "worker barrier did not start"
    return release, future


async def _wait_recorded(recorded, task):
    for _ in range(200):
        if recorded or task.done():
            break
        await asyncio.sleep(0.01)
    if task.done() and not recorded:
        error = task.exception()
        raise AssertionError(f"worker was not queued: {error!r}")
    assert recorded, "worker was not queued"
    return recorded[0]


@pytest.fixture(autouse=True)
def _reset_singleton():
    auto_trader.disarm()
    with auto_trader._lock:
        auto_trader._state.history.clear()
    broker._idempotency_cache.clear()
    broker._idempotency_inflight.clear()
    yield
    auto_trader.disarm()
    with auto_trader._lock:
        auto_trader._state.history.clear()
    broker._idempotency_cache.clear()
    broker._idempotency_inflight.clear()


@pytest.fixture(autouse=True)
def _fire_stubs(monkeypatch):
    monkeypatch.setattr(at, "_market_is_open", lambda *_a, **_k: True)
    monkeypatch.setattr(at, "_apply_vol_sizing", lambda strategy: strategy)
    monkeypatch.setattr(at, "_apply_event_veto", lambda *_a, **_k: None)
    monkeypatch.setattr(at, "_alert_refusal", lambda *_a, **_k: None)

    async def _no_quote(*_a, **_k):
        return None

    monkeypatch.setattr("app.services.auto_trade_booking.fetch_contract_quote_async", _no_quote)
    monkeypatch.setattr("app.services.auto_trade_booking.fetch_price_async", _no_quote)
    monkeypatch.setattr(portfolio, "fetch_contract_quote_async", _no_quote)
    monkeypatch.setattr(portfolio, "fetch_price_async", _no_quote)


@pytest.fixture(autouse=True)
def _workers_idle():
    yield
    auto_trade._FIRE_EXECUTOR.submit(lambda: None).result(timeout=5)
    scan._SCAN_FIRE_EXECUTOR.submit(lambda: None).result(timeout=5)


@pytest_asyncio.fixture
async def rig(tmp_path, monkeypatch):
    path = tmp_path / "dispatch.db"
    engine, sessions = _engine(path)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    raw = portfolio_risk._load_config()
    cfg = {
        **raw,
        "portfolio": {**raw["portfolio"], "portfolio_value": 100000, "max_total_exposure_pct": 0.01},
        "auto_trade": {**raw.get("auto_trade", {}), "max_daily_loss_pct": 0.02},
    }
    monkeypatch.setattr(portfolio_risk, "_load_config", lambda: cfg)
    monkeypatch.setattr(book, "sessions", sessions)
    service = daily_risk.DailyRiskService(sessions, config_provider=lambda: cfg, history_provider=lambda: [])
    monkeypatch.setattr(daily_risk, "reserve", service.reserve)
    monkeypatch.setattr(daily_risk, "resolve", service.resolve)

    def _capture():
        return daily_risk_hooks.DailyRiskHooks(asyncio.get_running_loop())

    monkeypatch.setattr(daily_risk_hooks, "capture_daily_risk_hooks", _capture)
    execute = MagicMock(return_value=OrderResult(order_id="auto-1", status="PreSubmitted", broker="ibkr_paper"))
    monkeypatch.setattr(at, "execute_option_order", execute)
    adapter = MagicMock()
    adapter.execute.return_value = OrderResult(order_id="manual-1", status="PreSubmitted", broker="ibkr_paper")
    monkeypatch.setattr(broker, "build_router_from_credentials", lambda: adapter)

    async def _booked(*_a, **_k):
        return BookingOutcome(booked=True, rec_id="book-skip", error=None, over_exposure=False)

    monkeypatch.setattr(auto_trade, "book_fired_order", _booked)
    app = FastAPI()
    app.include_router(auto_trade.router)
    app.include_router(scan.router)
    app.include_router(portfolio.router)
    app.include_router(broker.router)

    async def _db():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = _db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield SimpleNamespace(
            client=client, path=path, sessions=sessions, engine=engine,
            execute=execute, adapter=adapter, cfg=cfg,
        )
    await engine.dispose()


async def _arm(rig, symbol, premium, qty=1):
    response = await rig.client.post("/auto-trade/arm", json=_arm_body(symbol, premium, qty))
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_growing_patch_before_manual_fire_admission_posts_nothing(rig):
    await _seed(rig.sessions, [_option("AAPL-1", "AAPL", 1, 7)])
    await _arm(rig, "MSFT", 2)
    recorded = []
    real_submit = auto_trade._FIRE_EXECUTOR.submit

    def _submit(fn, *args, **kwargs):
        future = real_submit(fn, *args, **kwargs)
        if _bound_to(fn, at.AutoTradeService.fire):
            recorded.append(future)
        return future

    auto_trade._FIRE_EXECUTOR.submit = _submit
    release, _blocked = _occupy(auto_trade._FIRE_EXECUTOR)
    try:
        task = asyncio.create_task(rig.client.post("/auto-trade/fire"))
        await _wait_recorded(recorded, task)
        async with rig.sessions() as db:
            grown = await update_position(
                "AAPL-1",
                PortfolioPositionUpdate(qty=2, expectedQty=1, addedFillPrice=7),
                db,
            )
        assert grown.qty == 2
        release.set()
        response = await task
    finally:
        release.set()
        auto_trade._FIRE_EXECUTOR.submit = real_submit
    assert rig.execute.call_count == 0, response.text
    assert response.status_code == 400, response.text
    assert "exposure" in response.text.lower()


@pytest.mark.asyncio
async def test_growing_patch_before_scan_fire_admission_posts_nothing(rig, monkeypatch):
    await _seed(rig.sessions, [_option("AAPL-1", "AAPL", 1, 7)])
    await _arm(rig, "MSFT", 2)
    result = SimpleNamespace(
        scan_id="race-scan",
        candidates=[SimpleNamespace(finalStatus="PASS")],
        rejected=[],
    )

    async def _reported(_request, *, callback, **_kwargs):
        return await callback()

    monkeypatch.setattr(scan, "run_reported_scan", _reported)
    monkeypatch.setattr(scan, "_execute_scan_core", AsyncMock(return_value=result))
    monkeypatch.setattr(scan, "_upsert_session", AsyncMock())
    monkeypatch.setattr(scan, "_last_result", None)
    recorded = []
    real_submit = scan._SCAN_FIRE_EXECUTOR.submit

    def _submit(fn, *args, **kwargs):
        future = real_submit(fn, *args, **kwargs)
        if _bound_to(fn, at.AutoTradeService.maybe_fire_on_scan):
            recorded.append(future)
        return future

    scan._SCAN_FIRE_EXECUTOR.submit = _submit
    release, _blocked = _occupy(scan._SCAN_FIRE_EXECUTOR)
    try:
        async with rig.sessions() as db:
            task = asyncio.create_task(scan.run_scan(SimpleNamespace(), db))
            await _wait_recorded(recorded, task)
            async with rig.sessions() as other:
                grown = await update_position(
                    "AAPL-1",
                    PortfolioPositionUpdate(qty=2, expectedQty=1, addedFillPrice=7),
                    other,
                )
            assert grown.qty == 2
            release.set()
            await task
    finally:
        release.set()
        scan._SCAN_FIRE_EXECUTOR.submit = real_submit
    assert rig.execute.call_count == 0, "after-scan fire posted after the book grew"
    assert auto_trader.get_state().history[-1]["status"] == "cap_blocked"


@pytest.mark.asyncio
async def test_fire_hold_is_inside_the_later_fill_breach(rig):
    await _seed(rig.sessions, [_option("AAPL-1", "AAPL", 1, 4)])
    await _arm(rig, "MSFT", 4)
    fired = await rig.client.post("/auto-trade/fire")
    assert fired.status_code == 200, fired.text
    _total, holds, _rows = await _exposure(rig.sessions)
    assert len(holds) == 1, "fire did not persist an exposure hold"
    grown = await rig.client.patch(
        "/api/portfolio/AAPL-1",
        json={"qty": 2, "expectedQty": 1, "addedFillPrice": 4},
    )
    assert grown.status_code == 200, grown.text
    body = grown.json()
    assert body["qty"] == 2
    warning = body.get("exposureBreach") or ""
    assert "1200.00" in warning
    assert "total_exposure_limit_reached" in warning


@pytest.mark.asyncio
async def test_later_create_and_fire_cannot_spend_the_reserved_cap(rig):
    await _seed(rig.sessions, [_option("AAPL-1", "AAPL", 1, 4)])
    await _arm(rig, "MSFT", 4)
    fired = await rig.client.post("/auto-trade/fire")
    assert fired.status_code == 200, fired.text
    grown = await rig.client.patch(
        "/api/portfolio/AAPL-1",
        json={"qty": 2, "expectedQty": 1, "addedFillPrice": 4},
    )
    assert grown.status_code == 200, grown.text
    created = await rig.client.post("/api/portfolio", json={
        "recId": "NVDA-1", "symbol": "NVDA", "contract": "NVDA|200|2026-12-18|C",
        "direction": "Bullish", "entryPrice": 1, "qty": 1, "entryDate": "2026-10-13",
    })
    assert created.status_code == 422, created.text
    # $150 fits beside the stored $800 row and inside the daily budget.
    # It fits the cap only when the $400 fire hold is ignored.
    await _arm(rig, "QQQ", 1.5)
    rig.execute.reset_mock()
    again = await rig.client.post("/auto-trade/fire")
    assert rig.execute.call_count == 0, again.text
    assert again.status_code == 400, again.text


@pytest.mark.asyncio
async def test_second_fire_cannot_spend_a_hold_that_was_not_booked(rig):
    await _arm(rig, "MSFT", 6)
    first = await rig.client.post("/auto-trade/fire")
    assert first.status_code == 200, first.text
    _total, holds, _rows = await _exposure(rig.sessions)
    assert len(holds) == 1, "fire did not persist an exposure hold"
    await _arm(rig, "NVDA", 5)
    rig.execute.reset_mock()
    second = await rig.client.post("/auto-trade/fire")
    assert rig.execute.call_count == 0, second.text
    assert second.status_code == 400, second.text


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["PreSubmitted", "UnknownStatus"])
async def test_canceled_booking_keeps_the_hold_across_restart(rig, monkeypatch, status):
    entered = asyncio.Event()
    release = asyncio.Event()

    async def _block_quote(*_a, **_k):
        entered.set()
        await release.wait()
        return None

    monkeypatch.setattr("app.services.auto_trade_booking.fetch_contract_quote_async", _block_quote)
    from app.services.auto_trade_booking import book_fired_order
    monkeypatch.setattr(auto_trade, "book_fired_order", book_fired_order)
    rig.execute.return_value = OrderResult(order_id="live-1", status=status, broker="ibkr_paper")
    await _arm(rig, "MSFT", 4)
    task = asyncio.create_task(rig.client.post("/auto-trade/fire"))
    await asyncio.wait_for(entered.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    _total, holds, _rows = await _exposure(rig.sessions)
    assert len(holds) == 1, "canceled booking dropped the fire hold"
    await rig.engine.dispose()
    restarted, factory = _engine(rig.path)
    try:
        body = PortfolioPositionCreate(
            recId="LATER-1", symbol="NVDA", contract="NVDA|200|2026-12-18|C",
            direction="Bullish", entryPrice=7, qty=1, entryDate="2026-10-13",
        )
        async with factory() as db:
            with pytest.raises(HTTPException) as caught:
                from app.routers.portfolio import add_position
                await add_position(body, db)
    finally:
        await restarted.dispose()
    assert caught.value.status_code == 422


@pytest.mark.asyncio
async def test_booking_transfer_counts_the_exposure_once(rig, monkeypatch):
    from app.services.auto_trade_booking import book_fired_order
    monkeypatch.setattr(auto_trade, "book_fired_order", book_fired_order)
    await _arm(rig, "MSFT", 4)
    fired = await rig.client.post("/auto-trade/fire")
    assert fired.status_code == 200, fired.text
    assert fired.json()["booked"] is True, fired.text
    total, holds, rows = await _exposure(rig.sessions)
    assert len(holds) == 1, "booking removed the exposure hold instead of transferring it"
    assert holds[0].saved_rec_id
    assert int(holds[0].coverage_quantity or 0) == 1
    assert total == pytest.approx(400)
    assert rows[0].prepared_order is None
    assert rows[0].qty == 1


@pytest.mark.asyncio
async def test_delete_and_reduction_keep_uncovered_hold_notional(rig, monkeypatch):
    from app.services.auto_trade_booking import book_fired_order
    monkeypatch.setattr(auto_trade, "book_fired_order", book_fired_order)
    await _arm(rig, "MSFT", 2, qty=2)
    fired = await rig.client.post("/auto-trade/fire")
    assert fired.status_code == 200, fired.text
    assert fired.json()["booked"] is True, fired.text
    _total, holds, rows = await _exposure(rig.sessions)
    assert len(holds) == 1 and len(rows) == 1
    rec_id = rows[0].rec_id
    reduced = await rig.client.patch(f"/api/portfolio/{rec_id}", json={"qty": 1})
    assert reduced.status_code == 200, reduced.text
    total, holds, rows = await _exposure(rig.sessions)
    assert len(holds) == 1
    assert total == pytest.approx(400), "shrinking the booked row erased reserved exposure"
    deleted = await rig.client.delete(f"/api/portfolio/{rec_id}")
    assert deleted.status_code == 204, deleted.text
    total, holds, rows = await _exposure(rig.sessions)
    assert rows == []
    assert len(holds) == 1
    assert total == pytest.approx(400), "deleting the booked row erased reserved exposure"


@pytest.mark.asyncio
async def test_legacy_open_counts_beside_identical_inventory(rig):
    await _seed(rig.sessions, [_option("AAPL-1", "AAPL", 1, 1)])
    response = await rig.client.post("/broker/option-order", json=_option_order())
    assert response.status_code == 200, response.text
    total, holds, _rows = await _exposure(rig.sessions)
    assert len(holds) == 1, "standalone manual send did not reserve exposure"
    assert total == pytest.approx(200)


@pytest.mark.asyncio
async def test_save_first_create_stamps_prepared_order_and_plain_rows_do_not(rig):
    plain = await rig.client.post("/api/portfolio", json={
        "recId": "PLAIN", "symbol": "MSFT", "contract": "MSFT|STOCK",
        "direction": "Bullish", "entryPrice": 10, "qty": 1, "entryDate": "2026-10-13",
    })
    assert plain.status_code == 201, plain.text
    marked = await rig.client.post("/api/portfolio", json={
        "recId": "PREP", "symbol": "AAPL", "contract": "AAPL|STOCK",
        "direction": "Bullish", "entryPrice": 10, "qty": 1, "entryDate": "2026-10-13",
        "orderType": "LMT", "orderLimitPrice": 10,
    })
    assert marked.status_code == 201, marked.text
    _total, _holds, rows = await _exposure(rig.sessions)
    by_id = {row.rec_id: row for row in rows}
    assert by_id["PLAIN"].prepared_order is None
    prepared = by_id["PREP"].prepared_order
    assert prepared, "save-first row has no prepared_order marker"
    assert prepared["instrument"] == "AAPL|STOCK"
    assert prepared["symbol"] == "AAPL"
    assert prepared["action"] == "BUY"
    assert prepared["effect"] == "OPEN"
    assert prepared["quantity"] == 1
    assert prepared["order_type"] == "LMT"
    assert prepared["limit"] == "10"


@pytest.mark.asyncio
async def test_two_attempts_cannot_offset_one_prepared_row_twice(rig):
    await _seed(rig.sessions, [_stock("PREP", "AAPL", 1, 100, _prepared("AAPL", 1, "100"))])
    first = await rig.client.post(
        "/broker/stock-order",
        json=_stock_order(attempt_id="attempt-a", saved_rec_id="PREP"),
    )
    assert first.status_code == 200, first.text
    second = await rig.client.post(
        "/broker/stock-order",
        json=_stock_order(attempt_id="attempt-b", saved_rec_id="PREP"),
    )
    total, _holds, _rows = await _exposure(rig.sessions)
    assert second.status_code >= 400 or total == pytest.approx(200)
    assert not (second.status_code < 400 and total == pytest.approx(100)), (
        "second attempt reused the prepared row and the exposure stayed at one order"
    )


@pytest.mark.asyncio
async def test_marker_free_inventory_is_not_prepared_coverage(rig):
    await _seed(rig.sessions, [_stock("ROW", "AAPL", 1, 100)])
    linked = await rig.client.post(
        "/broker/stock-order",
        json=_stock_order(attempt_id="linked-plain", saved_rec_id="ROW"),
    )
    assert linked.status_code >= 400, linked.text
    assert rig.adapter.execute.call_count == 0
    standalone = await rig.client.post(
        "/broker/stock-order",
        json=_stock_order(symbol="AAPL", attempt_id="standalone-plain"),
    )
    assert standalone.status_code == 200, standalone.text
    total, holds, _rows = await _exposure(rig.sessions)
    assert len(holds) == 1
    assert int(holds[0].coverage_quantity or 0) == 0
    assert total == pytest.approx(200)


@pytest.mark.asyncio
async def test_changed_prepared_row_refuses_the_linked_send(rig):
    await _seed(rig.sessions, [_stock("PREP", "AAPL", 1, 100, _prepared("AAPL", 1, "100"))])
    async with rig.sessions() as db:
        row = (await db.execute(
            select(PortfolioPositionModel).where(PortfolioPositionModel.rec_id == "PREP")
        )).scalar_one()
        row.qty = 2
        await db.commit()
    response = await rig.client.post(
        "/broker/stock-order",
        json=_stock_order(attempt_id="changed-row", saved_rec_id="PREP"),
    )
    assert response.status_code >= 400, response.text
    assert rig.adapter.execute.call_count == 0


@pytest.mark.asyncio
async def test_deleted_prepared_row_refuses_the_linked_send(rig):
    await _seed(rig.sessions, [_stock("PREP", "AAPL", 1, 100, _prepared("AAPL", 1, "100"))])
    deleted = await rig.client.delete("/api/portfolio/PREP")
    assert deleted.status_code == 204, deleted.text
    response = await rig.client.post(
        "/broker/stock-order",
        json=_stock_order(attempt_id="deleted-row", saved_rec_id="PREP"),
    )
    assert response.status_code >= 400, response.text
    assert rig.adapter.execute.call_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["admission", "rejected"])
async def test_proven_refusal_releases_exposure_and_daily_budget(rig, outcome):
    seen = {}

    def _execute(*_args, **_kwargs):
        seen["holds"] = _hold_count(rig.path)
        if outcome == "admission":
            raise OrderAdmissionRefusedError("admission refused before post")
        return OrderResult(order_id="rej-1", status="Rejected", broker="ibkr_paper")

    rig.adapter.execute.side_effect = _execute
    response = await rig.client.post(
        "/broker/stock-order",
        json=_stock_order(attempt_id=f"refuse-{outcome}"),
    )
    assert response.status_code >= 400 or outcome == "rejected"
    if outcome == "rejected":
        assert response.status_code == 200, response.text
    assert seen.get("holds") == 1, "refusal path never reserved exposure"
    assert _hold_count(rig.path) == 0
    assert await _reserved(rig.sessions) == 0


@pytest.mark.asyncio
async def test_unknown_broker_error_keeps_exposure_and_daily_budget(rig):
    seen = {}

    def _execute(*_args, **_kwargs):
        seen["holds"] = _hold_count(rig.path)
        raise RuntimeError("ambiguous broker failure")

    rig.adapter.execute.side_effect = _execute
    response = await rig.client.post(
        "/broker/stock-order", json=_stock_order(attempt_id="unknown-manual"),
    )
    assert response.status_code >= 400, response.text
    assert seen.get("holds") == 1, "unknown dispatch never reserved exposure"
    assert _hold_count(rig.path) == 1
    assert await _reserved(rig.sessions) == 10000


@pytest.mark.asyncio
async def test_patch_proceeds_while_the_adapter_is_blocked_and_sees_the_hold(rig):
    await _seed(rig.sessions, [_stock("ROW", "MSFT", 1, 10)])
    started = threading.Event()
    release = threading.Event()
    seen = {}

    def _execute(*_args, **_kwargs):
        seen["holds"] = _hold_count(rig.path)
        started.set()
        assert release.wait(8)
        return OrderResult(order_id="blocked-1", status="PreSubmitted", broker="ibkr_paper")

    rig.adapter.execute.side_effect = _execute
    task = asyncio.create_task(rig.client.post(
        "/broker/stock-order", json=_stock_order(symbol="AAPL", attempt_id="blocked-send"),
    ))
    assert await asyncio.to_thread(started.wait, 5)
    try:
        async with rig.sessions() as db:
            patched = await asyncio.wait_for(
                update_position("ROW", PortfolioPositionUpdate(stop=9), db),
                timeout=5,
            )
    except TimeoutError:
        release.set()
        pytest.fail("PATCH blocked while the adapter was held")
    finally:
        release.set()
    response = await task
    assert response.status_code == 200, response.text
    assert getattr(patched, "stop", None) == 9
    assert seen.get("holds") == 1, "blocked adapter had no committed exposure hold"


@pytest.mark.asyncio
async def test_the_same_auto_attempt_cannot_post_twice(rig):
    strategy = ArmedStrategy(
        broker="ibkr_paper", symbol="ZED", option_symbol="ZED|200|2026-12-18|C",
        action="BUY", direction="Bullish", quantity=1, order_type="LMT",
        limit_price=1, conid=None, entry_premium=1, stop=100, scan_stock_price=200,
    )
    service = at.AutoTradeService()
    service.arm(strategy)
    first = await asyncio.to_thread(service.fire, portfolio_snapshot=[], attempt_id="t5-same-attempt")
    assert first.result.order_id == "auto-1"
    service.arm(strategy)
    try:
        await asyncio.to_thread(service.fire, portfolio_snapshot=[], attempt_id="t5-same-attempt")
    except Exception:
        pass
    assert rig.execute.call_count == 1, "the same auto attempt posted twice"
