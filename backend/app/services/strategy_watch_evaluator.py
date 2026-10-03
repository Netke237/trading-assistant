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
from dataclasses import dataclass, field, fields
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
from app.services.notifications.dispatch import notify_enabled_channels, read_notification_config

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
    by _commit -- after delivery on the notify path (P4b, D3).

    committed/pending: the snapshot the watch was evaluated with (see
    _effective_view) -- the queue a not-yet-delivered event is appended to."""
    event:     WatchEvent
    watch_id:  str
    new_state: dict
    committed: dict = field(default_factory=dict)
    pending:   list = field(default_factory=list)


# ── Undelivered events (WATCH-UNDELIVERED-EVENT-RESEND) ───────────────────────
# An event that could not be delivered is stored, oldest first, in
# last_state["pending_events"] as {"event", "new_state", "fired_at"}, and re-sent
# (labelled "Delayed") on the next run BEFORE re-evaluation -- even if the
# condition no longer holds. The watch's own state fields are the COMMITTED state
# (before the oldest undelivered event); evaluation runs from the EFFECTIVE state
# (the newest pending event's new_state), so a newer event queues behind it
# (decision WATCH-RESEND-QUEUE-2026-09-27). Disabled watches keep theirs.
_QUEUE_CAP = 20

# ── Skip on proof (WATCH-RESEND-HEAD-OF-LINE piece 1) ─────────────────────────
# A queued head that keeps failing would block every later alert of its watch.
# Each failed run as the head is counted on the head entry ("failures",
# "last_failure_at"), at most once per _FAILURE_SPACING. Once it has failed
# _UNDELIVERABLE_AFTER counted runs, the next alert of the watch is sent as a
# probe; if that is delivered the head is dropped at once (ERROR) -- never
# retried, never delivered out of order. A failed probe is an outage and drops
# nothing (decisions WATCH-RESEND-HEAD-OF-LINE-2026-10-01, WATCH-RESEND-SPLIT-2026-10-02).
_FAILURE_SPACING = timedelta(hours=1)
_UNDELIVERABLE_AFTER = 3
_DROP_LOG = ("strategy-watch: undeliverable alert dropped for %s after %d failed runs; "
             "a later alert was delivered: %s")
_PRICE_KEYS = ("entry_price", "stop_price", "target_price")
_EVENT_FLOATS = ("entry", "stop", "target", "rr_ratio", "close")


def _write(watch_id: str, state: dict) -> None:
    """Every evaluator state write. A failed write is logged and never raised, so
    one watch's failed save cannot stop another watch's alert. update_state
    changes the in-memory state before saving, so the next run still sees it."""
    try:
        strategy_watch_store.update_state(watch_id, state)
    except Exception:
        logger.error("strategy-watch: state write failed for %s", watch_id, exc_info=True)


def _split_state(last_state: dict) -> tuple[dict, list]:
    """(committed state, pending events) of a stored last_state."""
    pending = last_state.get("pending_events")
    committed = {k: v for k, v in last_state.items() if k != "pending_events"}
    return committed, (list(pending) if isinstance(pending, list) else [])


_REENABLE_MAX_AGE = timedelta(days=5)


async def set_enabled_and_expire(watch_id: str, enabled: bool, *, store=None) -> int | None:
    """Re-enable under the evaluation lock, committing the expired queue prefix.

    Both PATCH routes pass their imported store, including in reload-based
    fixtures. Failed persistence propagates without reporting an expiration.
    """
    store = strategy_watch_store if store is None else store
    async with _run_lock():
        dropped = []
        cutoff = _utcnow() - _REENABLE_MAX_AGE

        def expire(state: dict) -> dict:
            committed, pending = _split_state(state)
            for entry in pending:
                parsed = _parse_entry(entry)
                fired_at = entry.get("fired_at") if isinstance(entry, dict) else None
                at = None
                if isinstance(fired_at, str):
                    try:
                        at = datetime.fromisoformat(fired_at)
                        if at.tzinfo is None:
                            at = at.replace(tzinfo=timezone.utc)
                    except ValueError:
                        pass
                if parsed is not None and at is not None and at >= cutoff:
                    break
                dropped.append(fired_at)
                if parsed is not None:
                    committed = dict(parsed[1])
            if not dropped:
                return state
            rest = pending[len(dropped):]
            return {**committed, "pending_events": rest} if rest else committed

        if not store.set_enabled(watch_id, enabled, on_reenable=expire):
            return None
        for fired_at in dropped:
            logger.warning("strategy-watch: expired queued alert on re-enable for %s (fired_at=%r)",
                           watch_id, fired_at)
        return len(dropped)


def _effective_view(w: dict) -> dict:
    """The watch as the evaluators see it: last_state = the effective state; the
    committed state and the queue ride along under private keys, read only by
    _write_effective and _collect. Raises on a malformed tail (skips the watch)."""
    committed, pending = _split_state(dict(w.get("last_state") or {}))
    effective = committed
    if pending:
        tail = pending[-1].get("new_state") if isinstance(pending[-1], dict) else None
        if not isinstance(tail, dict):
            raise ValueError(f"malformed pending event on {w.get('id')}")
        effective = dict(tail)
    return {**w, "last_state": effective, "_committed": committed, "_pending": pending}


def _write_effective(w: dict, state: dict) -> None:
    """A non-event state write (sustain clock, composite re-arm). With events
    pending it lands in the newest one's new_state; committed state and queue
    are untouched."""
    pending = w.get("_pending") or []
    if not pending:
        _write(w["id"], state)
        return
    _write(w["id"], {**w.get("_committed", {}),
                     "pending_events": pending[:-1] + [{**pending[-1], "new_state": state}]})


def _num(v: object) -> float | None:
    return None if v is None else float(v)


def _event_to_dict(ev: WatchEvent) -> dict:
    """Plain YAML-safe values: a numpy scalar would be dumped as a python tag
    that yaml.safe_load rejects, and the store would then load no watches."""
    d = {f.name: getattr(ev, f.name) for f in fields(WatchEvent)}
    for k in _EVENT_FLOATS:
        d[k] = _num(d[k])
    for k in ("watch_id", "symbol", "strategy_key", "event_type", "reason"):
        d[k] = str(d[k])
    d["direction"] = None if d["direction"] is None else str(d["direction"])
    return d


def _plain_state(state: dict) -> dict:
    out = dict(state)
    for k in _PRICE_KEYS:
        if k in out:
            out[k] = _num(out[k])
    return out


def _pending_entry(t: "_Transition") -> dict:
    return {"event": _event_to_dict(t.event), "new_state": _plain_state(t.new_state),
            "fired_at": _now_iso()}


def _parse_entry(entry: object) -> tuple[WatchEvent, dict, str] | None:
    """(event, new_state, fired_at) of a stored entry, or None if malformed."""
    try:
        ev_d, new_state = entry["event"], entry["new_state"]
        if not isinstance(ev_d, dict) or not isinstance(new_state, dict):
            return None
        ev = WatchEvent(**{f.name: ev_d[f.name] for f in fields(WatchEvent)})
        return ev, new_state, str(entry.get("fired_at") or "")
    except (KeyError, TypeError, AttributeError):
        return None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _failures(entry: dict) -> int:
    """The entry's counted failures; anything but a non-negative int reads as 0."""
    v = entry.get("failures")
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def _failure_counts(entry: dict, now: datetime) -> bool:
    """True when a failure now is _FAILURE_SPACING after the last counted one.
    Absent, unparseable or future (clock jump) last_failure_at: counts; naive = UTC."""
    last = entry.get("last_failure_at")
    if not isinstance(last, str):
        return True
    try:
        at = datetime.fromisoformat(last)
    except ValueError:
        return True
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    if at > now:
        return True
    return now - at >= _FAILURE_SPACING


def _queue(t: "_Transition") -> None:
    """Store t's event behind the watch's pending ones (oldest first, capped)."""
    committed, pending = dict(t.committed), t.pending + [_pending_entry(t)]
    while len(pending) > _QUEUE_CAP:
        dropped = pending.pop(0)
        ns = dropped.get("new_state") if isinstance(dropped, dict) else None
        if isinstance(ns, dict):
            committed = ns
        logger.error("strategy-watch: undelivered alert dropped for %s, queue full (%d): %s",
                     t.watch_id, _QUEUE_CAP,
                     (dropped.get("event") or {}).get("reason") if isinstance(dropped, dict) else dropped)
    _write(t.watch_id, {**committed, "pending_events": pending})


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
                    _write_effective(
                        w, {**state, "pending_entry_since": _now_iso()},
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
                    _write_effective(
                        w, {**state, "pending_entry_since": _now_iso()},
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
            _write_effective(
                w, {k2: v for k2, v in state.items() if k2 != "pending_entry_since"},
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


def _bar_label(bar: dict) -> str:
    """'<Eastern time> (close X)' for the bar momentum judged."""
    t = bar.get("time")
    if isinstance(t, int) and not isinstance(t, bool):
        when = datetime.fromtimestamp(t, MARKET_TZ).strftime("%Y-%m-%d %H:%M ET")
    else:
        when = str(t)
    return f"{when} (close {bar.get('close')})"


async def _composite_watch_momentum(w: dict, trigger_def: dict, symbol: str, fetch_iv: str):
    """COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD 3.4 / Q5: the bars a composite
    watch's momentum confirmations judge -- the alert's own chart candles (the
    rule's cache key and refresh policy), regular-session bars only on intraday
    (Q11), ending at rows[-2] (the newest row is treated as forming, as the
    rule's closed candle). None = not read (no momentum confirmation, the fetch
    failed, or fewer than 2 rows); evaluate_scheduled's count decides whether
    that is no reading or a definite False. No new watch state."""
    from app.services.composite_trigger_evaluator import MomentumInput, has_momentum
    if not has_momentum(trigger_def):
        return None
    from app.data.chart_cache import get_intraday_with_fetched_at
    from app.data.market import _INTERVAL_COMPLETION_SECONDS, normalize_interval
    from app.services.indicator_compute import momentum_session_bars
    span = _INTERVAL_COMPLETION_SECONDS.get(normalize_interval(fetch_iv))
    try:
        rows, _fetched = await get_intraday_with_fetched_at(
            symbol, fetch_iv, refresh_on_close=True,
            max_age=float(span) if span is not None else None,
        )
    except Exception as exc:
        logger.warning("composite-watch: momentum chart fetch failed for %s [%s] — %s", symbol, fetch_iv, exc)
        return None
    rows = momentum_session_bars(rows or [], fetch_iv)
    if len(rows) < 2:
        return None
    return MomentumInput(rows[:-1], fetch_iv, str(w["id"]))


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
        _strategy_bar_type, completed_daily_rows, intraday_history_days,
    )
    # Every consumer of the daily bars (OMM/HMM_daily, rsi/bb, VWAP daily)
    # reads completed sessions only: get_bars can hold today's forming bar.
    bars = completed_daily_rows(bars, now_dt)
    if not bars:
        return None
    # W2-INTERVAL: the store holds the chart's spelling (migrated on load, and
    # every write maps it), so the stored interval is the one a rule reads.
    fetch_iv = w.get("interval") or "1D"          # the store's default
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
    momentum = await _composite_watch_momentum(w, trigger_def, symbol, fetch_iv)
    try:
        from app.services.composite_trigger_evaluator import (
            describe_match, evaluate_scheduled, format_composite_reason, momentum_sustain_ignored,
            strategy_direction,
        )
        fired = evaluate_scheduled(
            symbol, trigger_def, bars, bars_intraday,
            regime_bars_intraday=bars_intraday if model == "HMM_intraday" else None,
            unknown_as_none=True, interval=fetch_iv, bars_vwap_daily=vwap_daily,
            momentum=momentum, fallback_direction=wdir,
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
            _write_effective(
                w,
                {**{k: v for k, v in watch_state.items() if k != "pending_entry_since"},
                 "phase": "idle"},
            )
        return None

    sustain_min = trigger_def.get("sustain_minutes")
    if isinstance(sustain_min, (int, float)) and sustain_min < 0:
        sustain_min = 0
    # Q7: a momentum trigger fires on the bar that meets it.
    if momentum_sustain_ignored(trigger_def, w["id"]):
        sustain_min = 0
    if sustain_min:
        try:
            if fired:
                pending_since_str = watch_state.get("pending_entry_since")
                if pending_since_str is None:
                    _write_effective(
                        w, {**watch_state, "pending_entry_since": _now_iso()},
                    )
                    return None
                pending_since = datetime.fromisoformat(pending_since_str)
                elapsed_min = (datetime.now(timezone.utc) - pending_since).total_seconds() / 60.0
                if elapsed_min < sustain_min:
                    return None
            elif watch_state.get("pending_entry_since"):
                _write_effective(
                    w, {k: v for k, v in watch_state.items() if k != "pending_entry_since"},
                )
        except (ValueError, TypeError) as exc:
            logger.warning("composite-watch sustain-state parse failed for %s, treating as not-sustained: %s", symbol, exc)
            fired = False

    if not fired:
        return None
    close = float(bars[-1]["close"])
    try:
        _detail = describe_match(
            trigger_def, bars_daily=bars, bars_intraday=bars_intraday, symbol=symbol,
            # The strategy gate's own direction, so the alert lists what it matched.
            direction=strategy_direction(trigger_def, wdir),
            interval=fetch_iv, bars_vwap_daily=vwap_daily, momentum=momentum,
        )
        _reason = format_composite_reason((trigger_def.get("primary") or {}).get("to_state"), _detail)
        if momentum is not None and _detail.get("momentum_matched"):
            # Q5: the event's close is the daily close; name the judged bar.
            _reason += f" — momentum judged on the {fetch_iv} bar of {_bar_label(momentum.bars[-1])}"
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
            w_eff = _effective_view(w)
            t = await _eval_strategy_watch(w_eff, start, end, sustain_minutes)
            if t is not None:
                t.committed, t.pending = w_eff["_committed"], w_eff["_pending"]
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
            w_eff = _effective_view(w)
            t = await _eval_composite_watch(w_eff, start, end, now_ts, now_dt)
            if t is not None:
                t.committed, t.pending = w_eff["_committed"], w_eff["_pending"]
        except Exception:
            logger.error("composite-watch: watch %s failed, skipped this run", w.get("id"), exc_info=True)
            continue
        if t is not None:
            transitions.append(t)

    return transitions


def _commit(t: _Transition) -> None:
    """Write one transition's state. A failed write is logged and does not stop
    the remaining commits (which would re-send already-delivered alerts)."""
    _write(t.watch_id, t.new_state)


async def evaluate_all(sustain_minutes: int = 0, now_ts: float | None = None) -> list[WatchEvent]:
    """Evaluate every enabled watch; return one WatchEvent per fired transition.

    sustain_minutes: if > 0, a newly-appeared entry signal must remain present
    for at least this many minutes (checked across scheduler ticks, tracked in
    each watch's last_state.pending_entry_since) before the entry event fires.
    0 preserves the original instant-fire behavior. This is a single
    schedule-level setting (not per-watch) — contrast with the standard
    chart-alert rule builder's per-condition sustain_minutes.
    """
    async with _run_lock():
        await _resend_pending(any_channel=False)      # no notify path: commit the queue
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


def _delayed_when(fired_at: str) -> str:
    try:
        return datetime.fromisoformat(fired_at).astimezone(MARKET_TZ).strftime("%Y-%m-%d %H:%M ET")
    except (ValueError, TypeError):
        return str(fired_at)


def _format_event(ev: WatchEvent, delayed_since: str | None = None) -> tuple[str, str, str]:
    """Return (subject, plain_body, html_body) for a watch event. delayed_since
    (the stored fired_at) marks a re-sent undelivered event."""
    if ev.event_type == "entry":
        label = f"{'Short' if ev.direction == 'Bearish' else 'Long'} setup"
    else:
        label = _SUBJECT_PREFIX.get(ev.event_type, ev.event_type)
    strat = _strategy_label(ev.strategy_key)
    subject = f"{label}: {ev.symbol} — {strat}"
    delay_line = None
    if delayed_since is not None:
        delay_line = f"Delayed: {label} at {ev.close} on {_delayed_when(delayed_since)}"
        subject = f"Delayed: {subject}"
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
    if delay_line is not None:
        plain = f"{delay_line}\n\n{plain}"
        html = f"{html_lib.escape(delay_line)}\n\n{html}"
    return subject, plain, html


def _any_channel_enabled() -> bool:
    """True when at least one notification channel is enabled (D3). See
    _channel_status, which holds the rule; kept for its callers' and tests'
    bool contract (evaluate_and_notify reads _channel_status directly)."""
    return _channel_status()[0]


def _channel_status() -> tuple[bool, bool]:
    """(any channel enabled, config readable) from ONE config read.

    readable is False when the reader reports the file unreadable or raises;
    any_channel is True in both cases (the rule below). A run with an unreadable
    config is a known outage: it counts no failures and sends no probe (skip on
    proof).

    Same file notify_enabled_channels reads. A null or non-dict block counts as
    disabled. AN UNREADABLE settings.yaml COUNTS AS ENABLED (P6, decision
    P4B-FOLLOWUPS-2026-09-26 item 7): the watch then gates its state on
    delivery, notify_enabled_channels reports nothing delivered, and the event
    is kept and resent next run -- never committed silently. It used to read as
    "no channel", so a corrupt file quietly committed every transition. An
    exception escaping the reader is treated the same way (P4b code round 1,
    finding 5)."""
    try:
        cfg, readable = read_notification_config()
        if not readable:
            logger.error("strategy-watch: settings.yaml unreadable; gating state on delivery")
            return True, False
        if not isinstance(cfg, dict):
            return False, True

        def _enabled(block: object) -> bool:
            return isinstance(block, dict) and bool(block.get("enabled"))

        return _enabled(cfg.get("gmail")) or _enabled(cfg.get("telegram")), True
    except Exception:
        logger.error("strategy-watch: notification config unreadable; gating state on delivery", exc_info=True)
        return True, False


# Serialize evaluation and enable/expiry: no run sees an enabled watch until
# its expired queue prefix is committed, and no two runs send the same entry.
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


async def _send(ev: WatchEvent, delayed_since: str | None = None) -> bool:
    """One notification; an exception counts as not delivered."""
    try:
        subject, plain, html = _format_event(ev, delayed_since)
        return bool(await notify_enabled_channels(subject, plain, html))
    except Exception:
        logger.error("strategy-watch: notify failed for %s", ev.symbol, exc_info=True)
        return False


async def _resend_watch(w: dict, any_channel: bool, count_failures: bool = True) -> int | None:
    """Re-send one watch's queue oldest first. A failed head is counted and, once
    eligible, the next entry is sent as the probe (skip on proof). Returns the
    head's failures when the watch is PROBE-READY -- an eligible head failed with
    nothing valid behind it, so this run's fresh event can be the probe; else None."""
    committed, rest = _split_state(dict(w.get("last_state") or {}))
    if not rest or not w.get("enabled"):
        return None                # a disabled watch keeps its events (decision (b))

    def save() -> None:
        # A write after EVERY change: at most one event is sent-but-unwritten.
        _write(w["id"], {**committed, "pending_events": rest} if rest else committed)

    while rest:
        parsed = _parse_entry(rest[0])
        if parsed is None:
            logger.error("strategy-watch: malformed pending event dropped for %s: %r", w["id"], rest[0])
            rest = rest[1:]
            save()
            continue
        ev, new_state, fired_at = parsed
        if any_channel and not await _send(ev, delayed_since=fired_at):
            # The head failed: count it (a copy -- list_watches is shallow).
            head, changed = dict(rest[0]), False
            now = _utcnow()
            if count_failures and _failure_counts(head, now):
                head["failures"] = _failures(head) + 1
                head["last_failure_at"] = now.isoformat()
                rest = [head] + rest[1:]
                changed = True
            n = _failures(head)
            if not count_failures or n < _UNDELIVERABLE_AFTER:
                logger.warning("strategy-watch: delayed %s for %s still not delivered; kept",
                               ev.event_type, ev.symbol)
                if changed:
                    save()
                return None
            dropped = False
            while len(rest) > 1:
                probe = _parse_entry(rest[1])
                if probe is None:
                    logger.error("strategy-watch: malformed pending event dropped for %s: %r",
                                 w["id"], rest[1])
                    rest = [rest[0]] + rest[2:]
                    changed = True
                    continue
                if changed:
                    save()         # before the next send
                    changed = False
                pev, pstate, pfired = probe
                if not await _send(pev, delayed_since=pfired):
                    logger.warning("strategy-watch: probe %s for %s not delivered either; queue kept",
                                   pev.event_type, pev.symbol)
                    return None
                logger.error(_DROP_LOG, w["id"], n, ev.reason)
                committed, rest = pstate, rest[2:]
                save()
                dropped = True
                break
            if dropped:
                continue           # the walk goes on in order with the next entry as head
            if changed:
                save()
            return n               # eligible, nothing valid behind: probe-ready
        if not any_channel:
            logger.warning("strategy-watch: undelivered %s for %s dropped (no channel enabled)",
                           ev.event_type, ev.symbol)
        committed = new_state
        rest = rest[1:]
        save()
    return None


async def _resend_pending(any_channel: bool, count_failures: bool = True) -> dict[str, int]:
    """Re-send every enabled watch's undelivered events, oldest first, stopping
    a watch at a failed send (skip on proof aside). No channel enabled: nothing
    can ever deliver, so the queue's states are committed unsent (D3). Each
    watch is isolated (Q17). Returns {watch_id: head failures} of the
    probe-ready watches -- never when count_failures is False."""
    ready: dict[str, int] = {}
    for w in strategy_watch_store.list_watches():
        try:
            n = await _resend_watch(w, any_channel, count_failures)
        except Exception:
            logger.error("strategy-watch: resend for %s failed, skipped this run", w.get("id"), exc_info=True)
            continue
        if n is not None and count_failures:
            ready[w["id"]] = n
    return ready


async def _deliver_or_queue(t: _Transition, any_channel: bool,
                            probe_ready: dict[str, int] | None = None) -> None:
    ev = t.event
    if t.pending:
        n = (probe_ready or {}).get(t.watch_id)
        if n is not None and len(t.pending) == 1:
            # The watch's only queued alert is an eligible head that failed this
            # run: this fresh event is the probe (sent now, not labelled Delayed).
            if await _send(ev):
                head = _parse_entry(t.pending[0])
                logger.error(_DROP_LOG, t.watch_id, n, head[0].reason if head else "?")
                _commit(t)
                return
            _queue(t)
            logger.warning("strategy-watch: %s %s for %s (probe) not delivered; queued behind the head",
                           ev.strategy_key, ev.event_type, ev.symbol)
            return
        # Older events are still undelivered: keep the order, do not send this one.
        _queue(t)
        logger.warning("strategy-watch: %s %s for %s queued behind %d undelivered",
                       ev.strategy_key, ev.event_type, ev.symbol, len(t.pending))
        return
    if await _send(ev) or not any_channel:
        _commit(t)
        return
    _queue(t)
    logger.warning(
        "strategy-watch: %s %s for %s not delivered; stored, re-sent next run",
        ev.strategy_key, ev.event_type, ev.symbol,
    )


async def evaluate_and_notify(sustain_minutes: int = 0, now_ts: float | None = None) -> list[WatchEvent]:
    """Re-send stored undelivered events, evaluate all watches, send one
    notification per fired event, and commit each event's state only once it
    was delivered (open_questions[3], D3).

    Undelivered with a channel enabled: the event is stored with the watch and
    re-sent, labelled delayed, on the next run -- even if its condition no
    longer holds. No channel enabled at all: nothing could ever deliver, so the
    state is committed as before. Skip on proof: a queued head that has failed
    _UNDELIVERABLE_AFTER spaced runs is dropped (ERROR) as soon as the next alert
    of its watch is delivered -- an older queued one, or this run's fresh event.
    Returns every event fired THIS run, delivered or not (re-sent delayed
    events are not included)."""
    async with _run_lock():
        any_channel, readable = _channel_status()
        probe_ready = await _resend_pending(any_channel, count_failures=readable)
        transitions = await _collect(sustain_minutes, now_ts)
        for t in transitions:
            try:
                await _deliver_or_queue(t, any_channel, probe_ready)
            except Exception:
                logger.error("strategy-watch: delivery for %s failed, skipped this run",
                             t.watch_id, exc_info=True)
        return [t.event for t in transitions]
