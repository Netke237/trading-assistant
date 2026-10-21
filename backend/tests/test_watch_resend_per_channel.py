"""WATCH-RESEND-PER-CHANNEL (piece 3 of 3) -- per-channel delivery (decisions
WATCH-RESEND-HEAD-OF-LINE-2026-10-01, WATCH-RESEND-SPLIT-2026-10-02).

An alert is finished only when every ready channel delivered (or dropped) it;
each channel gets the queue in order; skip on proof runs per channel; a channel
with nothing outstanding gets a fresh alert at once; an enabled channel without
credentials is not a delivery target. Plan:
docs/superpowers/plans/2026-10-03-watch-resend-per-channel-plan.md."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

import app.services.notifications.dispatch as dispatch
import app.services.strategy_watch_evaluator as ev_mod
from app.services.strategy_watch_evaluator import evaluate_and_notify
from app.services.strategy_watch_store import StrategyWatchStore
from tests.test_watch_resend_skip_on_proof import _e
from tests.test_watch_undelivered_resend import _ARMED, _Env, _Store, _bars, _sw
from tests.watch_notify_helpers import configured_channels_no_real_sends  # noqa: F401

_EV = "app.services.strategy_watch_evaluator"
T0 = datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc)
OLD = (T0 - timedelta(hours=5)).isoformat()
BOTH = {"gmail": {"enabled": True}, "telegram": {"enabled": True}}
GMAIL_ONLY = {"gmail": {"enabled": True}, "telegram": {"enabled": False}}
FRESH = "AAPL: Pullback EMA stop hit at 100.0 (stop 101.0)"
ARMED_101 = {**_ARMED, "stop_price": 101.0}     # close 100 -> the next run fires exit_stop
DROP = "undeliverable alert dropped for"
ALL = object()


def _st(tag: str) -> dict:
    return {"phase": "idle", "last_event": "exit_stop", "m": tag}


class _Chan:
    """notify_channels fake: per channel, fails every reason in fail[channel]
    (or everything with ALL); records (channels, reason, delayed) per call."""

    def __init__(self, **fail):
        self.fail, self.calls = dict(fail), []

    async def __call__(self, cfg, subject, plain, html, channels):
        delayed = plain.startswith("Delayed:")
        reason = plain.split("\n\n", 1)[-1].split("\n", 1)[0] if delayed else plain.split("\n", 1)[0]
        self.calls.append((list(channels), reason, delayed))
        return {c: not (self.fail.get(c) is ALL or reason in (self.fail.get(c) or ())) for c in channels}

    def to(self, channel: str) -> list[str]:
        return [r for chs, r, _d in self.calls if channel in chs]


class _PCEnv(_Env):
    def __init__(self, store, chan: _Chan, cfg=BOTH, now=T0, cfg_reader=None, **kw):
        super().__init__(store, **kw)
        self.chan, self.cfg, self.now, self.cfg_reader = chan, cfg, now, cfg_reader

    async def run(self, **kw):
        reader = self.cfg_reader or {"return_value": (self.cfg, True)}
        with patch(f"{_EV}.strategy_watch_store", self.store), \
                patch(f"{_EV}.get_bars", new_callable=AsyncMock,
                      side_effect=lambda *a, **k: _bars(self.close)), \
                patch.dict(ev_mod._SIGNAL_FNS, {"pullback_ema": self.fn}), \
                patch("app.services.composite_trigger_evaluator.evaluate_scheduled",
                      side_effect=lambda *a, **k: self.fired), \
                patch("app.services.composite_trigger_evaluator.describe_match",
                      return_value={"structure_matched": [], "structure_total": 0,
                                    "strategy_matched": [], "strategy_total": 0}), \
                patch(f"{_EV}.read_notification_config", **reader), \
                patch(f"{_EV}._utcnow", side_effect=lambda: self.now), \
                patch(f"{_EV}.notify_channels", self.chan):
            return await evaluate_and_notify(**kw)


def _reasons(store, wid="a") -> list[str]:
    return [p["event"]["reason"] for p in store.pending(wid)]


def _armed_watch() -> dict:
    return _sw("a", "armed", direction="Bullish", entry_price=100.0, stop_price=101.0, target_price=110.0)


# ── 1-2: partial delivery, nothing held back ──────────────────────────────────

@pytest.mark.asyncio
async def test_1_partial_delivery_is_kept_for_the_failed_channel_only():
    store = _Store([_armed_watch()])
    chan = _Chan(telegram=ALL)
    env = _PCEnv(store, chan)
    assert [e.event_type for e in await env.run()] == ["exit_stop"]
    assert store.committed("a")["phase"] == "armed"                    # NOT committed
    assert _reasons(store) == [FRESH] and store.pending("a")[0]["channel_done"] == {"gmail": "delivered"}
    chan.fail = {}
    env.now = T0 + timedelta(hours=1)
    assert await env.run() == []
    assert chan.calls == [(["gmail", "telegram"], FRESH, False), (["telegram"], FRESH, True)]
    assert store.state("a")["phase"] == "idle" and "pending_events" not in store.state("a")


@pytest.mark.asyncio
async def test_1b_partial_delivery_on_the_real_store_rebuilt_from_disk(tmp_path):
    path = tmp_path / "watches.yaml"
    store = StrategyWatchStore(path=path)
    wid = store.add_watch("AAPL", "pullback_ema")["id"]
    store.update_state(wid, dict(ARMED_101))
    chan = _Chan(telegram=ALL)
    env = _PCEnv(StrategyWatchStore(path=path), chan)
    await env.run()
    pend = StrategyWatchStore(path=path).list_watches()[0]["last_state"]["pending_events"]
    assert [p["channel_done"] for p in pend] == [{"gmail": "delivered"}]      # written to disk
    chan.fail, env.store, env.now = {}, StrategyWatchStore(path=path), T0 + timedelta(hours=1)
    await env.run()
    final = StrategyWatchStore(path=path).list_watches()[0]["last_state"]
    assert "pending_events" not in final and final["phase"] == "idle"
    assert chan.to("gmail") == [FRESH] and chan.to("telegram") == [FRESH, FRESH]


@pytest.mark.asyncio
async def test_2_gmail_gets_a_fresh_alert_while_telegram_is_stuck_behind_an_older_one():
    store = _Store([_sw("a", pending=[_e("RZ-A", ARMED_101, event_type="entry",
                                         channel_done={"gmail": "delivered"})])])
    chan = _Chan(telegram=ALL)
    assert [e.event_type for e in await _PCEnv(store, chan).run()] == ["exit_stop"]
    assert chan.calls == [(["telegram"], "RZ-A", True), (["gmail"], FRESH, False)]
    assert _reasons(store) == ["RZ-A", FRESH]
    assert store.pending("a")[1]["channel_done"] == {"gmail": "delivered"}
    assert ev_mod._failures(store.pending("a")[0], "telegram") == 1


# ── 3-5: skip on proof, per channel ───────────────────────────────────────────

async def _skip_on_proof_runs(env, chan, store_of):
    env.now = T0
    await env.run()
    assert chan.calls == [(["gmail", "telegram"], "RZ-H", True), (["gmail"], "RZ-B", True)]
    for h, n in ((1, 2), (2, 3)):
        env.store, env.now = store_of(), T0 + timedelta(hours=h)
        await env.run()
    assert chan.calls[2:] == [(["telegram"], "RZ-H", True), (["telegram"], "RZ-H", True),
                              (["telegram"], "RZ-B", True)]
    assert chan.to("gmail") == ["RZ-H", "RZ-B"]                        # never re-sent


@pytest.mark.asyncio
async def test_3_skip_on_proof_drops_the_head_on_the_failing_channel_only(caplog):
    store = _Store([_sw("a", pending=[_e("RZ-H", _st("H")), _e("RZ-B", _st("B"))])])
    chan = _Chan(telegram={"RZ-H"})
    env = _PCEnv(store, chan)
    await env.run()
    assert ev_mod._failures(store.pending("a")[0], "telegram") == 1
    assert ev_mod._failures(store.pending("a")[0], "gmail") == 0
    chan.calls.clear()
    store.watches[0]["last_state"] = {"phase": "idle",
                                      "pending_events": [_e("RZ-H", _st("H")), _e("RZ-B", _st("B"))]}
    with caplog.at_level(logging.ERROR, logger=_EV):
        await _skip_on_proof_runs(env, chan, lambda: store)
    assert store.state("a") == _st("B")                               # committed = B, no queue
    assert f"{DROP} a after 3 failed runs on telegram" in caplog.text and "RZ-H" in caplog.text
    assert "on gmail" not in caplog.text


@pytest.mark.asyncio
async def test_3b_same_on_the_real_store_rebuilt_from_disk(tmp_path):
    path = tmp_path / "watches.yaml"
    store = StrategyWatchStore(path=path)
    store.add_watch("AAPL", "pullback_ema")
    wid = store.list_watches()[0]["id"]
    store.update_state(wid, {"phase": "idle", "pending_events": [_e("RZ-H", _st("H")), _e("RZ-B", _st("B"))]})
    chan = _Chan(telegram={"RZ-H"})
    env = _PCEnv(StrategyWatchStore(path=path), chan)
    await _skip_on_proof_runs(env, chan, lambda: StrategyWatchStore(path=path))
    final = StrategyWatchStore(path=path).list_watches()[0]["last_state"]
    assert "pending_events" not in final and final["m"] == "B"


@pytest.mark.asyncio
async def test_3c_a_drop_on_one_channel_leaves_the_head_outstanding_on_the_other(caplog):
    store = _Store([_sw("a", pending=[
        _e("RZ-H", _st("H"), channel_failures={"telegram": 3}, channel_last_failure_at={"telegram": OLD}),
        _e("RZ-B", _st("B"))])])
    chan = _Chan(gmail={"RZ-H"}, telegram={"RZ-H"})
    with caplog.at_level(logging.ERROR, logger=_EV):
        await _PCEnv(store, chan).run()
    assert chan.calls == [(["gmail", "telegram"], "RZ-H", True), (["telegram"], "RZ-B", True)]
    assert _reasons(store) == ["RZ-H", "RZ-B"] and store.committed("a") == {"phase": "idle"}
    head = store.pending("a")[0]
    assert head["channel_done"] == {"telegram": "dropped"} and ev_mod._failures(head, "gmail") == 1
    assert store.pending("a")[1]["channel_done"] == {"telegram": "delivered"}
    assert f"{DROP} a after 4 failed runs on telegram" in caplog.text and "on gmail" not in caplog.text


@pytest.mark.asyncio
async def test_4_counters_are_per_channel_and_the_legacy_scalar_counts_for_each(caplog):
    store = _Store([_sw("a", pending=[_e("RZ-H", _st("H"))])])
    chan = _Chan(gmail={"RZ-H"}, telegram={"RZ-H"})
    env = _PCEnv(store, chan)
    await env.run()
    head = store.pending("a")[0]
    assert ev_mod._failures(head, "gmail") == 1 and ev_mod._failures(head, "telegram") == 1
    chan.fail, env.now = {"telegram": {"RZ-H"}}, T0 + timedelta(hours=1)
    await env.run()
    head = store.pending("a")[0]
    assert head["channel_done"] == {"gmail": "delivered"}
    assert ev_mod._failures(head, "gmail") == 1 and ev_mod._failures(head, "telegram") == 2
    # piece 1's scalar: eligible on BOTH channels, each dropped by its own probe
    store = _Store([_sw("a", pending=[_e("RZ-H", _st("H"), failures=3, last_failure_at=OLD),
                                      _e("RZ-B", _st("B"))])])
    chan = _Chan(gmail={"RZ-H"}, telegram={"RZ-H"})
    with caplog.at_level(logging.ERROR, logger=_EV):
        await _PCEnv(store, chan).run()
    assert chan.calls == [(["gmail", "telegram"], "RZ-H", True), (["gmail", "telegram"], "RZ-B", True)]
    assert store.state("a") == _st("B")
    assert f"{DROP} a after 4 failed runs on gmail" in caplog.text
    assert f"{DROP} a after 4 failed runs on telegram" in caplog.text


@pytest.mark.asyncio
async def test_5_a_failed_probe_blocks_that_channel_only(caplog):
    store = _Store([_sw("a", pending=[
        _e("RZ-H", _st("H"), channel_done={"gmail": "delivered"},
           channel_failures={"telegram": 3}, channel_last_failure_at={"telegram": OLD}),
        _e("RZ-P", _st("P")), _e("RZ-C", _st("C"))])])
    chan = _Chan(telegram=ALL)
    with caplog.at_level(logging.ERROR, logger=_EV):
        await _PCEnv(store, chan).run()
    assert chan.calls == [(["telegram"], "RZ-H", True), (["gmail", "telegram"], "RZ-P", True),
                          (["gmail"], "RZ-C", True)]
    assert _reasons(store) == ["RZ-H", "RZ-P", "RZ-C"] and DROP not in caplog.text
    assert [p.get("channel_done") for p in store.pending("a")] == [{"gmail": "delivered"}] * 3
    assert ev_mod._failures(store.pending("a")[0], "telegram") == 4
    assert "channel_failures" not in store.pending("a")[1]            # the probe is not counted


# ── 6-8: which channels are targets ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_6_an_enabled_channel_without_credentials_is_not_a_target(monkeypatch, caplog):
    monkeypatch.delenv("BAMENDJOU_TELEGRAM_BOT_TOKEN")
    store = _Store([_armed_watch()])
    chan = _Chan()
    with caplog.at_level(logging.WARNING, logger=_EV):
        await _PCEnv(store, chan).run()
    assert chan.calls == [(["gmail"], FRESH, False)]
    assert store.state("a")["phase"] == "idle" and "pending_events" not in store.state("a")
    assert "telegram enabled but not configured" in caplog.text


@pytest.mark.asyncio
async def test_6b_enabled_but_nothing_configured_holds_everything(monkeypatch):
    for name in ("BAMENDJOU_GMAIL_PASSWORD", "BAMENDJOU_TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(name)
    store = _Store([_sw("a", pending=[_e("RZ-A", ARMED_101, event_type="entry")])])
    chan = _Chan()
    await _PCEnv(store, chan).run()
    assert chan.calls == [] and _reasons(store) == ["RZ-A", FRESH]
    assert store.committed("a") == {"phase": "idle"}
    assert "channel_failures" not in store.pending("a")[0]


@pytest.mark.asyncio
async def test_7_disabling_the_failing_channel_finishes_its_entries():
    store = _Store([_sw("a", pending=[_e("RZ-A", _st("A"), channel_done={"gmail": "delivered"})])])
    chan = _Chan()
    await _PCEnv(store, chan, cfg=GMAIL_ONLY).run()
    assert chan.calls == [] and store.state("a") == _st("A")


@pytest.mark.asyncio
async def test_8_a_channel_enabled_later_gets_a_still_queued_entry():
    store = _Store([_sw("a", pending=[_e("RZ-A", _st("A"))])])
    chan = _Chan(gmail=ALL)
    env = _PCEnv(store, chan, cfg=GMAIL_ONLY)
    await env.run()
    env.cfg, env.now = BOTH, T0 + timedelta(hours=1)
    await env.run()
    assert chan.calls == [(["gmail"], "RZ-A", True), (["gmail", "telegram"], "RZ-A", True)]
    assert store.pending("a")[0]["channel_done"] == {"telegram": "delivered"}


# ── 9-11: the fresh event ─────────────────────────────────────────────────────

def _stuck_on_telegram() -> dict:
    return _e("RZ-H", ARMED_101, event_type="entry", channel_done={"gmail": "delivered"},
              channel_failures={"telegram": 3}, channel_last_failure_at={"telegram": OLD})


@pytest.mark.asyncio
async def test_9_the_fresh_event_is_the_probe_on_the_stuck_channel(caplog):
    store = _Store([_sw("a", pending=[_stuck_on_telegram()])])
    chan = _Chan(telegram={"RZ-H"})
    with caplog.at_level(logging.ERROR, logger=_EV):
        await _PCEnv(store, chan).run()
    assert chan.calls == [(["telegram"], "RZ-H", True), (["gmail", "telegram"], FRESH, False)]
    assert store.state("a")["last_event"] == "exit_stop" and "pending_events" not in store.state("a")
    assert f"{DROP} a after 4 failed runs on telegram" in caplog.text


@pytest.mark.asyncio
async def test_9b_a_failed_fresh_probe_keeps_the_head(caplog):
    store = _Store([_sw("a", pending=[_stuck_on_telegram()])])
    chan = _Chan(telegram=ALL)
    with caplog.at_level(logging.ERROR, logger=_EV):
        await _PCEnv(store, chan).run()
    assert chan.calls == [(["telegram"], "RZ-H", True), (["gmail", "telegram"], FRESH, False)]
    assert _reasons(store) == ["RZ-H", FRESH] and DROP not in caplog.text
    assert [p["channel_done"] for p in store.pending("a")] == [{"gmail": "delivered"}] * 2


@pytest.mark.asyncio
async def test_9c_a_fresh_probe_drops_the_head_on_its_channel_only(caplog):
    store = _Store([_sw("a", pending=[
        _e("RZ-H", ARMED_101, event_type="entry",
           channel_failures={"telegram": 3}, channel_last_failure_at={"telegram": OLD})])])
    chan = _Chan(gmail={"RZ-H"}, telegram={"RZ-H"})
    with caplog.at_level(logging.ERROR, logger=_EV):
        await _PCEnv(store, chan).run()
    # Gmail is blocked behind H (1st failure); Telegram is probe-ready (4th).
    assert chan.calls == [(["gmail", "telegram"], "RZ-H", True), (["telegram"], FRESH, False)]
    assert _reasons(store) == ["RZ-H", FRESH] and store.committed("a") == {"phase": "idle"}
    assert store.pending("a")[0]["channel_done"] == {"telegram": "dropped"}
    assert store.pending("a")[1]["channel_done"] == {"telegram": "delivered"}
    assert f"{DROP} a after 4 failed runs on telegram" in caplog.text


@pytest.mark.asyncio
async def test_10_defensive_per_channel_length_check():
    store = _Store([_sw("a")])
    t = ev_mod._Transition(event=ev_mod.WatchEvent(
        watch_id="a", symbol="AAPL", strategy_key="pullback_ema", event_type="exit_stop",
        direction="Bullish", entry=100.0, stop=101.0, target=110.0, rr_ratio=None, close=100.0,
        reason="RZ-fresh"), watch_id="a", new_state=_st("F"), committed={"phase": "armed"},
        pending=[_e("RZ-H", channel_done={"gmail": "delivered"}),
                 _e("RZ-P", channel_done={"gmail": "delivered"})])
    chan = _Chan()
    with patch(f"{_EV}.strategy_watch_store", store), patch(f"{_EV}.notify_channels", chan):
        await ev_mod._deliver_or_queue(t, ev_mod._Run("send", BOTH, ("gmail", "telegram")),
                                       {"a": {"telegram": 3}})
    assert chan.calls == [(["gmail"], "RZ-fresh", False)]
    assert _reasons(store) == ["RZ-H", "RZ-P", "RZ-fresh"]


@pytest.mark.asyncio
async def test_11_openness_comes_from_the_stored_queue_when_the_pass_raised():
    store = _Store([_sw("a", pending=[_e("RZ-A", ARMED_101, event_type="entry",
                                         channel_done={"gmail": "delivered"})])])
    chan = _Chan()
    with patch(f"{_EV}._resend_watch", AsyncMock(side_effect=RuntimeError("boom"))):
        await _PCEnv(store, chan).run()
    assert chan.calls == [(["gmail"], FRESH, False)]                  # never to Telegram
    assert _reasons(store) == ["RZ-A", FRESH]


# ── 13-16: config, malformed keys, dispatch, cap ──────────────────────────────

@pytest.mark.parametrize("reader", [{"return_value": ({}, False)},
                                    {"side_effect": OSError("unreadable")}])
@pytest.mark.asyncio
async def test_13_unreadable_config_sends_nothing(reader):
    store = _Store([_sw("a", pending=[_e("RZ-A", ARMED_101, event_type="entry")])])
    chan = _Chan()
    await _PCEnv(store, chan, cfg_reader=reader).run()
    assert chan.calls == [] and _reasons(store) == ["RZ-A", FRESH]
    assert store.committed("a") == {"phase": "idle"} and "channel_failures" not in store.pending("a")[0]


@pytest.mark.parametrize("done,expect", [
    ("x", {}), ({"gmail": "yes"}, {}), ({"fax": "delivered"}, {}), ({1: "delivered"}, {}),
    ({"gmail": "dropped", "telegram": "delivered"}, {"gmail": "dropped", "telegram": "delivered"}),
])
def test_14_malformed_channel_done_reads_as_absent(done, expect):
    assert ev_mod._done({"channel_done": done}) == expect


@pytest.mark.parametrize("entry,expect", [
    ({"channel_failures": {"gmail": 4}, "failures": 1}, 4),
    ({"channel_failures": {"gmail": -1}, "failures": 2}, 2),
    ({"channel_failures": {"gmail": True}, "failures": 2}, 2),
    ({"channel_failures": "x", "failures": 2}, 2),
    ({"channel_failures": {"telegram": 5}}, 0),
    ({"failures": "x"}, 0),
])
def test_14b_per_channel_failures_fall_back_to_the_scalar(entry, expect):
    assert ev_mod._failures(entry, "gmail") == expect


def test_14c_last_failure_falls_back_to_the_scalar():
    assert ev_mod._last_failure({"channel_last_failure_at": {"gmail": "A"}, "last_failure_at": "B"},
                                "gmail") == "A"
    assert ev_mod._last_failure({"channel_last_failure_at": {"gmail": 3}, "last_failure_at": "B"},
                                "gmail") == "B"
    assert ev_mod._last_failure({"last_failure_at": 7}, "gmail") is None


@pytest.mark.asyncio
async def test_14d_a_malformed_channel_done_resends_to_both_channels():
    store = _Store([_sw("a", pending=[_e("RZ-A", _st("A"), channel_done="x")])])
    chan = _Chan()
    await _PCEnv(store, chan).run()
    assert chan.calls == [(["gmail", "telegram"], "RZ-A", True)] and store.state("a") == _st("A")


_CREDS = {"gmail": {"enabled": True, "smtp_user": "u", "smtp_password": "p", "to": "t"},
          "telegram": {"enabled": True, "bot_token": "tok", "chat_id": "1"}}


@pytest.mark.asyncio
async def test_15_notify_channels_attempts_only_listed_enabled_channels():
    gm, tg = AsyncMock(return_value=True), AsyncMock(return_value=True)
    with patch.object(dispatch, "send_gmail", gm), patch.object(dispatch, "send_telegram", tg), \
            patch.object(dispatch, "log_sent"):
        assert await dispatch.notify_channels(_CREDS, "s", "p", "h", ["telegram"]) == {"telegram": True}
        assert not gm.called and tg.await_count == 1
        off = {**_CREDS, "telegram": {**_CREDS["telegram"], "enabled": False}}
        assert await dispatch.notify_channels(off, "s", "p", "h", ["telegram"]) == {}
        tg.side_effect = RuntimeError("down")
        assert await dispatch.notify_channels(_CREDS, "s", "p", "h", ["gmail", "telegram"]) == \
            {"gmail": True, "telegram": False}


@pytest.mark.parametrize("gmail_ok,tg_ok,expect", [(False, True, True), (False, False, False)])
@pytest.mark.asyncio
async def test_15b_notify_enabled_channels_keeps_its_any_contract(gmail_ok, tg_ok, expect):
    with patch.object(dispatch, "load_notification_config", return_value=_CREDS), \
            patch.object(dispatch, "send_gmail", AsyncMock(return_value=gmail_ok)), \
            patch.object(dispatch, "send_telegram", AsyncMock(return_value=tg_ok)), \
            patch.object(dispatch, "log_sent"):
        assert await dispatch.notify_enabled_channels("s", "p", "h") is expect


@pytest.mark.parametrize("cfg,env,expect", [
    (_CREDS, {}, ["gmail", "telegram"]),
    ({"gmail": {"enabled": True}, "telegram": {"enabled": True}},
     {"BAMENDJOU_GMAIL_USER": "u", "BAMENDJOU_GMAIL_PASSWORD": "p", "BAMENDJOU_GMAIL_TO": "t",
      "BAMENDJOU_TELEGRAM_BOT_TOKEN": "t", "BAMENDJOU_TELEGRAM_CHAT_ID": "1"}, ["gmail", "telegram"]),
    ({"gmail": {"enabled": True}, "telegram": {"enabled": True}},
     {"BAMENDJOU_GMAIL_USER": "u", "BAMENDJOU_GMAIL_PASSWORD": "p",
      "BAMENDJOU_TELEGRAM_BOT_TOKEN": "t", "BAMENDJOU_TELEGRAM_CHAT_ID": "1"}, ["telegram"]),  # no to
    ({"telegram": {"enabled": True, "chat_id": "1"}}, {}, []),                 # no token
    ({"telegram": {"enabled": True, "bot_token": "t"}}, {}, []),               # no chat id
    ({"gmail": {"enabled": True, "smtp_user": "u", "to": "t"}}, {}, []),       # no password
    ({"gmail": {"enabled": True, "smtp_user": "u", "smtp_password": "p"}}, {}, []),  # no to in cfg/env
    ({**_CREDS, "gmail": {**_CREDS["gmail"], "enabled": False}}, {}, ["telegram"]),
    ({"gmail": None, "telegram": _CREDS["telegram"]}, {}, ["telegram"]),       # null block
])
def test_15c_ready_channels(monkeypatch, cfg, env, expect):
    for name in ("BAMENDJOU_GMAIL_USER", "BAMENDJOU_GMAIL_PASSWORD", "BAMENDJOU_GMAIL_TO",
                 "BAMENDJOU_TELEGRAM_BOT_TOKEN", "BAMENDJOU_TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(name, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert dispatch.ready_channels(cfg) == expect


@pytest.mark.asyncio
async def test_16_the_cap_names_a_partly_delivered_dropped_entry(caplog):
    cap = ev_mod._QUEUE_CAP
    pend = [_e(f"RZ-{i}", _st(str(i)), channel_done={"gmail": "delivered"}) for i in range(cap - 1)]
    pend.append(_e(f"RZ-{cap - 1}", ARMED_101, event_type="entry", channel_done={"gmail": "delivered"}))
    store = _Store([_sw("a", pending=pend)])
    chan = _Chan(telegram=ALL)
    with caplog.at_level(logging.ERROR, logger=_EV):
        await _PCEnv(store, chan).run()
    assert chan.calls == [(["telegram"], "RZ-0", True), (["gmail"], FRESH, False)]
    assert len(store.pending("a")) == cap and _reasons(store)[0] == "RZ-1"
    assert store.committed("a") == _st("0")
    assert "queue full" in caplog.text and "{'gmail': 'delivered'}" in caplog.text



# ── 17-23: DECISION-34-WATCH-DELIVERY-RESIDUALS ───────────────────────────────

@pytest.mark.asyncio
async def test_17_cross_watch_proof_two_stuck_in_a_row_drops_head_when_other_watch_delivers(caplog):
    # Watch A has stuck head (failures=2 + spaced -> 3) and probe RZ-P2 which also fails.
    # Watch B has RZ-B which delivers on gmail.
    # Order: A evaluated before B.
    store = _Store([
        _sw("a", pending=[_e("RZ-head", _st("H"), failures=2, last_failure_at=OLD),
                          _e("RZ-P2", _st("P2")), _e("RZ-C", _st("C"))]),
        _sw("b", pending=[_e("RZ-B", _st("B"))]),
    ])
    chan = _Chan(gmail={"RZ-head", "RZ-P2"})
    env = _PCEnv(store, chan, cfg=GMAIL_ONLY)
    with caplog.at_level(logging.ERROR, logger=_EV):
        await env.run()
    # Watch B delivered RZ-B on gmail, triggering cross-watch proof for Watch A
    assert "RZ-B" in chan.to("gmail")
    assert f"{DROP} a after 3 failed runs on gmail" in caplog.text
    # RZ-head dropped on gmail; RZ-P2 is new head and has 1 failure
    assert _reasons(store, "a") == ["RZ-P2", "RZ-C"]
    assert ev_mod._failures(store.pending("a")[0], "gmail") == 1
    # Watch B popped its delivered event
    assert len(store.pending("b")) == 0


@pytest.mark.asyncio
async def test_18_cross_watch_proof_order_independence_watch_b_delivers_before_watch_a(caplog):
    # Order: B evaluated before A. Watch B delivers first, populating delivered_channels.
    # When Watch A evaluates, it sees gmail already delivered.
    store = _Store([
        _sw("b", pending=[_e("RZ-B", _st("B"))]),
        _sw("a", pending=[_e("RZ-head", _st("H"), failures=2, last_failure_at=OLD),
                          _e("RZ-P2", _st("P2")), _e("RZ-C", _st("C"))]),
    ])
    chan = _Chan(gmail={"RZ-head", "RZ-P2"})
    env = _PCEnv(store, chan, cfg=GMAIL_ONLY)
    with caplog.at_level(logging.ERROR, logger=_EV):
        await env.run()
    assert "RZ-B" in chan.to("gmail")
    assert f"{DROP} a after 3 failed runs on gmail" in caplog.text
    assert _reasons(store, "a") == ["RZ-P2", "RZ-C"]
    assert ev_mod._failures(store.pending("a")[0], "gmail") == 1
    assert len(store.pending("b")) == 0


@pytest.mark.asyncio
async def test_19_cross_watch_proof_fresh_event_probe_failure(caplog):
    # Watch A has lone stuck head (failures=2 + spaced -> 3). Fresh exit_stop fires as probe and fails.
    # Watch B delivers RZ-B on gmail.
    store = _Store([
        _sw("a", pending=[_e("RZ-head", ARMED_101, event_type="entry",
                             failures=2, last_failure_at=OLD)]),
        _sw("b", pending=[_e("RZ-B", _st("B"))]),
    ])
    chan = _Chan(gmail={"RZ-head", FRESH})
    env = _PCEnv(store, chan, cfg=GMAIL_ONLY)
    with caplog.at_level(logging.ERROR, logger=_EV):
        await env.run()
    assert f"{DROP} a after 3 failed runs on gmail" in caplog.text
    # RZ-head dropped; fresh exit_stop queued with 1 failure on gmail
    assert len(store.pending("a")) == 1
    assert store.pending("a")[0]["event"]["event_type"] == "exit_stop"
    assert ev_mod._failures(store.pending("a")[0], "gmail") == 1


@pytest.mark.asyncio
async def test_20_outage_no_watch_delivers_drops_nothing(caplog):
    # Complete outage on gmail (ALL fail). No watch delivers.
    store = _Store([
        _sw("a", pending=[_e("RZ-head", _st("H"), failures=2, last_failure_at=OLD),
                          _e("RZ-P2", _st("P2"))]),
        _sw("b", pending=[_e("RZ-B", _st("B"))]),
    ])
    chan = _Chan(gmail=ALL)
    env = _PCEnv(store, chan, cfg=GMAIL_ONLY)
    with caplog.at_level(logging.ERROR, logger=_EV):
        await env.run()
    # Nothing dropped
    assert "undeliverable alert dropped" not in caplog.text
    assert _reasons(store, "a") == ["RZ-head", "RZ-P2"]
    assert _reasons(store, "b") == ["RZ-B"]


@pytest.mark.asyncio
async def test_21_lone_eligible_head_without_probe_not_dropped(caplog):
    # Watch A has lone eligible head (no second entry, no fresh event).
    # Watch B delivers on gmail.
    store = _Store([
        _sw("a", pending=[_e("RZ-head", _st("H"), failures=5)]),
        _sw("b", pending=[_e("RZ-B", _st("B"))]),
    ])
    chan = _Chan(gmail={"RZ-head"})
    env = _PCEnv(store, chan, cfg=GMAIL_ONLY)
    with caplog.at_level(logging.ERROR, logger=_EV):
        await env.run()
    # Lone head without a probe attempt is not dropped
    assert "undeliverable alert dropped" not in caplog.text
    assert _reasons(store, "a") == ["RZ-head"]


@pytest.mark.asyncio
async def test_22_m25_delivered_probe_clears_stuck_before_subsequent_entry(caplog):
    # M25 survivor test: queue has head, probe, and third entry.
    # Probe delivers -> stuck.pop(c) must clear stuck so RZ-P3 is not treated as a probe.
    store = _Store([
        _sw("a", pending=[_e("RZ-head", _st("H"), failures=2, last_failure_at=OLD),
                          _e("RZ-P2", _st("P2")),
                          _e("RZ-P3", _st("P3"))]),
    ])
    chan = _Chan(gmail={"RZ-head"})  # RZ-head fails; RZ-P2 and RZ-P3 deliver
    env = _PCEnv(store, chan, cfg=GMAIL_ONLY)
    with caplog.at_level(logging.ERROR, logger=_EV):
        await env.run()
    assert f"{DROP} a after 3 failed runs on gmail" in caplog.text
    assert "RZ-P2" in chan.to("gmail")
    assert "RZ-P3" in chan.to("gmail")
    # All entries popped, queue is clean
    assert len(store.pending("a")) == 0
    assert store.committed("a") == _st("P3")


@pytest.mark.asyncio
async def test_23_m33_commit_mode_queues_fresh_event_behind_non_empty_queue():
    # M33 survivor test: commit mode (no channels enabled) with non-empty pending_events.
    # Fresh transition must be queued behind pending, NOT committed directly.
    pend = [_e("RZ-head", _st("H"))]
    store = _Store([_sw("a", pending=pend)])
    t = ev_mod._Transition(
        event=ev_mod.WatchEvent(
            watch_id="a", symbol="AAPL", strategy_key="pullback_ema", event_type="exit_stop",
            direction="Bullish", entry=100.0, stop=101.0, target=110.0, rr_ratio=None, close=100.0,
            reason="RZ-fresh",
        ),
        watch_id="a", new_state=_st("F"), committed={"phase": "armed"},
        pending=pend,
    )
    with patch(f"{_EV}.strategy_watch_store", store):
        await ev_mod._deliver_or_queue(t, ev_mod._Run("commit"))
    # Fresh event queued behind existing entry, not committed
    assert len(store.pending("a")) == 2
    assert _reasons(store, "a") == ["RZ-head", "RZ-fresh"]
    assert store.committed("a") == {"phase": "armed"}
