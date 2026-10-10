"""P4b T2 + T3: one watch's failure skips only that watch (Q17); a fired event's
state is committed only after delivery (open_questions[3], decision D3); one
evaluate_and_notify runs at a time."""
from __future__ import annotations

import asyncio
import copy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.services.strategy_watch_evaluator as ev_mod
from tests.watch_notify_helpers import configured_channels_no_real_sends, per_channel  # noqa: F401
from app.services.strategy_watch_evaluator import (
    _Transition, _any_channel_enabled, _commit, evaluate_all, evaluate_and_notify,
)

_EV = "app.services.strategy_watch_evaluator"


class _Store:
    """In-memory stand-in for strategy_watch_store: update_state really changes
    what the next list_watches() returns."""

    def __init__(self, watches: list[dict]):
        self.watches = watches
        self.writes: list[tuple[str, dict]] = []

    def list_watches(self) -> list[dict]:
        return copy.deepcopy(self.watches)

    def update_state(self, watch_id: str, new_state: dict) -> None:
        self.writes.append((watch_id, new_state))
        for w in self.watches:
            if w["id"] == watch_id:
                w["last_state"] = dict(new_state)

    def state(self, watch_id: str) -> dict:
        return next(w for w in self.watches if w["id"] == watch_id)["last_state"]

    def committed(self, watch_id: str) -> dict:
        """The state without the undelivered-event queue (WATCH-UNDELIVERED-EVENT-RESEND)."""
        return {k: v for k, v in self.state(watch_id).items() if k != "pending_events"}

    def pending(self, watch_id: str) -> list:
        return self.state(watch_id).get("pending_events") or []


def _bars(close: float, n: int = 260) -> list[dict]:
    return [{"time": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}",
             "open": close, "high": close + 1, "low": close - 1,
             "close": close, "volume": 1_000_000} for i in range(n)]


def _signal(direction="Bullish", entry=100.0, stop=95.0, target=110.0):
    sig = MagicMock()
    sig.direction, sig.entry_price, sig.stop_price, sig.target_price = direction, entry, stop, target
    sig.rr_ratio = 2.0
    return sig


def _strategy_watch(wid: str, phase: str = "idle", **state) -> dict:
    return {"id": wid, "symbol": "AAPL", "strategy_key": "pullback_ema",
            "params_override": {}, "enabled": True, "direction": "Bullish",
            "last_state": {"phase": phase, **state}}


def _composite(wid: str, **state) -> dict:
    return {"id": wid, "symbol": "AAPL", "watch_type": "composite", "direction": "Bullish",
            "enabled": True, "interval": "1D",
            "trigger_def": {"primary": {"model": "OMM", "to_state": "bull_trend"}},
            "last_state": {"phase": "idle", **state}}


def _channels(enabled: bool):
    cfg = {"gmail": {"enabled": enabled}, "telegram": {"enabled": False}}
    return patch(f"{_EV}.read_notification_config", return_value=(cfg, True))


def _fire_strategy(store, sig=None):
    """Patches for a strategy watch whose signal fires (or not, sig=None)."""
    fn = MagicMock(return_value=sig)
    return (patch(f"{_EV}.strategy_watch_store", store),
            patch(f"{_EV}.get_bars", new_callable=AsyncMock, return_value=_bars(100.0)),
            patch.dict(ev_mod._SIGNAL_FNS, {"pullback_ema": fn}))


def _fire_composite(store, fired=True, bars=None):
    return (patch(f"{_EV}.strategy_watch_store", store),
            patch(f"{_EV}.get_bars", new_callable=AsyncMock,
                  return_value=bars if bars is not None else _bars(100.0)),
            patch("app.services.composite_trigger_evaluator.evaluate_scheduled", return_value=fired),
            patch("app.services.composite_trigger_evaluator.describe_match",
                  return_value={"structure_matched": [], "structure_total": 0,
                                "strategy_matched": [], "strategy_total": 0}))


# ── T2: per-watch isolation (Q17) ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_failing_strategy_watch_skips_only_itself():
    bad = _strategy_watch("bad")
    bad["last_state"] = "x"          # dict("x") raises ValueError in the watch body
    store = _Store([_strategy_watch("a"), bad, _strategy_watch("b")])
    p1, p2, p3 = _fire_strategy(store, _signal())
    with p1, p2, p3:
        events = await evaluate_all()
    assert [e.watch_id for e in events] == ["a", "b"]
    assert store.state("a")["phase"] == "armed"
    assert store.state("b")["phase"] == "armed"
    assert store.state("bad") == "x"


@pytest.mark.asyncio
async def test_a_failing_composite_watch_skips_only_itself():
    good_a, good_b = _composite("a"), _composite("b")
    bad = _composite("bad", )
    bad["symbol"] = "BAD"
    store = _Store([good_a, bad, good_b])

    async def _get_bars(symbol, start, end):
        # every bar's close is garbage for BAD, so float(bars[-1]["close"]) raises
        # however many trailing bars a completed-bar trim removes
        if symbol == "BAD":
            return [{**b, "close": "bad"} for b in _bars(100.0)]
        return _bars(100.0)

    p1, _p2, p3, p4 = _fire_composite(store)
    with p1, patch(f"{_EV}.get_bars", side_effect=_get_bars), p3, p4:
        events = await evaluate_all()
    assert [e.watch_id for e in events] == ["a", "b"]
    assert store.state("a")["phase"] == "armed"
    assert store.state("b")["phase"] == "armed"
    assert store.state("bad") == {"phase": "idle"}


# ── T3: commit after delivery (D3) ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_undelivered_strategy_entry_keeps_state_and_retries():
    # WATCH-UNDELIVERED-EVENT-RESEND replaced "re-derive next run" with "store and
    # re-send": run 2's signal is gone, yet the stored entry is still sent (delayed).
    store = _Store([_strategy_watch("a")])
    p1, p2, p3 = _fire_strategy(store, _signal())
    notify = AsyncMock(side_effect=[False, True])
    with p1, p2, p3, _channels(True), patch(f"{_EV}.notify_channels", per_channel(notify)):
        first = await evaluate_and_notify()
        assert [e.event_type for e in first] == ["entry"]     # reported as fired
        assert store.committed("a") == {"phase": "idle"}       # not committed
        assert len(store.pending("a")) == 1                    # stored
        ev_mod._SIGNAL_FNS["pullback_ema"].return_value = None  # setup gone
        second = await evaluate_and_notify()
    assert second == []                                        # nothing NEW fired
    assert notify.await_args_list[1].args[0].startswith("Delayed: ")
    assert store.state("a")["phase"] == "armed"
    assert "pending_events" not in store.state("a")
    assert notify.await_count == 2


@pytest.mark.asyncio
async def test_undelivered_strategy_exit_stays_armed():
    store = _Store([_strategy_watch("a", "armed", direction="Bullish",
                                    entry_price=100.0, stop_price=101.0, target_price=110.0)])
    p1, p2, p3 = _fire_strategy(store, None)          # close 100 <= stop 101 -> exit_stop
    with p1, p2, p3, _channels(True), \
            patch(f"{_EV}.notify_channels", per_channel(AsyncMock(return_value=False))):
        events = await evaluate_and_notify()
    assert [e.event_type for e in events] == ["exit_stop"]
    assert store.committed("a")["phase"] == "armed"
    assert [p["event"]["event_type"] for p in store.pending("a")] == ["exit_stop"]


@pytest.mark.asyncio
async def test_undelivered_composite_entry_stays_unarmed():
    store = _Store([_composite("a")])
    p1, p2, p3, p4 = _fire_composite(store)
    with p1, p2, p3, p4, _channels(True), \
            patch(f"{_EV}.notify_channels", per_channel(AsyncMock(return_value=False))):
        events = await evaluate_and_notify()
    assert [e.watch_id for e in events] == ["a"]
    assert store.committed("a") == {"phase": "idle"}
    assert [p["event"]["event_type"] for p in store.pending("a")] == ["entry"]


@pytest.mark.asyncio
async def test_notify_raising_counts_as_undelivered():
    store = _Store([_strategy_watch("a")])
    p1, p2, p3 = _fire_strategy(store, _signal())
    with p1, p2, p3, _channels(True), \
            patch(f"{_EV}.notify_channels", per_channel(AsyncMock(
                  side_effect=RuntimeError("smtp down")))):
        events = await evaluate_and_notify()
    assert len(events) == 1
    assert store.committed("a") == {"phase": "idle"}
    assert len(store.pending("a")) == 1


@pytest.mark.asyncio
async def test_no_channel_enabled_arms_anyway():
    """D3: with no channel enabled nothing could ever deliver, so the state is
    committed as before rather than re-firing every run. conftest's settings pin
    makes the real reader return {} (no channel) -- no patch needed here."""
    store = _Store([_strategy_watch("a")])
    p1, p2, p3 = _fire_strategy(store, _signal())
    with p1, p2, p3, \
            patch(f"{_EV}.notify_channels", per_channel(AsyncMock(return_value=False))):
        await evaluate_and_notify()
    assert store.state("a")["phase"] == "armed"


@pytest.mark.asyncio
async def test_delivered_arms():
    store = _Store([_strategy_watch("a")])
    p1, p2, p3 = _fire_strategy(store, _signal())
    with p1, p2, p3, _channels(True), \
            patch(f"{_EV}.notify_channels", per_channel(AsyncMock(return_value=True))):
        await evaluate_and_notify()
    assert store.state("a")["phase"] == "armed"


@pytest.mark.asyncio
async def test_evaluate_all_still_commits_without_notifying():
    store = _Store([_strategy_watch("a")])
    p1, p2, p3 = _fire_strategy(store, _signal())
    notify = AsyncMock()
    with p1, p2, p3, patch(f"{_EV}.notify_channels", per_channel(notify)):
        await evaluate_all()
    notify.assert_not_awaited()
    assert store.state("a")["phase"] == "armed"


@pytest.mark.parametrize("cfg, expected", [
    ({}, False),
    (None, False),                                        # `notifications: null`
    ({"gmail": None, "telegram": "x"}, False),            # null / non-dict blocks
    ({"gmail": {"enabled": False}, "telegram": {"enabled": True}}, True),
    ({"gmail": {"enabled": True}}, True),
])
def test_any_channel_enabled_reads_blocks_safely(cfg, expected):
    with patch(f"{_EV}.read_notification_config", return_value=(cfg, True)):
        assert _any_channel_enabled() is expected


def test_any_channel_enabled_is_true_when_the_reader_itself_raises():
    # read_notification_config reports file/parse errors as readable=False
    # (pinned in test_p6_notification_config.py); this pins only the guard for
    # an exception escaping the reader.
    with patch(f"{_EV}.read_notification_config", side_effect=OSError("disk")):
        assert _any_channel_enabled() is True


def test_one_failed_state_write_does_not_stop_the_next():
    store = MagicMock()
    store.update_state.side_effect = [RuntimeError("disk full"), None]
    ev = MagicMock()
    with patch(f"{_EV}.strategy_watch_store", store):
        _commit(_Transition(event=ev, watch_id="a", new_state={"phase": "armed"}))
        _commit(_Transition(event=ev, watch_id="b", new_state={"phase": "armed"}))
    assert [c.args[0] for c in store.update_state.call_args_list] == ["a", "b"]


# ── T3: one run at a time ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_runs_send_one_entry():
    """The scheduler tick and a manual /evaluate overlapping on one idle
    composite whose condition holds: exactly one send. The notify stub yields
    to the loop, so without the lock both runs collect before either commits."""
    store = _Store([_composite("a")])
    sends = 0

    async def _notify(subject, plain, html):
        nonlocal sends
        sends += 1
        await asyncio.sleep(0)
        return True

    p1, p2, p3, p4 = _fire_composite(store)
    with p1, p2, p3, p4, _channels(True), patch(f"{_EV}.notify_channels", per_channel(_notify)):
        first, second = await asyncio.gather(evaluate_and_notify(), evaluate_and_notify())
    assert sends == 1
    assert sorted(len(r) for r in (first, second)) == [0, 1]
    assert store.state("a")["phase"] == "armed"
