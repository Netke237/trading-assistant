# backend/tests/test_strategy_watch_store.py
from __future__ import annotations

import pytest

from app.services.strategy_watch_store import StrategyWatchStore


def test_add_watch_upper_cases_symbol_and_assigns_id(tmp_path):
    store = StrategyWatchStore(path=tmp_path / "watches.yaml")
    entry = store.add_watch("aapl", "pullback_ema")
    assert entry["symbol"] == "AAPL"
    assert entry["strategy_key"] == "pullback_ema"
    assert entry["id"].startswith("wch_")
    assert entry["enabled"] is True
    assert entry["last_state"]["phase"] == "idle"


def test_add_watch_rejects_unknown_strategy(tmp_path):
    store = StrategyWatchStore(path=tmp_path / "watches.yaml")
    with pytest.raises(ValueError, match="unknown strategy"):
        store.add_watch("AAPL", "not_a_strategy")


def test_add_watch_rejects_duplicate_pair_same_direction(tmp_path):
    store = StrategyWatchStore(path=tmp_path / "watches.yaml")
    store.add_watch("AAPL", "pullback_ema", direction="Bullish")
    with pytest.raises(ValueError, match="already watched"):
        store.add_watch("aapl", "pullback_ema", direction="Bullish")


def test_add_watch_allows_same_symbol_strategy_different_direction(tmp_path):
    store = StrategyWatchStore(path=tmp_path / "watches.yaml")
    bullish = store.add_watch("AAPL", "pullback_ema", direction="Bullish")
    bearish = store.add_watch("AAPL", "pullback_ema", direction="Bearish")
    assert bullish["id"] != bearish["id"]
    symbols = {(w["symbol"], w["strategy_key"], w["direction"]) for w in store.list_watches()}
    assert symbols == {("AAPL", "pullback_ema", "Bullish"), ("AAPL", "pullback_ema", "Bearish")}


def test_bulk_add_skips_duplicates_and_returns_added(tmp_path):
    store = StrategyWatchStore(path=tmp_path / "watches.yaml")
    store.add_watch("AAPL", "breakout_base")
    added = store.add_watches_bulk(["AAPL", "MSFT", "GOOG"], "breakout_base")
    assert {e["symbol"] for e in added} == {"MSFT", "GOOG"}  # AAPL skipped (dup)


def test_remove_and_set_enabled(tmp_path):
    store = StrategyWatchStore(path=tmp_path / "watches.yaml")
    e = store.add_watch("AAPL", "ma_crossover")
    store.set_enabled(e["id"], False)
    assert store.list_watches()[0]["enabled"] is False
    store.remove_watch(e["id"])
    assert store.list_watches() == []


def test_update_state_persists_and_round_trips(tmp_path):
    path = tmp_path / "watches.yaml"
    store = StrategyWatchStore(path=path)
    e = store.add_watch("AAPL", "pullback_ema")
    store.update_state(e["id"], {"phase": "armed", "direction": "Bullish",
                                 "entry_price": 100.0, "stop_price": 95.0,
                                 "target_price": 110.0, "last_event": "entry",
                                 "last_event_at": "2026-06-13T18:00:00Z"})
    reloaded = StrategyWatchStore(path=path)
    state = reloaded.list_watches()[0]["last_state"]
    assert state["phase"] == "armed"
    assert state["entry_price"] == 100.0


def test_update_state_reset_genuinely_removes_a_key_not_reintroduced_by_fresh_state_defaults(tmp_path):
    path = tmp_path / "watches.yaml"
    store = StrategyWatchStore(path=path)
    e = store.add_watch("AAPL", "pullback_ema")
    store.update_state(e["id"], {"phase": "idle", "pending_entry_since": "2026-06-13T18:00:00+00:00"})
    state = store.list_watches()[0]["last_state"]
    assert state["pending_entry_since"] == "2026-06-13T18:00:00+00:00"

    reset_state = {k: v for k, v in state.items() if k != "pending_entry_since"}
    store.update_state(e["id"], reset_state)
    state_after = store.list_watches()[0]["last_state"]
    assert "pending_entry_since" not in state_after


def test_load_migrates_legacy_entries_missing_direction(tmp_path):
    path = tmp_path / "watches.yaml"
    path.write_text(
        "schedule: {enabled: false, mode: eod, eod_time: '16:15', poll_hours: 4, sustain_minutes: 0}\n"
        "watches:\n"
        "- id: wch_legacy001\n"
        "  symbol: AAPL\n"
        "  strategy_key: pullback_ema\n"
        "  params_override: {}\n"
        "  enabled: true\n"
        "  created_at: '2026-06-13T20:48:29.893224+00:00'\n"
        "  last_state: {phase: idle, direction: null, entry_price: null, stop_price: null,\n"
        "               target_price: null, last_event: null, last_event_at: null}\n"
        "  watch_type: strategy\n"
        "  trigger_def: null\n"
        "  interval: 1D\n"
    )
    store = StrategyWatchStore(path=path)
    assert store.list_watches()[0]["direction"] == "Bullish"


def test_schedule_defaults_and_update(tmp_path):
    store = StrategyWatchStore(path=tmp_path / "watches.yaml")
    sched = store.get_schedule()
    assert sched == {"enabled": False, "mode": "eod", "eod_time": "16:15", "poll_hours": 4,
                     "sustain_minutes": 0}
    store.set_schedule({"enabled": True, "mode": "poll", "eod_time": "16:15", "poll_hours": 2})
    assert store.get_schedule()["mode"] == "poll"
    assert store.get_schedule()["poll_hours"] == 2
