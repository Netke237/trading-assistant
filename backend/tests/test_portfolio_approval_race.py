"""Approval insert versus the hard delete that already removes approvals.

File-backed SQLite, two connections. The position commit and the approval
commit are separate. One side flushes and holds SQLite's reserved lock at that
boundary; the other blocks in the database, not on a mocked clock.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
import app.routers.portfolio as portfolio_router
import app.services.audit as audit_module
import app.services.auto_trade_booking as atb
from app.database import Base
from app.data.ibkr_paper import OrderResult
from app.models.audit_event import AuditEventModel
from app.models.closed_position import ClosedPositionModel
from app.models.portfolio import PortfolioPositionModel
from app.routers.portfolio import add_position, close_position, delete_position
from app.schemas import ClosePositionRequest, PortfolioPositionCreate
from app.services.auto_trade_booking import book_fired_order
from app.services.auto_trader import ArmedStrategy, FiredOrder


def _engine(path):
    url = f"sqlite+aiosqlite:///{path.as_posix()}"
    engine = create_async_engine(
        url, connect_args={"timeout": 5, "check_same_thread": False},
    )
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _ready(path):
    engine, factory = _engine(path)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, factory


@pytest.fixture(autouse=True)
def audit_log(tmp_path, monkeypatch):
    path = tmp_path / "audit.log"
    monkeypatch.setattr(audit_module, "_LOG_PATH", str(path))
    return path


@pytest.fixture(autouse=True)
def _no_live_quotes(monkeypatch):
    async def _none(*_args, **_kwargs):
        return None

    monkeypatch.setattr(portfolio_router, "fetch_contract_quote_async", _none)
    monkeypatch.setattr(portfolio_router, "fetch_price_async", _none)
    monkeypatch.setattr(atb, "fetch_contract_quote_async", _none)
    monkeypatch.setattr(atb, "fetch_price_async", _none)


def _stock(rec, symbol="AAPL"):
    return PortfolioPositionCreate(
        recId=rec,
        symbol=symbol,
        contract=f"{symbol}|STOCK",
        direction="Bullish",
        entryPrice=10.0,
        qty=1,
        entryDate="2026-10-13",
        tradeCardSnapshot={"why": rec},
    )


def _fired(symbol="AAPL", attempt="attempt-race"):
    contract = f"{symbol}|185|2026-12-18|C"
    strategy = ArmedStrategy(
        broker="ibkr_paper",
        symbol=symbol,
        option_symbol=contract,
        action="BUY",
        direction="Bullish",
        quantity=1,
        order_type="LMT",
        limit_price=2.50,
        conid=None,
        entry_premium=2.50,
        stop=180.0,
        scan_stock_price=190.0,
        trade_card_snapshot={"why": symbol},
    )
    return FiredOrder(
        result=OrderResult("777", "Submitted", "ibkr_paper"),
        strategy=strategy,
        attempt_id=attempt,
    )


def _jsonl(path, rec):
    if not path.exists():
        return []
    found = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("event") == "approval" and item.get("rec_id") == rec:
            found.append(item)
    return found


async def _count(factory, model, rec):
    async with factory() as db:
        rows = (await db.execute(select(model).where(model.rec_id == rec))).scalars().all()
    return len(rows)


async def _drop_read_snapshot(db):
    """The writer refresh leaves a shared lock. Commit it, don't roll it back:
    this SQLAlchemy expires every object on rollback, and the caller still
    reads the in-memory position after approval returns."""
    await db.commit()


def _install_commit_spy(pause):
    real = AsyncSession.commit

    async def commit_spy(self):
        await pause(self)
        return await real(self)

    AsyncSession.commit = commit_spy
    return real


async def _add(factory, body):
    async with factory() as db:
        return await add_position(body, db)


async def _book(factory, fired):
    async with factory() as db:
        return await book_fired_order(fired, db)


async def _delete(factory, rec):
    async with factory() as db:
        db.sync_session.info["hold_delete"] = True
        await delete_position(rec, db)


async def _delete_plain(factory, rec):
    async with factory() as db:
        await delete_position(rec, db)


async def _delete_wins(tmp_path, name, writer, rec, audit_log, module):
    """Position is committed. Delete holds the write lock. Then approval runs."""
    engine_a, factory_a = await _ready(tmp_path / name)
    engine_b, factory_b = _engine(tmp_path / name)
    at_boundary = asyncio.Event()
    release_read = asyncio.Event()
    read_dropped = asyncio.Event()
    continue_approval = asyncio.Event()
    delete_holding = asyncio.Event()
    release_delete = asyncio.Event()
    real_log = module.log_approval
    seen = {}

    async def paused(rec_id, data, db):
        seen["rec"] = rec_id
        at_boundary.set()
        await release_read.wait()
        await _drop_read_snapshot(db)
        read_dropped.set()
        await continue_approval.wait()
        await real_log(rec_id, data, db)

    async def pause(session):
        info = session.sync_session.info
        if info.get("hold_delete") and not info.get("delete_held"):
            info["delete_held"] = True
            delete_holding.set()
            await release_delete.wait()

    module.log_approval = paused
    real_commit = _install_commit_spy(pause)
    add_task = asyncio.create_task(writer(factory_a))
    delete_task = None
    try:
        await asyncio.wait_for(at_boundary.wait(), 5)
        rec = seen["rec"]
        # Drop the post-refresh shared lock before delete reserves the database.
        release_read.set()
        await asyncio.wait_for(read_dropped.wait(), 5)
        delete_task = asyncio.create_task(_delete(factory_b, rec))
        await asyncio.wait_for(delete_holding.wait(), 5)
        continue_approval.set()
        await asyncio.sleep(0.3)
        assert not add_task.done(), "approval finished while the delete transaction held the database lock"
        release_delete.set()
        await asyncio.wait_for(asyncio.gather(add_task, delete_task), 8)
        approvals = await _count(factory_a, AuditEventModel, rec)
        assert approvals == 0, f"orphan approval survived a delete ({approvals})"
        assert await _count(factory_a, PortfolioPositionModel, rec) == 0
        assert _jsonl(audit_log, rec) == [], "successful approval was emitted after deletion won"
    finally:
        release_read.set()
        continue_approval.set()
        release_delete.set()
        module.log_approval = real_log
        AsyncSession.commit = real_commit
        for task in (add_task, delete_task):
            if task is not None and not task.done():
                task.cancel()
        pending = [task for task in (add_task, delete_task) if task is not None]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await engine_a.dispose()
        await engine_b.dispose()


async def _approval_wins(tmp_path, name, writer, rec):
    """Approval flushes under the write lock. Delete blocks, then removes it."""
    engine_a, factory_a = await _ready(tmp_path / name)
    engine_b, factory_b = _engine(tmp_path / name)
    holding = asyncio.Event()
    release = asyncio.Event()

    async def pause(session):
        info = session.sync_session.info
        if info.get("approval_held"):
            return
        pending = any(isinstance(obj, AuditEventModel) for obj in session.sync_session.new)
        if not pending:
            return
        info["approval_held"] = True
        await session.flush()
        holding.set()
        await release.wait()

    real_commit = _install_commit_spy(pause)
    add_task = asyncio.create_task(writer(factory_a))
    delete_task = None
    try:
        await asyncio.wait_for(holding.wait(), 5)
        delete_task = asyncio.create_task(_delete_plain(factory_b, rec))
        await asyncio.sleep(0.3)
        assert not delete_task.done(), "delete finished while the approval transaction held the database lock"
        release.set()
        await asyncio.wait_for(asyncio.gather(add_task, delete_task), 8)
        approvals = await _count(factory_a, AuditEventModel, rec)
        assert approvals == 0, f"orphan approval survived a delete ({approvals})"
        assert await _count(factory_a, PortfolioPositionModel, rec) == 0
    finally:
        release.set()
        AsyncSession.commit = real_commit
        for task in (add_task, delete_task):
            if task is not None and not task.done():
                task.cancel()
        pending = [task for task in (add_task, delete_task) if task is not None]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await engine_a.dispose()
        await engine_b.dispose()


@pytest.mark.asyncio
async def test_delete_then_create_leaves_no_orphan_approval(tmp_path, audit_log):
    rec = "REC-DELETE-THEN-CREATE"
    await _delete_wins(
        tmp_path, "delete-then-create.db",
        lambda factory: _add(factory, _stock(rec, "AAA")),
        rec, audit_log, portfolio_router,
    )


@pytest.mark.asyncio
async def test_create_then_delete_leaves_no_orphan_approval(tmp_path):
    rec = "REC-CREATE-THEN-DELETE"

    async def writer(factory):
        async with factory() as db:
            return await add_position(_stock(rec, "BBB"), db)

    await _approval_wins(tmp_path, "create-then-delete.db", writer, rec)


@pytest.mark.asyncio
async def test_delete_then_auto_book_leaves_no_orphan_approval(tmp_path, audit_log):
    await _delete_wins(
        tmp_path, "delete-then-book.db",
        lambda factory: _book(factory, _fired("CCC", "attempt-delete-first")),
        None, audit_log, atb,
    )


@pytest.mark.asyncio
async def test_auto_book_then_delete_leaves_no_orphan_approval(tmp_path):
    seen = {}
    real_log = atb.log_approval

    async def wrapped(rec_id, data, db):
        seen["rec"] = rec_id
        await real_log(rec_id, data, db)

    async def writer(factory):
        async with factory() as db:
            return await book_fired_order(_fired("DDD", "attempt-approval-first"), db)

    engine_a, factory_a = await _ready(tmp_path / "book-then-delete.db")
    engine_b, factory_b = _engine(tmp_path / "book-then-delete.db")
    holding = asyncio.Event()
    release = asyncio.Event()

    async def pause(session):
        info = session.sync_session.info
        if info.get("approval_held"):
            return
        pending = any(isinstance(obj, AuditEventModel) for obj in session.sync_session.new)
        if not pending:
            return
        info["approval_held"] = True
        await session.flush()
        holding.set()
        await release.wait()

    atb.log_approval = wrapped
    real_commit = _install_commit_spy(pause)
    book_task = asyncio.create_task(writer(factory_a))
    delete_task = None
    try:
        await asyncio.wait_for(holding.wait(), 5)
        rec = seen["rec"]
        delete_task = asyncio.create_task(_delete_plain(factory_b, rec))
        await asyncio.sleep(0.3)
        assert not delete_task.done(), "delete finished while the approval transaction held the database lock"
        release.set()
        await asyncio.wait_for(asyncio.gather(book_task, delete_task), 8)
        approvals = await _count(factory_a, AuditEventModel, rec)
        assert approvals == 0, f"orphan approval survived a delete ({approvals})"
        assert await _count(factory_a, PortfolioPositionModel, rec) == 0
    finally:
        release.set()
        atb.log_approval = real_log
        AsyncSession.commit = real_commit
        for task in (book_task, delete_task):
            if task is not None and not task.done():
                task.cancel()
        pending = [task for task in (book_task, delete_task) if task is not None]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await engine_a.dispose()
        await engine_b.dispose()


@pytest.mark.asyncio
async def test_close_between_position_commit_and_approval_keeps_history_approval(tmp_path, audit_log):
    rec = "REC-CLOSE-BETWEEN"
    engine_a, factory_a = await _ready(tmp_path / "close-between.db")
    engine_b, factory_b = _engine(tmp_path / "close-between.db")
    at_boundary = asyncio.Event()
    release_read = asyncio.Event()
    read_dropped = asyncio.Event()
    continue_approval = asyncio.Event()
    real_log = portfolio_router.log_approval

    async def paused(rec_id, data, db):
        at_boundary.set()
        await release_read.wait()
        await _drop_read_snapshot(db)
        read_dropped.set()
        await continue_approval.wait()
        await real_log(rec_id, data, db)

    portfolio_router.log_approval = paused
    add_task = asyncio.create_task(_add(factory_a, _stock(rec, "EEE")))
    try:
        await asyncio.wait_for(at_boundary.wait(), 5)
        release_read.set()
        await asyncio.wait_for(read_dropped.wait(), 5)
        async with factory_b() as db:
            await close_position(rec, ClosePositionRequest(exitPrice=11.0, exitDate="2026-10-13"), db)
        continue_approval.set()
        await asyncio.wait_for(add_task, 8)
        assert await _count(factory_a, PortfolioPositionModel, rec) == 0
        assert await _count(factory_a, ClosedPositionModel, rec) == 1
        assert await _count(factory_a, AuditEventModel, rec) == 1
        assert len(_jsonl(audit_log, rec)) == 1
    finally:
        release_read.set()
        continue_approval.set()
        portfolio_router.log_approval = real_log
        if not add_task.done():
            add_task.cancel()
        await asyncio.gather(add_task, return_exceptions=True)
        await engine_a.dispose()
        await engine_b.dispose()


@pytest.mark.asyncio
async def test_approval_insert_failure_leaves_the_valid_position(tmp_path, audit_log, monkeypatch):
    import app.models.audit_event as audit_event_module

    def _explode(*_args, **_kwargs):
        raise RuntimeError("approval insert failed")

    monkeypatch.setattr(audit_event_module, "AuditEventModel", _explode)
    engine, factory = await _ready(tmp_path / "insert-fails.db")
    rec = "REC-INSERT-FAILS"
    try:
        async with factory() as db:
            saved = await add_position(_stock(rec, "FFF"), db)
        assert saved.recId == rec and saved.qty == 1
        assert await _count(factory, PortfolioPositionModel, rec) == 1
        assert await _count(factory, AuditEventModel, rec) == 0
        assert _jsonl(audit_log, rec) == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_jsonl_failure_after_commit_does_not_fail_the_save(tmp_path, monkeypatch):
    def _explode(*_args, **_kwargs):
        raise OSError("jsonl failed")

    monkeypatch.setattr(audit_module, "log_event", _explode)
    engine, factory = await _ready(tmp_path / "jsonl-fails.db")
    rec = "REC-JSONL-FAILS"
    try:
        async with factory() as db:
            saved = await add_position(_stock(rec, "GGG"), db)
        assert saved.recId == rec and saved.entryPrice == 10.0
        assert await _count(factory, PortfolioPositionModel, rec) == 1
        assert await _count(factory, AuditEventModel, rec) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_create_still_conflicts_without_a_second_approval(tmp_path, audit_log):
    engine, factory = await _ready(tmp_path / "duplicate.db")
    try:
        async with factory() as db:
            saved = await add_position(_stock("REC-DUP-1", "HHH"), db)
        assert saved.recId == "REC-DUP-1"
        async with factory() as db:
            with pytest.raises(HTTPException) as raised:
                await add_position(_stock("REC-DUP-2", "HHH"), db)
        assert raised.value.status_code == 409
        assert await _count(factory, PortfolioPositionModel, "REC-DUP-1") == 1
        assert await _count(factory, PortfolioPositionModel, "REC-DUP-2") == 0
        assert await _count(factory, AuditEventModel, "REC-DUP-1") == 1
        assert await _count(factory, AuditEventModel, "REC-DUP-2") == 0
        assert len(_jsonl(audit_log, "REC-DUP-1")) == 1
        assert _jsonl(audit_log, "REC-DUP-2") == []
    finally:
        await engine.dispose()
