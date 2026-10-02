"""WATCH-RESEND-HEAD-OF-LINE piece 1 -- skip on proof (decisions
WATCH-RESEND-HEAD-OF-LINE-2026-10-01, WATCH-RESEND-SPLIT-2026-10-02,
WATCH-RESEND-P1-BUILD-FROM-V4-2026-10-02).

A queued alert that has failed on 3 runs at least 1 h apart is dropped (ERROR)
the first time the next alert of the same watch is delivered after that; an
outage drops nothing. Plan: docs/superpowers/plans/2026-10-02-watch-resend-skip-on-proof-plan.md."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

import app.services.strategy_watch_evaluator as ev_mod
from app.services.strategy_watch_evaluator import evaluate_and_notify
from app.services.strategy_watch_store import StrategyWatchStore
from tests.test_watch_undelivered_resend import _ARMED, _Env, _Store, _bars, _entry, _sw

_EV = "app.services.strategy_watch_evaluator"
T0 = datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc)
IDLE = {"phase": "idle", "last_event": "exit_stop"}
DROP = "undeliverable alert dropped for"


def _e(reason: str, new_state: dict | None = None, event_type="exit_stop", **extra) -> dict:
    """A pending entry with its own reason (the fake notify keys on it)."""
    e = _entry(event_type, dict(new_state or IDLE))
    e["event"]["reason"] = reason
    e.update(extra)
    return e


class _Notify:
    """notify_enabled_channels fake: fails every body carrying a reason in
    `fail`, delivers the rest; records the reasons it was asked to send."""

    def __init__(self, fail=(), deliver_all=True):
        self.fail, self.deliver_all, self.sent = set(fail), deliver_all, []
        self.mock = AsyncMock(side_effect=self._call)

    async def _call(self, subject, plain, html):
        reason = plain.split("\n\n", 1)[-1].split("\n", 1)[0] if plain.startswith("Delayed:") \
            else plain.split("\n", 1)[0]
        self.sent.append((reason, subject))
        return self.deliver_all and reason not in self.fail

    def reasons(self) -> list[str]:
        return [r for r, _ in self.sent]


class _CfgEnv(_Env):
    """_Env with a settable notification-config reader and clock."""

    def __init__(self, store, notify: _Notify, now=T0, cfg_reader=None, **kw):
        super().__init__(store, notify=notify.mock, **kw)
        self.n, self.now = notify, now
        self.cfg_reader = cfg_reader or {
            "return_value": ({"gmail": {"enabled": True}, "telegram": {"enabled": False}}, True)}

    async def run(self, **kw):
        with patch(f"{_EV}.strategy_watch_store", self.store), \
                patch(f"{_EV}.get_bars", new_callable=AsyncMock,
                      side_effect=lambda *a, **k: _bars(self.close)), \
                patch.dict(ev_mod._SIGNAL_FNS, {"pullback_ema": self.fn}), \
                patch("app.services.composite_trigger_evaluator.evaluate_scheduled",
                      side_effect=lambda *a, **k: self.fired), \
                patch("app.services.composite_trigger_evaluator.describe_match",
                      return_value={"structure_matched": [], "structure_total": 0,
                                    "strategy_matched": [], "strategy_total": 0}), \
                patch(f"{_EV}.read_notification_config", **self.cfg_reader), \
                patch(f"{_EV}._utcnow", side_effect=lambda: self.now), \
                patch(f"{_EV}.notify_enabled_channels", self.notify):
            return await evaluate_and_notify(**kw)


def _head(store, wid="a") -> dict:
    return store.pending(wid)[0]


def _reasons_pending(store, wid="a") -> list[str]:
    return [p["event"]["reason"] for p in store.pending(wid)]


async def _runs(env, *offsets_h):
    for h in offsets_h:
        env.now = T0 + timedelta(hours=h)
        await env.run()


# ── 1: the defect, end to end ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_1_poison_head_dropped_on_third_spaced_run_when_next_delivers(caplog):
    behind = {**IDLE, "marker": "behind"}
    store = _Store([_sw("a", pending=[_e("RZ-head"), _e("RZ-next", behind)])])
    n = _Notify(fail={"RZ-head"})
    env = _CfgEnv(store, n)
    await _runs(env, 0, 1)
    assert n.reasons() == ["RZ-head", "RZ-head"]            # the entry behind is never sent
    assert _head(store)["failures"] == 2 and _reasons_pending(store) == ["RZ-head", "RZ-next"]
    with caplog.at_level(logging.ERROR, logger=_EV):
        await _runs(env, 2)
    assert n.reasons() == ["RZ-head", "RZ-head", "RZ-head", "RZ-next"]
    assert store.state("a") == behind                         # committed = probe's new_state, no queue
    assert f"{DROP} a after 3 failed runs" in caplog.text and "RZ-head" in caplog.text


@pytest.mark.asyncio
async def test_1b_same_on_the_real_store_rebuilt_from_disk_each_run(tmp_path):
    path = tmp_path / "watches.yaml"
    store = StrategyWatchStore(path=path)
    wid = store.add_watch("AAPL", "pullback_ema")["id"]
    store.update_state(wid, {"phase": "idle", "pending_events": [_e("RZ-head"), _e("RZ-next")]})
    n = _Notify(fail={"RZ-head"})
    env = _CfgEnv(StrategyWatchStore(path=path), n)
    for h in (0, 1, 2):
        env.store, env.now = StrategyWatchStore(path=path), T0 + timedelta(hours=h)
        await env.run()
        if h < 2:
            head = StrategyWatchStore(path=path).list_watches()[0]["last_state"]["pending_events"][0]
            assert head["failures"] == h + 1                  # written, not only mutated in memory
    final = StrategyWatchStore(path=path).list_watches()[0]["last_state"]
    assert "pending_events" not in final and n.reasons()[-1] == "RZ-next"


# ── 2-4: counting, eligibility, outage ────────────────────────────────────────

@pytest.mark.asyncio
async def test_2_stored_two_not_counted_no_probe_counted_probes():
    recent = (T0 - timedelta(minutes=10)).isoformat()
    store = _Store([_sw("a", pending=[_e("RZ-head", failures=2, last_failure_at=recent), _e("RZ-next")])])
    n = _Notify(fail={"RZ-head"})
    env = _CfgEnv(store, n)
    await env.run()
    assert n.reasons() == ["RZ-head"] and _head(store)["failures"] == 2
    env.now = T0 + timedelta(hours=1)
    await env.run()
    assert n.reasons() == ["RZ-head", "RZ-head", "RZ-next"] and "pending_events" not in store.state("a")


@pytest.mark.asyncio
async def test_2b_already_eligible_head_probes_inside_the_spacing():
    recent = (T0 - timedelta(minutes=5)).isoformat()
    store = _Store([_sw("a", pending=[_e("RZ-head", failures=3, last_failure_at=recent), _e("RZ-next")])])
    n = _Notify(fail={"RZ-head"})
    await _CfgEnv(store, n).run()
    assert n.reasons() == ["RZ-head", "RZ-next"] and "pending_events" not in store.state("a")


@pytest.mark.parametrize("reader", [{"return_value": ({}, False)},
                                    {"side_effect": OSError("unreadable")}])
@pytest.mark.asyncio
async def test_2c_unreadable_config_counts_nothing_and_never_probes(reader):
    old = (T0 - timedelta(hours=5)).isoformat()
    # (a) failures stay 0 over 3 spaced runs
    store = _Store([_sw("a", pending=[_e("RZ-head"), _e("RZ-next")])])
    n = _Notify(fail={"RZ-head"})
    env = _CfgEnv(store, n, cfg_reader=reader)
    await _runs(env, 0, 1, 2)
    assert "failures" not in _head(store) and n.reasons() == ["RZ-head"] * 3
    # (b) eligible head, P deliverable -> P not sent, nothing dropped
    store = _Store([_sw("a", pending=[_e("RZ-head", failures=3, last_failure_at=old), _e("RZ-next")])])
    n = _Notify(fail={"RZ-head"})
    await _CfgEnv(store, n, cfg_reader=reader).run()
    assert n.reasons() == ["RZ-head"] and _reasons_pending(store) == ["RZ-head", "RZ-next"]
    assert _head(store)["failures"] == 3
    # (c) eligible head alone + a fresh stop hit -> fresh queued unsent
    head_state = {**_ARMED, "stop_price": 101.0}
    store = _Store([_sw("a", pending=[_e("RZ-head", head_state, event_type="entry",
                                         failures=3, last_failure_at=old)])])
    n = _Notify(fail={"RZ-head"})
    env = _CfgEnv(store, n, cfg_reader=reader)
    assert [e.event_type for e in await env.run()] == ["exit_stop"]
    assert n.reasons() == ["RZ-head"] and store.kinds("a") == ["entry", "exit_stop"]


@pytest.mark.asyncio
async def test_3_failures_within_the_hour_count_once():
    store = _Store([_sw("a", pending=[_e("RZ-head"), _e("RZ-next")])])
    env = _CfgEnv(store, _Notify(fail={"RZ-head"}))
    for m in (0, 5, 10):
        env.now = T0 + timedelta(minutes=m)
        await env.run()
    assert _head(store)["failures"] == 1
    env.now = T0 + timedelta(minutes=61)
    await env.run()
    assert _head(store)["failures"] == 2


@pytest.mark.asyncio
async def test_4_outage_drops_nothing():
    store = _Store([_sw("a", phase="armed", pending=[_e("RZ-head"), _e("RZ-next")])])
    n = _Notify(deliver_all=False)
    env = _CfgEnv(store, n)
    await _runs(env, 0, 1, 2, 3, 4, 5)
    assert _head(store)["failures"] == 6 and _reasons_pending(store) == ["RZ-head", "RZ-next"]
    assert store.committed("a")["phase"] == "armed"
    assert n.reasons().count("RZ-next") == 4                  # probed from the 3rd run, never dropped


# ── 5-9: after the drop, fresh probe, malformed ───────────────────────────────

@pytest.mark.asyncio
async def test_5_after_the_drop_the_walk_continues_in_order():
    b_state = {**IDLE, "marker": "B"}
    store = _Store([_sw("a", pending=[_e("RZ-head", failures=2), _e("RZ-A"), _e("RZ-B", b_state)])])
    n = _Notify(fail={"RZ-head"})
    await _CfgEnv(store, n).run()
    assert n.reasons() == ["RZ-head", "RZ-A", "RZ-B"]
    assert store.state("a") == b_state


@pytest.mark.asyncio
async def test_6_two_stuck_in_a_row_nothing_dropped():
    store = _Store([_sw("a", pending=[_e("RZ-head", failures=2), _e("RZ-P2"), _e("RZ-C")])])
    n = _Notify(fail={"RZ-head", "RZ-P2"})
    await _CfgEnv(store, n).run()
    assert n.reasons() == ["RZ-head", "RZ-P2"]
    assert _reasons_pending(store) == ["RZ-head", "RZ-P2", "RZ-C"] and _head(store)["failures"] == 3


@pytest.mark.asyncio
async def test_7_fresh_stop_hit_is_the_probe_in_the_run_it_fires(caplog):
    old = (T0 - timedelta(hours=5)).isoformat()
    head_state = {**_ARMED, "stop_price": 101.0}             # close 100 -> stop hit fires
    store = _Store([_sw("a", pending=[_e("RZ-head", head_state, event_type="entry",
                                         failures=3, last_failure_at=old)])])
    n = _Notify(fail={"RZ-head"})
    env = _CfgEnv(store, n)
    with caplog.at_level(logging.ERROR, logger=_EV):
        assert [e.event_type for e in await env.run()] == ["exit_stop"]
    assert len(n.sent) == 2 and n.sent[0][0] == "RZ-head"
    assert n.sent[1][1] == "Stop hit: AAPL — Pullback EMA"    # not labelled Delayed
    s = store.state("a")
    assert s["phase"] == "idle" and s["last_event"] == "exit_stop" and "pending_events" not in s
    assert f"{DROP} a after 4 failed runs" in caplog.text


@pytest.mark.asyncio
async def test_7b_fresh_probe_failing_is_queued_behind_the_head():
    old = (T0 - timedelta(hours=5)).isoformat()
    store = _Store([_sw("a", pending=[_e("RZ-head", {**_ARMED, "stop_price": 101.0}, event_type="entry",
                                         failures=3, last_failure_at=old)])])
    env = _CfgEnv(store, _Notify(deliver_all=False))
    await env.run()
    assert store.kinds("a") == ["entry", "exit_stop"]
    assert _head(store)["failures"] == 4 and _head(store)["last_failure_at"] == T0.isoformat()


@pytest.mark.asyncio
async def test_8_eligible_head_alone_without_a_fresh_event_drops_nothing():
    store = _Store([_sw("a", pending=[_e("RZ-head", failures=5)])])
    n = _Notify(fail={"RZ-head"})
    await _CfgEnv(store, n).run()
    assert n.reasons() == ["RZ-head"] and _reasons_pending(store) == ["RZ-head"]


def _malformed():
    return {"event": {"symbol": "AAPL"}, "new_state": "x", "fired_at": "2026-09-25T20:31:00+00:00"}


@pytest.mark.asyncio
async def test_9_malformed_behind_eligible_head_is_dropped_and_next_probed():
    store = _Store([_sw("a", pending=[_e("RZ-head", failures=2), _malformed(), _e("RZ-next")])])
    n = _Notify(fail={"RZ-head"})
    await _CfgEnv(store, n).run()
    assert n.reasons() == ["RZ-head", "RZ-next"] and "pending_events" not in store.state("a")


@pytest.mark.asyncio
async def test_9_failed_probe_leaves_an_unreached_malformed_entry():
    store = _Store([_sw("a", pending=[_e("RZ-head", failures=2), _e("RZ-P"), _malformed()])])
    await _CfgEnv(store, _Notify(fail={"RZ-head", "RZ-P"})).run()
    assert len(store.pending("a")) == 3


@pytest.mark.asyncio
async def test_9_malformed_tail_dropped_and_written_even_without_a_counted_failure(caplog):
    recent = (T0 - timedelta(minutes=5)).isoformat()
    store = _Store([_sw("a", pending=[_e("RZ-head", failures=3, last_failure_at=recent), _malformed()])])
    with caplog.at_level(logging.ERROR, logger=_EV):
        await _CfgEnv(store, _Notify(fail={"RZ-head"})).run()
    assert _reasons_pending(store) == ["RZ-head"]
    assert "skipped this run" not in caplog.text             # this run's _collect evaluated it


@pytest.mark.asyncio
async def test_9b_failed_older_probe_keeps_the_fresh_event_unsent():
    old = (T0 - timedelta(hours=5)).isoformat()
    store = _Store([_sw("a", pending=[_e("RZ-head", failures=3, last_failure_at=old),
                                      _e("RZ-P", {**_ARMED, "stop_price": 101.0}, event_type="entry")])])
    n = _Notify(fail={"RZ-head", "RZ-P"})
    env = _CfgEnv(store, n)
    assert [e.event_type for e in await env.run()] == ["exit_stop"]
    assert n.reasons() == ["RZ-head", "RZ-P"]
    assert store.kinds("a") == ["exit_stop", "entry", "exit_stop"]
    assert store.committed("a")["phase"] == "idle"


# ── 10-15: values, counts, guards ─────────────────────────────────────────────

@pytest.mark.parametrize("failures,last,expect", [
    ("x", None, 1), (-1, None, 1), (True, None, 1), (2, "garbage", 3),
    (2, "2026-10-01T13:30:00", 2),                            # naive = UTC, 30 min ago: not counted
    (2, (T0 + timedelta(hours=2)).isoformat(), 3),            # future = absent: counted
])
@pytest.mark.asyncio
async def test_10_malformed_and_odd_counter_values(failures, last, expect):
    extra = {"failures": failures}
    if last is not None:
        extra["last_failure_at"] = last
    store = _Store([_sw("a", pending=[_e("RZ-head", **extra)])])
    await _CfgEnv(store, _Notify(fail={"RZ-head"})).run()
    assert _head(store)["failures"] == expect


@pytest.mark.asyncio
async def test_11_each_entry_sent_at_most_once_per_run():
    store = _Store([_sw("a", pending=[_e("RZ-head", failures=2), _e("RZ-A"), _e("RZ-B")])])
    n = _Notify(fail={"RZ-head"})
    await _CfgEnv(store, n).run()
    assert sorted(n.reasons()) == sorted(set(n.reasons()))


@pytest.mark.asyncio
async def test_12_no_channel_commits_unsent_and_never_probes():
    store = _Store([_sw("a", pending=[_e("RZ-head", failures=9), _e("RZ-next", {**IDLE, "m": 1})])])
    env = _CfgEnv(store, _Notify(), cfg_reader={"return_value": ({"gmail": {"enabled": False}}, True)})
    await env.run()
    assert env.n.sent == [] and store.state("a") == {**IDLE, "m": 1}


@pytest.mark.asyncio
async def test_13_failed_drop_write_resends_head_then_probe_next_run():
    store = _Store([_sw("a", pending=[_e("RZ-head", failures=2), _e("RZ-P")]),
                    _sw("b", pending=[_e("RZ-other")])])
    store.raise_on("a", lambda s: "pending_events" not in s)  # only the drop write
    n = _Notify(fail={"RZ-head"})
    env = _CfgEnv(store, n)
    await env.run()
    assert "RZ-other" in n.reasons() and "pending_events" not in store.state("b")
    store._raise.clear()
    n.sent.clear()
    env.now = T0 + timedelta(minutes=5)
    await env.run()
    assert n.reasons() == ["RZ-head", "RZ-P"]


@pytest.mark.asyncio
async def test_14_counters_survive_write_effective_and_leave_with_an_evicted_head():
    # _write_effective on a single-entry queue (head = tail): composite re-arm keeps the counters
    store = _Store([{"id": "c", "symbol": "AAPL", "watch_type": "composite", "direction": "Bullish",
                     "enabled": True, "interval": "1D",
                     "trigger_def": {"primary": {"model": "OMM", "to_state": "bull_trend"}},
                     "last_state": {"phase": "idle", "pending_events": [
                         _e("RZ-head", {"phase": "armed"}, event_type="entry", failures=1)]}}])
    env = _CfgEnv(store, _Notify(fail={"RZ-head"}), fired=False)
    env.now = T0 + timedelta(hours=3)
    await env.run()
    head = store.pending("c")[0]
    assert head["failures"] == 2 and head["new_state"]["phase"] == "idle"
    # the cap evicts the head with its counters; the new head starts at 0
    pend = [_e("RZ-head", failures=2)] + [_e(f"RZ-{i}") for i in range(ev_mod._QUEUE_CAP - 1)]
    store = _Store([_sw("a", pending=pend)])
    env = _CfgEnv(store, _Notify(deliver_all=False), sig=None)
    env.store.watches[0]["last_state"]["pending_events"][-1]["new_state"] = {**_ARMED, "stop_price": 101.0}
    await env.run()
    assert len(store.pending("a")) == ev_mod._QUEUE_CAP
    assert store.pending("a")[0]["event"]["reason"] == "RZ-0" and "failures" not in store.pending("a")[0]


@pytest.mark.asyncio
async def test_15_one_watch_raising_in_delivery_does_not_stop_the_others():
    store = _Store([_sw("a", phase="armed", direction="Bullish", entry_price=100.0, stop_price=101.0,
                        target_price=110.0),
                    _sw("b", phase="armed", direction="Bullish", entry_price=100.0, stop_price=101.0,
                        target_price=110.0)])
    real = ev_mod._deliver_or_queue

    async def flaky(t, *a, **k):
        if t.watch_id == "a":
            raise RuntimeError("boom")
        return await real(t, *a, **k)

    env = _CfgEnv(store, _Notify())
    with patch(f"{_EV}._deliver_or_queue", side_effect=flaky):
        await env.run()
    assert store.state("b")["phase"] == "idle" and store.state("a")["phase"] == "armed"
