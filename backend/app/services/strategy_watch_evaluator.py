# backend/app/services/strategy_watch_evaluator.py
"""Runs each enabled strategy-watch on daily bars and emits state-transition events.

The state machine (per watch) is the dedup mechanism: it only returns events on a
genuine transition (idle→entry, armed→exit_stop/exit_target, armed→reversal), so a
standing setup never re-alerts. Each watch's direction (Bullish/Bearish) is fixed
at creation, so a reversal can't be detected by comparing the primary signal
(always evaluated in the watch's own fixed direction) against the armed state's
direction -- those can never disagree. Instead, while armed (and neither stop nor
target has hit), the evaluator also evaluates the signal function for the
OPPOSITE direction, using that direction's own tuned params (get_active). If the
opposite-direction signal fires, that's a genuine reversal and the watch re-arms
in the new direction.
"""
from __future__ import annotations

import asyncio
import html as html_lib
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from app.services.historical_store import get_bars
from app.services.scheduling_tz import MARKET_TZ
from app.services.strategy_engine import (
    pullback_ema_signal, breakout_base_signal,
    ma_crossover_signal, mean_reversion_rsi_signal,
    mean_reversion_bb_signal,
)
from app.services.strategy_watch_store import strategy_watch_store
from app.services.strategy_param_store import get_active, get_exit
from app.services.notifications.dispatch import load_notification_config, notify_enabled_channels

logger = logging.getLogger(__name__)

# Keep in sync with app/routers/stock_scan.py:_SIGNAL_FNS.
_SIGNAL_FNS = {
    "pullback_ema":       pullback_ema_signal,
    "breakout_base":      breakout_base_signal,
    "ma_crossover":       ma_crossover_signal,
    "mean_reversion_rsi": mean_reversion_rsi_signal,
    "mean_reversion_bb":  mean_reversion_bb_signal,
}

# Human-readable strategy names for notification text — naive .title() on the
# snake_case key produces awkward results ("Pullback Ema", "Rsi" instead of
# "RSI"), so these are spelled out explicitly.
_STRATEGY_LABELS = {
    "pullback_ema":       "Pullback EMA",
    "breakout_base":      "Breakout Base",
    "ma_crossover":       "MA Crossover",
    "mean_reversion_rsi": "Mean Reversion (RSI)",
    "mean_reversion_bb":  "Mean Reversion (Bollinger Bands)",
    "composite":          "Composite Trigger",
}


def _strategy_label(key: str) -> str:
    return _STRATEGY_LABELS.get(key, key.replace("_", " ").title())

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


@dataclass
class _Transition:
    """A fired event plus the watch state it moves to. The state is written only
    by _commit -- after delivery on the notify path (P4b, D3)."""
    event:     WatchEvent
    watch_id:  str
    new_state: dict


async def _eval_strategy_watch(
    w: dict, start: date, end: date, sustain_minutes: int,
) -> _Transition | None:
    """One strategy watch. Non-event state writes (the sustain clock) happen here;
    the event's own state change is returned, not written."""
    symbol = w["symbol"]
    key = w.get("strategy_key")
    fn = _SIGNAL_FNS.get(key)
    if fn is None:
        return None
    try:
        bars = await get_bars(symbol, start, end)
    except Exception as exc:
        logger.warning("strategy-watch: get_bars failed for %s — %s", symbol, exc)
        return None
    if not bars:
        return None

    close = float(bars[-1]["close"])
    wdir = w.get("direction", "Bullish")
    try:
        adopted = {**get_exit(key), **get_active(key, wdir)}
        params_override = w.get("params_override") or {}
        adopted.update(params_override)  # params_override wins
        signal = fn(bars, direction=wdir, **adopted)
    except Exception as exc:
        logger.warning("strategy-watch: %s signal failed for %s — %s", key, symbol, exc)
        return None

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
                    return None
                try:
                    pending_since = datetime.fromisoformat(pending_since_str)
                    elapsed_min = (datetime.now(timezone.utc) - pending_since).total_seconds() / 60.0
                    sustained = elapsed_min >= sustain_minutes
                except (ValueError, TypeError):
                    # Corrupted pending_entry_since -- treat as not-yet-sustained
                    # (restart the clock) rather than raising, which would abort
                    # evaluation for every remaining watch in this tick.
                    logger.warning(
                        "strategy-watch: corrupted pending_entry_since for %s, "
                        "restarting sustain clock", w["id"],
                    )
                    strategy_watch_store.update_state(
                        w["id"], {**state, "pending_entry_since": _now_iso()},
                    )
                    return None
                if not sustained:
                    return None
            event = WatchEvent(
                watch_id=w["id"], symbol=symbol, strategy_key=key,
                event_type="entry", direction=signal.direction,
                entry=signal.entry_price, stop=signal.stop_price,
                target=signal.target_price, rr_ratio=round(signal.rr_ratio, 2),
                close=close,
                reason=(f"{symbol}: {_strategy_label(key)} "
                        f"{'short' if signal.direction == 'Bearish' else 'long'} setup — "
                        f"entry {signal.entry_price}, "
                        f"stop {signal.stop_price}, target {signal.target_price} "
                        f"(reward-to-risk {round(signal.rr_ratio, 2)})"),
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
                reason=f"{symbol}: {_strategy_label(key)} stop hit at {close} (stop {stop_price})",
            )
            state = {"phase": "idle", "last_event": "exit_stop", "last_event_at": _now_iso()}
        elif target_hit:
            event = WatchEvent(
                watch_id=w["id"], symbol=symbol, strategy_key=key,
                event_type="exit_target", direction=state.get("direction"),
                entry=state.get("entry_price"), stop=stop_price,
                target=target_price, rr_ratio=None, close=close,
                reason=f"{symbol}: {_strategy_label(key)} target hit at {close} (target {target_price})",
            )
            state = {"phase": "idle", "last_event": "exit_target", "last_event_at": _now_iso()}
        else:
            # NOTE: no hysteresis/cooldown here -- if both directions' signal
            # functions are "sticky" (true for several consecutive days, common
            # for trend/breakout signals), a watch can in principle whipsaw
            # Bullish<->Bearish on consecutive ticks, notifying each time.
            # Accepted as a known limitation of this fix (making reversal
            # reachable, not adding debounce) -- revisit if this proves noisy.
            opposite_dir = "Bearish" if sdir == "Bullish" else "Bullish"
            try:
                opp_params = {**get_exit(key), **get_active(key, opposite_dir)}
                opp_params.update(params_override)
                opp_signal = fn(bars, direction=opposite_dir, **opp_params)
            except Exception as exc:
                logger.warning("strategy-watch: %s reversal signal failed for %s — %s",
                                key, symbol, exc)
                opp_signal = None
            if opp_signal is not None:
                event = WatchEvent(
                    watch_id=w["id"], symbol=symbol, strategy_key=key,
                    event_type="reversal", direction=opposite_dir,
                    entry=opp_signal.entry_price, stop=opp_signal.stop_price,
                    target=opp_signal.target_price, rr_ratio=round(opp_signal.rr_ratio, 2),
                    close=close,
                    reason=f"{symbol}: {_strategy_label(key)} reversal to {opposite_dir} at {close}",
                )
                state = {"phase": "armed", "direction": opposite_dir,
                         "entry_price": opp_signal.entry_price, "stop_price": opp_signal.stop_price,
                         "target_price": opp_signal.target_price, "last_event": "reversal",
                         "last_event_at": _now_iso()}

    if event is None:
        return None
    return _Transition(event=event, watch_id=w["id"], new_state=state)


async def _eval_composite_watch(
    w: dict, start: date, end: date, now_ts: float, now_dt: datetime,
) -> _Transition | None:
    """One composite watch. Non-event state writes (sustain clock, armed -> idle
    re-arm) happen here; the entry's armed state is returned, not written."""
    symbol = w["symbol"]
    trigger_def = w.get("trigger_def") or {}
    wdir = w.get("direction", "Bullish")
    model = (trigger_def.get("primary") or {}).get("model", "OMM")
    try:
        bars = await get_bars(symbol, start, end)
    except Exception as exc:
        logger.warning("composite-watch: get_bars failed for %s — %s", symbol, exc)
        return None
    # Lazy imports: tests patch these at their source modules.
    from app.data.market import completed_bars_for_interval, fetch_intraday_candles, normalize_interval
    from app.services.composite_trigger_evaluator import (
        _strategy_bar_type, completed_daily_rows, intraday_history_days, watch_fetch_interval,
    )
    # Every consumer of the daily bars (OMM/HMM_daily, rsi/bb, VWAP daily)
    # reads completed sessions only: get_bars can hold today's forming bar.
    bars = completed_daily_rows(bars, now_dt)
    if not bars:
        return None
    interval = w.get("interval") or "1D"          # the store's default
    fetch_iv = watch_fetch_interval(interval)     # D5: the chart spelling a rule reads
    confirmations = trigger_def.get("strategy_confirmations") or []
    vwap_intraday = (
        "mean_reversion_vwap" in confirmations
        and _strategy_bar_type("mean_reversion_vwap", fetch_iv) == "intraday"
    )
    bars_intraday: list[dict] = []
    if model == "HMM_intraday" or vwap_intraday:
        try:
            raw = fetch_intraday_candles(
                symbol, interval=fetch_iv, days=intraday_history_days(fetch_iv),
            )
            # A4c + VWAP-CONFIRMATION-LIKE-REGIME-MODELS: the HMM fit AND the
            # VWAP confirmation read COMPLETED bars of the watch's interval.
            bars_intraday = completed_bars_for_interval(raw, fetch_iv, now=now_ts)
        except Exception as exc:
            logger.warning("composite-watch: intraday fetch failed for %s — %s", symbol, exc)
    # 1D/1W (D7): VWAP runs the daily variant on the completed daily bars.
    vwap_daily = bars if normalize_interval(fetch_iv) in ("daily", "weekly") else None
    try:
        from app.services.composite_trigger_evaluator import evaluate_scheduled, describe_match, format_composite_reason
        fired = evaluate_scheduled(
            symbol, trigger_def, bars, bars_intraday,
            regime_bars_intraday=bars_intraday if model == "HMM_intraday" else None,
            unknown_as_none=True, interval=fetch_iv, bars_vwap_daily=vwap_daily,
        )
    except Exception as exc:
        logger.warning("composite-watch: evaluate_scheduled failed for %s — %s", symbol, exc)
        return None
    if fired is None:
        # No reading (feed or model failure inside evaluate_scheduled): the
        # state is left exactly as it was -- an armed watch must not re-arm
        # on a blip and re-send the same entry when the feed recovers.
        logger.warning("composite-watch: no reading for %s this run; state unchanged", symbol)
        return None

    watch_state = dict(w.get("last_state") or {})
    # ONCE PER ENTRY (Kenneth, 2026-09-25). evaluate_scheduled is
    # level-triggered -- true on every run while the regime holds -- so
    # without this a composite re-sent the same "setup" alert every run.
    # armed = already alerted for the current entry; it re-arms (-> idle)
    # only when the condition goes false. Fetch/evaluate failures above
    # `continue` with the state untouched, so an outage neither re-arms nor
    # fires.
    if watch_state.get("phase", "idle") == "armed":
        if not fired:
            strategy_watch_store.update_state(
                w["id"],
                {**{k: v for k, v in watch_state.items() if k != "pending_entry_since"},
                 "phase": "idle"},
            )
        return None

    sustain_min = trigger_def.get("sustain_minutes")
    if isinstance(sustain_min, (int, float)) and sustain_min < 0:
        sustain_min = 0
    if sustain_min:
        try:
            if fired:
                pending_since_str = watch_state.get("pending_entry_since")
                if pending_since_str is None:
                    strategy_watch_store.update_state(
                        w["id"], {**watch_state, "pending_entry_since": _now_iso()},
                    )
                    return None
                pending_since = datetime.fromisoformat(pending_since_str)
                elapsed_min = (datetime.now(timezone.utc) - pending_since).total_seconds() / 60.0
                if elapsed_min < sustain_min:
                    return None
            elif watch_state.get("pending_entry_since"):
                strategy_watch_store.update_state(
                    w["id"], {k: v for k, v in watch_state.items() if k != "pending_entry_since"},
                )
        except (ValueError, TypeError) as exc:
            logger.warning("composite-watch sustain-state parse failed for %s, treating as not-sustained: %s", symbol, exc)
            fired = False

    if not fired:
        return None
    close = float(bars[-1]["close"])
    try:
        _detail = describe_match(
            trigger_def, bars_daily=bars, bars_intraday=bars_intraday, symbol=symbol, direction=wdir,
            interval=fetch_iv, bars_vwap_daily=vwap_daily,
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
    return _Transition(
        event=event, watch_id=w["id"],
        new_state={**{k: v for k, v in watch_state.items() if k != "pending_entry_since"},
                   "phase": "armed", "direction": wdir,
                   "last_event": "entry", "last_event_at": _now_iso()},
    )


async def _collect(sustain_minutes: int = 0, now_ts: float | None = None) -> list[_Transition]:
    """Evaluate every enabled watch; one _Transition per fired event.

    Q17 (Kenneth, 2026-09-25): each watch is isolated -- an exception from one
    watch is logged and skips only that watch, never the rest of the run.
    """
    transitions: list[_Transition] = []
    # One instant for the run's completed-bar judgements (tests inject it; the
    # sustain clock keeps datetime.now, unchanged).
    if now_ts is None:
        now_ts = time.time()
    now_dt = datetime.fromtimestamp(now_ts, MARKET_TZ)
    end = date.today()
    start = end - timedelta(days=_HISTORY_DAYS)

    for w in strategy_watch_store.list_watches():
        if not w.get("enabled"):
            continue
        # Strategy watches only -- composites have their own loop below and
        # carry no strategy_key (add_composite_watch never writes one). Reading
        # w["strategy_key"] on one raised KeyError and aborted the WHOLE tick, so
        # no watch of either kind was ever notified while a composite was enabled.
        if w.get("watch_type") == "composite":
            continue
        try:
            t = await _eval_strategy_watch(w, start, end, sustain_minutes)
        except Exception:
            logger.error("strategy-watch: watch %s failed, skipped this run", w.get("id"), exc_info=True)
            continue
        if t is not None:
            transitions.append(t)

    # ── Composite watches ──────────────────────────────────────────────────────
    for w in strategy_watch_store.list_watches():
        if not w.get("enabled"):
            continue
        if w.get("watch_type") != "composite":
            continue
        try:
            t = await _eval_composite_watch(w, start, end, now_ts, now_dt)
        except Exception:
            logger.error("composite-watch: watch %s failed, skipped this run", w.get("id"), exc_info=True)
            continue
        if t is not None:
            transitions.append(t)

    return transitions


def _commit(t: _Transition) -> None:
    """Write one transition's state. A failed write is logged and does not stop
    the remaining commits (which would re-send already-delivered alerts)."""
    try:
        strategy_watch_store.update_state(t.watch_id, t.new_state)
    except Exception:
        logger.error("strategy-watch: state write failed for %s", t.watch_id, exc_info=True)


async def evaluate_all(sustain_minutes: int = 0, now_ts: float | None = None) -> list[WatchEvent]:
    """Evaluate every enabled watch; return one WatchEvent per fired transition.

    sustain_minutes: if > 0, a newly-appeared entry signal must remain present
    for at least this many minutes (checked across scheduler ticks, tracked in
    each watch's last_state.pending_entry_since) before the entry event fires.
    0 preserves the original instant-fire behavior. This is a single
    schedule-level setting (not per-watch) — contrast with the standard
    chart-alert rule builder's per-condition sustain_minutes.
    """
    transitions = await _collect(sustain_minutes, now_ts)
    for t in transitions:
        _commit(t)
    return [t.event for t in transitions]


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
    strat = _strategy_label(ev.strategy_key)
    subject = f"{label}: {ev.symbol} — {strat}"
    lines = [ev.reason, "", f"Strategy: {strat}", f"Last close: {ev.close}"]
    if ev.entry is not None:
        lines.append(f"Entry {ev.entry} · Stop {ev.stop} · Target {ev.target}")
    if ev.rr_ratio is not None:
        lines.append(f"Reward-to-risk ratio: {ev.rr_ratio}")
    plain = "\n".join(lines)
    # Telegram's HTML parse_mode only recognizes a small tag allowlist (b/i/u/s/
    # a/code/pre/blockquote) -- NOT h3/p/ul/li or any other block tag. This body
    # is dispatched to Telegram via notify_enabled_channels() -> send_telegram()
    # with parse_mode='HTML'; an unsupported tag makes the Bot API reject the
    # whole message with a 400 that dispatch.py's error handling swallows into a
    # log line with no user-visible signal -- so every strategy-watch Telegram
    # alert was silently failing to send. Line breaks must be plain '\n', same
    # as chart_alerts.py/alert_notifier.py's notification builders. Free-text
    # values (symbol/reason are effectively internal-built today, but nothing
    # enforces that) are escaped for the same reason those two files escape
    # theirs -- a stray '<' or '&' would trigger the identical failure mode.
    html = (
        f"<b>{html_lib.escape(subject)}</b>\n"
        f"{html_lib.escape(ev.reason)}\n\n"
        f"Strategy: {html_lib.escape(strat)}\n"
        f"Last close: {ev.close}\n"
        + (f"Entry {ev.entry} · Stop {ev.stop} · Target {ev.target}\n" if ev.entry is not None else "")
        + (f"Reward-to-risk ratio: {ev.rr_ratio}\n" if ev.rr_ratio is not None else "")
    )
    return subject, plain, html


def _any_channel_enabled() -> bool:
    """True when at least one notification channel is enabled (D3).

    Same reader notify_enabled_channels uses. A null or non-dict block counts as
    disabled; only a genuine read error returns True -- an unreadable config
    must not silently commit alerts that were never delivered."""
    try:
        cfg = load_notification_config()
        if not isinstance(cfg, dict):
            return False

        def _enabled(block: object) -> bool:
            return isinstance(block, dict) and bool(block.get("enabled"))

        return _enabled(cfg.get("gmail")) or _enabled(cfg.get("telegram"))
    except Exception:
        logger.error("strategy-watch: notification config unreadable; gating state on delivery", exc_info=True)
        return True


# One evaluate_and_notify at a time: the scheduler tick and a manual /evaluate
# (run_now) could otherwise both see a watch idle and both send its entry.
# Created lazily per running loop -- an asyncio.Lock that once waited is bound
# to its loop, and pytest runs each test on a fresh one.
_lock: asyncio.Lock | None = None
_lock_loop: asyncio.AbstractEventLoop | None = None


def _run_lock() -> asyncio.Lock:
    global _lock, _lock_loop
    loop = asyncio.get_running_loop()
    if _lock is None or _lock_loop is not loop:
        _lock = asyncio.Lock()
        _lock_loop = loop
    return _lock


async def evaluate_and_notify(sustain_minutes: int = 0, now_ts: float | None = None) -> list[WatchEvent]:
    """Evaluate all watches, send one notification per fired event, and commit
    each event's state only once it was delivered (open_questions[3], D3).

    Undelivered with a channel enabled: the state is kept, so the next run
    fires (and sends) the same transition again. No channel enabled at all:
    nothing could ever deliver, so the state is committed as before.
    Returns every fired event, delivered or not."""
    async with _run_lock():
        transitions = await _collect(sustain_minutes, now_ts)
        any_channel = _any_channel_enabled()
        for t in transitions:
            ev = t.event
            subject, plain, html = _format_event(ev)
            try:
                delivered = await notify_enabled_channels(subject, plain, html)
            except Exception:
                logger.error("strategy-watch: notify failed for %s", ev.symbol, exc_info=True)
                delivered = False
            if delivered or not any_channel:
                _commit(t)
            else:
                logger.warning(
                    "strategy-watch: %s %s for %s not delivered; state kept, retries next run",
                    ev.strategy_key, ev.event_type, ev.symbol,
                )
        return [t.event for t in transitions]
