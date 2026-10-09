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


@pytest.fixture
def scan_env(monkeypatch):
    """A PASS scan result, no persistence, a counted booking mock."""
    result = SimpleNamespace(scan_id="REC-H1",
                             candidates=[SimpleNamespace(finalStatus="PASS")])
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
