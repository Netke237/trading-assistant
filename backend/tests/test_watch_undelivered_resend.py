"""WATCH-UNDELIVERED-EVENT-RESEND: an undelivered watch event is stored in
last_state.pending_events and re-sent (labelled "Delayed") on the next run BEFORE
re-evaluation, even if its condition no longer holds; newer events queue behind
it, oldest first (decision WATCH-RESEND-QUEUE-2026-09-27); disabled watches keep
theirs. Plan: docs/superpowers/plans/2026-09-27-watch-undelivered-event-resend-plan.md."""
from __future__ import annotations

import asyncio
import copy
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
import yaml

import app.services.strategy_watch_evaluator as ev_mod
from app.services.strategy_watch_evaluator import (
    WatchEvent, _QUEUE_CAP, _format_event, evaluate_and_notify,
)
from app.services.strategy_watch_store import StrategyWatchStore

_EV = "app.services.strategy_watch_evaluator"


class _Store:
    """In-memory stand-in for strategy_watch_store (update_state really changes
    what the next list_watches() returns). raise_on(id, pred) makes a write raise."""

    def __init__(self, watches: list[dict]):
        self.watches = watches
        self._raise: list = []

    def raise_on(self, watch_id, pred=lambda s: True):
        self._raise.append((watch_id, pred))

    def list_watches(self) -> list[dict]:
        return copy.deepcopy(self.watches)

    def update_state(self, watch_id: str, new_state: dict) -> None:
        for wid, pred in self._raise:
            if wid == watch_id and pred(new_state):
                raise OSError("disk full")
        for w in self.watches:
            if w["id"] == watch_id:
                w["last_state"] = copy.deepcopy(new_state)

    def state(self, wid: str) -> dict:
        return next(w for w in self.watches if w["id"] == wid)["last_state"]

    def committed(self, wid: str) -> dict:
        return {k: v for k, v in self.state(wid).items() if k != "pending_events"}

    def pending(self, wid: str) -> list:
        return self.state(wid).get("pending_events") or []

    def kinds(self, wid: str) -> list[str]:
        return [p["event"]["event_type"] for p in self.pending(wid)]


def _bars(close: float, n: int = 260) -> list[dict]:
    return [{"time": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}",
             "open": close, "high": close + 1, "low": close - 1,
             "close": close, "volume": 1_000_000} for i in range(n)]


def _signal(direction="Bullish", entry=100.0, stop=95.0, target=110.0):
    sig = MagicMock()
    sig.direction, sig.entry_price, sig.stop_price, sig.target_price = direction, entry, stop, target
    sig.rr_ratio = 2.0
    return sig


def _sw(wid="a", phase="idle", enabled=True, pending=None, **state) -> dict:
    ls = {"phase": phase, **state}
    if pending is not None:
        ls["pending_events"] = pending
    return {"id": wid, "symbol": "AAPL", "strategy_key": "pullback_ema",
            "params_override": {}, "enabled": enabled, "direction": "Bullish", "last_state": ls}


def _cw(wid="c", pending=None, **state) -> dict:
    ls = {"phase": "idle", **state}
    if pending is not None:
        ls["pending_events"] = pending
    return {"id": wid, "symbol": "AAPL", "watch_type": "composite", "direction": "Bullish",
            "enabled": True, "interval": "1D",
            "trigger_def": {"primary": {"model": "OMM", "to_state": "bull_trend"}},
            "last_state": ls}


def _entry(event_type: str, new_state: dict, wid="a", fired_at="2026-09-25T20:31:00+00:00") -> dict:
    return {"event": {"watch_id": wid, "symbol": "AAPL", "strategy_key": "pullback_ema",
                      "event_type": event_type, "direction": "Bullish", "entry": 100.0,
                      "stop": 95.0, "target": 110.0, "rr_ratio": None, "close": 100.0,
                      "reason": f"AAPL {event_type}"},
            "new_state": new_state, "fired_at": fired_at}


_ARMED = {"phase": "armed", "direction": "Bullish", "entry_price": 100.0,
          "stop_price": 95.0, "target_price": 110.0, "last_event": "entry"}


class _Env:
    """Patches for one scenario; close / signal / fired / notify are mutable
    between runs."""

    def __init__(self, store, close=100.0, sig=None, fired=True, channels=True, notify=None):
        self.store, self.close, self.fired = store, close, fired
        self.fn = MagicMock(return_value=sig)
        self.notify = notify if notify is not None else AsyncMock(return_value=True)
        self.channels = channels

    def subjects(self) -> list[str]:
        return [c.args[0] for c in self.notify.await_args_list]

    async def run(self, **kw):
        cfg = {"gmail": {"enabled": self.channels}, "telegram": {"enabled": False}}
        with patch(f"{_EV}.strategy_watch_store", self.store), \
                patch(f"{_EV}.get_bars", new_callable=AsyncMock,
                      side_effect=lambda *a, **k: _bars(self.close)), \
                patch.dict(ev_mod._SIGNAL_FNS, {"pullback_ema": self.fn}), \
                patch("app.services.composite_trigger_evaluator.evaluate_scheduled",
                      side_effect=lambda *a, **k: self.fired), \
                patch("app.services.composite_trigger_evaluator.describe_match",
                      return_value={"structure_matched": [], "structure_total": 0,
                                    "strategy_matched": [], "strategy_total": 0}), \
                patch(f"{_EV}.read_notification_config", return_value=(cfg, True)), \
                patch(f"{_EV}.notify_enabled_channels", self.notify):
            return await evaluate_and_notify(**kw)


# ── 1-3: the three loss cases ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_1_undelivered_stop_is_resent_after_price_reverts():
    store = _Store([_sw("a", "armed", direction="Bullish", entry_price=100.0,
                        stop_price=101.0, target_price=110.0)])
    env = _Env(store, close=100.0, notify=AsyncMock(return_value=False))
    assert [e.event_type for e in await env.run()] == ["exit_stop"]
    assert store.committed("a")["phase"] == "armed" and store.kinds("a") == ["exit_stop"]
    env.close, env.notify = 105.0, AsyncMock(return_value=True)      # reverted above the stop
    assert await env.run() == []
    assert env.subjects() == ["Delayed: Stop hit: AAPL — Pullback EMA"]
    assert store.state("a")["phase"] == "idle" and "pending_events" not in store.state("a")


@pytest.mark.asyncio
async def test_2_undelivered_entry_is_resent_after_setup_is_gone():
    store = _Store([_sw("a")])
    env = _Env(store, sig=_signal(), notify=AsyncMock(return_value=False))
    await env.run()
    env.fn.return_value, env.notify = None, AsyncMock(return_value=True)
    await env.run()
    assert env.subjects() == ["Delayed: Long setup: AAPL — Pullback EMA"]
    s = store.state("a")
    assert (s["phase"], s["entry_price"], s["stop_price"], s["target_price"]) == ("armed", 100.0, 95.0, 110.0)
    assert "pending_events" not in s


@pytest.mark.asyncio
async def test_3_undelivered_composite_entry_resent_then_rearmed():
    store = _Store([_cw("c")])
    env = _Env(store, fired=True, notify=AsyncMock(return_value=False))
    await env.run()
    assert store.committed("c")["phase"] == "idle" and store.kinds("c") == ["entry"]
    env.fired, env.notify = False, AsyncMock(return_value=True)
    await env.run()
    assert env.subjects() == ["Delayed: Long setup: AAPL — Composite Trigger"]
    assert store.state("c")["phase"] == "idle" and "pending_events" not in store.state("c")


# ── 4-7: queue and effective state ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_4_new_event_queues_behind_and_both_send_oldest_first():
    store = _Store([_sw("a")])
    env = _Env(store, sig=_signal(), notify=AsyncMock(return_value=False))
    await env.run()                                     # entry undelivered
    env.fn.return_value, env.close = None, 94.0         # stop 95 hit
    env.notify = AsyncMock(return_value=False)
    assert [e.event_type for e in await env.run()] == ["exit_stop"]
    assert env.notify.await_count == 1                  # only the resend was tried
    assert store.kinds("a") == ["entry", "exit_stop"] and store.committed("a")["phase"] == "idle"
    env.close, env.notify = 100.0, AsyncMock(return_value=True)
    await env.run()
    assert env.subjects() == ["Delayed: Long setup: AAPL — Pullback EMA",
                              "Delayed: Stop hit: AAPL — Pullback EMA"]
    assert store.state("a")["phase"] == "idle" and "pending_events" not in store.state("a")


@pytest.mark.asyncio
async def test_5_partial_drain_commits_the_delivered_one():
    store = _Store([_sw("a", pending=[_entry("entry", _ARMED),
                                      _entry("exit_stop", {"phase": "idle", "last_event": "exit_stop"})])])
    env = _Env(store, notify=AsyncMock(side_effect=[True, False]))
    await env.run()
    assert store.committed("a") == _ARMED and store.kinds("a") == ["exit_stop"]


@pytest.mark.asyncio
async def test_6_evaluation_runs_from_the_effective_state():
    # Committed idle + a queued entry (effective armed, stop 95). The signal is
    # still present: judged from the committed state it would fire a 2nd entry.
    store = _Store([_sw("a", pending=[_entry("entry", _ARMED)])])
    env = _Env(store, close=94.0, sig=_signal(), notify=AsyncMock(return_value=False))
    assert [e.event_type for e in await env.run()] == ["exit_stop"]
    assert store.kinds("a") == ["entry", "exit_stop"] and store.committed("a") == {"phase": "idle"}


@pytest.mark.asyncio
async def test_7a_composite_rearm_while_pending_lands_in_the_queued_entry():
    armed = {"phase": "armed", "direction": "Bullish", "last_event": "entry"}
    store = _Store([_cw("c", pending=[_entry("entry", armed, wid="c")])])
    env = _Env(store, fired=False, notify=AsyncMock(return_value=False))
    await env.run()
    assert store.committed("c") == {"phase": "idle"}
    assert len(store.pending("c")) == 1 and store.pending("c")[0]["new_state"]["phase"] == "idle"


@pytest.mark.asyncio
async def test_7b_sustain_clock_while_pending_lands_in_the_queued_event():
    idle = {"phase": "idle", "last_event": "exit_stop"}
    store = _Store([_sw("a", "armed", pending=[_entry("exit_stop", idle)], **{
        k: v for k, v in _ARMED.items() if k != "phase"})])
    env = _Env(store, sig=_signal(), notify=AsyncMock(return_value=False))
    await env.run(sustain_minutes=5)
    assert store.committed("a")["phase"] == "armed"
    assert len(store.pending("a")) == 1
    assert "pending_entry_since" in store.pending("a")[0]["new_state"]


# ── 8-11: no channel, disabled, malformed, cap ────────────────────────────────

@pytest.mark.asyncio
async def test_8_no_channel_commits_the_queue_unsent():
    store = _Store([_sw("a", pending=[_entry("entry", _ARMED)])])
    env = _Env(store, channels=False, notify=AsyncMock(return_value=False))
    await env.run()
    env.notify.assert_not_awaited()
    assert store.state("a") == _ARMED


@pytest.mark.asyncio
async def test_9_disabled_watch_keeps_its_events_and_sends_on_reenable():
    store = _Store([_sw("a", enabled=False, pending=[_entry("entry", _ARMED)])])
    env = _Env(store)
    await env.run()
    env.notify.assert_not_awaited()
    assert store.kinds("a") == ["entry"]
    store.watches[0]["enabled"] = True
    await env.run()
    assert env.subjects() == ["Delayed: Long setup: AAPL — Pullback EMA"]
    assert store.state("a") == _ARMED


@pytest.mark.asyncio
async def test_10_malformed_entry_dropped_next_one_still_sent(caplog):
    bad = {"event": {"symbol": "AAPL"}, "new_state": {"phase": "armed"}, "fired_at": "x"}
    store = _Store([_sw("a", pending=[bad, _entry("entry", _ARMED)])])
    env = _Env(store)
    with caplog.at_level(logging.ERROR):
        await env.run()
    assert "malformed pending event" in caplog.text
    assert env.subjects() == ["Delayed: Long setup: AAPL — Pullback EMA"]
    assert store.state("a") == _ARMED


@pytest.mark.asyncio
async def test_11_queue_cap_drops_the_oldest_and_applies_its_state(caplog):
    pending = [_entry("entry", {"phase": "idle", "n": i}) for i in range(_QUEUE_CAP)]
    store = _Store([_sw("a", pending=pending)])
    env = _Env(store, sig=_signal(), notify=AsyncMock(return_value=False))
    with caplog.at_level(logging.ERROR):
        assert [e.event_type for e in await env.run()] == ["entry"]
    assert len(store.pending("a")) == _QUEUE_CAP
    assert store.committed("a") == {"phase": "idle", "n": 0}
    assert store.pending("a")[0]["new_state"]["n"] == 1
    assert store.pending("a")[-1]["new_state"]["phase"] == "armed"
    assert "queue full" in caplog.text


# ── 12: message text ──────────────────────────────────────────────────────────

_AAPL = WatchEvent("w", "AAPL", "pullback_ema", "entry", "Bullish", 100.0, 95.0, 110.0, 2.0,
                   100.0, "AAPL: <setup> & go")
_MSFT = WatchEvent("w", "MSFT", "breakout_base", "exit_stop", "Bearish", 50.0, 55.0, 40.0, None,
                   56.0, "MSFT stop")


def test_12a_undelayed_text_is_unchanged():
    # Golden strings captured from main e101c42's _format_event.
    assert _format_event(_AAPL) == (
        'Long setup: AAPL — Pullback EMA',
        'AAPL: <setup> & go\n\nStrategy: Pullback EMA\nLast close: 100.0\n'
        'Entry 100.0 · Stop 95.0 · Target 110.0\nReward-to-risk ratio: 2.0',
        '<b>Long setup: AAPL — Pullback EMA</b>\nAAPL: &lt;setup&gt; &amp; go\n\n'
        'Strategy: Pullback EMA\nLast close: 100.0\nEntry 100.0 · Stop 95.0 · Target 110.0\n'
        'Reward-to-risk ratio: 2.0\n')
    assert _format_event(_MSFT) == (
        'Stop hit: MSFT — Breakout Base',
        'MSFT stop\n\nStrategy: Breakout Base\nLast close: 56.0\nEntry 50.0 · Stop 55.0 · Target 40.0',
        '<b>Stop hit: MSFT — Breakout Base</b>\nMSFT stop\n\nStrategy: Breakout Base\n'
        'Last close: 56.0\nEntry 50.0 · Stop 55.0 · Target 40.0\n')


def test_12b_delayed_text():
    subject, plain, html = _format_event(_MSFT, delayed_since="2026-09-25T20:31:00+00:00")
    line = "Delayed: Stop hit at 56.0 on 2026-09-25 16:31 ET"
    assert subject == "Delayed: Stop hit: MSFT — Breakout Base"
    assert plain == line + "\n\n" + _format_event(_MSFT)[1]
    assert html == line + "\n\n" + _format_event(_MSFT)[2].replace("<b>", "<b>Delayed: ", 1)
    _, plain_bad, _ = _format_event(_MSFT, delayed_since="garbage")
    assert plain_bad.startswith("Delayed: Stop hit at 56.0 on garbage\n")


# ── 13-16: persistence and failure handling ───────────────────────────────────

@pytest.mark.asyncio
async def test_13_numpy_prices_round_trip_through_the_real_yaml_store(tmp_path):
    path = tmp_path / "watches.yaml"
    store = StrategyWatchStore(path=path)
    store.add_watch("AAPL", "pullback_ema")
    store.add_watch("MSFT", "pullback_ema")
    sig = _signal(entry=np.float64(100.5), stop=np.float64(95.25), target=np.float64(110.75))
    sig.rr_ratio = np.float64(2.1234)
    env = _Env(store, sig=sig, notify=AsyncMock(return_value=False))
    env.close = np.float64(100.5)
    await env.run()
    assert "!!python" not in path.read_text()
    yaml.safe_load(path.read_text())                     # what load() uses
    reloaded = StrategyWatchStore(path=path).list_watches()
    assert len(reloaded) == 2
    p = reloaded[0]["last_state"]["pending_events"][0]
    assert p["event"]["entry"] == 100.5 and p["new_state"]["stop_price"] == 95.25


@pytest.mark.asyncio
async def test_14_delivered_first_send_stores_no_queue():
    store = _Store([_sw("a")])
    env = _Env(store, sig=_signal())
    await env.run()
    assert env.subjects() == ["Long setup: AAPL — Pullback EMA"]
    assert store.state("a")["phase"] == "armed" and "pending_events" not in store.state("a")


@pytest.mark.asyncio
async def test_15a_failed_queue_write_does_not_stop_the_next_watch():
    store = _Store([_sw("a"), _sw("b")])
    store.raise_on("a", lambda s: "pending_events" in s)
    notify = AsyncMock(side_effect=[False, True])        # a undelivered, b delivered
    env = _Env(store, sig=_signal(), notify=notify)
    assert [e.watch_id for e in await env.run()] == ["a", "b"]
    assert notify.await_count == 2
    assert store.state("b")["phase"] == "armed"


@pytest.mark.asyncio
async def test_15b_failed_resend_write_does_not_stop_other_resends_or_evaluation():
    store = _Store([_sw("a", pending=[_entry("entry", _ARMED)]),
                    _sw("b", pending=[_entry("entry", _ARMED, wid="b")]), _sw("c")])
    store.raise_on("a")
    env = _Env(store, sig=_signal())
    events = await env.run()
    assert env.subjects()[:2] == ["Delayed: Long setup: AAPL — Pullback EMA"] * 2
    assert "pending_events" not in store.state("b")       # b's resend committed
    assert "c" in [e.watch_id for e in events]


@pytest.mark.asyncio
async def test_16_cancel_mid_walk_keeps_the_delivered_one_committed():
    store = _Store([_sw("a", pending=[_entry("entry", _ARMED),
                                      _entry("exit_stop", {"phase": "idle", "last_event": "exit_stop"})])])
    env = _Env(store, notify=AsyncMock(side_effect=[True, asyncio.CancelledError()]))
    with pytest.raises(asyncio.CancelledError):
        await env.run()
    assert store.committed("a") == _ARMED and store.kinds("a") == ["exit_stop"]
