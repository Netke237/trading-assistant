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
    mean_reversion_bb_signal,
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
    "mean_reversion_bb":  mean_reversion_bb_signal,
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


async def evaluate_all(sustain_minutes: int = 0) -> list[WatchEvent]:
    """Evaluate every enabled watch; return one WatchEvent per fired transition.

    sustain_minutes: if > 0, a newly-appeared entry signal must remain present
    for at least this many minutes (checked across scheduler ticks, tracked in
    each watch's last_state.pending_entry_since) before the entry event fires.
    0 preserves the original instant-fire behavior. This is a single
    schedule-level setting (not per-watch) — contrast with the standard
    chart-alert rule builder's per-condition sustain_minutes.
    """
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
            adopted = get_active(key, wdir)
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
                if sustain_minutes:
                    pending_since_str = state.get("pending_entry_since")
                    if pending_since_str is None:
                        strategy_watch_store.update_state(
                            w["id"], {**state, "pending_entry_since": _now_iso()},
                        )
                        continue
                    pending_since = datetime.fromisoformat(pending_since_str)
                    elapsed_min = (datetime.now(timezone.utc) - pending_since).total_seconds() / 60.0
                    if elapsed_min < sustain_minutes:
                        continue
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
            elif state.get("pending_entry_since"):
                # Signal disappeared before the sustain window elapsed — reset the clock.
                strategy_watch_store.update_state(
                    w["id"], {k2: v for k2, v in state.items() if k2 != "pending_entry_since"},
                )
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

    # ── Composite watches ──────────────────────────────────────────────────────
    for w in strategy_watch_store.list_watches():
        if not w.get("enabled"):
            continue
        if w.get("watch_type") != "composite":
            continue
        symbol = w["symbol"]
        trigger_def = w.get("trigger_def") or {}
        wdir = w.get("direction", "Bullish")
        model = (trigger_def.get("primary") or {}).get("model", "OMM")
        try:
            bars = await get_bars(symbol, start, end)
        except Exception as exc:
            logger.warning("composite-watch: get_bars failed for %s — %s", symbol, exc)
            continue
        if not bars:
            continue
        bars_intraday: list[dict] = []
        needs_intraday = model == "HMM_intraday" or "mean_reversion_vwap" in (trigger_def.get("strategy_confirmations") or [])
        if needs_intraday:
            interval = w.get("interval", "15m")
            try:
                from app.data.market import fetch_intraday_candles
                bars_intraday = fetch_intraday_candles(symbol, interval=interval, days=55)
            except Exception as exc:
                logger.warning("composite-watch: intraday fetch failed for %s — %s", symbol, exc)
        try:
            from app.services.composite_trigger_evaluator import evaluate_scheduled, describe_match, format_composite_reason
            fired = evaluate_scheduled(symbol, trigger_def, bars, bars_intraday)
        except Exception as exc:
            logger.warning("composite-watch: evaluate_scheduled failed for %s — %s", symbol, exc)
            continue

        sustain_min = trigger_def.get("sustain_minutes")
        watch_state = dict(w.get("last_state") or {})
        if sustain_min:
            try:
                if fired:
                    pending_since_str = watch_state.get("pending_entry_since")
                    if pending_since_str is None:
                        strategy_watch_store.update_state(
                            w["id"], {**watch_state, "pending_entry_since": _now_iso()},
                        )
                        continue
                    pending_since = datetime.fromisoformat(pending_since_str)
                    elapsed_min = (datetime.now(timezone.utc) - pending_since).total_seconds() / 60.0
                    if elapsed_min < sustain_min:
                        continue
                elif watch_state.get("pending_entry_since"):
                    strategy_watch_store.update_state(
                        w["id"], {k: v for k, v in watch_state.items() if k != "pending_entry_since"},
                    )
            except (ValueError, TypeError) as exc:
                logger.warning("composite-watch sustain-state parse failed for %s, treating as not-sustained: %s", symbol, exc)
                fired = False

        if not fired:
            continue
        close = float(bars[-1]["close"])
        try:
            _detail = describe_match(
                trigger_def, bars_daily=bars, bars_intraday=bars_intraday, symbol=symbol, direction=wdir,
            )
            _reason = format_composite_reason((trigger_def.get("primary") or {}).get("to_state"), _detail)
        except Exception as exc:
            logger.warning("composite-watch: describe_match failed for %s — %s", symbol, exc)
            _reason = f"{symbol}: composite Markov trigger fired"
        event = WatchEvent(
            watch_id=w["id"], symbol=symbol, strategy_key="composite",
            event_type="entry", direction=wdir,
            entry=None, stop=None, target=None, rr_ratio=None,
            close=close,
            reason=_reason,
        )
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


async def evaluate_and_notify(sustain_minutes: int = 0) -> list[WatchEvent]:
    """Evaluate all watches and dispatch a notification per fired event."""
    events = await evaluate_all(sustain_minutes)
    for ev in events:
        subject, plain, html = _format_event(ev)
        try:
            notify_enabled_channels(subject, plain, html)
        except Exception:
            logger.error("strategy-watch: notify failed for %s", ev.symbol, exc_info=True)
    return events
