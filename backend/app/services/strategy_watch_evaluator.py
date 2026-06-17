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
from app.services.strategy_param_store import get_active
from app.services.notifications.dispatch import notify_enabled_channels

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
        wdir = w.get("direction", "Bullish")
        try:
            adopted = get_active(key)
            params_override = w.get("params_override") or {}
            adopted.update(params_override)  # params_override wins
            signal = fn(bars, direction=wdir, **adopted)
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
                    reason=(f"{symbol}: {key} "
                            f"{'short' if signal.direction == 'Bearish' else 'long'} setup — "
                            f"entry {signal.entry_price}, "
                            f"stop {signal.stop_price}, target {signal.target_price} "
                            f"(R:R {round(signal.rr_ratio, 2)})"),
                )
                state = {"phase": "armed", "direction": signal.direction,
                         "entry_price": signal.entry_price, "stop_price": signal.stop_price,
                         "target_price": signal.target_price, "last_event": "entry",
                         "last_event_at": _now_iso()}
        elif phase == "armed":
            sdir = state.get("direction", "Bullish")
            stop_price = state.get("stop_price")
            target_price = state.get("target_price")
            stop_hit = (
                (close <= stop_price) if sdir == "Bullish" else (close >= stop_price)
            ) if stop_price is not None else False
            target_hit = (
                (close >= target_price) if sdir == "Bullish" else (close <= target_price)
            ) if target_price is not None else False
            if stop_hit:
                event = WatchEvent(
                    watch_id=w["id"], symbol=symbol, strategy_key=key,
                    event_type="exit_stop", direction=state.get("direction"),
                    entry=state.get("entry_price"), stop=stop_price,
                    target=target_price, rr_ratio=None, close=close,
                    reason=f"{symbol}: {key} stop hit at {close} (stop {stop_price})",
                )
                state = {"phase": "idle", "last_event": "exit_stop", "last_event_at": _now_iso()}
            elif target_hit:
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


_SUBJECT_PREFIX = {
    "entry":       "Buy setup",
    "exit_stop":   "Stop hit",
    "exit_target": "Target hit",
    "reversal":    "Reversal",
}


def _format_event(ev: WatchEvent) -> tuple[str, str, str]:
    """Return (subject, plain_body, html_body) for a watch event."""
    if ev.event_type == "entry":
        label = f"{'Short' if ev.direction == 'Bearish' else 'Long'} setup"
    else:
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
