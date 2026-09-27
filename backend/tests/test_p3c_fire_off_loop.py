"""P3c item 7 — POST /auto-trade/fire runs `fire()` off the event loop.

`fire_now` submits `auto_trader.fire` to `_FIRE_EXECUTOR` (one dedicated
worker) and awaits it, so the loop keeps serving other requests during the
market-open check, the regime fetch and the broker call. Pinned here:

- the loop is free while a fire is in flight, and `fire()` runs on the
  `auto-trade-fire*` thread;
- the 500 (sizing config) and 400 (RuntimeError) mappings still hold;
- two concurrent /fire calls are SERIALISED by the single worker — the
  second is still queued while the first is held inside `fire()`;
- the snapshot read's transaction is released before the wait;
- a cancel while `fire()` runs, or while it is queued, writes exactly one line
  from `_log_unbooked` (never "exception calling callback") and books nothing.

`fire` is patched ON THE INSTANCE so the handler's `submit(auto_trader.fire,
...)` receives exactly the stub. Every test that patches it arms first and
disarms in `finally` — `auto_trader` is a process-wide singleton — and every
held stub is released in `finally`, so a failed assertion can never leave the
one worker blocked (the autouse fixture below checks it is idle).
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.services.auto_trader as at
from app.data.ibkr_paper import OrderResult
from app.database import Base, get_db
from app.routers import auto_trade
from app.scoring.conviction_sizing import SizingConfigError
from app.services.auto_trade_booking import BookingOutcome
from app.services.auto_trader import ArmPreservedError, ArmedStrategy, FiredOrder

_LOGGER = "app.routers.auto_trade"


def _make_armed(symbol="AAPL", premium=2.50, qty=1, pv=100_000.0):
    return ArmedStrategy(
        broker="ibkr_paper", symbol=symbol,
        option_symbol=f"{symbol}260620C00185000",
        action="BUY", direction="Bullish", quantity=qty, order_type="LMT",
        limit_price=premium, conid=None,
        entry_premium=premium, portfolio_value=pv,
    )


def _fired(strategy: ArmedStrategy) -> FiredOrder:
    return FiredOrder(OrderResult("oid-1", "filled", "ibkr_paper"), strategy, "attempt-p3c")


class _FakeResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _FakeDb:
    async def execute(self, *a, **k):
        return _FakeResult()

    async def rollback(self):
        pass


@pytest.fixture(autouse=True)
def _fire_worker_idle_after_each_test():
    """Function-scoped: the one worker must be free when each test ends."""
    yield
    auto_trade._FIRE_EXECUTOR.submit(lambda: None).result(timeout=5)


@pytest.fixture
def recorded_submits(monkeypatch):
    """Wrap `_FIRE_EXECUTOR.submit`; record the future ONLY for the patched
    `fire` (looked up at call time), so a helper submitted in the same test is
    never mistaken for the handler's `cf`. Returns (records, original submit)."""
    real_submit = auto_trade._FIRE_EXECUTOR.submit
    recorded: list = []

    def _submit(fn, *a, **k):
        f = real_submit(fn, *a, **k)
        if fn is auto_trade.auto_trader.fire:
            recorded.append(f)
        return f

    monkeypatch.setattr(auto_trade._FIRE_EXECUTOR, "submit", _submit)
    return recorded, real_submit


def _barrier():
    """The single worker finishes the previous item, done-callbacks included,
    before it takes the next — so after this `_log_unbooked` has run."""
    auto_trade._FIRE_EXECUTOR.submit(lambda: None).result(timeout=5)


async def _wait_recorded(recorded, task):
    for _ in range(100):
        if recorded or task.done():
            break
        await asyncio.sleep(0)
    if not recorded and task.done():
        raise AssertionError(f"handler ended before submitting: {task.exception()!r}")
    assert recorded, "fire was never submitted"
    return recorded[0]


def _unbooked_lines(caplog):
    return [r for r in caplog.records
            if r.name == _LOGGER and "POST /auto-trade/fire for" in r.getMessage()]


def _callback_errors(caplog):
    return [r for r in caplog.records if "exception calling callback" in r.getMessage()]


def _app_client(db_factory=_FakeDb) -> AsyncClient:
    app = FastAPI()
    app.include_router(auto_trade.router)

    async def _get_db():
        yield db_factory()

    app.dependency_overrides[get_db] = _get_db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def _booked_mock(mocker):
    return mocker.patch.object(auto_trade, "book_fired_order", AsyncMock(
        return_value=BookingOutcome(booked=True, rec_id="r1", error=None, over_exposure=False)))


# ── The loop is free ─────────────────────────────────────────────────────────

async def test_the_event_loop_serves_other_requests_while_fire_runs(mocker):
    armed = _make_armed(symbol="MSFT")
    auto_trade.auto_trader.arm(armed)
    try:
        def _slow_fire(**kwargs):
            time.sleep(0.5)
            return _fired(armed)

        mocker.patch.object(auto_trade.auto_trader, "fire", _slow_fire)
        _booked_mock(mocker)
        order: list[str] = []

        async with _app_client() as c:
            async def _post():
                r = await c.post("/auto-trade/fire")
                order.append("post")
                return r

            async def _get():
                await asyncio.sleep(0.05)
                r = await c.get("/auto-trade/status")
                order.append("get")
                return r

            post_r, get_r = await asyncio.gather(_post(), _get())

        assert order == ["get", "post"], order
        assert get_r.status_code == 200
        assert post_r.status_code == 200, post_r.text
        assert post_r.json()["rec_id"] == "r1"
    finally:
        auto_trade.auto_trader.disarm()


async def test_fire_runs_on_the_dedicated_worker_thread(mocker):
    armed = _make_armed()
    auto_trade.auto_trader.arm(armed)
    try:
        seen: list[str] = []

        def _fire(**kwargs):
            seen.append(threading.current_thread().name)
            return _fired(armed)

        mocker.patch.object(auto_trade.auto_trader, "fire", _fire)
        _booked_mock(mocker)
        await auto_trade.fire_now(db=_FakeDb())
        assert len(seen) == 1
        assert seen[0].startswith("auto-trade-fire")
        assert seen[0] != threading.current_thread().name
    finally:
        auto_trade.auto_trader.disarm()


# ── Error mapping still holds through the executor ───────────────────────────

async def test_sizing_config_error_from_the_worker_is_still_a_500(mocker):
    auto_trade.auto_trader.arm(_make_armed())
    try:
        exc = SizingConfigError("regime_sizing.min_mult is 0.0, outside (0, 1]")
        stub = mocker.patch.object(auto_trade.auto_trader, "fire", side_effect=exc)
        book = _booked_mock(mocker)
        with pytest.raises(HTTPException) as ei:
            await auto_trade.fire_now(db=_FakeDb())
        assert ei.value.status_code == 500
        assert ei.value.detail == f"{auto_trade.SIZING_CONFIG_REFUSED_PREFIX}{exc}"
        assert stub.call_count == 1
        book.assert_not_awaited()
    finally:
        auto_trade.auto_trader.disarm()


async def test_runtime_error_from_the_worker_is_still_a_400(mocker):
    auto_trade.auto_trader.arm(_make_armed())
    try:
        exc = RuntimeError("market closed — refused")
        stub = mocker.patch.object(auto_trade.auto_trader, "fire", side_effect=exc)
        _booked_mock(mocker)
        with pytest.raises(HTTPException) as ei:
            await auto_trade.fire_now(db=_FakeDb())
        assert ei.value.status_code == 400
        assert ei.value.detail == str(exc)
        assert stub.call_count == 1
    finally:
        auto_trade.auto_trader.disarm()


# ── Two concurrent /fire calls are serialised ───────────────────────────────

async def test_two_concurrent_fires_are_serialised_and_the_second_is_refused(
        mocker, monkeypatch, recorded_submits):
    subs, _ = recorded_submits
    # The REAL fire() appends a "filled" row to the process-wide history and
    # counts toward _check_daily_loss in later fires — isolate it.
    monkeypatch.setattr(auto_trade.auto_trader._state, "history", [])
    mocker.patch.object(at, "_market_is_open", return_value=True)
    mocker.patch.object(at, "_apply_vol_sizing", lambda s: s)
    execute = mocker.patch.object(
        at, "execute_option_order", return_value=OrderResult("oid-9", "filled", "ibkr_paper"))
    _booked_mock(mocker)

    real_fire = auto_trade.auto_trader.fire
    hold = threading.Event()
    calls: list[dict] = []
    lock = threading.Lock()

    def _wrapper(**kwargs):
        rec = {"enter": time.monotonic(), "exit": None, "raised": None}
        with lock:
            first = not calls
            calls.append(rec)
        try:
            if first and not hold.wait(timeout=5):
                raise AssertionError("hold was never released")
            return real_fire(**kwargs)
        except BaseException as e:
            rec["raised"] = type(e)
            raise
        finally:
            rec["exit"] = time.monotonic()

    auto_trade.auto_trader.arm(_make_armed(symbol="NVDA"))
    mocker.patch.object(auto_trade.auto_trader, "fire", _wrapper)
    try:
        async with _app_client() as c:
            both = asyncio.gather(c.post("/auto-trade/fire"), c.post("/auto-trade/fire"))
            try:
                deadline = time.monotonic() + 5
                while len(subs) < 2 and time.monotonic() < deadline:
                    await asyncio.sleep(0.01)
                assert len(subs) == 2, "both requests should pass the armed check"
                deadline = time.monotonic() + 0.5
                while not (len(calls) >= 2 or subs[1].running()) and time.monotonic() < deadline:
                    await asyncio.sleep(0.01)
                # The second call is still QUEUED while the first is held.
                assert len(calls) == 1 and not subs[1].running()
            finally:
                hold.set()
            r1, r2 = await both
    finally:
        hold.set()
        auto_trade.auto_trader.disarm()

    assert len(calls) == 2
    assert [c["raised"] for c in calls].count(ArmPreservedError) == 1
    first, second = sorted(calls, key=lambda c: c["enter"])
    assert second["enter"] >= first["exit"]
    assert execute.call_count == 1
    assert sorted([r1.status_code, r2.status_code]) == [200, 400]


# ── The snapshot read's connection is released before the wait ─────────────

@pytest_asyncio.fixture
async def real_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 connect_args={"check_same_thread": False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as s:
        yield s
    await engine.dispose()


async def test_no_transaction_is_held_while_fire_runs(mocker, real_session):
    armed = _make_armed()
    started, ev = threading.Event(), threading.Event()

    def _held(**kwargs):
        started.set()
        if not ev.wait(timeout=5):
            raise AssertionError("never released")
        return _fired(armed)

    auto_trade.auto_trader.arm(armed)
    try:
        mocker.patch.object(auto_trade.auto_trader, "fire", _held)
        mocker.patch.object(auto_trade, "book_fired_order", AsyncMock())
        task = asyncio.create_task(auto_trade.fire_now(db=real_session))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            assert real_session.in_transaction() is False
        finally:
            ev.set()
        await task
    finally:
        ev.set()
        auto_trade.auto_trader.disarm()


# ── Cancellation ─────────────────────────────────────────────────────────────

@pytest.fixture
def log_capture(caplog):
    caplog.set_level(logging.DEBUG, logger="concurrent.futures")
    caplog.set_level(logging.INFO, logger=_LOGGER)
    return caplog


async def test_case_a_cancel_while_fire_runs_logs_the_unbooked_order(
        mocker, recorded_submits, log_capture):
    recorded, _ = recorded_submits
    armed = _make_armed(symbol="TSLA")
    started, ev = threading.Event(), threading.Event()
    fired = _fired(armed)

    def _held(**kwargs):
        started.set()
        if not ev.wait(timeout=5):
            raise AssertionError("never released")
        return fired

    auto_trade.auto_trader.arm(armed)
    try:
        mocker.patch.object(auto_trade.auto_trader, "fire", _held)
        book = mocker.patch.object(auto_trade, "book_fired_order", AsyncMock())
        task = asyncio.create_task(auto_trade.fire_now(db=_FakeDb()))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            cf = recorded[0]
            assert cf.running()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            ev.set()
        _barrier()
    finally:
        ev.set()
        auto_trade.auto_trader.disarm()

    lines = _unbooked_lines(log_capture)
    assert len(lines) == 1
    assert lines[0].levelno == logging.ERROR
    msg = lines[0].getMessage()
    assert "TSLA" in msg and "cancelled while fire() ran" in msg and repr(fired) in msg
    assert not _callback_errors(log_capture)
    book.assert_not_awaited()


async def test_case_b_cancel_after_fire_finished_logs_at_once(
        mocker, recorded_submits, log_capture):
    recorded, _ = recorded_submits
    armed = _make_armed(symbol="AMD")
    ev = threading.Event()
    fired = _fired(armed)

    def _held(**kwargs):
        if not ev.wait(timeout=5):
            raise AssertionError("never released")
        return fired

    auto_trade.auto_trader.arm(armed)
    try:
        mocker.patch.object(auto_trade.auto_trader, "fire", _held)
        book = mocker.patch.object(auto_trade, "book_fired_order", AsyncMock())
        task = asyncio.create_task(auto_trade.fire_now(db=_FakeDb()))
        try:
            cf = await _wait_recorded(recorded, task)
            ev.set()
            cf.result(timeout=5)
            task.cancel()  # no yield since cf finished: the handler sees it done
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            ev.set()
    finally:
        ev.set()
        auto_trade.auto_trader.disarm()

    lines = _unbooked_lines(log_capture)
    assert len(lines) == 1
    assert lines[0].levelno == logging.ERROR
    assert "AMD" in lines[0].getMessage() and repr(fired) in lines[0].getMessage()
    assert not _callback_errors(log_capture)
    book.assert_not_awaited()


async def test_case_c_cancel_while_fire_runs_then_raises_logs_the_error(
        mocker, recorded_submits, log_capture):
    recorded, _ = recorded_submits
    armed = _make_armed(symbol="META")
    started, ev = threading.Event(), threading.Event()

    def _held(**kwargs):
        started.set()
        if not ev.wait(timeout=5):
            raise AssertionError("never released")
        raise ValueError("boom")

    auto_trade.auto_trader.arm(armed)
    try:
        mocker.patch.object(auto_trade.auto_trader, "fire", _held)
        book = mocker.patch.object(auto_trade, "book_fired_order", AsyncMock())
        task = asyncio.create_task(auto_trade.fire_now(db=_FakeDb()))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            assert recorded[0].running()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            ev.set()
        _barrier()
    finally:
        ev.set()
        auto_trade.auto_trader.disarm()

    lines = _unbooked_lines(log_capture)
    assert len(lines) == 1
    assert lines[0].levelno == logging.ERROR
    assert "META" in lines[0].getMessage() and "boom" in lines[0].getMessage()
    assert not _callback_errors(log_capture)
    book.assert_not_awaited()


async def test_case_d_cancel_while_queued_never_runs_fire(
        mocker, recorded_submits, log_capture):
    recorded, real_submit = recorded_submits
    armed = _make_armed(symbol="ORCL")
    ev = threading.Event()

    def held_blocker():
        if not ev.wait(timeout=5):
            raise AssertionError("never released")

    stub = mocker.MagicMock(side_effect=AssertionError("fire must not run"))
    auto_trade.auto_trader.arm(armed)
    try:
        mocker.patch.object(auto_trade.auto_trader, "fire", stub)
        book = mocker.patch.object(auto_trade, "book_fired_order", AsyncMock())
        blocker = real_submit(held_blocker)
        task = asyncio.create_task(auto_trade.fire_now(db=_FakeDb()))
        try:
            cf = await _wait_recorded(recorded, task)
            assert not cf.running()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert cf.cancelled()
        finally:
            ev.set()
        blocker.result(timeout=5)
        _barrier()
    finally:
        ev.set()
        auto_trade.auto_trader.disarm()

    lines = _unbooked_lines(log_capture)
    assert len(lines) == 1
    assert lines[0].levelno == logging.WARNING
    assert "ORCL" in lines[0].getMessage()
    assert "cancelled before fire() ran" in lines[0].getMessage()
    stub.assert_not_called()
    assert not _callback_errors(log_capture)
    book.assert_not_awaited()
