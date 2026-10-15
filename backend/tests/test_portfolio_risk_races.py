"""Portfolio exposure races and added-fill cost basis.

File-backed SQLite, separate sessions. A reported quantity increase is an
actual fill: both fills persist, the later assessment sees the combined book,
and a stale expectedQty does not apply a second fill.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
import app.routers.portfolio as portfolio_router
import app.services.position_writer as position_writer
from app.database import Base
from app.models.broker_attempt import ExposureHold
from app.models.portfolio import PortfolioPositionModel
from app.schemas import PortfolioPositionCreate, PortfolioPositionUpdate
from app.services import portfolio_risk
from app.services.auto_trader import ArmedStrategy, AutoTradeService
from app.services.portfolio_risk import orm_positions_to_risk
from app.services.position_writer import create_position
from app.routers.portfolio import update_position


def _engine(path):
    url = f"sqlite+aiosqlite:///{path.as_posix()}"
    engine = create_async_engine(url, connect_args={"timeout": 30, "check_same_thread": False})
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _ready(path):
    engine, factory = _engine(path)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, factory


def _stock(rec, symbol, qty, entry, stop=None, targets=None):
    return PortfolioPositionModel(
        rec_id=rec, symbol=symbol, contract=f"{symbol}|STOCK", direction="Bullish",
        entry_price=entry, qty=qty, entry_date="2026-10-13", stop=stop, targets=targets or [],
    )


async def _seed(factory, rows):
    async with factory() as db:
        for row in rows:
            db.add(row)
        await db.commit()


async def _rows(factory):
    async with factory() as db:
        found = (await db.execute(select(PortfolioPositionModel))).scalars().all()
        return {row.rec_id: row for row in found}


def _patch_config(monkeypatch, **portfolio_overrides):
    raw = portfolio_risk._load_config()
    patched = {**raw, "portfolio": {**raw["portfolio"], **portfolio_overrides}}
    monkeypatch.setattr(portfolio_risk, "_load_config", lambda: patched)


async def _update(factory, rec, payload):
    async with factory() as db:
        try:
            return await update_position(rec, PortfolioPositionUpdate(**payload), db)
        except HTTPException as exc:
            return exc


async def _create(factory, **fields):
    body = PortfolioPositionCreate(**fields)
    async with factory() as db:
        try:
            return await create_position(
                body, db,
                quote_fetcher=_no_quote,
                price_fetcher=_no_quote,
            )
        except HTTPException as exc:
            return exc


async def _no_quote(*_args, **_kwargs):
    return None


async def _overlap(first, second, second_symbol):
    """Hold the first writer's commit so the second assesses before it lands.

    After the exposure guard exists, the second blocks on that lock instead of
    assessing, and the wait times out. Releasing the commit then lets it read
    the committed book.
    """
    at_commit = asyncio.Event()
    release = asyncio.Event()
    checked = asyncio.Event()
    used = {"commit": False}
    real_commit = AsyncSession.commit
    real_check = portfolio_risk.check_position_risk

    async def commit_spy(self):
        if not used["commit"]:
            used["commit"] = True
            at_commit.set()
            await release.wait()
        return await real_commit(self)

    def check_spy(*args, **kwargs):
        result = real_check(*args, **kwargs)
        symbol = kwargs.get("symbol", args[0] if args else None)
        if symbol == second_symbol:
            checked.set()
        return result

    AsyncSession.commit = commit_spy
    portfolio_risk.check_position_risk = check_spy
    portfolio_router.check_position_risk = check_spy
    position_writer.check_position_risk = check_spy
    try:
        task_a = asyncio.create_task(first())
        await asyncio.wait_for(at_commit.wait(), timeout=5)
        task_b = asyncio.create_task(second())
        try:
            await asyncio.wait_for(checked.wait(), timeout=2)
        except TimeoutError:
            pass
        release.set()
        return await asyncio.gather(task_a, task_b)
    finally:
        release.set()
        AsyncSession.commit = real_commit
        portfolio_risk.check_position_risk = real_check
        portfolio_router.check_position_risk = real_check
        position_writer.check_position_risk = real_check


def _breach(result):
    if isinstance(result, HTTPException):
        return None
    return getattr(result, "exposureBreach", None)


@pytest.mark.asyncio
async def test_concurrent_patches_persist_both_full_fills_and_the_later_one_warns(tmp_path, monkeypatch):
    _patch_config(monkeypatch, portfolio_value=10000, max_total_stock_exposure_pct=0.015,
                  max_single_stock_position_pct=0.20)
    engine_a, factory_a = await _ready(tmp_path / "patch-patch.db")
    engine_b, _factory_b = _engine(tmp_path / "patch-patch.db")
    factory_b = async_sessionmaker(engine_b, class_=AsyncSession, expire_on_commit=False)
    await _seed(factory_a, [_stock("AAA", "AAA", 1, 10), _stock("BBB", "BBB", 1, 10)])
    fill = {"qty": 10, "expectedQty": 1, "addedFillPrice": 10}
    try:
        first, second = await _overlap(
            lambda: _update(factory_a, "AAA", fill),
            lambda: _update(factory_b, "BBB", fill),
            "BBB",
        )
        rows = await _rows(factory_a)
    finally:
        await engine_a.dispose()
        await engine_b.dispose()
    assert rows["AAA"].qty == 10 and rows["BBB"].qty == 10
    assert rows["AAA"].entry_price == 10 and rows["BBB"].entry_price == 10
    breaches = [_breach(first), _breach(second)]
    assert sum(bool(item) for item in breaches) == 1
    warning = next(item for item in breaches if item)
    assert "total_exposure_limit_reached" in warning
    assert "200.00" in warning


@pytest.mark.asyncio
async def test_later_create_and_fire_refuse_after_the_combined_breach(tmp_path, monkeypatch):
    _patch_config(monkeypatch, portfolio_value=10000, max_total_stock_exposure_pct=0.015,
                  max_single_stock_position_pct=0.20)
    engine, factory = await _ready(tmp_path / "after-breach.db")
    await _seed(factory, [_stock("AAA", "AAA", 1, 10), _stock("BBB", "BBB", 1, 10)])
    fill = {"qty": 10, "expectedQty": 1, "addedFillPrice": 10}
    try:
        first = await _update(factory, "AAA", fill)
        second = await _update(factory, "BBB", fill)
        created = await _create(
            factory, recId="CCC", symbol="CCC", contract="CCC|STOCK", direction="Bullish",
            entryPrice=10, qty=1, entryDate="2026-10-13",
        )
        rows = await _rows(factory)
        snapshot = orm_positions_to_risk(rows.values())
        fired = None
        try:
            AutoTradeService._check_exposure(_stock_arm("DDD"), snapshot, 10000)
        except RuntimeError as exc:
            fired = exc
    finally:
        await engine.dispose()
    assert not isinstance(first, HTTPException)
    assert not isinstance(second, HTTPException)
    assert rows["AAA"].qty == 10 and rows["BBB"].qty == 10
    assert _breach(second) and "total_exposure_limit_reached" in _breach(second)
    assert "200.00" in _breach(second)
    assert isinstance(created, HTTPException) and created.status_code == 422
    assert "total_exposure_limit_reached" in created.detail
    assert "CCC" not in rows
    assert fired is not None and "Exposure cap" in str(fired)


def _stock_arm(symbol):
    return ArmedStrategy(
        broker="ibkr_paper", symbol=symbol, option_symbol=f"{symbol}|STOCK",
        action="BUY", direction="Bullish", quantity=1, order_type="LMT",
        limit_price=10, conid=None, entry_premium=10,
    )


@pytest.mark.asyncio
async def test_patch_arriving_before_create_create_refuses(tmp_path, monkeypatch):
    _patch_config(monkeypatch, portfolio_value=10000, max_total_stock_exposure_pct=0.015,
                  max_single_stock_position_pct=0.20)
    engine_a, factory_a = await _ready(tmp_path / "patch-create.db")
    engine_b, _factory_b = _engine(tmp_path / "patch-create.db")
    factory_b = async_sessionmaker(engine_b, class_=AsyncSession, expire_on_commit=False)
    await _seed(factory_a, [_stock("AAA", "AAA", 1, 10)])
    try:
        patched, created = await _overlap(
            lambda: _update(factory_a, "AAA", {"qty": 10, "expectedQty": 1, "addedFillPrice": 10}),
            lambda: _create(
                factory_b, recId="BBB", symbol="BBB", contract="BBB|STOCK", direction="Bullish",
                entryPrice=10, qty=10, entryDate="2026-10-13",
            ),
            "BBB",
        )
        rows = await _rows(factory_a)
    finally:
        await engine_a.dispose()
        await engine_b.dispose()
    assert not isinstance(patched, HTTPException) and rows["AAA"].qty == 10
    assert isinstance(created, HTTPException) and created.status_code == 422
    assert "total_exposure_limit_reached" in created.detail
    assert "BBB" not in rows


@pytest.mark.asyncio
async def test_create_arriving_before_patch_patch_warns(tmp_path, monkeypatch):
    _patch_config(monkeypatch, portfolio_value=10000, max_total_stock_exposure_pct=0.015,
                  max_single_stock_position_pct=0.20)
    engine_a, factory_a = await _ready(tmp_path / "create-patch.db")
    engine_b, _factory_b = _engine(tmp_path / "create-patch.db")
    factory_b = async_sessionmaker(engine_b, class_=AsyncSession, expire_on_commit=False)
    await _seed(factory_a, [_stock("AAA", "AAA", 1, 10)])
    try:
        created, patched = await _overlap(
            lambda: _create(
                factory_a, recId="BBB", symbol="BBB", contract="BBB|STOCK", direction="Bullish",
                entryPrice=10, qty=10, entryDate="2026-10-13",
            ),
            lambda: _update(factory_b, "AAA", {"qty": 10, "expectedQty": 1, "addedFillPrice": 10}),
            "AAA",
        )
        rows = await _rows(factory_a)
    finally:
        await engine_a.dispose()
        await engine_b.dispose()
    assert not isinstance(created, HTTPException)
    assert rows["BBB"].qty == 10 and rows["AAA"].qty == 10
    warning = _breach(patched)
    assert warning and "total_exposure_limit_reached" in warning and "200.00" in warning


@pytest.mark.asyncio
async def test_same_row_concurrent_added_fills_one_wins_and_the_other_is_stale(tmp_path, monkeypatch):
    _patch_config(monkeypatch, portfolio_value=100000)
    engine_a, factory_a = await _ready(tmp_path / "same-row.db")
    engine_b, _factory_b = _engine(tmp_path / "same-row.db")
    factory_b = async_sessionmaker(engine_b, class_=AsyncSession, expire_on_commit=False)
    await _seed(factory_a, [_stock("AAA", "AAA", 2, 10)])
    try:
        first, second = await _overlap(
            lambda: _update(factory_a, "AAA", {"qty": 5, "expectedQty": 2, "addedFillPrice": 20}),
            lambda: _update(factory_b, "AAA", {"qty": 5, "expectedQty": 2, "addedFillPrice": 30}),
            "AAA",
        )
        rows = await _rows(factory_a)
    finally:
        await engine_a.dispose()
        await engine_b.dispose()
    assert rows["AAA"].qty == 5
    assert rows["AAA"].entry_price == 16
    assert not isinstance(first, HTTPException)
    assert isinstance(second, HTTPException) and second.status_code == 422
    assert "stale_expected_qty" in second.detail


@pytest.mark.asyncio
async def test_stock_added_fill_weights_entry_at_two_ten_plus_three_twenty(tmp_path, monkeypatch):
    _patch_config(monkeypatch, portfolio_value=100000)
    engine, factory = await _ready(tmp_path / "stock-basis.db")
    await _seed(factory, [_stock("AAA", "AAA", 2, 10)])
    try:
        result = await _update(factory, "AAA", {"qty": 5, "expectedQty": 2, "addedFillPrice": 20})
        rows = await _rows(factory)
    finally:
        await engine.dispose()
    assert not isinstance(result, HTTPException)
    assert result.qty == 5
    assert result.entryPrice == 16
    assert rows["AAA"].entry_price == 16
    # 5 * 16 * 1 = 80, inside the stock caps. An option multiplier would warn.
    assert not _breach(result)


@pytest.mark.asyncio
async def test_option_added_fill_weights_entry_and_uses_contract_multiplier(tmp_path, monkeypatch):
    _patch_config(monkeypatch, portfolio_value=100000)
    engine, factory = await _ready(tmp_path / "option-basis.db")
    async with factory() as db:
        db.add(PortfolioPositionModel(
            rec_id="OPT", symbol="OPT", contract="OPT|100|2026-12-18|C", direction="Bullish",
            entry_price=10, qty=2, entry_date="2026-10-13", targets=[],
        ))
        await db.commit()
    try:
        result = await _update(factory, "OPT", {"qty": 5, "expectedQty": 2, "addedFillPrice": 20})
        rows = await _rows(factory)
    finally:
        await engine.dispose()
    # 2 @ 10 + 3 @ 20 = 5 @ 16. Notional 5 * 16 * 100 = 8000, over the option cap.
    assert not isinstance(result, HTTPException)
    assert result.qty == 5
    assert result.entryPrice == 16
    assert rows["OPT"].qty == 5 and rows["OPT"].entry_price == 16
    warning = _breach(result)
    assert warning and "8000.00" in warning
    assert "size_reduced_to_fit_exposure_limit" in warning or "single_trade_exposure_too_high" in warning


@pytest.mark.asyncio
@pytest.mark.parametrize("extra,code", [
    ({}, "added_fill_price_required"),
    ({"addedFillPrice": 0}, "added_fill_price_required"),
    ({"addedFillPrice": -5}, "added_fill_price_required"),
])
async def test_missing_or_invalid_fill_price_keeps_qty_entry_and_saves_stop(tmp_path, monkeypatch, extra, code):
    _patch_config(monkeypatch, portfolio_value=100000)
    engine, factory = await _ready(tmp_path / "bad-price.db")
    await _seed(factory, [_stock("AAA", "AAA", 2, 10)])
    payload = {"qty": 5, "expectedQty": 2, "stop": 9, "targets": [{"stockPrice": 12, "contractsToSell": 5}]}
    payload.update(extra)
    try:
        result = await _update(factory, "AAA", payload)
        rows = await _rows(factory)
    finally:
        await engine.dispose()
    assert isinstance(result, HTTPException) and result.status_code == 422
    assert code in result.detail
    assert rows["AAA"].qty == 2 and rows["AAA"].entry_price == 10 and rows["AAA"].stop == 9
    assert [t["contractsToSell"] for t in rows["AAA"].targets] == [2]


@pytest.mark.asyncio
@pytest.mark.parametrize("extra,code", [
    ({"addedFillPrice": 20}, "expected_qty_required"),
    ({"addedFillPrice": 20, "expectedQty": 1}, "stale_expected_qty"),
])
async def test_stale_or_missing_expected_qty_keeps_qty_entry_and_saves_stop(tmp_path, monkeypatch, extra, code):
    _patch_config(monkeypatch, portfolio_value=100000)
    engine, factory = await _ready(tmp_path / "stale-base.db")
    await _seed(factory, [_stock("AAA", "AAA", 2, 10)])
    payload = {"qty": 5, "stop": 8, "targets": [{"stockPrice": 12, "contractsToSell": 5}]}
    payload.update(extra)
    try:
        result = await _update(factory, "AAA", payload)
        rows = await _rows(factory)
    finally:
        await engine.dispose()
    assert isinstance(result, HTTPException) and result.status_code == 422
    assert code in result.detail
    assert rows["AAA"].qty == 2 and rows["AAA"].entry_price == 10 and rows["AAA"].stop == 8
    assert [t["contractsToSell"] for t in rows["AAA"].targets] == [2]


@pytest.mark.asyncio
async def test_decrease_preserves_entry(tmp_path, monkeypatch):
    _patch_config(monkeypatch, portfolio_value=100000)
    engine, factory = await _ready(tmp_path / "decrease.db")
    await _seed(factory, [_stock("AAA", "AAA", 5, 16)])
    try:
        result = await _update(factory, "AAA", {"qty": 2, "addedFillPrice": 99, "expectedQty": 5})
        rows = await _rows(factory)
    finally:
        await engine.dispose()
    assert not isinstance(result, HTTPException)
    assert result.qty == 2 and result.entryPrice == 16
    assert rows["AAA"].qty == 2 and rows["AAA"].entry_price == 16
    assert not _breach(result)


@pytest.mark.asyncio
async def test_same_total_does_not_apply_another_fill(tmp_path, monkeypatch):
    _patch_config(monkeypatch, portfolio_value=100000)
    engine, factory = await _ready(tmp_path / "same-total.db")
    await _seed(factory, [_stock("AAA", "AAA", 5, 16)])
    try:
        result = await _update(factory, "AAA", {"qty": 5, "expectedQty": 5, "addedFillPrice": 99})
        rows = await _rows(factory)
    finally:
        await engine.dispose()
    assert not isinstance(result, HTTPException)
    assert result.qty == 5 and result.entryPrice == 16
    assert rows["AAA"].entry_price == 16


@pytest.mark.asyncio
async def test_pending_hold_is_in_the_create_snapshot(tmp_path, monkeypatch):
    _patch_config(monkeypatch, portfolio_value=10000)
    engine, factory = await _ready(tmp_path / "hold.db")
    now = datetime.now(timezone.utc)
    async with factory() as db:
        db.add(ExposureHold(
            attempt_id="hold-1", instrument="MSFT|100|2026-12-18|C", quantity=1,
            limit_price="24.00", multiplier=100, notional="2400.00", state="pending",
            effect="OPEN", saved_rec_id=None, coverage_quantity=0, created_at=now, updated_at=now,
        ))
        await db.commit()
    try:
        created = await _create(
            factory, recId="NEW", symbol="AAPL", contract="AAPL|100|2026-12-18|C",
            direction="Bullish", entryPrice=2, qty=1, entryDate="2026-10-13",
        )
        rows = await _rows(factory)
    finally:
        await engine.dispose()
    assert isinstance(created, HTTPException) and created.status_code == 422
    assert "total_exposure_limit_reached" in created.detail
    assert "NEW" not in rows
