"""AUTOTRADE-FIRE-HYGIENE H1 — POST /scan keeps its auto-fire worker's outcome.

`run_scan` submits `auto_trader.maybe_fire_on_scan` to `_SCAN_FIRE_EXECUTOR`
(one dedicated worker, shared with neither /fire nor the default pool) and
awaits the retained concurrent Future. A cancelled await cancels the Future if
it is still queued, installs ONE thread-side done-callback and re-raises; the
callback writes exactly one terminal diagnostic and books nothing. Pinned here:

- a running worker that finishes after the caller was cancelled logs the
  returned order (its OWN symbol, order id, status, attempt id) once;
- a call queued behind an occupied executor is cancelled without entering the
  worker, so the arm is not consumed;
- a worker that finished before the CancelledError handler ran is logged at
  once, on the caller's thread (the add_done_callback race);
- None and exception outcomes each log one line of their own;
- the callback never raises, for a cancelled Future or an unreadable result;
- the uncancelled path still books once, on the loop, with the request db.

H2 (second half of this file) extends the ownership through booking: a
cancel at delivery logs "booking never started"; a cancel while
`book_fired_order` is awaited — before its write, or after the real writer
committed — logs "booking confirmation unavailable" once, never NOT booked; a
cancel in later scan persistence leaves the booked line standing. It also pins
who submits/books, that scheduled scans never dispatch (also overlapping a
manual one), and that the identity guards refuse an old snapshot.

`maybe_fire_on_scan` is patched ON THE singleton instance (run_scan imports
the singleton lazily), which is armed first and disarmed in `finally`. Every
held stub or blocker is released in `finally`, and an autouse fixture checks
the one worker is idle when each test ends. No broker, provider or network.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import re
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.routers.scan as scan_module
import app.services.auto_trade_booking as atb
from app.data.ibkr_paper import OrderResult
from app.services.auto_trade_booking import BookingOutcome
from app.services.auto_trader import ArmedStrategy, FiredOrder, auto_trader

_LOGGER = "app.routers.scan"
_MARKER = "POST /scan was cancelled"


def _armed(symbol="TSLA", premium=2.50):
    return ArmedStrategy(
        broker="ibkr_paper", symbol=symbol,
        option_symbol=f"{symbol}260620C00185000",
        action="BUY", direction="Bullish", quantity=1, order_type="LMT",
        limit_price=premium, conid=None, entry_premium=premium,
    )


def _fired(strategy, status="Submitted", order_id="oid-h1", attempt="attempt-h1"):
    return FiredOrder(OrderResult(order_id, status, "ibkr_paper"), strategy, attempt)


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
def _scan_fire_worker_idle_after_each_test():
    yield
    scan_module._SCAN_FIRE_EXECUTOR.submit(lambda: None).result(timeout=5)


@pytest.fixture(autouse=True)
def _isolated_broker_callback_boundary(monkeypatch):
    # These worker/booking unit tests deliberately use non-schema request and
    # result doubles. Durable integration with actual schemas is tested separately.
    async def reported_callback(request, *, callback, **kwargs):
        return await callback()
    monkeypatch.setattr(scan_module, "run_reported_scan", reported_callback)


@pytest.fixture
def scan_env(monkeypatch):
    """A PASS scan result, no persistence, a counted booking mock."""
    async def reported_callback(request, *, callback, **kwargs):
        return await callback()
    monkeypatch.setattr(scan_module, "run_reported_scan", reported_callback)
    result = SimpleNamespace(scan_id="REC-H1",
                             candidates=[SimpleNamespace(finalStatus="PASS")],
                             rejected=[], noLiveQuoteNames=0)
    monkeypatch.setattr(scan_module, "_execute_scan_core",
                        AsyncMock(return_value=result))
    upsert = AsyncMock()
    monkeypatch.setattr(scan_module, "_upsert_session", upsert)
    monkeypatch.setattr(scan_module, "_last_request", None)
    monkeypatch.setattr(scan_module, "_last_result", None)
    book = AsyncMock(return_value=BookingOutcome(
        booked=True, rec_id="r-h1", error=None, over_exposure=False))
    monkeypatch.setattr(atb, "book_fired_order", book)
    return SimpleNamespace(result=result, upsert=upsert, book=book)


@pytest.fixture
def stub(monkeypatch):
    """Install a `maybe_fire_on_scan` stub on the armed singleton and record
    every `_SCAN_FIRE_EXECUTOR.submit` of it (looked up at call time)."""
    real_submit = scan_module._SCAN_FIRE_EXECUTOR.submit
    state = SimpleNamespace(recorded=[], calls=[], real_submit=real_submit)

    def _submit(fn, *a, **k):
        f = real_submit(fn, *a, **k)
        if fn is auto_trader.maybe_fire_on_scan:
            state.recorded.append(f)
        return f

    monkeypatch.setattr(scan_module._SCAN_FIRE_EXECUTOR, "submit", _submit)

    def install(body):
        def _stub(*args, **kwargs):
            state.calls.append(threading.current_thread().name)
            return body()
        monkeypatch.setattr(auto_trader, "maybe_fire_on_scan", _stub)

    state.install = install
    return state


@pytest.fixture
def armed():
    strategy = _armed()
    auto_trader.arm(strategy)
    try:
        yield strategy
    finally:
        auto_trader.disarm()


@pytest.fixture
def log_capture(caplog):
    caplog.set_level(logging.DEBUG, logger="concurrent.futures")
    caplog.set_level(logging.INFO, logger=_LOGGER)
    return caplog


def _barrier():
    """The single worker finishes the previous item, done-callbacks included,
    before it takes the next — so after this the callback has run."""
    scan_module._SCAN_FIRE_EXECUTOR.submit(lambda: None).result(timeout=5)


async def _wait_recorded(recorded, task):
    for _ in range(200):
        if recorded or task.done():
            break
        await asyncio.sleep(0)
    if not recorded and task.done():
        raise AssertionError(f"run_scan ended before submitting: {task.exception()!r}")
    assert recorded, "maybe_fire_on_scan was never submitted"
    return recorded[0]


def _lines(caplog):
    return [r for r in caplog.records
            if r.name == _LOGGER and _MARKER in r.getMessage()]


def _callback_errors(caplog):
    return [r for r in caplog.records if "exception calling callback" in r.getMessage()]


def _held(started, release, outcome):
    def body():
        started.set()
        if not release.wait(timeout=5):
            raise AssertionError("never released")
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome
    return body


async def _cancel_while_running(stub, scan_env, outcome):
    """Run the scan, cancel it while the stub is held inside the worker, then
    let the stub finish. Returns the retained Future."""
    started, release = threading.Event(), threading.Event()
    stub.install(_held(started, release, outcome))
    task = asyncio.create_task(scan_module.run_scan(SimpleNamespace(), _FakeDb()))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        cf = stub.recorded[0]
        assert cf.running()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
    _barrier()
    return cf


# ── A running worker finishes after the caller was cancelled ────────────────

async def test_running_worker_finishing_after_cancel_logs_its_own_order_once(
        stub, scan_env, armed, log_capture):
    fired = _fired(armed, status="Submitted", order_id="oid-777")
    started, release = threading.Event(), threading.Event()
    stub.install(_held(started, release, fired))
    task = asyncio.create_task(scan_module.run_scan(SimpleNamespace(), _FakeDb()))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        cf = stub.recorded[0]
        assert cf.running()
        # A re-arm while the worker runs: the diagnostic must name the order
        # the worker returned, never what the slot holds now.
        auto_trader.arm(_armed(symbol="NVDA"))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not cf.done(), "the running worker is not stopped by the cancel"
    finally:
        release.set()
    _barrier()

    assert len(stub.recorded) == 1 and len(stub.calls) == 1
    assert stub.calls[0].startswith("scan-auto-fire")
    scan_env.book.assert_not_awaited()
    scan_env.upsert.assert_not_awaited()
    lines = _lines(log_capture)
    assert len(lines) == 1
    line = lines[0]
    assert line.levelno == logging.ERROR
    assert line.threadName.startswith("scan-auto-fire")
    msg = line.getMessage()
    for part in ("TSLA", "oid-777", "'Submitted'", "attempt-h1", "ibkr_paper", "REC-H1"):
        assert part in msg, (part, msg)
    assert "NVDA" not in msg
    assert "booking never started" in msg
    assert not re.search(r"\b(filled|live)\b", msg.lower())
    assert "ArmedStrategy(" not in msg   # selected fields, not whole objects
    assert not _callback_errors(log_capture)


async def test_a_rejected_order_is_logged_with_its_reported_status(
        stub, scan_env, armed, log_capture):
    await _cancel_while_running(stub, scan_env, _fired(armed, status="rejected"))
    [line] = _lines(log_capture)
    msg = line.getMessage()
    assert "'rejected'" in msg
    assert not re.search(r"\b(filled|live)\b", msg.lower())
    scan_env.book.assert_not_awaited()


# ── A call queued behind an occupied executor ───────────────────────────────

async def test_queued_call_is_cancelled_without_entering_the_worker(
        stub, scan_env, armed, log_capture):
    stub.install(lambda: pytest.fail("the queued call must never run"))
    occupied, blocker_release = threading.Event(), threading.Event()

    def _blocker():
        occupied.set()
        blocker_release.wait(timeout=5)

    stub.real_submit(_blocker)
    task = asyncio.create_task(scan_module.run_scan(SimpleNamespace(), _FakeDb()))
    try:
        assert await asyncio.to_thread(occupied.wait, 5)
        cf = await _wait_recorded(stub.recorded, task)
        assert not cf.running() and not cf.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cf.cancelled()
    finally:
        blocker_release.set()
    _barrier()

    assert len(stub.recorded) == 1
    assert stub.calls == []
    state = auto_trader.get_state()
    assert state.armed and state.strategy is armed, "the arm was consumed"
    scan_env.book.assert_not_awaited()
    scan_env.upsert.assert_not_awaited()
    lines = _lines(log_capture)
    assert len(lines) == 1
    assert lines[0].levelno == logging.WARNING
    msg = lines[0].getMessage()
    assert "before maybe_fire_on_scan ran" in msg and "nothing was dispatched" in msg
    assert not _callback_errors(log_capture)


# ── Completion races the callback's installation ────────────────────────────

async def test_worker_done_before_the_handler_runs_is_logged_at_once(
        stub, scan_env, armed, log_capture):
    fired = _fired(armed, order_id="oid-race")
    release = threading.Event()

    def body():
        if not release.wait(timeout=5):
            raise AssertionError("never released")
        return fired

    stub.install(body)
    task = asyncio.create_task(scan_module.run_scan(SimpleNamespace(), _FakeDb()))
    try:
        cf = await _wait_recorded(stub.recorded, task)
        release.set()
        cf.result(timeout=5)
        task.cancel()   # no yield since cf finished: the handler sees it done
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()

    assert len(stub.recorded) == 1 and len(stub.calls) == 1
    scan_env.book.assert_not_awaited()
    scan_env.upsert.assert_not_awaited()
    lines = _lines(log_capture)
    assert len(lines) == 1
    # Already done, so add_done_callback ran it at once on this thread.
    assert lines[0].threadName == threading.current_thread().name
    assert lines[0].levelno == logging.ERROR
    assert "oid-race" in lines[0].getMessage() and "TSLA" in lines[0].getMessage()
    _barrier()
    assert len(_lines(log_capture)) == 1
    assert not _callback_errors(log_capture)


# ── None and exception outcomes ─────────────────────────────────────────────

async def test_none_outcome_after_cancel_logs_no_order_and_books_nothing(
        stub, scan_env, armed, log_capture):
    await _cancel_while_running(stub, scan_env, None)

    assert len(stub.recorded) == 1 and len(stub.calls) == 1
    scan_env.book.assert_not_awaited()
    lines = _lines(log_capture)
    assert len(lines) == 1
    assert lines[0].levelno == logging.WARNING
    msg = lines[0].getMessage()
    assert "returned no order" in msg
    assert "order_id" not in msg and "attempt_id" not in msg
    assert not _callback_errors(log_capture)


async def test_exception_outcome_after_cancel_logs_status_unknown(
        stub, scan_env, armed, log_capture):
    await _cancel_while_running(stub, scan_env, RuntimeError("broker timed out"))

    assert len(stub.recorded) == 1 and len(stub.calls) == 1
    scan_env.book.assert_not_awaited()
    lines = _lines(log_capture)
    assert len(lines) == 1
    assert lines[0].levelno == logging.ERROR
    msg = lines[0].getMessage()
    assert "RuntimeError" in msg and "broker timed out" in msg
    assert "unknown" in msg
    assert not _callback_errors(log_capture)


# ── The callback never raises ───────────────────────────────────────────────

def test_callback_on_a_cancelled_future_does_not_raise(log_capture):
    cf: concurrent.futures.Future = concurrent.futures.Future()
    assert cf.cancel()
    assert scan_module._log_scan_fire_outcome("REC-X", cf) is None
    # And through add_done_callback, which runs it at once.
    cf.add_done_callback(lambda f: scan_module._log_scan_fire_outcome("REC-Y", f))
    lines = _lines(log_capture)
    assert len(lines) == 2
    assert all("nothing was dispatched" in r.getMessage() for r in lines)
    assert not _callback_errors(log_capture)


def test_callback_on_an_unreadable_result_does_not_raise(log_capture):
    class _Unreadable:
        @property
        def result(self):
            raise ValueError("boom")

        @property
        def strategy(self):
            raise ValueError("boom")

    cf: concurrent.futures.Future = concurrent.futures.Future()
    cf.set_result(_Unreadable())
    assert scan_module._log_scan_fire_outcome("REC-Z", cf) is None
    lines = _lines(log_capture)
    assert len(lines) == 1
    assert lines[0].levelno == logging.ERROR
    assert not _callback_errors(log_capture)


# ── The uncancelled path is unchanged ───────────────────────────────────────

async def test_uncancelled_scan_fires_on_the_scan_worker_and_books_once_on_the_loop(
        stub, scan_env, armed, log_capture):
    fired = _fired(armed)
    stub.install(lambda: fired)
    db = _FakeDb()

    out = await scan_module.run_scan(SimpleNamespace(), db)

    assert out is scan_env.result
    assert len(stub.recorded) == 1 and len(stub.calls) == 1
    assert stub.calls[0].startswith("scan-auto-fire")
    scan_env.book.assert_awaited_once_with(fired, db)
    scan_env.upsert.assert_awaited_once()
    assert _lines(log_capture) == []


# ════════════════════════════════════════════════════════════════════════════
# AUTOTRADE-FIRE-HYGIENE H2 — run_scan owns the fire's outcome through booking.
#
# Phases: worker pending → booking not started (FiredOrder delivered) →
# booking started → booking returned. No await separates delivery from the
# `book_fired_order` call, so a cancellation "at delivery" is raised by the
# worker await itself, with `cf` already done; the H1 callback then logs the
# returned order as booking never started. Once booking has started, a cancel
# reports "booking confirmation unavailable" (the writer may have committed);
# after it returned, the booked / NOT booked line already said what happened.
# The real writer (test_o4_step4_booking's harness) is used for
# commit-then-cancel: a cancelled coroutine is NOT assumed to roll back.
# ════════════════════════════════════════════════════════════════════════════

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.position_writer import create_position as _real_create_position
from tests.test_o4_step4_booking import (  # noqa: F401  (fixtures used by name)
    _fired as _o4_fired, _rows, engine_and_session, env,
)

_UNCONFIRMED = "booking confirmation unavailable; check broker and portfolio before acting"


def _scan_lines(caplog):
    return [r for r in caplog.records if r.name == _LOGGER]


def _messages(caplog, text):
    return [r for r in _scan_lines(caplog) if text in r.getMessage()]


@pytest.fixture
def counted_booking(monkeypatch):
    """The REAL `book_fired_order`, counted, recording the thread it runs on."""
    real = atb.book_fired_order
    state = SimpleNamespace(calls=[], threads=[])

    async def _book(fired, db):
        state.calls.append((fired, db))
        state.threads.append(threading.current_thread().name)
        return await real(fired, db)

    monkeypatch.setattr(atb, "book_fired_order", _book)
    return state


async def _run_until(task, event: asyncio.Event):
    """Wait for `event` while `task` runs; fail if the task ends first."""
    waiter = asyncio.ensure_future(event.wait())
    done, _ = await asyncio.wait({waiter, task}, timeout=5,
                                 return_when=asyncio.FIRST_COMPLETED)
    if waiter not in done:
        waiter.cancel()
        if task in done:
            raise AssertionError(f"run_scan ended first: {task.exception()!r}")
        raise AssertionError("the event was never set")


# ── Who submits and who books (existing behaviour, pinned) ──────────────────

async def test_a_pass_scan_submits_once_and_books_once_on_the_loop(
        stub, scan_env, armed, log_capture):
    fired = _fired(armed)
    stub.install(lambda: fired)
    db = _FakeDb()
    out = await scan_module.run_scan(SimpleNamespace(), db)
    assert out is scan_env.result
    assert len(stub.recorded) == 1 and len(stub.calls) == 1
    scan_env.book.assert_awaited_once_with(fired, db)
    assert len(_messages(log_capture, "fired order booked as r-h1")) == 1
    assert _lines(log_capture) == []


@pytest.mark.parametrize("arm", [True, False], ids=["armed", "unarmed"])
async def test_non_pass_or_unarmed_scans_neither_submit_nor_book(
        stub, scan_env, log_capture, arm):
    stub.install(lambda: pytest.fail("must not be called"))
    if arm:
        scan_env.result.candidates = [SimpleNamespace(finalStatus="CAUTION"),
                                      SimpleNamespace(finalStatus="REJECT")]
        auto_trader.arm(_armed())
    else:
        auto_trader.disarm()
    try:
        await scan_module.run_scan(SimpleNamespace(), _FakeDb())
    finally:
        auto_trader.disarm()
    assert stub.recorded == [] and stub.calls == []
    scan_env.book.assert_not_awaited()
    scan_env.upsert.assert_awaited_once()
    assert _lines(log_capture) == []


async def test_a_none_outcome_or_refusal_books_nothing(
        stub, scan_env, armed, log_capture):
    stub.install(lambda: None)
    await scan_module.run_scan(SimpleNamespace(), _FakeDb())
    assert len(stub.recorded) == 1
    scan_env.book.assert_not_awaited()
    scan_env.upsert.assert_awaited_once()
    assert _lines(log_capture) == []


async def test_a_broker_rejection_is_handed_to_booking_as_today(
        stub, scan_env, armed, log_capture):
    fired = _fired(armed, status="rejected")
    stub.install(lambda: fired)
    scan_env.book.return_value = BookingOutcome(
        booked=False, rec_id=None, error="order oid-h1 was not booked: rejection",
        over_exposure=False)
    db = _FakeDb()
    await scan_module.run_scan(SimpleNamespace(), db)
    scan_env.book.assert_awaited_once_with(fired, db)
    assert len(_messages(log_capture, "fired order NOT booked")) == 1
    scan_env.upsert.assert_awaited_once()


async def test_the_worker_never_receives_the_request_session(
        stub, scan_env, armed, monkeypatch):
    seen = []

    def _stub(*args, **kwargs):
        seen.append((args, kwargs, threading.current_thread().name))
        return None

    monkeypatch.setattr(auto_trader, "maybe_fire_on_scan", _stub)
    db = _FakeDb()
    await scan_module.run_scan(SimpleNamespace(), db)
    [(args, kwargs, thread)] = seen
    assert thread.startswith("scan-auto-fire")
    values = list(args) + list(kwargs.values())
    assert all(v is not db and not isinstance(v, AsyncSession) for v in values)


# ── (a) Cancellation at delivery: booking never starts ──────────────────────

async def test_cancel_after_delivery_before_the_task_resumes_logs_booking_not_started(
        stub, scan_env, armed, log_capture):
    """The worker's result has reached the loop and the task's wake-up is
    queued when the cancel lands: it is raised at the worker await, so the
    booking call is never made and the returned order is logged once."""
    fired = _fired(armed, order_id="oid-deliv")
    release = threading.Event()

    def body():
        if not release.wait(timeout=5):
            raise AssertionError("never released")
        return fired

    stub.install(body)
    task = asyncio.create_task(scan_module.run_scan(SimpleNamespace(), _FakeDb()))
    try:
        cf = await _wait_recorded(stub.recorded, task)
        release.set()
        cf.result(timeout=5)
        _barrier()                   # cf's callbacks (the loop hand-off) have run
        await asyncio.sleep(0)       # the hand-off sets the asyncio future
        task.cancel()                # the task's wake-up is queued, not yet run
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
    _barrier()

    scan_env.book.assert_not_awaited()
    scan_env.upsert.assert_not_awaited()
    [line] = _lines(log_capture)
    msg = line.getMessage()
    assert "booking never started" in msg and "oid-deliv" in msg
    assert "confirmation unavailable" not in msg
    assert not _callback_errors(log_capture)


# ── (b) Cancellation while booking is awaited, before its write ─────────────

async def test_cancel_while_booking_awaits_before_its_write_reports_confirmation_unavailable(
        stub, armed, engine_and_session, env, counted_booking, monkeypatch,
        log_capture):
    _, Session = engine_and_session
    result = SimpleNamespace(scan_id="REC-H2B",
                             candidates=[SimpleNamespace(finalStatus="PASS")])
    monkeypatch.setattr(scan_module, "_execute_scan_core", AsyncMock(return_value=result))
    monkeypatch.setattr(scan_module, "_last_request", None)   # run_scan writes both
    monkeypatch.setattr(scan_module, "_last_result", None)
    upsert = AsyncMock()
    monkeypatch.setattr(scan_module, "_upsert_session", upsert)
    entered, hold = asyncio.Event(), asyncio.Event()
    writer_threads = []

    async def _held_before_write(*a, **k):
        writer_threads.append(threading.current_thread().name)
        entered.set()
        await hold.wait()
        return await _real_create_position(*a, **k)

    monkeypatch.setattr(atb, "create_position", _held_before_write)
    fired = _o4_fired()
    stub.install(lambda: fired)
    s = Session()
    task = asyncio.create_task(scan_module.run_scan(SimpleNamespace(), s))
    try:
        await _run_until(task, entered)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        hold.set()
        await s.close()
    _barrier()

    assert len(stub.recorded) == 1 and len(stub.calls) == 1
    assert len(counted_booking.calls) == 1
    assert counted_booking.threads == [threading.current_thread().name]
    assert writer_threads == [threading.current_thread().name]
    upsert.assert_not_awaited()
    assert await _rows(Session) == []
    [line] = _lines(log_capture)
    msg = line.getMessage()
    assert _UNCONFIRMED in msg
    for part in ("AAPL", "'777'", "'Submitted'", "attempt-direct", "REC-H2B"):
        assert part in msg, (part, msg)
    assert "not booked" not in msg.lower()
    assert "booking never started" not in msg
    assert "add it" not in msg.lower() and "by hand" not in msg.lower()
    assert _messages(log_capture, "fired order booked") == []
    assert _messages(log_capture, "fired order NOT booked") == []
    env.notify.assert_not_awaited()


# ── (c) Cancellation after the writer committed, before booking returns ─────

async def test_cancel_after_the_writers_commit_keeps_the_row_and_reports_confirmation_unavailable(
        stub, armed, engine_and_session, env, counted_booking, monkeypatch,
        log_capture):
    _, Session = engine_and_session
    result = SimpleNamespace(scan_id="REC-H2C",
                             candidates=[SimpleNamespace(finalStatus="PASS")])
    monkeypatch.setattr(scan_module, "_execute_scan_core", AsyncMock(return_value=result))
    monkeypatch.setattr(scan_module, "_last_request", None)   # run_scan writes both
    monkeypatch.setattr(scan_module, "_last_result", None)
    upsert = AsyncMock()
    monkeypatch.setattr(scan_module, "_upsert_session", upsert)
    committed, hold = asyncio.Event(), asyncio.Event()

    async def _commit_then_hold(*a, **k):
        out = await _real_create_position(*a, **k)   # the REAL writer commits
        committed.set()
        await hold.wait()
        return out

    monkeypatch.setattr(atb, "create_position", _commit_then_hold)
    fired = _o4_fired()
    stub.install(lambda: fired)
    s = Session()
    task = asyncio.create_task(scan_module.run_scan(SimpleNamespace(), s))
    try:
        await _run_until(task, committed)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        hold.set()
        await s.close()
    _barrier()

    assert len(stub.recorded) == 1 and len(counted_booking.calls) == 1
    upsert.assert_not_awaited()
    [row] = await _rows(Session)           # committed; the cancel did not undo it
    assert row.contract == fired.strategy.option_symbol
    [line] = _lines(log_capture)
    msg = line.getMessage()
    assert _UNCONFIRMED in msg
    assert "'777'" in msg and "attempt-direct" in msg and "REC-H2C" in msg
    assert "not booked" not in msg.lower() and "booking never started" not in msg
    assert "add it" not in msg.lower()
    assert _messages(log_capture, "fired order NOT booked") == []


# ── (d) Cancellation in later scan persistence ──────────────────────────────

async def test_cancel_during_scan_persistence_keeps_the_known_booking(
        stub, armed, engine_and_session, env, counted_booking, monkeypatch,
        log_capture):
    _, Session = engine_and_session
    result = SimpleNamespace(scan_id="REC-H2D",
                             candidates=[SimpleNamespace(finalStatus="PASS")])
    monkeypatch.setattr(scan_module, "_execute_scan_core", AsyncMock(return_value=result))
    monkeypatch.setattr(scan_module, "_last_request", None)
    monkeypatch.setattr(scan_module, "_last_result", None)
    entered, hold = asyncio.Event(), asyncio.Event()
    upsert_calls = []

    async def _held_upsert(db, **kwargs):
        upsert_calls.append(kwargs)
        entered.set()
        await hold.wait()

    monkeypatch.setattr(scan_module, "_upsert_session", _held_upsert)
    fired = _o4_fired()
    stub.install(lambda: fired)
    req = SimpleNamespace(tag="manual-h2d")
    s = Session()
    task = asyncio.create_task(scan_module.run_scan(req, s))
    try:
        await _run_until(task, entered)
        # Another manual scan replacing the globals must not cross the pair.
        scan_module._last_request = SimpleNamespace(tag="other")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        hold.set()
        await s.close()
    _barrier()

    assert len(stub.recorded) == 1 and len(counted_booking.calls) == 1
    [row] = await _rows(Session)
    [kw] = upsert_calls
    assert kw["req"] is req and kw["result"] is result
    booked = _messages(log_capture, "fired order booked as")
    assert len(booked) == 1 and row.rec_id in booked[0].getMessage()
    assert _lines(log_capture) == []                 # no cancellation diagnostic
    assert _messages(log_capture, "NOT booked") == []
    assert _messages(log_capture, "confirmation unavailable") == []


# ── Scheduled scans never dispatch ──────────────────────────────────────────

def _scheduled_entry(entry_id):
    return dict(
        id=entry_id, label="H2 sched", mode="options",
        profile_id="p1", profile_name="p", profile_synced_at="2026-01-01T00:00:00Z",
        resolved_request={"universe": ["AAPL"], "direction": "Bullish",
                          "horizon": "Swing", "overrides": {}},
        pattern="fixed_time", enabled=True, days_of_week=[0, 1, 2, 3, 4],
        fire_time="09:00",
    )


@pytest.fixture
def scheduled(monkeypatch):
    from app.services import scan_schedule_scheduler as sss
    from app.services.scan_schedule_store import scan_schedule_store
    from tests.conftest import _TestSession
    import app.database as dbmod

    monkeypatch.setattr(dbmod, "AsyncSessionLocal", _TestSession)
    async def reported_callback(request, *, callback, **kwargs):
        return await callback()
    monkeypatch.setattr(sss, "run_reported_scan", reported_callback)
    monkeypatch.setattr(sss, "persisted_result", lambda result: {})
    monkeypatch.setattr(sss, "get_latest_successful_run", AsyncMock(return_value=None))
    record = AsyncMock()
    monkeypatch.setattr(sss, "record_scheduled_scan_run", record)
    monkeypatch.setattr(sss, "_notify_scan_schedule_success", AsyncMock())
    monkeypatch.setattr(sss, "_notify_scan_schedule_error", AsyncMock())
    scan_schedule_store.upsert(_scheduled_entry("h2-sched"))
    try:
        yield SimpleNamespace(run=lambda: sss._run_scheduled_entry("h2-sched"),
                              record=record)
    finally:
        scan_schedule_store.delete("h2-sched")


async def test_a_scheduled_pass_scan_never_dispatches_while_armed(
        stub, scan_env, armed, scheduled, log_capture):
    scan_env.result.model_dump_json = lambda: "{}"
    stub.install(lambda: pytest.fail("a scheduled scan must never fire"))
    await scheduled.run()
    assert scheduled.record.await_args.kwargs["status"] == "success"
    assert stub.recorded == [] and stub.calls == []
    scan_env.book.assert_not_awaited()
    state = auto_trader.get_state()
    assert state.armed and state.strategy is armed


async def test_a_manual_scan_overlapping_a_scheduled_one_dispatches_once(
        stub, scan_env, armed, scheduled, monkeypatch, log_capture):
    from app.schemas import ScanRequest
    manual_result = scan_env.result
    sched_result = SimpleNamespace(scan_id="REC-SCHED", model_dump_json=lambda: "{}",
                                   candidates=[SimpleNamespace(finalStatus="PASS")],
                                   rejected=[], noLiveQuoteNames=0)
    sched_in_core, sched_gate = asyncio.Event(), asyncio.Event()

    async def _core(req, db, previous_result=None):
        if isinstance(req, ScanRequest):          # the scheduled entry's request
            sched_in_core.set()
            await sched_gate.wait()
            return sched_result
        return manual_result

    monkeypatch.setattr(scan_module, "_execute_scan_core", _core)
    fired = _fired(armed)
    started, release = threading.Event(), threading.Event()
    stub.install(_held(started, release, fired))
    sched_task = asyncio.create_task(scheduled.run())
    manual_task = None
    try:
        await _run_until(sched_task, sched_in_core)       # scheduled is mid-scan
        manual_task = asyncio.create_task(
            scan_module.run_scan(SimpleNamespace(), _FakeDb()))
        assert await asyncio.to_thread(started.wait, 5)   # manual worker held
        sched_gate.set()
        await sched_task                                  # scheduled completes
        assert len(stub.recorded) == 1 and len(stub.calls) == 1
        release.set()
        await manual_task
    finally:
        sched_gate.set()
        release.set()
        if manual_task is not None and not manual_task.done():
            manual_task.cancel()
    assert scheduled.record.await_args.kwargs["status"] == "success"
    assert len(stub.recorded) == 1 and len(stub.calls) == 1
    scan_env.book.assert_awaited_once()
    assert scan_env.book.await_args.args[0] is fired


# ── Re-arm / manual-fire overlap: the identity guards hold ──────────────────

@pytest.fixture
def real_trigger(mocker, monkeypatch, scan_env):
    """The REAL singleton `maybe_fire_on_scan` (not stubbed); broker mocked."""
    import app.services.auto_trader as at
    monkeypatch.setattr(auto_trader._state, "history", [])
    execute = mocker.patch.object(
        at, "execute_option_order",
        side_effect=AssertionError("no order may be sent on an old snapshot"))
    mocker.patch.object(at, "_apply_vol_sizing", lambda s: s)
    stale_alert = mocker.patch.object(at, "_alert_stale_arm")
    return SimpleNamespace(at=at, execute=execute, stale_alert=stale_alert)


@pytest.mark.parametrize("overlap", ["re-armed", "consumed-by-manual-fire"])
async def test_a_slot_change_inside_fires_window_never_sends_the_old_snapshot(
        real_trigger, scan_env, monkeypatch, log_capture, overlap):
    """`maybe_fire_on_scan` read A and calls `fire(expect=A)`; while that
    attempt is inside `_market_is_open` (before its disarm) the slot changes.
    The identity re-check under the disarm's own lock refuses: nothing sent,
    nothing booked, the new arm preserved."""
    a, b = _armed("TSLA"), _armed("NVDA")
    entered, release = threading.Event(), threading.Event()

    def _held_market_open(symbol):
        entered.set()
        if not release.wait(timeout=5):
            raise AssertionError("never released")
        return True

    monkeypatch.setattr(real_trigger.at, "_market_is_open", _held_market_open)
    auto_trader.arm(a)
    task = asyncio.create_task(scan_module.run_scan(SimpleNamespace(), _FakeDb()))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        if overlap == "re-armed":
            auto_trader.arm(b)
        else:
            auto_trader.disarm()   # what a manual /fire's own disarm leaves
        release.set()
        await task
    finally:
        release.set()
        state = auto_trader.get_state()
        auto_trader.disarm()

    real_trigger.execute.assert_not_called()
    scan_env.book.assert_not_awaited()
    if overlap == "re-armed":
        assert state.armed and state.strategy is b
    else:
        assert not state.armed
    assert auto_trader._state.history == []
    assert _lines(log_capture) == []


async def test_a_re_arm_inside_the_stale_check_is_not_aged_out(
        real_trigger, scan_env, monkeypatch, log_capture):
    import dataclasses
    from datetime import datetime, timedelta, timezone
    a = dataclasses.replace(_armed("TSLA"),
                            armed_at=datetime.now(timezone.utc) - timedelta(days=1))
    b = _armed("NVDA")
    entered, release = threading.Event(), threading.Event()

    def _held_max_age():
        entered.set()
        if not release.wait(timeout=5):
            raise AssertionError("never released")
        return 30

    monkeypatch.setattr(auto_trader, "_max_arm_age_minutes", _held_max_age)
    auto_trader.arm(a)
    task = asyncio.create_task(scan_module.run_scan(SimpleNamespace(), _FakeDb()))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        auto_trader.arm(b)
        release.set()
        await task
    finally:
        release.set()
        state = auto_trader.get_state()
        auto_trader.disarm()

    assert state.armed and state.strategy is b, "B was destroyed on A's age"
    real_trigger.execute.assert_not_called()
    real_trigger.stale_alert.assert_not_called()
    scan_env.book.assert_not_awaited()
    assert auto_trader._state.history == []


def test_the_unconfirmed_diagnostic_does_not_raise_on_an_unreadable_order(log_capture):
    class _Unreadable:
        @property
        def result(self):
            raise ValueError("boom")

    assert scan_module._log_scan_booking_unconfirmed("REC-U", _Unreadable()) is None
    [line] = _lines(log_capture)
    assert _UNCONFIRMED in line.getMessage()
    assert "not booked" not in line.getMessage().lower()
