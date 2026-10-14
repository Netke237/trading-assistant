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
from collections.abc import Callable
from contextlib import contextmanager
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

_DEFAULT_SCHEDULE = {"enabled": False, "mode": "eod", "eod_time": "16:30", "poll_hours": 4, "sustain_minutes": 0}


def _fresh_state() -> dict:
    return {
        "phase": "idle",          # idle | armed
        "direction": None,        # Bullish | Bearish | None
        "entry_price": None,
        "stop_price": None,
        "target_price": None,
        "last_event": None,       # entry | exit_target | exit_stop | time_stop | reversal
        "last_event_at": None,
    }


def _primary_model(trigger_def: object) -> object:
    if not isinstance(trigger_def, dict):
        return None
    primary = trigger_def.get("primary")
    return primary.get("model") if isinstance(primary, dict) else None


def _migrate_hmm_intraday_intervals(watches: list[dict]) -> list[tuple]:
    """A4f: a composite HMM_intraday watch stored with a non-intraday interval
    (the dialog saved '1D' while displaying '5m') fetched ~38 daily bars, below
    the HMM's minimum, and never fired. Move it to '5min' -- the chart spelling
    (W2-INTERVAL) of what the user saw -- and keep the old value in `interval_migrated_from`. Returns (id, symbol, old)
    for each migrated entry; idempotent."""
    from app.data.market import is_intraday_interval
    migrated = []
    for w in watches:
        if w.get("watch_type") != "composite" or _primary_model(w.get("trigger_def")) != "HMM_intraday":
            continue
        old = w.get("interval")
        if is_intraday_interval(old):
            continue
        w["interval"] = "5min"
        w["interval_migrated_from"] = old
        migrated.append((w.get("id"), w.get("symbol"), old))
    return migrated


def _migrate_interval_spellings(watches: list[dict]) -> list[tuple]:
    """W2-INTERVAL (decisions FOLLOWUPS-QUEUE-2026-09-25 (1), P4B-FOLLOWUPS-2026-09-26
    (2)): a watch stored on a short interval spelling ('5m', '15m', ...) moves to
    the chart's spelling ('5min', ...), the one the evaluator fetches with now
    that P4b's read-side map is gone. Only `interval` changes. Returns
    (id, symbol, old, new) for each migrated entry; idempotent."""
    from app.data.market import _CHART_SPELLING
    migrated = []
    for w in watches:
        old = w.get("interval")
        if not isinstance(old, str) or old not in _CHART_SPELLING:
            continue
        w["interval"] = _CHART_SPELLING[old]
        migrated.append((w.get("id"), w.get("symbol"), old, w["interval"]))
    return migrated


class StrategyWatchStore:
    def __init__(self, path: Path | None = _DEFAULT_PATH) -> None:
        self._path = path
        self._lock = threading.RLock()
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
            migrated = _migrate_hmm_intraday_intervals(self._watches)
            respelled = _migrate_interval_spellings(self._watches)
            self._schedule = {**_DEFAULT_SCHEDULE, **(raw.get("schedule") or {})}
        if not migrated and not respelled:
            return
        listing = ", ".join(
            [f"{i} {s} {old!r}" for i, s, old in migrated]
            + [f"{i} {s} {old!r}->{new!r}" for i, s, old, new in respelled]
        )
        if migrated:
            logger.warning(
                "A4f: migrated %d HMM_intraday composite watch(es) from a non-intraday interval "
                "to '5min' (on that interval they could not fire): [%s]", len(migrated),
                ", ".join(f"{i} {s} {old!r}" for i, s, old in migrated),
            )
        if respelled:
            logger.warning(
                "W2-INTERVAL: migrated %d watch(es) to the chart's interval spelling: [%s]",
                len(respelled), ", ".join(f"{i} {s} {old!r}->{new!r}" for i, s, old, new in respelled),
            )
        # load() runs at import time of the module-level store and must never
        # raise: a failed write would stop the backend from booting (A4f plan F-1).
        # The migration stays in memory; the next mutation's save() persists it.
        try:
            self.save()
        except Exception as exc:
            logger.error(
                "A4f: could not persist the interval migration (%s); in memory only, "
                "retried on the next save or reload: [%s]", exc, listing,
            )

    def save(self) -> None:
        if not self._path:
            return
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".yaml.tmp")
            data = {"schedule": dict(self._schedule),
                    "watches": [dict(w) for w in self._watches]}
            tmp.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
            os.replace(tmp, self._path)

    @contextmanager
    def _mutation(self):
        """Keep rollback and persistence under the same writer lock."""
        with self._lock:
            watches = [dict(w) for w in self._watches]
            schedule = dict(self._schedule)
            try:
                yield
            except Exception:
                self._watches = watches
                self._schedule = schedule
                raise

    # ── watches ──────────────────────────────────────────────────────────────
    def list_watches(self) -> list[dict]:
        with self._lock:
            return [dict(w) for w in self._watches]

    def add_watch(self, symbol: str, strategy_key: str,
                  params_override: dict | None = None,
                  direction: str = "Bullish",
                  params_horizon: str | None = None) -> dict:
        """``params_horizon`` (a tuned horizon, STOCKS-HORIZON-T1 H7) picks the
        parameter profile the watch evaluates with and its hold: the watch
        stores ``hold_max_days = HOLD_MAX_DAYS[params_horizon]`` (None without
        a horizon) and time-stops once armed that many days."""
        from app.services.horizon_profiles import HOLD_MAX_DAYS
        symbol = symbol.strip().upper()
        if strategy_key not in VALID_STRATEGIES:
            raise ValueError(f"unknown strategy: {strategy_key}")
        if params_horizon is not None and params_horizon not in HOLD_MAX_DAYS:
            raise ValueError(f"unknown params horizon: {params_horizon}")
        with self._mutation():
            for w in self._watches:
                # Composites carry no strategy_key and can never duplicate a
                # strategy watch; indexing one raised KeyError (a 500, and a
                # half-applied bulk add).
                if w.get("watch_type") == "composite":
                    continue
                if (w["symbol"] == symbol and w.get("strategy_key") == strategy_key
                        and w.get("direction", "Bullish") == direction):
                    raise ValueError(f"{symbol}/{strategy_key}/{direction} already watched")
            entry = {
                "id": f"wch_{uuid.uuid4().hex[:12]}",
                "symbol": symbol,
                "strategy_key": strategy_key,
                "direction": direction,
                "params_override": dict(params_override or {}),
                "params_horizon": params_horizon,
                "hold_max_days": HOLD_MAX_DAYS[params_horizon] if params_horizon is not None else None,
                "enabled": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_state": _fresh_state(),
            }
            self._watches.append(entry)
            self.save()
        return dict(entry)

    def add_watches_bulk(self, symbols: list[str], strategy_key: str,
                         direction: str = "Bullish",
                         params_horizon: str | None = None) -> list[dict]:
        added: list[dict] = []
        for sym in symbols:
            try:
                added.append(self.add_watch(sym, strategy_key, direction=direction,
                                            params_horizon=params_horizon))
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
        from app.data.market import chart_interval
        interval = chart_interval(interval)   # W2-INTERVAL: stored in the chart's spelling
        if _primary_model(trigger_def) == "HMM_intraday":
            from app.data.market import is_intraday_interval
            if not is_intraday_interval(interval):
                raise ValueError(
                    f"HMM_intraday needs an intraday interval (e.g. 5min, 15min, 1h), got {interval!r}"
                )
        symbol = symbol.strip().upper()
        with self._mutation():
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
        with self._mutation():
            before = len(self._watches)
            self._watches = [w for w in self._watches if w["id"] != watch_id]
            removed = len(self._watches) < before
            if removed:
                self.save()
        return removed

    def set_enabled(self, watch_id: str, enabled: bool, *,
                    on_reenable: Callable[[dict], dict] | None = None) -> bool:
        """Persist enable and an optional re-enable state transform together.

        The transform must not mutate its input. A failed save restores the
        watch in memory and propagates the error to the caller.
        """
        with self._lock:
            for index, w in enumerate(self._watches):
                if w["id"] == watch_id:
                    previous = dict(w)
                    try:
                        if enabled and not w.get("enabled", True) and on_reenable is not None:
                            w["last_state"] = on_reenable(dict(w.get("last_state") or {}))
                        w["enabled"] = bool(enabled)
                        self.save()
                    except Exception:
                        self._watches[index] = previous
                        raise
                    return True
        return False

    def update_state(self, watch_id: str, new_state: dict) -> None:
        with self._mutation():
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
        with self._mutation():
            self._schedule = {**_DEFAULT_SCHEDULE, **{k: cfg[k] for k in _DEFAULT_SCHEDULE if k in cfg}}
            result = dict(self._schedule)
            self.save()
        return result


_path = Path(os.getenv("BAMENDJOU_STRATEGY_WATCHES_PATH", str(_DEFAULT_PATH)))
strategy_watch_store = StrategyWatchStore(path=_path)
