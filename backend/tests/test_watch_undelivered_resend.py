"""WATCH-UNDELIVERED-EVENT-RESEND (decision WATCH-RESEND-QUEUE-2026-09-26).

A fired watch event moves its watch to the new state at once; an alert that
could not be sent waits in last_state["pending_events"] and is re-sent,
labelled "Delayed", at the start of the next run -- even if the condition no
longer holds. Plan: docs/superpowers/plans/2026-09-26-watch-undelivered-event-resend-plan.md
(test numbers below are the plan's section 6)."""
from __future__ import annotations

import copy
import logging
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

import app.services.strategy_watch_evaluator as ev_mod
from app.services.strategy_watch_evaluator import (
    WatchEvent, _format_event, _plain_event, evaluate_all, evaluate_and_notify,
)
from app.services.strategy_watch_store import StrategyWatchStore

_EV = "app.services.strategy_watch_evaluator"


class _Store:
    """In-memory stand-in shaped like the real store: list_watches is a SHALLOW
    copy (nested last_state dicts are the store's own), and update_state keeps
    a deep copy -- so an in-place mutation of a snapshot's queue shows up as a
    change the evaluator never wrote."""

    def __init__(self, watches: list[dict]):
        self.watches = watches
        self.writes: list[tuple[str, dict]] = []

    def list_watches(self) -> list[dict]:
        return [dict(w) for w in self.watches]

    def update_state(self, watch_id: str, new_state: dict) -> None:
        self.writes.append((watch_id, copy.deepcopy(new_state)))
        for w in self.watches:
            if w["id"] == watch_id:
                w["last_state"] = copy.deepcopy(new_state)

    def state(self, watch_id: str) -> dict:
        return next(w for w in self.watches if w["id"] == watch_id)["last_state"]

    def queue(self, watch_id: str) -> list[dict] | None:
        return self.state(watch_id).get("pending_events")


def _bars(close: float, n: int = 260) -> list[dict]:
    return [{"time": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}",
             "open": close, "high": close + 1, "low": close - 1,
             "close": close, "volume": 1_000_000} for i in range(n)]


_LAST_BAR = _bars(1.0)[-1]["time"]


def _signal(direction="Bullish", entry=100.0, stop=99.0, target=110.0):
    sig = MagicMock()
    sig.direction, sig.entry_price, sig.stop_price, sig.target_price = direction, entry, stop, target
    sig.rr_ratio = 10.0
    return sig


def _strategy_watch(wid: str, phase: str = "idle", **state) -> dict:
    return {"id": wid, "symbol": "AAPL", "strategy_key": "pullback_ema",
            "params_override": {}, "enabled": True, "direction": "Bullish",
            "last_state": {"phase": phase, **state}}


def _armed(wid: str = "a", **state) -> dict:
    return _strategy_watch(wid, "armed", direction="Bullish", entry_price=100.0,
                           stop_price=99.0, target_price=110.0, **state)


def _composite(wid: str = "c", **state) -> dict:
    return {"id": wid, "symbol": "AAPL", "watch_type": "composite", "direction": "Bullish",
            "enabled": True, "interval": "1D",
            "trigger_def": {"primary": {"model": "OMM", "to_state": "bull_trend"}},
            "last_state": {"phase": "idle", **state}}


def _event(event_type="entry", reason="queued alert", **kw) -> WatchEvent:
    base = dict(watch_id="a", symbol="AAPL", strategy_key="pullback_ema",
                event_type=event_type, direction="Bullish", entry=100.0, stop=99.0,
                target=110.0, rr_ratio=None, close=100.0, reason=reason,
                fired_at="2026-09-25T20:05:00+00:00", bar_time="2026-09-25")
    base.update(kw)
    return WatchEvent(**base)


def _entry(event_type="entry", attempts=0, **kw) -> dict:
    return {"event": _plain_event(_event(event_type, **kw)), "attempts": attempts}


class _Ctl:
    """What one run sees. Mutated between runs."""

    def __init__(self, *, close=100.0, sig=None, channel=True, fired=True):
        self.close, self.sig, self.channel, self.fired = close, sig, channel, fired
        self.signal_calls = 0

    def signal(self, bars, direction, **kw):
        self.signal_calls += 1
        return self.sig if self.sig is not None and direction == self.sig.direction else None


def _patches(store, ctl: _Ctl, notify) -> ExitStack:
    stack = ExitStack()
    stack.enter_context(patch(f"{_EV}.strategy_watch_store", store))
    stack.enter_context(patch(f"{_EV}.get_bars", new_callable=AsyncMock,
                              side_effect=lambda *a, **k: _bars(ctl.close)))
    stack.enter_context(patch.dict(ev_mod._SIGNAL_FNS, {"pullback_ema": ctl.signal}))
    stack.enter_context(patch(f"{_EV}.load_notification_config",
                              side_effect=lambda: {"gmail": {"enabled": ctl.channel}}))
    stack.enter_context(patch(f"{_EV}.notify_enabled_channels", notify))
    stack.enter_context(patch("app.services.composite_trigger_evaluator.evaluate_scheduled",
                              side_effect=lambda *a, **k: ctl.fired))
    stack.enter_context(patch("app.services.composite_trigger_evaluator.describe_match",
                              return_value={"structure_matched": [], "structure_total": 0,
                                            "strategy_matched": [], "strategy_total": 0}))
    return stack


def _subjects(notify) -> list[str]:
    return [c.args[0] for c in notify.await_args_list]


# ── 1-3: the defect ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_1_undelivered_exit_stop_goes_idle_and_is_queued():
    store = _Store([_armed()])
    ctl = _Ctl(close=98.0)                                   # 98 <= stop 99
    notify = AsyncMock(return_value=False)
    with _patches(store, ctl, notify):
        events = await evaluate_and_notify()
    assert [(e.event_type, e.delayed) for e in events] == [("exit_stop", False)]
    assert store.state("a")["phase"] == "idle"
    queue = store.queue("a")
    assert len(queue) == 1 and queue[0]["attempts"] == 0
    ev = queue[0]["event"]
    assert ev["event_type"] == "exit_stop" and ev["close"] == 98.0
    assert isinstance(ev["fired_at"], str) and ev["bar_time"] == _LAST_BAR


@pytest.mark.asyncio
async def test_2_the_lost_stop_is_sent_next_run_even_though_price_recovered():
    store = _Store([_armed()])
    ctl = _Ctl(close=98.0)
    notify = AsyncMock(side_effect=[False, True])
    with _patches(store, ctl, notify):
        await evaluate_and_notify()
        ctl.close = 105.0                                    # back above the old stop
        events = await evaluate_and_notify()
    assert notify.await_count == 2
    subject, plain, html = notify.await_args_list[1].args
    assert subject.startswith("Delayed: Stop hit")
    first = plain.splitlines()[0]
    assert first.startswith("Delayed: Stop hit — close 98.0 (bar " + _LAST_BAR + "), detected ")
    assert "the condition may no longer hold" in first
    assert "pending_events" not in store.state("a")
    assert [(e.event_type, e.delayed) for e in events] == [("exit_stop", True)]


@pytest.mark.asyncio
async def test_3_a_failed_resend_counts_an_attempt_and_the_watch_is_still_evaluated():
    store = _Store([_armed()])
    ctl = _Ctl(close=98.0)
    notify = AsyncMock(return_value=False)
    with _patches(store, ctl, notify):
        await evaluate_and_notify()
        ctl.close, ctl.signal_calls = 105.0, 0
        await evaluate_and_notify()
    assert ctl.signal_calls >= 1
    assert [q["attempts"] for q in store.queue("a")] == [1]


# ── 4-8: order and channels ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_4_lost_exit_scenario_nothing_is_lost():
    store = _Store([_strategy_watch("a")])
    ctl = _Ctl(close=100.0, sig=_signal(entry=100.0, stop=99.0, target=110.0))
    notify = AsyncMock(return_value=False)
    with _patches(store, ctl, notify):
        await evaluate_and_notify()                          # run 1: entry, undelivered
        assert store.state("a")["phase"] == "armed"
        assert [q["event"]["event_type"] for q in store.queue("a")] == ["entry"]
        assert notify.await_count == 1

        ctl.close, ctl.sig = 98.0, None                      # run 2: stop hit, still down
        await evaluate_and_notify()
        assert notify.await_count == 2                       # only the failed resend
        assert store.state("a")["phase"] == "idle"
        assert [(q["event"]["event_type"], q["attempts"]) for q in store.queue("a")] == \
            [("entry", 1), ("exit_stop", 0)]

        ctl.close = 105.0                                    # run 3: channel back
        notify.side_effect = None
        notify.return_value = True
        await evaluate_and_notify()
    assert notify.await_count == 4
    assert [s.split(":")[0] + ":" + s.split(":")[1] for s in _subjects(notify)[2:]] == \
        ["Delayed: Long setup", "Delayed: Stop hit"]
    assert "pending_events" not in store.state("a")
    assert store.state("a")["phase"] == "idle"


@pytest.mark.asyncio
async def test_5_flushed_queue_then_new_transition_sent_normally_in_the_same_run():
    store = _Store([_armed(pending_events=[_entry("entry")])])
    ctl = _Ctl(close=98.0)
    notify = AsyncMock(return_value=True)
    with _patches(store, ctl, notify):
        events = await evaluate_and_notify()
    assert [(e.event_type, e.delayed) for e in events] == [("entry", True), ("exit_stop", False)]
    subjects = _subjects(notify)
    assert subjects[0].startswith("Delayed: Long setup") and subjects[1].startswith("Stop hit")
    assert "pending_events" not in store.state("a")
    assert store.state("a")["phase"] == "idle"


@pytest.mark.asyncio
async def test_6_flush_stops_at_the_first_failure_and_keeps_order():
    store = _Store([_strategy_watch("a", pending_events=[_entry(reason="A"), _entry(reason="B")])])
    notify = AsyncMock(side_effect=[False])
    with _patches(store, _Ctl(), notify):
        await evaluate_and_notify()
    assert notify.await_count == 1
    assert [(q["event"]["reason"], q["attempts"]) for q in store.queue("a")] == [("A", 1), ("B", 0)]


@pytest.mark.asyncio
async def test_7_composite_queued_entry_is_sent_and_the_watch_re_arms_same_run():
    store = _Store([_composite()])
    ctl = _Ctl(fired=True)
    notify = AsyncMock(return_value=False)
    with _patches(store, ctl, notify):
        await evaluate_and_notify()
        assert store.state("c")["phase"] == "armed"
        assert [q["event"]["strategy_key"] for q in store.queue("c")] == ["composite"]
        ctl.fired = False
        notify.return_value = True
        events = await evaluate_and_notify()
    assert [(e.event_type, e.delayed) for e in events] == [("entry", True)]
    assert _subjects(notify)[-1].startswith("Delayed: Long setup")
    assert store.state("c")["phase"] == "idle"
    assert "pending_events" not in store.state("c")


@pytest.mark.asyncio
async def test_8_no_channel_keeps_the_queue_and_new_events_join_it():
    store = _Store([_armed(pending_events=[_entry("entry")])])
    ctl = _Ctl(close=98.0, channel=False)
    notify = AsyncMock(return_value=True)
    with _patches(store, ctl, notify):
        events = await evaluate_and_notify()
        notify.assert_not_awaited()
        assert [(e.event_type, e.delayed) for e in events] == [("exit_stop", False)]
        assert [(q["event"]["event_type"], q["attempts"]) for q in store.queue("a")] == \
            [("entry", 0), ("exit_stop", 0)]
        assert store.state("a")["phase"] == "idle"

        ctl.channel, ctl.close = True, 105.0
        events = await evaluate_and_notify()
    assert [(e.event_type, e.delayed) for e in events] == [("entry", True), ("exit_stop", True)]
    assert [s.startswith("Delayed: ") for s in _subjects(notify)] == [True, True]
    assert "pending_events" not in store.state("a")


@pytest.mark.asyncio
async def test_8b_no_channel_and_no_queue_commits_without_queueing():
    store = _Store([_strategy_watch("a")])
    notify = AsyncMock(return_value=False)
    with _patches(store, _Ctl(sig=_signal(), channel=False), notify):
        await evaluate_and_notify()
    assert store.state("a")["phase"] == "armed"
    assert "pending_events" not in store.state("a")


# ── 9: non-event writes keep the queue ────────────────────────────────────────

def _q():
    return [_entry("exit_stop")]


@pytest.mark.parametrize("watch, ctl, sustain", [
    (_strategy_watch("a", pending_events=_q()), _Ctl(sig=_signal()), 10),              # clock start
    (_strategy_watch("a", pending_events=_q(), pending_entry_since="garbage"),
     _Ctl(sig=_signal()), 10),                                                         # restart
    (_strategy_watch("a", pending_events=_q(), pending_entry_since="2026-09-25T00:00:00+00:00"),
     _Ctl(sig=None), 10),                                                              # reset
    ({**_composite("a", pending_events=_q()),
      "trigger_def": {"primary": {"model": "OMM"}, "sustain_minutes": 10}},
     _Ctl(fired=True), 0),                                                             # composite start
    ({**_composite("a", pending_events=_q(), pending_entry_since="2026-09-25T00:00:00+00:00"),
      "trigger_def": {"primary": {"model": "OMM"}, "sustain_minutes": 10}},
     _Ctl(fired=False), 0),                                                            # composite reset
    (_composite("a", pending_events=_q(), phase="armed"), _Ctl(fired=False), 0),       # armed -> idle
], ids=["sustain-start", "sustain-restart", "sustain-reset",
        "composite-sustain-start", "composite-sustain-reset", "composite-rearm"])
@pytest.mark.asyncio
async def test_9_non_event_writes_keep_the_queue(watch, ctl, sustain):
    store = _Store([watch])
    with _patches(store, ctl, AsyncMock(return_value=False)):
        await evaluate_and_notify(sustain)
    assert len(store.writes) >= 2                             # flush write + the non-event write
    assert [(q["event"]["event_type"], q["attempts"]) for q in store.queue("a")] == [("exit_stop", 1)]


# ── 10-11: malformed values and isolation ─────────────────────────────────────

_VALID = _entry("exit_stop")


@pytest.mark.parametrize("value, kept, logged", [
    (None, [], False),
    ({}, [], True),
    ("", [], True),
    (["x"], [], True),
    ([{"event": "x"}], [], True),
    ([{"event": {k: v for k, v in _VALID["event"].items() if k != "close"}}], [], True),
    ([{"event": _VALID["event"], "attempts": "x"}], [1], False),
    ([{"event": _VALID["event"], "attempts": float("inf")}], [1], False),
    ([{"event": _VALID["event"], "attempts": float("nan")}], [1], False),
    ([_VALID, "x"], [1], True),
])
@pytest.mark.asyncio
async def test_10_malformed_queue_values(value, kept, logged, caplog):
    store = _Store([_strategy_watch("a", pending_events=value)])
    ctl = _Ctl()
    with caplog.at_level(logging.ERROR, logger=_EV), \
            _patches(store, ctl, AsyncMock(return_value=False)):
        await evaluate_and_notify()
    if kept:
        assert [q["attempts"] for q in store.queue("a")] == kept
    else:
        assert store.state("a").get("pending_events") is None   # malformed value removed
    assert any("malformed pending_events" in r.message for r in caplog.records) is logged
    assert ctl.signal_calls >= 1                               # evaluated normally


def test_10a_pending_never_raises_on_a_non_dict_state():
    assert ev_mod._pending("x") == ([], False)
    assert ev_mod._pending(None) == ([], False)


@pytest.mark.asyncio
async def test_10b_non_dict_last_state_does_not_stop_the_run():
    bad = _strategy_watch("bad")
    bad["last_state"] = "x"
    store = _Store([bad, _strategy_watch("b", pending_events=[_entry()])])
    notify = AsyncMock(return_value=True)
    with _patches(store, _Ctl(), notify):
        events = await evaluate_and_notify()
    assert [(e.event_type, e.delayed) for e in events] == [("entry", True)]
    assert "pending_events" not in store.state("b")
    assert store.state("bad") == "x"


@pytest.mark.asyncio
async def test_11_one_watch_failing_in_the_flush_does_not_stop_the_others(caplog):
    store = _Store([_strategy_watch("a", tag="A", pending_events=[_entry()]),
                    _strategy_watch("b", pending_events=[_entry()])])
    real = ev_mod._pending

    def _pending(state, log=True):
        if isinstance(state, dict) and state.get("tag") == "A":
            raise RuntimeError("boom")
        return real(state, log)

    notify = AsyncMock(return_value=True)
    with caplog.at_level(logging.ERROR, logger=_EV), _patches(store, _Ctl(), notify), \
            patch(f"{_EV}._pending", _pending):
        await evaluate_and_notify()
    assert notify.await_count == 1
    assert "pending_events" not in store.state("b")
    assert any("queue flush failed for watch a" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_11b_a_failed_write_for_one_watch_does_not_stop_the_others(caplog):
    store = _Store([_strategy_watch("a", pending_events=[_entry()]),
                    _strategy_watch("b", pending_events=[_entry()])])
    real_update = store.update_state

    def _update(wid, state):
        if wid == "a":
            raise OSError("disk full")
        real_update(wid, state)

    store.update_state = _update
    notify = AsyncMock(return_value=True)
    with caplog.at_level(logging.ERROR, logger=_EV), _patches(store, _Ctl(), notify):
        await evaluate_and_notify()
    assert notify.await_count == 2
    assert len(store.queue("a")) == 1                         # delivered, not removed: may re-send
    assert "pending_events" not in store.state("b")
    assert any("may be re-sent" in r.message for r in caplog.records)


# ── 12: YAML round-trip through the real store ────────────────────────────────

def test_12_queue_round_trips_through_the_real_store(tmp_path):
    path = tmp_path / "w.yaml"
    store = StrategyWatchStore(path)
    w = store.add_watch("AAPL", "pullback_ema")
    ev = _event("exit_stop", close=np.float64(98.5), entry=np.float64(100.0),
                rr_ratio=np.float64(2.5))
    queue = [{"event": _plain_event(ev), "attempts": 0}]
    store.update_state(w["id"], {"phase": "idle", "pending_events": queue})
    assert "!!python" not in path.read_text()
    reloaded = StrategyWatchStore(path).list_watches()[0]["last_state"]["pending_events"]
    assert reloaded == queue
    assert type(reloaded[0]["event"]["close"]) is float


# ── 13 + 21: message format ───────────────────────────────────────────────────

_ENTRY = WatchEvent("w1", "AAPL", "pullback_ema", "entry", "Bullish", 100.0, 95.0, 110.0, 2.0, 100.5,
                    "AAPL: Pullback EMA long setup — entry 100.0, stop 95.0, target 110.0 (reward-to-risk 2.0)")
_STOP = WatchEvent("w1", "AAPL", "pullback_ema", "exit_stop", "Bullish", 100.0, 99.0, 110.0, None, 98.0,
                   "AAPL: Pullback EMA stop hit at 98.0 (stop 99.0)")


def test_13_on_time_messages_are_byte_identical_to_before():
    # Copied from the code BEFORE this package (not captured from the new function).
    assert _format_event(_ENTRY) == (
        'Long setup: AAPL — Pullback EMA',
        'AAPL: Pullback EMA long setup — entry 100.0, stop 95.0, target 110.0 (reward-to-risk 2.0)\n\n'
        'Strategy: Pullback EMA\nLast close: 100.5\nEntry 100.0 · Stop 95.0 · Target 110.0\n'
        'Reward-to-risk ratio: 2.0',
        '<b>Long setup: AAPL — Pullback EMA</b>\nAAPL: Pullback EMA long setup — entry 100.0, stop 95.0, '
        'target 110.0 (reward-to-risk 2.0)\n\nStrategy: Pullback EMA\nLast close: 100.5\n'
        'Entry 100.0 · Stop 95.0 · Target 110.0\nReward-to-risk ratio: 2.0\n',
    )
    assert _format_event(_STOP) == (
        'Stop hit: AAPL — Pullback EMA',
        'AAPL: Pullback EMA stop hit at 98.0 (stop 99.0)\n\nStrategy: Pullback EMA\nLast close: 98.0\n'
        'Entry 100.0 · Stop 99.0 · Target 110.0',
        '<b>Stop hit: AAPL — Pullback EMA</b>\nAAPL: Pullback EMA stop hit at 98.0 (stop 99.0)\n\n'
        'Strategy: Pullback EMA\nLast close: 98.0\nEntry 100.0 · Stop 99.0 · Target 110.0\n',
    )


def test_13b_delayed_message():
    ev = _event("exit_stop", close=98.0, reason="AAPL <b> stop", delayed=True)
    subject, plain, html = _format_event(ev)
    line = ("Delayed: Stop hit — close 98.0 (bar 2026-09-25), detected 2026-09-25 16:05 EDT. "
            "Not delivered at the time; the condition may no longer hold.")
    assert subject == "Delayed: Stop hit: AAPL — Pullback EMA"
    assert plain.splitlines()[:2] == [line, "AAPL <b> stop"]
    assert html.splitlines()[:3] == [
        "<b>Delayed: Stop hit: AAPL — Pullback EMA</b>", line, "AAPL &lt;b&gt; stop"]


def test_21_plain_event_keeps_none_and_the_line_omits_a_missing_bar():
    ev = _event(direction=None, bar_time=None, fired_at=None)
    plain = _plain_event(ev)
    assert plain["direction"] is None and plain["bar_time"] is None and plain["fired_at"] is None
    ev.delayed = True
    first = _format_event(ev)[1].splitlines()[0]
    assert "(bar" not in first and "detected unknown time." in first


# ── 14-17: disabled, evaluate_all, cap, escalation ────────────────────────────

@pytest.mark.asyncio
async def test_14_disabled_watch_keeps_its_queue_until_re_enabled():
    w = _strategy_watch("a", pending_events=[_entry()])
    w["enabled"] = False
    store = _Store([w])
    notify = AsyncMock(return_value=True)
    with _patches(store, _Ctl(), notify):
        await evaluate_and_notify()
        notify.assert_not_awaited()
        assert len(store.queue("a")) == 1
        w["enabled"] = True
        await evaluate_and_notify()
    assert notify.await_count == 1
    assert "pending_events" not in store.state("a")


@pytest.mark.asyncio
async def test_15_evaluate_all_sends_nothing_and_keeps_the_queue():
    store = _Store([_armed(pending_events=[_entry()])])
    notify = AsyncMock(return_value=True)
    with _patches(store, _Ctl(close=98.0), notify):
        events = await evaluate_all()
    notify.assert_not_awaited()
    assert [e.event_type for e in events] == ["exit_stop"]
    assert store.state("a")["phase"] == "idle"
    assert [q["event"]["event_type"] for q in store.queue("a")] == ["entry"]


@pytest.mark.asyncio
async def test_16_cap_drops_the_oldest(caplog):
    queue = [_entry(reason=f"r{i}") for i in range(50)]
    store = _Store([_armed(pending_events=queue)])
    with caplog.at_level(logging.ERROR, logger=_EV), \
            _patches(store, _Ctl(close=98.0), AsyncMock(return_value=False)):
        await evaluate_and_notify()
    stored = store.queue("a")
    assert len(stored) == 50
    assert [q["event"]["reason"] for q in stored[:2]] == ["r1", "r2"]
    assert stored[-1]["event"]["event_type"] == "exit_stop"
    assert any("oldest undelivered alert dropped" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_17_log_escalates_at_three_attempts_and_nothing_ever_gives_up(caplog):
    store = _Store([_strategy_watch("a", pending_events=[_entry(attempts=1)])])
    with caplog.at_level(logging.WARNING, logger=_EV), \
            _patches(store, _Ctl(), AsyncMock(return_value=False)):
        await evaluate_and_notify()
        assert [r.levelno for r in caplog.records if "still undelivered" in r.message] == [logging.WARNING]
        caplog.clear()
        await evaluate_and_notify()
        assert [r.levelno for r in caplog.records if "still undelivered after 3" in r.message] == \
            [logging.ERROR]
        for _ in range(12):
            await evaluate_and_notify()
    assert [q["attempts"] for q in store.queue("a")] == [15]


# ── 18-20, 22-23 ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_18_no_written_state_is_mutated_afterwards_on_the_real_store(tmp_path):
    path = tmp_path / "w.yaml"
    store = StrategyWatchStore(path)
    w = store.add_watch("AAPL", "pullback_ema")
    store.update_state(w["id"], {"phase": "armed", "direction": "Bullish", "entry_price": 100.0,
                                 "stop_price": 99.0, "target_price": 110.0,
                                 "pending_events": [_entry()]})
    written: list[tuple[dict, dict]] = []
    real_update = store.update_state

    def _spy(wid, state):
        written.append((state, copy.deepcopy(state)))
        real_update(wid, state)

    store.update_state = _spy
    with _patches(store, _Ctl(close=98.0), AsyncMock(return_value=False)):
        await evaluate_and_notify()
    assert len(written) == 2
    for obj, snapshot in written:
        assert obj == snapshot
    mem = store.list_watches()[0]["last_state"]["pending_events"]
    assert [q["event"]["event_type"] for q in mem] == ["entry", "exit_stop"]
    assert StrategyWatchStore(path).list_watches()[0]["last_state"]["pending_events"] == mem


@pytest.mark.asyncio
async def test_19_queued_alerts_go_out_before_anything_is_evaluated():
    store = _Store([_strategy_watch("a", pending_events=[_entry()])])
    order: list[str] = []

    async def _notify(*a):
        order.append("notify")
        return True

    async def _get_bars(*a, **k):
        order.append("get_bars")
        return _bars(100.0)

    with _patches(store, _Ctl(), AsyncMock(side_effect=_notify)), \
            patch(f"{_EV}.get_bars", side_effect=_get_bars):
        await evaluate_and_notify()
    assert order[:2] == ["notify", "get_bars"]


@pytest.mark.asyncio
async def test_20_a_failed_queue_read_never_wipes_the_queue(caplog):
    store = _Store([_armed("a", pending_events=[_entry(reason="keep me")]), _strategy_watch("b")])
    ctl = _Ctl(close=98.0, sig=_signal(entry=98.0, stop=97.0, target=110.0))
    real = ev_mod._current_queue

    def _cq(watch_id, log=True):
        if watch_id == "a" and log:                  # _commit's read (the send check passes log=False)
            raise RuntimeError("store unreadable")
        return real(watch_id, log)

    notify = AsyncMock(side_effect=[False, True])     # flush of a fails; b's entry delivered
    with caplog.at_level(logging.ERROR, logger=_EV), _patches(store, ctl, notify), \
            patch(f"{_EV}._current_queue", _cq):
        await evaluate_and_notify()
    assert store.state("a")["phase"] == "armed"                    # not written
    assert [(q["event"]["reason"], q["attempts"]) for q in store.queue("a")] == [("keep me", 1)]
    assert store.state("b")["phase"] == "armed"                    # next transition committed
    assert any("state not written; queue preserved" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_22_poison_entries(caplog):
    bad = _entry()
    bad["event"]["strategy_key"] = None
    store = _Store([_strategy_watch("a", pending_events=[bad, _entry(reason="good")])])
    notify = AsyncMock(return_value=True)
    with caplog.at_level(logging.ERROR, logger=_EV), _patches(store, _Ctl(), notify):
        await evaluate_and_notify()
    assert notify.await_count == 1
    assert "pending_events" not in store.state("a")
    assert any("malformed pending_events entry dropped" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_22b_a_format_failure_is_a_failed_attempt():
    store = _Store([_strategy_watch("a", pending_events=[_entry()])])
    notify = AsyncMock(return_value=True)
    with _patches(store, _Ctl(), notify), \
            patch(f"{_EV}._format_event", side_effect=RuntimeError("bad text")):
        await evaluate_and_notify()
    notify.assert_not_awaited()
    assert [q["attempts"] for q in store.queue("a")] == [1]


@pytest.mark.asyncio
async def test_23_writes_strip_a_stale_queue_key():
    store = _Store([_composite(pending_events=[_entry()])])
    notify = AsyncMock(return_value=True)
    with _patches(store, _Ctl(fired=True), notify):
        await evaluate_and_notify()
    assert notify.await_count == 2
    assert store.state("c")["phase"] == "armed"
    assert "pending_events" not in store.state("c")


@pytest.mark.asyncio
async def test_23b_evaluate_all_drops_a_malformed_queue_carried_in_new_state():
    """Composite new states spread the snapshot, malformed queue included; the
    write must store the cleaned queue, not the snapshot's value."""
    store = _Store([_composite(pending_events=["x"])])
    with _patches(store, _Ctl(fired=True), AsyncMock()):
        await evaluate_all()
    assert store.state("c")["phase"] == "armed"
    assert "pending_events" not in store.state("c")
