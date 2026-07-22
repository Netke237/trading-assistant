# backend/app/services/strategy_watch_store.py
"""Thread-safe, YAML-backed store of strategy-watch entries + schedule config.

Mirrors credential_store.py: an in-memory dict guarded by a lock, persisted to a
local YAML file with an atomic temp-file replace. One file holds two blocks:
a `watches` list and a `schedule` config.
"""
from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Canonical strategy keys for strategy watches — must match strategy_watch_evaluator._SIGNAL_FNS.
# IMPORTANT: Do NOT add 'breakout_setup' or 'mean_reversion_vwap' here:
#   breakout_setup returns SetupSignal (no entry/stop/target) — not watchable.
#   mean_reversion_vwap is intraday-only — watch evaluator uses daily bars.
VALID_STRATEGIES = {
    "pullback_ema",
    "breakout_base",
    "ma_crossover",
    "mean_reversion_rsi",
    "mean_reversion_bb",    # SWS-1: added
}

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "config" / "strategy_watches.yaml"

_DEFAULT_SCHEDULE = {"enabled": False, "mode": "eod", "eod_time": "16:15", "poll_hours": 4, "sustain_minutes": 0}


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
        except (yaml.YAMLError, OSError) as exc:
            logger.warning("strategy_watch_store: failed to load %s — %s", self._path, exc)
            return
        with self._lock:
            self._watches = list(raw.get("watches") or [])
            # Forward-compatibility migration: ensure all watch entries have required fields.
            for w in self._watches:
                w.setdefault("watch_type", "strategy")
                w.setdefault("trigger_def", None)
                w.setdefault("interval", "1D")
                w.setdefault("last_state", _fresh_state())
                w.setdefault("enabled", True)
                w.setdefault("direction", "Bullish")
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
                  params_override: dict | None = None,
                  direction: str = "Bullish") -> dict:
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
                "direction": direction,
                "params_override": dict(params_override or {}),
                "enabled": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_state": _fresh_state(),
            }
            self._watches.append(entry)
        self.save()
        return dict(entry)

    def add_watches_bulk(self, symbols: list[str], strategy_key: str,
                         direction: str = "Bullish") -> list[dict]:
        added: list[dict] = []
        for sym in symbols:
            try:
                added.append(self.add_watch(sym, strategy_key, direction=direction))
            except ValueError:
                continue  # skip duplicates / blanks
        return added

    def add_composite_watch(
        self,
        symbol: str,
        trigger_def: dict,
        direction: str = "Bullish",
        interval: str = "1D",
    ) -> dict:
        """Create a composite (Markov + N-of-M confirmation) watch entry.

        Does NOT check VALID_STRATEGIES — composite watches are not tied to a signal function.
        Does NOT deduplicate — multiple composite watches per symbol with different trigger
        definitions are allowed. Each call creates a new entry with a unique ID.
        """
        symbol = symbol.strip().upper()
        with self._lock:
            entry = {
                "id": f"cwch_{uuid.uuid4().hex[:12]}",
                "watch_type": "composite",
                "symbol": symbol,
                "direction": direction,
                "interval": interval,
                "trigger_def": dict(trigger_def),
                "enabled": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_state": _fresh_state(),
            }
            self._watches.append(entry)
        self.save()
        return dict(entry)

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
