# Strategy Watch & Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user pin a strategy to a stock and receive Gmail/Telegram alerts on entry / exit / reversal signals, evaluated on an EOD or intraday-poll schedule.

**Architecture:** A YAML-backed store holds (symbol, strategy) watch entries plus a schedule config. A pure evaluator runs each watched strategy on DB-first daily bars and classifies state transitions (idle→entry, armed→exit, armed→reversal) into events; a thin notify wrapper formats events and dispatches through the existing Gmail/Telegram channel. A background scheduler loop (modeled on `ScanScheduler`) triggers evaluation EOD or every N hours. A REST router exposes CRUD + manual evaluate, and a frontend page manages the list.

**Tech Stack:** Python 3.14, FastAPI, Pydantic v2, PyYAML, pytest + pytest-asyncio, `unittest.mock`; TypeScript 5.7, React, Zustand v5, CSS Modules.

**Source spec:** `docs/superpowers/specs/2026-06-13-strategy-watch-alerts-design.md`

---

## File Structure

- **Create** `backend/app/services/strategy_watch_store.py` — thread-safe YAML store of watch entries + schedule config.
- **Create** `backend/tests/test_strategy_watch_store.py` — store unit tests.
- **Create** `backend/app/services/strategy_watch_evaluator.py` — `WatchEvent`, `evaluate_all()`, `evaluate_and_notify()`.
- **Create** `backend/tests/test_strategy_watch_evaluator.py` — state-machine + notify unit tests.
- **Create** `backend/app/services/strategy_watch_scheduler.py` — background cadence loop.
- **Create** `backend/tests/test_strategy_watch_scheduler.py` — scheduler unit tests.
- **Create** `backend/app/routers/strategy_watch.py` — REST endpoints.
- **Create** `backend/tests/test_strategy_watch_router.py` — router unit tests.
- **Modify** `backend/app/main.py` — register router + start/stop scheduler in lifespan.
- **Modify** `frontend/lib/api.ts` — strategy-watch API methods + types.
- **Create** `frontend/lib/strategyWatchStore.ts` — Zustand store fronting the API.
- **Create** `frontend/app/(frame)/strategy-watch/page.tsx` + `page.module.css` — management page.
- **Modify** the nav component to add a "Strategy Watch" link (see Task 8 for discovery).

Run backend commands from `backend/`. Test pattern: `python -m pytest tests/<file>::<test> -v`.
Frontend: `cd frontend && npm run typecheck`.

---

### Task 1: strategy_watch_store — persisted watch entries + schedule

**Files:**
- Create: `backend/app/services/strategy_watch_store.py`
- Test: `backend/tests/test_strategy_watch_store.py`

- [ ] **Step 1: Write the failing test**

```python
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


def test_add_watch_rejects_duplicate_pair(tmp_path):
    store = StrategyWatchStore(path=tmp_path / "watches.yaml")
    store.add_watch("AAPL", "pullback_ema")
    with pytest.raises(ValueError, match="already watched"):
        store.add_watch("aapl", "pullback_ema")


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


def test_schedule_defaults_and_update(tmp_path):
    store = StrategyWatchStore(path=tmp_path / "watches.yaml")
    sched = store.get_schedule()
    assert sched == {"enabled": False, "mode": "eod", "eod_time": "16:15", "poll_hours": 4}
    store.set_schedule({"enabled": True, "mode": "poll", "eod_time": "16:15", "poll_hours": 2})
    assert store.get_schedule()["mode"] == "poll"
    assert store.get_schedule()["poll_hours"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_strategy_watch_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.strategy_watch_store'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/strategy_watch_store.py
"""Thread-safe, YAML-backed store of strategy-watch entries + schedule config.

Mirrors credential_store.py: an in-memory dict guarded by a lock, persisted to a
local YAML file with an atomic temp-file replace. One file holds two blocks:
a `watches` list and a `schedule` config.
"""
from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Canonical strategy keys — must match app/routers/stock_scan.py:_SIGNAL_FNS.
VALID_STRATEGIES = {"pullback_ema", "breakout_base", "ma_crossover", "mean_reversion_rsi"}

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "config" / "strategy_watches.yaml"

_DEFAULT_SCHEDULE = {"enabled": False, "mode": "eod", "eod_time": "16:15", "poll_hours": 4}


def _fresh_state() -> dict:
    return {
        "phase": "idle",          # idle | armed
        "direction": None,        # Bullish | Bearish | None
        "entry_price": None,
        "stop_price": None,
        "target_price": None,
        "last_event": None,       # entry | exit_target | exit_stop | reversal
        "last_event_at": None,
    }


class StrategyWatchStore:
    def __init__(self, path: Path | None = _DEFAULT_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._watches: list[dict] = []
        self._schedule: dict = dict(_DEFAULT_SCHEDULE)
        if self._path and self._path.exists():
            self.load()

    # ── persistence ──────────────────────────────────────────────────────────
    def load(self) -> None:
        try:
            raw = yaml.safe_load(self._path.read_text()) or {}
        except (yaml.YAMLError, OSError):
            return
        with self._lock:
            self._watches = list(raw.get("watches") or [])
            self._schedule = {**_DEFAULT_SCHEDULE, **(raw.get("schedule") or {})}

    def save(self) -> None:
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".yaml.tmp")
        with self._lock:
            data = {"schedule": dict(self._schedule),
                    "watches": [dict(w) for w in self._watches]}
        tmp.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
        os.replace(tmp, self._path)

    # ── watches ──────────────────────────────────────────────────────────────
    def list_watches(self) -> list[dict]:
        with self._lock:
            return [dict(w) for w in self._watches]

    def add_watch(self, symbol: str, strategy_key: str,
                  params_override: dict | None = None) -> dict:
        symbol = symbol.strip().upper()
        if strategy_key not in VALID_STRATEGIES:
            raise ValueError(f"unknown strategy: {strategy_key}")
        with self._lock:
            for w in self._watches:
                if w["symbol"] == symbol and w["strategy_key"] == strategy_key:
                    raise ValueError(f"{symbol}/{strategy_key} already watched")
            entry = {
                "id": f"wch_{uuid.uuid4().hex[:12]}",
                "symbol": symbol,
                "strategy_key": strategy_key,
                "params_override": dict(params_override or {}),
                "enabled": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_state": _fresh_state(),
            }
            self._watches.append(entry)
        self.save()
        return dict(entry)

    def add_watches_bulk(self, symbols: list[str], strategy_key: str) -> list[dict]:
        added: list[dict] = []
        for sym in symbols:
            try:
                added.append(self.add_watch(sym, strategy_key))
            except ValueError:
                continue  # skip duplicates / blanks
        return added

    def remove_watch(self, watch_id: str) -> bool:
        with self._lock:
            before = len(self._watches)
            self._watches = [w for w in self._watches if w["id"] != watch_id]
            removed = len(self._watches) < before
        if removed:
            self.save()
        return removed

    def set_enabled(self, watch_id: str, enabled: bool) -> bool:
        with self._lock:
            found = False
            for w in self._watches:
                if w["id"] == watch_id:
                    w["enabled"] = bool(enabled)
                    found = True
                    break
        if found:
            self.save()
        return found

    def update_state(self, watch_id: str, new_state: dict) -> None:
        with self._lock:
            for w in self._watches:
                if w["id"] == watch_id:
                    w["last_state"] = {**_fresh_state(), **new_state}
                    break
        self.save()

    # ── schedule ───────────────────────────────────────────────────────────────
    def get_schedule(self) -> dict:
        with self._lock:
            return dict(self._schedule)

    def set_schedule(self, cfg: dict) -> dict:
        with self._lock:
            self._schedule = {**_DEFAULT_SCHEDULE, **{k: cfg[k] for k in _DEFAULT_SCHEDULE if k in cfg}}
            result = dict(self._schedule)
        self.save()
        return result


_path = Path(os.getenv("BAMENDJOU_STRATEGY_WATCHES_PATH", str(_DEFAULT_PATH)))
strategy_watch_store = StrategyWatchStore(path=_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_strategy_watch_store.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add backend/app/services/strategy_watch_store.py backend/tests/test_strategy_watch_store.py
git commit -m "feat(strategy-watch): YAML-backed watch + schedule store"
```

---

### Task 2: strategy_watch_evaluator — WatchEvent + state machine

**Files:**
- Create: `backend/app/services/strategy_watch_evaluator.py`
- Test: `backend/tests/test_strategy_watch_evaluator.py`

The evaluator runs each enabled watch's strategy on daily bars and emits an event only on a
state *transition*. Strategy functions live in `strategy_engine` and are looked up by key.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_strategy_watch_evaluator.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.strategy_watch_evaluator import WatchEvent, evaluate_all


def _bars(close: float, n: int = 260) -> list[dict]:
    return [{"time": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}",
             "open": close, "high": close + 1, "low": close - 1,
             "close": close, "volume": 1_000_000} for i in range(n)]


def _signal(direction="Bullish", entry=100.0, stop=95.0, target=110.0):
    sig = MagicMock()
    sig.strategy = "pullback_ema"
    sig.direction = direction
    sig.entry_price = entry
    sig.stop_price = stop
    sig.target_price = target
    sig.rr_ratio = 2.0
    return sig


def _watch(phase="idle", **state):
    base = {"phase": phase, "direction": None, "entry_price": None,
            "stop_price": None, "target_price": None, "last_event": None,
            "last_event_at": None}
    base.update(state)
    return {"id": "wch_1", "symbol": "AAPL", "strategy_key": "pullback_ema",
            "params_override": {}, "enabled": True, "last_state": base}


@pytest.mark.asyncio
async def test_idle_with_signal_emits_entry_and_arms():
    store = MagicMock()
    store.list_watches.return_value = [_watch("idle")]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: _signal()}):
        events = await evaluate_all()
    assert len(events) == 1
    assert events[0].event_type == "entry"
    store.update_state.assert_called_once()
    assert store.update_state.call_args[0][1]["phase"] == "armed"


@pytest.mark.asyncio
async def test_armed_below_stop_emits_exit_stop_and_resets():
    store = MagicMock()
    store.list_watches.return_value = [_watch("armed", direction="Bullish",
                                              entry_price=100.0, stop_price=95.0,
                                              target_price=110.0)]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(94.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: None}):
        events = await evaluate_all()
    assert events[0].event_type == "exit_stop"
    assert store.update_state.call_args[0][1]["phase"] == "idle"


@pytest.mark.asyncio
async def test_armed_above_target_emits_exit_target():
    store = MagicMock()
    store.list_watches.return_value = [_watch("armed", direction="Bullish",
                                              entry_price=100.0, stop_price=95.0,
                                              target_price=110.0)]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(111.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: None}):
        events = await evaluate_all()
    assert events[0].event_type == "exit_target"


@pytest.mark.asyncio
async def test_armed_holding_emits_nothing():
    store = MagicMock()
    store.list_watches.return_value = [_watch("armed", direction="Bullish",
                                              entry_price=100.0, stop_price=95.0,
                                              target_price=110.0)]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(102.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: _signal()}):
        events = await evaluate_all()
    assert events == []
    store.update_state.assert_not_called()


@pytest.mark.asyncio
async def test_get_bars_failure_skips_symbol():
    store = MagicMock()
    store.list_watches.return_value = [_watch("idle")]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, side_effect=RuntimeError("db down")), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: _signal()}):
        events = await evaluate_all()
    assert events == []
    store.update_state.assert_not_called()


@pytest.mark.asyncio
async def test_disabled_watch_skipped():
    store = MagicMock()
    w = _watch("idle")
    w["enabled"] = False
    store.list_watches.return_value = [w]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)) as gb, \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: _signal()}):
        events = await evaluate_all()
    assert events == []
    gb.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_strategy_watch_evaluator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.strategy_watch_evaluator'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/strategy_watch_evaluator.py
"""Runs each enabled strategy-watch on daily bars and emits state-transition events.

The state machine (per watch) is the dedup mechanism: it only returns events on a
genuine transition (idle→entry, armed→exit_stop/exit_target, armed→reversal), so a
standing setup never re-alerts. Reversal is wired but dormant — the four current
strategy functions emit Bullish-only signals.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from app.services.historical_store import get_bars
from app.services.strategy_engine import (
    pullback_ema_signal, breakout_base_signal,
    ma_crossover_signal, mean_reversion_rsi_signal,
)
from app.services.strategy_watch_store import strategy_watch_store

logger = logging.getLogger(__name__)

# Keep in sync with app/routers/stock_scan.py:_SIGNAL_FNS.
_SIGNAL_FNS = {
    "pullback_ema":       pullback_ema_signal,
    "breakout_base":      breakout_base_signal,
    "ma_crossover":       ma_crossover_signal,
    "mean_reversion_rsi": mean_reversion_rsi_signal,
}

_HISTORY_DAYS = 730  # ~2 calendar years — enough for the 200-SMA strategy


@dataclass
class WatchEvent:
    watch_id:     str
    symbol:       str
    strategy_key: str
    event_type:   str          # entry | exit_stop | exit_target | reversal
    direction:    str | None
    entry:        float | None
    stop:         float | None
    target:       float | None
    rr_ratio:     float | None
    close:        float
    reason:       str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def evaluate_all() -> list[WatchEvent]:
    """Evaluate every enabled watch; return one WatchEvent per fired transition."""
    events: list[WatchEvent] = []
    end = date.today()
    start = end - timedelta(days=_HISTORY_DAYS)

    for w in strategy_watch_store.list_watches():
        if not w.get("enabled"):
            continue
        symbol = w["symbol"]
        key = w["strategy_key"]
        fn = _SIGNAL_FNS.get(key)
        if fn is None:
            continue
        try:
            bars = await get_bars(symbol, start, end)
        except Exception as exc:
            logger.warning("strategy-watch: get_bars failed for %s — %s", symbol, exc)
            continue
        if not bars:
            continue

        close = float(bars[-1]["close"])
        try:
            signal = fn(bars, **(w.get("params_override") or {}))
        except Exception as exc:
            logger.warning("strategy-watch: %s signal failed for %s — %s", key, symbol, exc)
            continue

        state = dict(w["last_state"])
        phase = state.get("phase", "idle")
        event: WatchEvent | None = None

        if phase == "idle":
            if signal is not None:
                event = WatchEvent(
                    watch_id=w["id"], symbol=symbol, strategy_key=key,
                    event_type="entry", direction=signal.direction,
                    entry=signal.entry_price, stop=signal.stop_price,
                    target=signal.target_price, rr_ratio=round(signal.rr_ratio, 2),
                    close=close,
                    reason=(f"{symbol}: {key} buy setup — entry {signal.entry_price}, "
                            f"stop {signal.stop_price}, target {signal.target_price} "
                            f"(R:R {round(signal.rr_ratio, 2)})"),
                )
                state = {"phase": "armed", "direction": signal.direction,
                         "entry_price": signal.entry_price, "stop_price": signal.stop_price,
                         "target_price": signal.target_price, "last_event": "entry",
                         "last_event_at": _now_iso()}
        elif phase == "armed":
            stop_price = state.get("stop_price")
            target_price = state.get("target_price")
            if stop_price is not None and close <= stop_price:
                event = WatchEvent(
                    watch_id=w["id"], symbol=symbol, strategy_key=key,
                    event_type="exit_stop", direction=state.get("direction"),
                    entry=state.get("entry_price"), stop=stop_price,
                    target=target_price, rr_ratio=None, close=close,
                    reason=f"{symbol}: {key} stop hit at {close} (stop {stop_price})",
                )
                state = {"phase": "idle", "last_event": "exit_stop", "last_event_at": _now_iso()}
            elif target_price is not None and close >= target_price:
                event = WatchEvent(
                    watch_id=w["id"], symbol=symbol, strategy_key=key,
                    event_type="exit_target", direction=state.get("direction"),
                    entry=state.get("entry_price"), stop=stop_price,
                    target=target_price, rr_ratio=None, close=close,
                    reason=f"{symbol}: {key} target hit at {close} (target {target_price})",
                )
                state = {"phase": "idle", "last_event": "exit_target", "last_event_at": _now_iso()}
            elif signal is not None and signal.direction != state.get("direction"):
                event = WatchEvent(
                    watch_id=w["id"], symbol=symbol, strategy_key=key,
                    event_type="reversal", direction=signal.direction,
                    entry=signal.entry_price, stop=signal.stop_price,
                    target=signal.target_price, rr_ratio=round(signal.rr_ratio, 2),
                    close=close,
                    reason=f"{symbol}: {key} reversal to {signal.direction} at {close}",
                )
                state = {"phase": "armed", "direction": signal.direction,
                         "entry_price": signal.entry_price, "stop_price": signal.stop_price,
                         "target_price": signal.target_price, "last_event": "reversal",
                         "last_event_at": _now_iso()}

        if event is not None:
            strategy_watch_store.update_state(w["id"], state)
            events.append(event)

    return events
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_strategy_watch_evaluator.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add backend/app/services/strategy_watch_evaluator.py backend/tests/test_strategy_watch_evaluator.py
git commit -m "feat(strategy-watch): evaluator state machine emitting entry/exit/reversal events"
```

---

### Task 3: evaluate_and_notify — format events and dispatch

**Files:**
- Modify: `backend/app/services/strategy_watch_evaluator.py`
- Test: `backend/tests/test_strategy_watch_evaluator.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_strategy_watch_evaluator.py
from unittest.mock import patch as _patch

from app.services.strategy_watch_evaluator import evaluate_and_notify, _format_event


def test_format_event_builds_subject_and_bodies():
    ev = WatchEvent(
        watch_id="wch_1", symbol="AAPL", strategy_key="pullback_ema",
        event_type="entry", direction="Bullish", entry=100.0, stop=95.0,
        target=110.0, rr_ratio=2.0, close=100.0,
        reason="AAPL: pullback_ema buy setup — entry 100.0, stop 95.0, target 110.0 (R:R 2.0)",
    )
    subject, plain, html = _format_event(ev)
    assert "AAPL" in subject and "Buy setup" in subject
    assert "100.0" in plain
    assert "<" in html  # html body has markup


@pytest.mark.asyncio
async def test_evaluate_and_notify_dispatches_per_event():
    ev = WatchEvent(
        watch_id="wch_1", symbol="AAPL", strategy_key="pullback_ema",
        event_type="entry", direction="Bullish", entry=100.0, stop=95.0,
        target=110.0, rr_ratio=2.0, close=100.0, reason="x",
    )
    with _patch("app.services.strategy_watch_evaluator.evaluate_all",
                new_callable=AsyncMock, return_value=[ev]), \
         _patch("app.services.strategy_watch_evaluator.notify_enabled_channels") as notify:
        result = await evaluate_and_notify()
    assert result == [ev]
    notify.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_strategy_watch_evaluator.py -k "format or notify" -v`
Expected: FAIL with `ImportError: cannot import name 'evaluate_and_notify'`

- [ ] **Step 3: Write minimal implementation**

Add the import near the top of `backend/app/services/strategy_watch_evaluator.py`:

```python
from app.services.notifications.dispatch import notify_enabled_channels
```

Append these functions to `backend/app/services/strategy_watch_evaluator.py`:

```python
_SUBJECT_PREFIX = {
    "entry":       "Buy setup",
    "exit_stop":   "Stop hit",
    "exit_target": "Target hit",
    "reversal":    "Reversal",
}


def _format_event(ev: WatchEvent) -> tuple[str, str, str]:
    """Return (subject, plain_body, html_body) for a watch event."""
    label = _SUBJECT_PREFIX.get(ev.event_type, ev.event_type)
    strat = ev.strategy_key.replace("_", " ").title()
    subject = f"{label}: {ev.symbol} — {strat}"
    lines = [ev.reason, "", f"Strategy: {strat}", f"Last close: {ev.close}"]
    if ev.entry is not None:
        lines.append(f"Entry {ev.entry} · Stop {ev.stop} · Target {ev.target}")
    if ev.rr_ratio is not None:
        lines.append(f"Reward:Risk {ev.rr_ratio}")
    plain = "\n".join(lines)
    html = (f"<h3>{subject}</h3><p>{ev.reason}</p>"
            f"<ul><li>Strategy: {strat}</li><li>Last close: {ev.close}</li>"
            + (f"<li>Entry {ev.entry} · Stop {ev.stop} · Target {ev.target}</li>"
               if ev.entry is not None else "")
            + (f"<li>Reward:Risk {ev.rr_ratio}</li>" if ev.rr_ratio is not None else "")
            + "</ul>")
    return subject, plain, html


async def evaluate_and_notify() -> list[WatchEvent]:
    """Evaluate all watches and dispatch a notification per fired event."""
    events = await evaluate_all()
    for ev in events:
        subject, plain, html = _format_event(ev)
        try:
            notify_enabled_channels(subject, plain, html)
        except Exception:
            logger.error("strategy-watch: notify failed for %s", ev.symbol, exc_info=True)
    return events
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_strategy_watch_evaluator.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add backend/app/services/strategy_watch_evaluator.py backend/tests/test_strategy_watch_evaluator.py
git commit -m "feat(strategy-watch): format events and dispatch Gmail/Telegram notifications"
```

---

### Task 4: strategy_watch_scheduler — EOD + poll cadence loop

**Files:**
- Create: `backend/app/services/strategy_watch_scheduler.py`
- Test: `backend/tests/test_strategy_watch_scheduler.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_strategy_watch_scheduler.py
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.services.strategy_watch_scheduler import StrategyWatchScheduler


@pytest.mark.asyncio
async def test_disabled_schedule_does_not_run():
    sched = StrategyWatchScheduler()
    with patch.object(sched, "_load_schedule",
                      return_value={"enabled": False, "mode": "eod",
                                    "eod_time": "16:15", "poll_hours": 4}), \
         patch("app.services.strategy_watch_scheduler.evaluate_and_notify",
               new_callable=AsyncMock) as run:
        ran = await sched._maybe_run(now=datetime(2026, 6, 12, 17, 0))  # Friday 5pm
    assert ran is False
    run.assert_not_called()


@pytest.mark.asyncio
async def test_eod_runs_once_after_time_then_not_again_same_day():
    sched = StrategyWatchScheduler()
    cfg = {"enabled": True, "mode": "eod", "eod_time": "16:15", "poll_hours": 4}
    with patch.object(sched, "_load_schedule", return_value=cfg), \
         patch("app.services.strategy_watch_scheduler.evaluate_and_notify",
               new_callable=AsyncMock) as run:
        first = await sched._maybe_run(now=datetime(2026, 6, 12, 16, 20))   # after 16:15
        second = await sched._maybe_run(now=datetime(2026, 6, 12, 18, 0))   # same day
    assert first is True
    assert second is False
    assert run.await_count == 1


@pytest.mark.asyncio
async def test_eod_does_not_run_before_time():
    sched = StrategyWatchScheduler()
    cfg = {"enabled": True, "mode": "eod", "eod_time": "16:15", "poll_hours": 4}
    with patch.object(sched, "_load_schedule", return_value=cfg), \
         patch("app.services.strategy_watch_scheduler.evaluate_and_notify",
               new_callable=AsyncMock) as run:
        ran = await sched._maybe_run(now=datetime(2026, 6, 12, 15, 0))  # before 16:15
    assert ran is False
    run.assert_not_called()


@pytest.mark.asyncio
async def test_poll_respects_interval():
    sched = StrategyWatchScheduler()
    cfg = {"enabled": True, "mode": "poll", "eod_time": "16:15", "poll_hours": 2}
    with patch.object(sched, "_load_schedule", return_value=cfg), \
         patch("app.services.strategy_watch_scheduler._market_open", return_value=True), \
         patch("app.services.strategy_watch_scheduler.evaluate_and_notify",
               new_callable=AsyncMock) as run:
        first = await sched._maybe_run(now=datetime(2026, 6, 12, 10, 0))
        too_soon = await sched._maybe_run(now=datetime(2026, 6, 12, 11, 0))   # +1h < 2h
        later = await sched._maybe_run(now=datetime(2026, 6, 12, 12, 30))     # +2.5h
    assert first is True and too_soon is False and later is True
    assert run.await_count == 2


@pytest.mark.asyncio
async def test_poll_skips_when_market_closed():
    sched = StrategyWatchScheduler()
    cfg = {"enabled": True, "mode": "poll", "eod_time": "16:15", "poll_hours": 2}
    with patch.object(sched, "_load_schedule", return_value=cfg), \
         patch("app.services.strategy_watch_scheduler._market_open", return_value=False), \
         patch("app.services.strategy_watch_scheduler.evaluate_and_notify",
               new_callable=AsyncMock) as run:
        ran = await sched._maybe_run(now=datetime(2026, 6, 12, 10, 0))
    assert ran is False
    run.assert_not_called()


def test_run_now_status_shape():
    sched = StrategyWatchScheduler()
    status = sched.get_status()
    assert set(status) >= {"running", "last_run_at", "mode", "enabled"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_strategy_watch_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.strategy_watch_scheduler'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/strategy_watch_scheduler.py
"""Background cadence loop for strategy-watch evaluation.

Modeled on scan_scheduler.ScanScheduler: one asyncio loop that ticks every
_TICK_SECONDS and decides whether to run evaluate_and_notify(), based on the
schedule config (EOD time-of-day, or every N hours during market hours).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time as dtime

from app.services.strategy_watch_evaluator import evaluate_and_notify
from app.services.strategy_watch_store import strategy_watch_store

logger = logging.getLogger(__name__)

_TICK_SECONDS = 300  # 5 minutes


def _market_open(now: datetime | None = None) -> bool:
    """True on a weekday between 09:30 and 16:00 (naive local time; coarse by design)."""
    now = now or datetime.now()
    if now.weekday() >= 5:  # Sat/Sun
        return False
    return dtime(9, 30) <= now.time() <= dtime(16, 0)


class StrategyWatchScheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False
        self._cancelled = False
        self._last_run_at: datetime | None = None
        self._last_eod_run_date: date | None = None

    def _load_schedule(self) -> dict:
        return strategy_watch_store.get_schedule()

    async def _maybe_run(self, now: datetime | None = None) -> bool:
        """Decide and possibly run one evaluation. Returns True if it ran."""
        now = now or datetime.now()
        cfg = self._load_schedule()
        if not cfg.get("enabled"):
            return False

        mode = cfg.get("mode", "eod")
        if mode == "eod":
            hh, mm = (int(x) for x in str(cfg.get("eod_time", "16:15")).split(":"))
            if now.weekday() >= 5:
                return False
            if now.time() < dtime(hh, mm):
                return False
            if self._last_eod_run_date == now.date():
                return False
            await evaluate_and_notify()
            self._last_run_at = now
            self._last_eod_run_date = now.date()
            return True

        # poll mode
        if not _market_open(now):
            return False
        interval_h = float(cfg.get("poll_hours", 4))
        if self._last_run_at is not None:
            elapsed_h = (now - self._last_run_at).total_seconds() / 3600.0
            if elapsed_h < interval_h:
                return False
        await evaluate_and_notify()
        self._last_run_at = now
        return True

    async def _loop(self) -> None:
        while not self._cancelled:
            try:
                await self._maybe_run()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("strategy-watch scheduler tick failed", exc_info=True)
            try:
                await asyncio.sleep(_TICK_SECONDS)
            except asyncio.CancelledError:
                raise
        self._running = False

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._cancelled = False
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._cancelled = True
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._running = False

    async def run_now(self) -> list:
        """Manual trigger — bypasses schedule gates. Returns fired events."""
        events = await evaluate_and_notify()
        self._last_run_at = datetime.now()
        return events

    def get_status(self) -> dict:
        cfg = self._load_schedule()
        return {
            "running": self._running and not self._cancelled,
            "last_run_at": self._last_run_at.isoformat() if self._last_run_at else None,
            "mode": cfg.get("mode"),
            "enabled": cfg.get("enabled"),
        }


strategy_watch_scheduler = StrategyWatchScheduler()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_strategy_watch_scheduler.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add backend/app/services/strategy_watch_scheduler.py backend/tests/test_strategy_watch_scheduler.py
git commit -m "feat(strategy-watch): EOD + poll cadence scheduler loop"
```

---

### Task 5: strategy_watch router — REST CRUD + evaluate + schedule

**Files:**
- Create: `backend/app/routers/strategy_watch.py`
- Test: `backend/tests/test_strategy_watch_router.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_strategy_watch_router.py
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    # Point the store at a temp file so tests don't touch the real config.
    monkeypatch.setenv("BAMENDJOU_STRATEGY_WATCHES_PATH", str(tmp_path / "w.yaml"))
    import importlib
    import app.services.strategy_watch_store as sws
    importlib.reload(sws)
    import app.routers.strategy_watch as r
    importlib.reload(r)
    return create_app()


@pytest.mark.asyncio
async def test_add_list_remove_roundtrip(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        add = await ac.post("/api/strategy-watch/",
                            json={"symbol": "aapl", "strategy_key": "pullback_ema"})
        assert add.status_code == 201
        wid = add.json()["id"]
        lst = await ac.get("/api/strategy-watch/")
        assert lst.status_code == 200 and len(lst.json()) == 1
        rm = await ac.delete(f"/api/strategy-watch/{wid}")
        assert rm.status_code == 200
        lst2 = await ac.get("/api/strategy-watch/")
        assert lst2.json() == []


@pytest.mark.asyncio
async def test_add_unknown_strategy_returns_400(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        resp = await ac.post("/api/strategy-watch/",
                            json={"symbol": "AAPL", "strategy_key": "nope"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_add_duplicate_returns_409(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        await ac.post("/api/strategy-watch/", json={"symbol": "AAPL", "strategy_key": "ma_crossover"})
        dup = await ac.post("/api/strategy-watch/", json={"symbol": "AAPL", "strategy_key": "ma_crossover"})
    assert dup.status_code == 409


@pytest.mark.asyncio
async def test_bulk_add(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        resp = await ac.post("/api/strategy-watch/bulk",
                            json={"symbols": ["AAPL", "MSFT"], "strategy_key": "breakout_base"})
    assert resp.status_code == 201
    assert resp.json()["added"] == 2


@pytest.mark.asyncio
async def test_schedule_get_and_put(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        get = await ac.get("/api/strategy-watch/schedule")
        assert get.json()["mode"] == "eod"
        put = await ac.put("/api/strategy-watch/schedule",
                          json={"enabled": True, "mode": "poll", "eod_time": "16:15", "poll_hours": 3})
        assert put.json()["mode"] == "poll"


@pytest.mark.asyncio
async def test_evaluate_returns_events(app):
    fake_event = {"symbol": "AAPL", "event_type": "entry"}
    with patch("app.routers.strategy_watch.strategy_watch_scheduler.run_now",
               new_callable=AsyncMock) as run:
        run.return_value = [type("E", (), fake_event)()]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            resp = await ac.post("/api/strategy-watch/evaluate")
    assert resp.status_code == 200
    assert resp.json()["fired"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_strategy_watch_router.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.routers.strategy_watch'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/routers/strategy_watch.py
"""REST API for strategy-watch entries + schedule + manual evaluation."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.strategy_watch_store import strategy_watch_store
from app.services.strategy_watch_scheduler import strategy_watch_scheduler

router = APIRouter(prefix="/api/strategy-watch", tags=["strategy-watch"])


class AddWatch(BaseModel):
    symbol: str
    strategy_key: str
    params_override: dict | None = None


class BulkAdd(BaseModel):
    symbols: list[str]
    strategy_key: str


class EnabledPatch(BaseModel):
    enabled: bool


class ScheduleIn(BaseModel):
    enabled: bool
    mode: str = Field(pattern="^(eod|poll)$")
    eod_time: str = "16:15"
    poll_hours: int = Field(default=4, ge=1, le=24)


@router.get("/")
async def list_watches() -> list[dict]:
    return strategy_watch_store.list_watches()


@router.post("/", status_code=201)
async def add_watch(body: AddWatch) -> dict:
    try:
        return strategy_watch_store.add_watch(body.symbol, body.strategy_key, body.params_override)
    except ValueError as exc:
        msg = str(exc)
        raise HTTPException(status_code=409 if "already watched" in msg else 400, detail=msg)


@router.post("/bulk", status_code=201)
async def bulk_add(body: BulkAdd) -> dict:
    if body.strategy_key not in __import__("app.services.strategy_watch_store",
                                           fromlist=["VALID_STRATEGIES"]).VALID_STRATEGIES:
        raise HTTPException(status_code=400, detail=f"unknown strategy: {body.strategy_key}")
    added = strategy_watch_store.add_watches_bulk(body.symbols, body.strategy_key)
    return {"added": len(added), "watches": added}


@router.delete("/{watch_id}")
async def remove_watch(watch_id: str) -> dict:
    if not strategy_watch_store.remove_watch(watch_id):
        raise HTTPException(status_code=404, detail="watch not found")
    return {"removed": watch_id}


@router.patch("/{watch_id}")
async def set_enabled(watch_id: str, body: EnabledPatch) -> dict:
    if not strategy_watch_store.set_enabled(watch_id, body.enabled):
        raise HTTPException(status_code=404, detail="watch not found")
    return {"id": watch_id, "enabled": body.enabled}


@router.get("/schedule")
async def get_schedule() -> dict:
    return strategy_watch_store.get_schedule()


@router.put("/schedule")
async def set_schedule(body: ScheduleIn) -> dict:
    return strategy_watch_store.set_schedule(body.model_dump())


@router.post("/evaluate")
async def evaluate_now() -> dict:
    events = await strategy_watch_scheduler.run_now()
    serialized = [asdict(e) if is_dataclass(e) else getattr(e, "__dict__", {}) for e in events]
    return {"fired": len(events), "events": serialized}


@router.get("/status")
async def status() -> dict:
    return strategy_watch_scheduler.get_status()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_strategy_watch_router.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add backend/app/routers/strategy_watch.py backend/tests/test_strategy_watch_router.py
git commit -m "feat(strategy-watch): REST router for CRUD, schedule, and evaluate"
```

---

### Task 6: Register router + start/stop scheduler in main.py

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add the router import**

In `backend/app/main.py`, next to the other router imports (near `from app.routers.ingestion import router as ingestion_router` at line ~40), add:

```python
from app.routers.strategy_watch import router as strategy_watch_router
```

- [ ] **Step 2: Register the router**

In `create_app()`, with the other `app.include_router(...)` calls (after `app.include_router(stock_scan_router)` at line ~153), add:

```python
    app.include_router(strategy_watch_router)
```

- [ ] **Step 3: Start the scheduler in lifespan startup**

In the `lifespan` function, just before `yield` (after the startup catch-up block ending near line 91), add:

```python
    # ── Strategy-watch scheduler ──────────────────────────────────────────
    try:
        from app.services.strategy_watch_scheduler import strategy_watch_scheduler
        await strategy_watch_scheduler.start()
    except Exception as _exc:
        logger.warning("strategy_watch_scheduler startup failed: %s", _exc)
```

- [ ] **Step 4: Stop the scheduler in lifespan shutdown**

In the shutdown section (after `yield`, near the `_isched.shutdown()` block at line ~95), add:

```python
    try:
        from app.services.strategy_watch_scheduler import strategy_watch_scheduler
        await strategy_watch_scheduler.stop()
    except Exception:
        pass
```

- [ ] **Step 5: Verify the app imports and the route is registered**

Run:
```bash
cd "F:/Git/GitHub/Trading assistant/backend"
python -c "from app.main import create_app; app = create_app(); print([r.path for r in app.routes if 'strategy-watch' in getattr(r, 'path', '')])"
```
Expected: a non-empty list including `/api/strategy-watch/` and `/api/strategy-watch/schedule`.

- [ ] **Step 6: Run the full backend suite**

Run:
```bash
cd "F:/Git/GitHub/Trading assistant/backend"
python -m pytest -q
```
Expected: all pass (previous 524 + the new strategy-watch tests), 3 skipped, 0 failures.

- [ ] **Step 7: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add backend/app/main.py
git commit -m "feat(strategy-watch): register router and run scheduler in app lifespan"
```

---

### Task 7: Frontend API methods + Zustand store

**Files:**
- Modify: `frontend/lib/api.ts`
- Create: `frontend/lib/strategyWatchStore.ts`

- [ ] **Step 1: Add types and API methods to `frontend/lib/api.ts`**

Add these interfaces near the top exports (after the `DataSourceInfo` interface around line 30):

```typescript
export interface StrategyWatchState {
  phase: 'idle' | 'armed';
  direction: 'Bullish' | 'Bearish' | null;
  entry_price: number | null;
  stop_price: number | null;
  target_price: number | null;
  last_event: 'entry' | 'exit_stop' | 'exit_target' | 'reversal' | null;
  last_event_at: string | null;
}

export interface StrategyWatch {
  id: string;
  symbol: string;
  strategy_key: string;
  params_override: Record<string, unknown>;
  enabled: boolean;
  created_at: string;
  last_state: StrategyWatchState;
}

export interface StrategyWatchSchedule {
  enabled: boolean;
  mode: 'eod' | 'poll';
  eod_time: string;
  poll_hours: number;
}
```

Add these methods inside the `api` object (alongside the existing methods):

```typescript
  getStrategyWatches: () =>
    get<StrategyWatch[]>('/api/strategy-watch/'),
  addStrategyWatch: (symbol: string, strategy_key: string) =>
    post<StrategyWatch>('/api/strategy-watch/', { symbol, strategy_key }),
  addStrategyWatchesBulk: (symbols: string[], strategy_key: string) =>
    post<{ added: number; watches: StrategyWatch[] }>('/api/strategy-watch/bulk', { symbols, strategy_key }),
  removeStrategyWatch: (id: string) =>
    del(`/api/strategy-watch/${id}`),
  setStrategyWatchEnabled: (id: string, enabled: boolean) =>
    patch<{ id: string; enabled: boolean }>(`/api/strategy-watch/${id}`, { enabled }),
  getStrategyWatchSchedule: () =>
    get<StrategyWatchSchedule>('/api/strategy-watch/schedule'),
  setStrategyWatchSchedule: (cfg: StrategyWatchSchedule) =>
    put<StrategyWatchSchedule>('/api/strategy-watch/schedule', cfg),
  evaluateStrategyWatches: () =>
    post<{ fired: number; events: unknown[] }>('/api/strategy-watch/evaluate', {}),
```

- [ ] **Step 2: Add `patch` and `put` helpers to `frontend/lib/api.ts` if missing**

Check the top of the file for `patch`/`put` helpers. The file already has `get`, `post`, `del`. If `put`/`patch` are not present, add them next to `post` (around line 24):

```typescript
async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}
```

- [ ] **Step 3: Create `frontend/lib/strategyWatchStore.ts`**

```typescript
'use client';

import { create } from 'zustand';
import { api, type StrategyWatch, type StrategyWatchSchedule } from '@/lib/api';

interface StrategyWatchStore {
  watches: StrategyWatch[];
  schedule: StrategyWatchSchedule | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  add: (symbol: string, strategyKey: string) => Promise<void>;
  addBulk: (symbols: string[], strategyKey: string) => Promise<void>;
  remove: (id: string) => Promise<void>;
  setEnabled: (id: string, enabled: boolean) => Promise<void>;
  saveSchedule: (cfg: StrategyWatchSchedule) => Promise<void>;
  evaluateNow: () => Promise<number>;
}

export const useStrategyWatchStore = create<StrategyWatchStore>((set, get) => ({
  watches: [],
  schedule: null,
  loading: false,
  error: null,

  refresh: async () => {
    set({ loading: true, error: null });
    try {
      const [watches, schedule] = await Promise.all([
        api.getStrategyWatches(),
        api.getStrategyWatchSchedule(),
      ]);
      set({ watches, schedule, loading: false });
    } catch (e) {
      set({ error: (e as Error).message, loading: false });
    }
  },

  add: async (symbol, strategyKey) => {
    try {
      await api.addStrategyWatch(symbol, strategyKey);
      await get().refresh();
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },

  addBulk: async (symbols, strategyKey) => {
    try {
      await api.addStrategyWatchesBulk(symbols, strategyKey);
      await get().refresh();
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },

  remove: async (id) => {
    await api.removeStrategyWatch(id);
    await get().refresh();
  },

  setEnabled: async (id, enabled) => {
    await api.setStrategyWatchEnabled(id, enabled);
    await get().refresh();
  },

  saveSchedule: async (cfg) => {
    const saved = await api.setStrategyWatchSchedule(cfg);
    set({ schedule: saved });
  },

  evaluateNow: async () => {
    const result = await api.evaluateStrategyWatches();
    await get().refresh();
    return result.fired;
  },
}));
```

- [ ] **Step 4: Typecheck**

Run:
```bash
cd "F:/Git/GitHub/Trading assistant/frontend"
npm run typecheck
```
Expected: 0 errors.

- [ ] **Step 5: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add frontend/lib/api.ts frontend/lib/strategyWatchStore.ts
git commit -m "feat(strategy-watch): frontend API methods and Zustand store"
```

---

### Task 8: Strategy Watch page + nav link

**Files:**
- Create: `frontend/app/(frame)/strategy-watch/page.tsx`
- Create: `frontend/app/(frame)/strategy-watch/page.module.css`
- Modify: the nav component (discover in Step 1)

- [ ] **Step 1: Find the nav component to add the link**

Run:
```bash
cd "F:/Git/GitHub/Trading assistant/frontend"
grep -rn "watchlist\|portfolio\|NavRail\|href=\"/" components/organisms/ app/\(frame\)/ --include="*.tsx" | grep -i "nav\|href" | head -20
```
Identify the navigation list (likely `components/organisms/NavRail/index.tsx`). Note the existing
link pattern (icon + label + href) — you will mirror it in Step 4.

- [ ] **Step 2: Create `frontend/app/(frame)/strategy-watch/page.module.css`**

```css
.page { padding: 24px; display: flex; flex-direction: column; gap: 20px; }
.section { border: 1px solid var(--border-subtle); border-radius: 6px; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
.row { display: flex; gap: 8px; align-items: center; }
.input, .select {
  background: var(--bg-surface); color: var(--text-primary);
  border: 1px solid var(--border-subtle); border-radius: 4px; padding: 6px 8px; font-size: 13px;
}
.btn {
  background: var(--bg-surface); color: var(--text-primary);
  border: 1px solid var(--border-subtle); border-radius: 4px; padding: 6px 12px;
  font-size: 13px; cursor: pointer;
}
.btn:hover { border-color: var(--text-dim); }
.table { width: 100%; border-collapse: collapse; font-size: 13px; }
.table th, .table td { text-align: left; padding: 8px; border-bottom: 1px solid var(--border-subtle); }
.pill { display: inline-flex; padding: 2px 8px; border-radius: 3px; font-size: 11px; font-weight: 500; }
.pillIdle    { background: color-mix(in srgb, var(--text-dim) 14%, var(--bg-surface)); color: var(--text-dim); }
.pillArmed   { background: color-mix(in srgb, var(--pass) 14%, var(--bg-surface)); color: var(--pass); }
.error { color: var(--reject); font-size: 12px; }
```

- [ ] **Step 3: Create `frontend/app/(frame)/strategy-watch/page.tsx`**

```tsx
'use client';

import { useEffect, useState } from 'react';
import { useStrategyWatchStore } from '@/lib/strategyWatchStore';
import type { StrategyWatchSchedule } from '@/lib/api';
import styles from './page.module.css';

const STRATEGIES = [
  { key: 'pullback_ema',       label: 'Pullback EMA' },
  { key: 'breakout_base',      label: 'Breakout Base' },
  { key: 'ma_crossover',       label: 'MA Crossover' },
  { key: 'mean_reversion_rsi', label: 'Mean Reversion RSI' },
] as const;

function phasePill(phase: string) {
  if (phase === 'armed') return <span className={`${styles.pill} ${styles.pillArmed}`}>In trade / setup live</span>;
  return <span className={`${styles.pill} ${styles.pillIdle}`}>Waiting</span>;
}

export default function StrategyWatchPage() {
  const { watches, schedule, error, refresh, add, addBulk, remove, setEnabled, saveSchedule, evaluateNow } =
    useStrategyWatchStore();

  const [symbol, setSymbol] = useState('');
  const [strategyKey, setStrategyKey] = useState(STRATEGIES[0].key);
  const [bulkSymbols, setBulkSymbols] = useState('');
  const [bulkStrategy, setBulkStrategy] = useState(STRATEGIES[0].key);
  const [evalMsg, setEvalMsg] = useState('');

  useEffect(() => { refresh(); }, [refresh]);

  const onAdd = async () => {
    if (!symbol.trim()) return;
    await add(symbol.trim(), strategyKey);
    setSymbol('');
  };

  const onBulkAdd = async () => {
    const syms = bulkSymbols.split(',').map((s) => s.trim()).filter(Boolean);
    if (syms.length === 0) return;
    await addBulk(syms, bulkStrategy);
    setBulkSymbols('');
  };

  const onEvaluate = async () => {
    setEvalMsg('Evaluating…');
    const fired = await evaluateNow();
    setEvalMsg(`Done — ${fired} alert(s) fired.`);
  };

  const updateSched = (patch: Partial<StrategyWatchSchedule>) => {
    if (!schedule) return;
    saveSchedule({ ...schedule, ...patch });
  };

  return (
    <div className={styles.page}>
      <h1>Strategy Watch</h1>
      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.section}>
        <strong>Add a watch</strong>
        <div className={styles.row}>
          <input className={styles.input} placeholder="Symbol (e.g. AAPL)"
                 value={symbol} onChange={(e) => setSymbol(e.target.value)} />
          <select className={styles.select} value={strategyKey}
                  onChange={(e) => setStrategyKey(e.target.value as typeof strategyKey)}>
            {STRATEGIES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
          <button className={styles.btn} onClick={onAdd}>Add</button>
        </div>
        <div className={styles.row}>
          <input className={styles.input} placeholder="Bulk: AAPL, MSFT, GOOG"
                 value={bulkSymbols} onChange={(e) => setBulkSymbols(e.target.value)} />
          <select className={styles.select} value={bulkStrategy}
                  onChange={(e) => setBulkStrategy(e.target.value as typeof bulkStrategy)}>
            {STRATEGIES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
          <button className={styles.btn} onClick={onBulkAdd}>Bulk add</button>
        </div>
      </div>

      <div className={styles.section}>
        <strong>Schedule</strong>
        {schedule && (
          <div className={styles.row}>
            <label><input type="checkbox" checked={schedule.enabled}
                          onChange={(e) => updateSched({ enabled: e.target.checked })} /> Enabled</label>
            <select className={styles.select} value={schedule.mode}
                    onChange={(e) => updateSched({ mode: e.target.value as 'eod' | 'poll' })}>
              <option value="eod">End of day</option>
              <option value="poll">Every N hours</option>
            </select>
            {schedule.mode === 'eod' ? (
              <input className={styles.input} type="time" value={schedule.eod_time}
                     onChange={(e) => updateSched({ eod_time: e.target.value })} />
            ) : (
              <input className={styles.input} type="number" min={1} max={24} value={schedule.poll_hours}
                     onChange={(e) => updateSched({ poll_hours: Number(e.target.value) })} />
            )}
            <button className={styles.btn} onClick={onEvaluate}>Evaluate now</button>
            <span>{evalMsg}</span>
          </div>
        )}
      </div>

      <div className={styles.section}>
        <strong>Watched ({watches.length})</strong>
        <table className={styles.table}>
          <thead><tr><th>Symbol</th><th>Strategy</th><th>State</th><th>Enabled</th><th></th></tr></thead>
          <tbody>
            {watches.map((w) => (
              <tr key={w.id}>
                <td>{w.symbol}</td>
                <td>{STRATEGIES.find((s) => s.key === w.strategy_key)?.label ?? w.strategy_key}</td>
                <td>{phasePill(w.last_state.phase)}</td>
                <td><input type="checkbox" checked={w.enabled}
                           onChange={(e) => setEnabled(w.id, e.target.checked)} /></td>
                <td><button className={styles.btn} onClick={() => remove(w.id)}>Remove</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Add the nav link**

In the nav component found in Step 1, add an entry mirroring the existing link pattern, pointing
to `/strategy-watch` with label "Strategy Watch". Example (adapt to the actual pattern — if links
are objects in an array, add `{ href: '/strategy-watch', label: 'Strategy Watch' }`; if they are
JSX `<NavLink>` elements, add one matching the others):

```tsx
{ href: '/strategy-watch', label: 'Strategy Watch' }
```

- [ ] **Step 5: Typecheck**

Run:
```bash
cd "F:/Git/GitHub/Trading assistant/frontend"
npm run typecheck
```
Expected: 0 errors.

- [ ] **Step 6: Visual verification**

Start the dev server (`npm run dev`, port 3001) and open `/strategy-watch`. Confirm: the page
renders, you can add a watch (it appears in the table), toggle enabled, set the schedule, and
click "Evaluate now" (it returns a fired count without error). Capture a screenshot for the user.

- [ ] **Step 7: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add "frontend/app/(frame)/strategy-watch/" frontend/components
git commit -m "feat(strategy-watch): management page and nav link"
```

---

## Self-Review

**Spec coverage:**
- ✅ Persisted (symbol, strategy) watch entries + bulk add — Task 1 (`add_watch`, `add_watches_bulk`).
- ✅ Entry / exit_stop / exit_target / reversal state machine, dedup via transitions — Task 2.
- ✅ Notification through existing Gmail/Telegram dispatcher — Task 3 (`notify_enabled_channels`).
- ✅ EOD + intraday-poll cadence, started in lifespan — Tasks 4 + 6.
- ✅ REST CRUD + bulk + schedule + evaluate-now + status — Task 5.
- ✅ Frontend page (add one, bulk apply, state pills, schedule, evaluate now) + store + API — Tasks 7 + 8.
- ✅ Error handling: get_bars failure skips symbol (Task 2 test), unknown strategy 400 / dup 409 (Task 5 tests), scheduler tick survives exceptions (Task 4 loop).
- ✅ Deferred real-time streaming + dormant reversal — documented in spec; reversal branch present but inactive for Bullish-only signals.

**Placeholder scan:** No TBD/TODO. Task 8 Step 4 intentionally adapts to the discovered nav pattern (the only place exact code can't be pre-written without reading the nav file); the example covers both array-of-objects and JSX-element cases.

**Type consistency:** `StrategyWatchStore` methods (`add_watch`, `add_watches_bulk`, `remove_watch`, `set_enabled`, `update_state`, `get_schedule`, `set_schedule`) match across Tasks 1/5. `WatchEvent` fields (`watch_id, symbol, strategy_key, event_type, direction, entry, stop, target, rr_ratio, close, reason`) match across Tasks 2/3/5. `_SIGNAL_FNS` keys identical to `stock_scan.py`. Schedule shape `{enabled, mode, eod_time, poll_hours}` identical across store, scheduler, router, and frontend. Frontend `StrategyWatch`/`StrategyWatchState`/`StrategyWatchSchedule` mirror the backend JSON.

**Out of scope (correctly deferred):** auto-execution from alerts, options-contract watching, real-time streaming, multi-user.
