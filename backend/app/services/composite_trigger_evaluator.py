"""Composite trigger evaluator — two paths.

evaluate_from_context: WebSocket/alert path — receives pre-computed model outputs.
evaluate_scheduled:    Watch/scheduler path — receives raw bars, runs models internally.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from functools import partial
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.composite_trigger import CompositeTriggerDef

logger = logging.getLogger(__name__)


def hmm_intraday_interval_error(trigger_def: object, interval: object) -> str | None:
    """A4f-rules: the message to refuse a composite HMM_intraday definition on a
    non-intraday interval with, else None. Never raises: a non-dict trigger_def /
    primary means "no model" (other validation owns malformed bodies).

    Deliberately NOT built on strategy_watch_store._primary_model: importing that
    module instantiates its module-level store, whose load() reads and can rewrite
    config/strategy_watches.yaml. Same wording as add_composite_watch's ValueError;
    tests/test_a4f_rules_hmm_intraday_interval.py pins that both accept/reject the
    same intervals with the same message."""
    primary = trigger_def.get("primary") if isinstance(trigger_def, dict) else None
    model = primary.get("model") if isinstance(primary, dict) else None
    if model != "HMM_intraday":
        return None
    from app.data.market import is_intraday_interval
    if is_intraday_interval(interval):
        return None
    return f"HMM_intraday needs an intraday interval (e.g. 5min, 15min, 1h), got {interval!r}"


# HMM-INTRADAY-4H-HISTORY (Kenneth, 2026-09-25): history a composite WATCH
# fetches per interval. 4h is yfinance 1h resampled, so 55 days gave ~110
# completed 4h bars < regime_hmm.MIN_BARS (200) and the HMM never fitted;
# 180 days ("6mo") gives ~250. WATCH-RULE-BAR-PARITY 2.1: 1h also fetches 180
# days (~880 bars), so the HMM fits its last 800 bars as a composite RULE did on
# the chart's 730-day series; a composite rule now makes this same fetch
# (chart_alerts._composite_model_series). Every other interval keeps 55.
_INTRADAY_HISTORY_DAYS = {"1h": 180, "4h": 180}


def intraday_history_days(interval: str) -> int:
    from app.data.market import normalize_interval
    return _INTRADAY_HISTORY_DAYS.get(normalize_interval(interval), 55)


def omm_direction(trigger_def: object, fallback: object = None) -> str:
    """WATCH-RULE-BAR-PARITY 2.5 (decision OMM-DIRECTION): the direction a
    composite's OMM is judged in, on the watch and the rule path alike -- the
    trigger's own ``direction`` when it is exactly "Bullish"/"Bearish", else
    ``fallback`` when it is exactly "Bullish"/"Bearish", else "Bullish".
    compute_omm raises ValueError on any other value and ``composite_def`` /
    ``trigger_def`` are stored unvalidated, so a raw value is never passed
    through. WATCH-DIRECTION-TO-EVALUATOR: the watch path passes the watch's own
    saved direction as ``fallback``; the rule path has none."""
    d = trigger_def.get("direction") if isinstance(trigger_def, dict) else None
    if d in ("Bullish", "Bearish"):
        return d
    return fallback if fallback in ("Bullish", "Bearish") else "Bullish"


def strategy_direction(trigger_def: object, fallback: object = None) -> object:
    """WATCH-DIRECTION-TO-EVALUATOR: the direction evaluate_scheduled's
    strategy-confirmation gate judges in -- a truthy trigger ``direction``
    exactly as stored (today's behaviour, no normalisation), else the valid
    ``fallback``, else "Bullish". Shared with the watch's describe_match call so
    an alert lists the strategies the gate matched."""
    d = trigger_def.get("direction") if isinstance(trigger_def, dict) else None
    return d or omm_direction(None, fallback)


# WATCH-RULE-BAR-PARITY 2.2: the nominal span of an intraday candle, i.e. its
# close instant is ``time + span``. NOT market._INTERVAL_COMPLETION_SECONDS: its
# 4h entry is 5 h (a completion lag), which would let an 11:00-stamped 4h candle
# read that day's 16:00 close.
_NOMINAL_SPAN_SECONDS: dict[str, int] = {
    "1min": 60, "1m": 60,
    "5min": 300, "5m": 300,
    "15min": 900, "15m": 900,
    "30min": 1800, "30m": 1800,
    "1h": 3600,
    "4h": 4 * 3600,
}


def _daily_session_close(d: date) -> datetime:
    from datetime import time as dtime
    from app.services.scheduling_tz import MARKET_TZ
    return datetime.combine(d, dtime(16, 0), tzinfo=MARKET_TZ)


def candle_close_instant(closed_candle: object, interval: object) -> datetime | None:
    """The instant a closed candle of ``interval`` closed (aware, ET), or None
    when it cannot be dated: a non-int / bool ``time``, or an unknown interval.

    Intraday: ``time + _NOMINAL_SPAN_SECONDS``. 1D / 1W: the close of the first
    weekday (1D) / first Friday (1W) ``d`` with ``close(d) >= stamp`` -- every
    stamp convention in use (00:00 ET, 00:00 UTC, session open, session close;
    Monday or Friday for a week) lies after the previous close and at or before
    its own, as market_session.completed_session_bars relies on."""
    from datetime import timedelta
    from app.data.market import normalize_interval
    from app.services.scheduling_tz import MARKET_TZ

    t = closed_candle.get("time") if isinstance(closed_candle, dict) else None
    if not isinstance(t, int) or isinstance(t, bool) or not isinstance(interval, str):
        return None
    span = _NOMINAL_SPAN_SECONDS.get(interval)
    if span is None:
        span = _NOMINAL_SPAN_SECONDS.get(normalize_interval(interval))
    if span is not None:
        return datetime.fromtimestamp(t + span, MARKET_TZ)
    norm = normalize_interval(interval)
    if norm not in ("daily", "weekly"):
        return None
    stamp = datetime.fromtimestamp(t, MARKET_TZ)
    d = stamp.date()
    for _ in range(8):   # a weekday / Friday with close >= stamp is at most 7 days on
        if (d.weekday() < 5) if norm == "daily" else (d.weekday() == 4):
            close = _daily_session_close(d)
            if close >= stamp:
                return close
        d += timedelta(days=1)
    return None   # unreachable


def daily_rows_at_candle(rows: list[dict], closed_candle: object, interval: object) -> list[dict]:
    """WATCH-RULE-BAR-PARITY 2.2 (decision Q-B): the daily rows a composite rule
    judging ``closed_candle`` may read -- exactly those whose session close
    (16:00 ET on the row's date) is at or before the candle's close instant.

    So the 1D candle of day D keeps row D, the 1W candle keeps its Friday, a
    15:45 15min candle (close 16:00) keeps row D, and a 15:15 one never sees
    day D's close -- catch-up candles included. Deliberately NOT built on
    completed_daily_rows / last_session_close: those answer "latest close at
    or before", inclusive-forming at 16:00:00, and would drop row D.

    An undatable candle (see candle_close_instant) -> [] (fail closed) and one
    WARNING. A row whose ``time`` is not an ISO date string is dropped. Order is
    preserved and ``rows`` is not mutated."""
    close_at = candle_close_instant(closed_candle, interval)
    if close_at is None:
        logger.warning(
            "daily_rows_at_candle: cannot date closed candle %r on %r; no daily rows (fail closed)",
            closed_candle.get("time") if isinstance(closed_candle, dict) else closed_candle, interval,
        )
        return []
    out: list[dict] = []
    for r in rows:
        t = r.get("time") if isinstance(r, dict) else None
        if not isinstance(t, str):
            continue
        try:
            d = date.fromisoformat(t[:10])
        except ValueError:
            continue
        if _daily_session_close(d) <= close_at:
            out.append(r)
    return out


def _check_primary_omm(trigger_def: dict, omm_result) -> bool:
    """Check OMM primary condition. omm_result is OmmResult dataclass or None."""
    if omm_result is None:
        return False
    primary = trigger_def.get("primary", {})
    to_state = primary.get("to_state")
    if to_state and omm_result.state != to_state:
        return False
    conviction_min = primary.get("conviction_min", 50)
    if omm_result.conviction_pct < conviction_min:
        return False
    p_stay_min = primary.get("p_stay_min", 0.5)
    if omm_result.p_stay < p_stay_min:
        return False
    return True


def _check_primary_hmm(trigger_def: dict, hmm_result) -> bool:
    """Check HMM primary condition.

    hmm_result is HmmResult dataclass with:
      .state (str), .p_stay (float), .p_transition (list[dict{to, prob}])
    or a plain dict with the same keys.
    """
    if hmm_result is None:
        return False
    primary = trigger_def.get("primary", {})

    # Support both dataclass (attribute access) and dict access
    if hasattr(hmm_result, "state"):
        state = hmm_result.state
        p_stay = hmm_result.p_stay
        p_transition_list = hmm_result.p_transition
    else:
        state = hmm_result.get("state", "")
        p_stay = hmm_result.get("p_stay", 0.0)
        p_transition_list = hmm_result.get("p_transition", [])

    to_state = primary.get("to_state")
    if to_state and state != to_state:
        return False

    p_stay_min = primary.get("p_stay_min", 0.5)
    if p_stay < p_stay_min:
        return False

    # p_transition_min: compare against the maximum transition probability to any other state
    p_transition_min = primary.get("p_transition_min", 0.3)
    if p_transition_min > 0.0 and p_transition_list:
        max_transition = max((entry.get("prob", 0.0) for entry in p_transition_list), default=0.0)
        if max_transition < p_transition_min:
            return False

    return True


@dataclass(frozen=True)
class MomentumInput:
    """COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD 3.2: what the momentum
    confirmations read -- `bars` ending at the judged bar (the rule's closed
    candle / the watch's rows[-2]), the rule/watch `interval`, and `log_key`
    (the rule/watch id) that dedupes momentum WARNINGs. `momentum=None`
    anywhere below means "not read"."""
    bars: list
    interval: str
    log_key: str


def _is_momentum(conf: object) -> bool:
    return isinstance(conf, dict) and conf.get("type") == "momentum"


def has_momentum(trigger_def: object) -> bool:
    """At least one momentum confirmation AND min_confirmations > 0 -- with 0
    the confirmations are never evaluated, so sustain must still apply (Q7)
    and nothing needs fetching."""
    if not isinstance(trigger_def, dict):
        return False
    min_conf = trigger_def.get("min_confirmations", 1)
    if not (isinstance(min_conf, (int, float)) and not isinstance(min_conf, bool) and min_conf > 0):
        return False
    return any(_is_momentum(c) for c in (trigger_def.get("confirmations") or []))


def momentum_confirmation_error(trigger_def: object) -> str | None:
    """Q10c save validation: the message to refuse a momentum confirmation that
    could never fire with, else None (other validation owns malformed bodies)."""
    confs = trigger_def.get("confirmations") if isinstance(trigger_def, dict) else None
    if not isinstance(confs, list):
        return None
    from app.services.indicator_compute import MOMENTUM_KINDS, rsi_level
    for i, c in enumerate(confs):
        if not _is_momentum(c):
            continue
        kind = c.get("signal_kind")
        if kind not in MOMENTUM_KINDS:
            return f"confirmations[{i}]: momentum signal_kind must be one of {', '.join(MOMENTUM_KINDS)}, got {kind!r}"
        d = c.get("direction")
        if d is not None and not (isinstance(d, str) and d.lower() in ("bullish", "bearish")):
            return f"confirmations[{i}]: direction must be Bullish, Bearish or null, got {d!r}"
        if kind == "rsi_cross" and "min_confidence" in c and rsi_level(c["min_confidence"]) is None:
            return (f"confirmations[{i}]: rsi_cross min_confidence is the RSI level and must be "
                    f"an integer 1-99, got {c['min_confidence']!r}")
    return None


def momentum_confirmations(trigger_def: object) -> list:
    """The momentum confirmations of a definition, in order (for the PUT exemption)."""
    confs = trigger_def.get("confirmations") if isinstance(trigger_def, dict) else None
    return [c for c in confs if _is_momentum(c)] if isinstance(confs, list) else []


def _matched_indexes(trigger_def: dict, structure_signals: list[dict],
                     momentum: MomentumInput | None = None) -> list[int]:
    """The index of each confirmation condition that is met. A momentum
    confirmation is met only when `momentum` was read and momentum_match says
    so on its last bar; `momentum=None` (not read) matches none."""
    matched: list[int] = []
    for i, conf in enumerate(trigger_def.get("confirmations", []) or []):
        if not isinstance(conf, dict):
            continue
        signal_kind = conf.get("signal_kind", "")
        direction = conf.get("direction")  # 'Bullish', 'Bearish', or None
        conf_type = conf.get("type", "structure")

        if conf_type == "structure":
            min_conf = conf.get("min_confidence", 60)
            for sig in structure_signals:
                kind_match = sig.get("kind", "") == signal_kind or sig.get("type", "") == signal_kind
                # market_structure.py uses lowercase directions; trigger def may use title case — compare case-insensitively
                sig_dir = sig.get("direction", "")
                dir_match = direction is None or sig_dir.lower() == direction.lower()
                conf_match = sig.get("confidence", 0) >= min_conf
                if kind_match and dir_match and conf_match:
                    matched.append(i)
                    break
        elif conf_type == "momentum":
            # COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD: computed from the bars,
            # never read from a standard rule's indicator series (the old
            # indicator_values leak, plan 1.2).
            if isinstance(momentum, MomentumInput):
                from app.services.indicator_compute import momentum_match
                if momentum_match(momentum.bars, momentum.interval, signal_kind, direction,
                                  conf.get("min_confidence"), momentum.log_key):
                    matched.append(i)
    return matched


def _matched_confirmations(trigger_def: dict, structure_signals: list[dict],
                           momentum: MomentumInput | None = None) -> list[str]:
    """The signal_kind of each confirmation condition that is met."""
    confs = trigger_def.get("confirmations", []) or []
    return [confs[i].get("signal_kind", "") for i in _matched_indexes(trigger_def, structure_signals, momentum)]


def _count_confirmations(trigger_def: dict, structure_signals: list[dict],
                         momentum: MomentumInput | None = None) -> int:
    """Count how many confirmation conditions are met."""
    return len(_matched_indexes(trigger_def, structure_signals, momentum))


def momentum_sustain_ignored(trigger_def: dict, log_key: object) -> bool:
    """Q7: a trigger with a momentum confirmation fires on the bar that meets
    it -- a cross is a one-bar event, so a non-zero sustain_minutes could
    never be met. True when sustain must be skipped (one WARNING per id when a
    non-zero sustain is being ignored)."""
    if not has_momentum(trigger_def):
        return False
    sustain = trigger_def.get("sustain_minutes")
    if isinstance(sustain, (int, float)) and not isinstance(sustain, bool) and sustain > 0:
        from app.services.indicator_compute import momentum_warn_once
        momentum_warn_once(log_key, "sustain",
                           "composite %s: sustain_minutes=%s ignored -- a momentum confirmation "
                           "fires on the bar that meets it", log_key, sustain)
    return True


_MR_STRATEGY_LOOKBACK = 3   # bars scanned to detect a recent signal
_MIN_STRATEGY_BARS = 60     # fewer bars of a strategy's kind -> not judged ("starved")

# VWAP-CONFIRMATION-LIKE-REGIME-MODELS (Kenneth, 2026-09-25): the composite
# mean_reversion_vwap confirmation reads COMPLETED bars of the rule/watch's own
# interval, gives the same answer on the watch and the rule path, and on 1D/1W
# runs mean_reversion_vwap_daily_signal on completed daily bars. Intraday
# intervals -> the spelling mean_reversion_vwap_signal's allow-list accepts
# ('4h' added there by decision D2). Before this the signal was called with no
# interval, so its intraday gate always saw its '15m' default and passed
# whatever bars it was handed -- daily bars on a 1D watch included.
_VWAP_SIGNAL_INTERVAL = {
    "1m": "1m", "1min": "1m", "5m": "5m", "5min": "5m", "15m": "15m", "15min": "15m",
    "30m": "30m", "30min": "30m", "1h": "1h", "60m": "1h", "4h": "4h",
}


def _strategy_bar_type(key: str, interval: str | None) -> str | None:
    """Which bars a confirmable strategy reads: "daily", "intraday", or None
    (cannot be judged -- VWAP on a missing/unknown interval never matches)."""
    if key in ("mean_reversion_rsi", "mean_reversion_bb"):
        return "daily"
    if key != "mean_reversion_vwap" or not isinstance(interval, str):
        return None
    if interval in _VWAP_SIGNAL_INTERVAL:
        return "intraday"
    from app.data.market import normalize_interval
    if normalize_interval(interval) in ("daily", "weekly"):
        return "daily"
    return None


def _strategy_bars(
    key: str,
    interval: str | None,
    bars_daily: list[dict],
    bars_intraday: list[dict],
    bars_vwap_daily: list[dict] | None,
) -> list[dict] | None:
    """The one bar list a strategy reads -- shared by the matcher and the
    starved count so they cannot disagree. None = not judged (not starved).

    rsi/bb read bars_daily. VWAP reads bars_intraday on an intraday interval and
    ONLY bars_vwap_daily on 1D/1W (D7): every 1D/1W caller passes completed
    get_bars rows there, never chart-cache or weekly candles."""
    bar_type = _strategy_bar_type(key, interval)
    if bar_type is None:
        return None
    if key == "mean_reversion_vwap":
        return bars_intraday if bar_type == "intraday" else bars_vwap_daily
    return bars_daily


def completed_daily_rows(bars: list[dict], now: datetime) -> list[dict]:
    """``bars`` (historical_store.get_bars rows) without trailing daily bars that
    are still forming at ``now`` (an aware datetime).

    get_bars rows carry ``time`` as an ISO date string, which
    market_session.completed_session_bars treats as undatable and pops -- it
    would drop the last COMPLETED bar every run. Here a str time compares by
    date against the last completed session close, an int (non-bool) time by
    timestamp. Any other last ``time``, or a str that is not an ISO date,
    drops that bar only and stops (fail closed, as A4g). Order is preserved and
    ``bars`` is not mutated. Since WATCH-RULE-BAR-PARITY plan 2.10 get_bars
    never stores a daily row before its session's close + 2 h (18:00 ET), and re-fetches
    legacy rows stored before that rule once they have settled (A4g open
    question (a)), so a stored row is a completed bar; this trim still guards
    the rows a caller passes from elsewhere.
    """
    from app.services.market_session import last_session_close

    close = last_session_close(now)
    cutoff_date = close.date()
    cutoff_ts = close.timestamp()
    out = list(bars)
    while out:
        t = out[-1].get("time")
        if isinstance(t, str):
            try:
                forming = date.fromisoformat(t[:10]) > cutoff_date
            except ValueError:
                out.pop()
                break
        elif isinstance(t, int) and not isinstance(t, bool):
            forming = t > cutoff_ts
        else:
            out.pop()
            break
        if not forming:
            break
        out.pop()
    return out


def _matched_strategy_signals(
    strategy_keys: list[str],
    bars_daily: list[dict],
    bars_intraday: list[dict],
    direction: str = "Bullish",
    interval: str | None = None,
    bars_vwap_daily: list[dict] | None = None,
) -> list[str]:
    """Return which of the given mean-reversion strategies fired within the last few bars."""
    from app.services.strategy_engine import (
        mean_reversion_rsi_signal,
        mean_reversion_bb_signal,
        mean_reversion_vwap_signal,
        mean_reversion_vwap_daily_signal,
        SIGNAL_WINDOW_BARS,
    )

    matched: list[str] = []
    for key in strategy_keys:
        bars = _strategy_bars(key, interval, bars_daily, bars_intraday, bars_vwap_daily)
        if bars is None:
            logger.debug("_matched_strategy_signals: %s not judged on interval %r", key, interval)
            continue
        if key == "mean_reversion_rsi":
            call = partial(mean_reversion_rsi_signal, direction=direction)
        elif key == "mean_reversion_bb":
            call = partial(mean_reversion_bb_signal, direction=direction)
        elif _strategy_bar_type(key, interval) == "intraday":
            call = partial(mean_reversion_vwap_signal, direction=direction,
                           interval=_VWAP_SIGNAL_INTERVAL[interval])
        else:
            call = partial(mean_reversion_vwap_daily_signal, direction=direction)
        if len(bars) < _MIN_STRATEGY_BARS:
            logger.debug("_matched_strategy_signals: skipping %s — insufficient bars (%d)", key, len(bars))
            continue
        # STOCKS-HORIZON-T1 H1: a daily key gets the scan's SIGNAL_WINDOW_BARS
        # window; the intraday VWAP keeps 120 bars (its anchored VWAP spans the
        # whole slice, so a longer one would move every reading).
        window = 120 if _strategy_bar_type(key, interval) == "intraday" else SIGNAL_WINDOW_BARS
        for i in range(len(bars) - _MR_STRATEGY_LOOKBACK, len(bars)):
            slice_bars = bars[max(0, i - window + 1): i + 1]
            try:
                if call(slice_bars) is not None:
                    matched.append(key)
                    break
            except Exception:
                pass
    return matched


def _check_strategy_signals(
    strategy_keys: list[str],
    bars_daily: list[dict],
    bars_intraday: list[dict],
    direction: str = "Bullish",
    interval: str | None = None,
    bars_vwap_daily: list[dict] | None = None,
) -> int:
    """Return how many of the given mean-reversion strategies fired within the last few bars."""
    return len(_matched_strategy_signals(
        strategy_keys, bars_daily, bars_intraday, direction,
        interval=interval, bars_vwap_daily=bars_vwap_daily,
    ))


def evaluate_from_context(
    trigger_def: dict,
    omm_result,              # OmmResult dataclass | None
    structure_signals: list[dict],
    indicator_values: dict,
    bars_daily: list[dict] | None = None,
    bars_intraday: list[dict] | None = None,
    regime_bars_intraday: list[dict] | None = None,
    interval: str | None = None,
    bars_vwap_daily: list[dict] | None = None,
    *,
    momentum: MomentumInput | None = None,
) -> bool:
    """Alert/WebSocket path. Receives pre-computed model outputs — no I/O for the
    primary/confirmations checks. bars_daily/bars_intraday are optional and,
    when supplied by the caller, let this path apply the same strategy_confirmations
    gate and HMM_intraday/HMM_daily primary-condition checks evaluate_scheduled()
    applies — keeping WS-fired and scheduled-fired composite alerts behaviorally
    consistent.

    trigger_def: CompositeTriggerDef serialized as dict (or the Pydantic model)
    omm_result: OmmResult dataclass from compute_omm() — attribute access (.state, .conviction_pct, .p_stay);
        ignored unless primary.model == "OMM"
    structure_signals: list of market structure signal dicts from market_structure.py
    indicator_values: no longer read (COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD:
        momentum confirmations are computed from `momentum`, not looked up in a
        standard rule's indicator series); kept for call compatibility.
    momentum: the bars momentum confirmations judge (MomentumInput). None: not
        read -- two-valued here, so those confirmations are not matched.
    bars_daily: OHLCV daily bars — needed if trigger_def sets strategy_confirmations,
        OR if primary.model == "HMM_daily" (used to fit the HMM directly)
    bars_intraday: OHLCV intraday bars — needed if trigger_def sets strategy_confirmations,
        OR if primary.model == "HMM_intraday" (used to fit the HMM directly)
    regime_bars_intraday: A4c -- when not None, the HMM_intraday fit uses THIS
        series (the caller's completed bars) instead of bars_intraday.
    interval: the rule's interval -- decides which VWAP variant runs and on which
        bars (VWAP-CONFIRMATION-LIKE-REGIME-MODELS). None: VWAP never matches.
    bars_vwap_daily: completed daily bars for the VWAP daily variant on 1D/1W.
    bars_intraday must be COMPLETED bars of ``interval`` (the caller trims).
    """
    if isinstance(trigger_def, dict):
        td = trigger_def
    else:
        td = trigger_def.model_dump()

    primary = td.get("primary", {})
    model = primary.get("model", "OMM")

    # Check primary Markov condition
    if model == "OMM":
        if not _check_primary_omm(td, omm_result):
            return False
    elif model == "HMM_intraday":
        _hmm_bars = regime_bars_intraday if regime_bars_intraday is not None else bars_intraday
        if not _hmm_bars:
            logger.warning("evaluate_from_context: HMM_intraday requested but no intraday bars supplied; skipping")
            return False
        try:
            from app.services.regime_hmm import compute_intraday_hmm
            hmm_result = compute_intraday_hmm(_hmm_bars)
            if not _check_primary_hmm(td, hmm_result):
                return False
        except Exception as exc:
            # Deliberate fail-closed: if the HMM model errors we suppress the alert
            # (return False) rather than surfacing an error alert, matching the OMM/
            # regime-failure pattern. Logged at WARNING for observability. If this
            # ever needs to become a user-visible error, that is a product decision,
            # not a silent code change.
            logger.warning("evaluate_from_context: HMM_intraday failed — %s", exc)
            return False
    elif model == "HMM_daily":
        # compute_intraday_hmm works on any list[dict] with 'close' keys; use daily
        # bars — same model choice evaluate_scheduled()'s own HMM_daily branch makes.
        if not bars_daily:
            logger.warning("evaluate_from_context: HMM_daily requested but no daily bars supplied; skipping")
            return False
        try:
            from app.services.regime_hmm import compute_intraday_hmm
            hmm_result = compute_intraday_hmm(bars_daily)
            if not _check_primary_hmm(td, hmm_result):
                return False
        except Exception as exc:
            # Deliberate fail-closed: see the HMM_intraday branch above for rationale.
            logger.warning("evaluate_from_context: HMM_daily failed — %s", exc)
            return False
    elif model == "any":
        # 'any' means regime model doesn't matter — skip primary check
        pass

    # Count confirmations
    min_conf = td.get("min_confirmations", 1)
    if min_conf > 0:
        count = _count_confirmations(td, structure_signals, momentum)
        if count < min_conf:
            return False

    # Strategy confirmations — same N-of-M gate as evaluate_scheduled, so a composite
    # rule with strategy_confirmations behaves identically whether it fires via the
    # WebSocket path or the scheduled watch path. If the gate is configured but no
    # bars were supplied, _check_strategy_signals naturally returns 0 matches
    # (below any min_strategy_conf >= 1), i.e. this fails closed rather than
    # silently skipping the gate as before.
    strategy_conf_list: list[str] = td.get("strategy_confirmations", [])
    min_strategy_conf: int = td.get("min_strategy_confirmations", 1)
    if strategy_conf_list:
        direction: str = td.get("direction") or "Bullish"
        strategy_fired = _check_strategy_signals(
            strategy_conf_list, bars_daily or [], bars_intraday or [], direction=direction,
            interval=interval, bars_vwap_daily=bars_vwap_daily,
        )
        if strategy_fired < min_strategy_conf:
            return False

    return True


def evaluate_from_context_detailed(
    trigger_def: dict,
    omm_result,
    structure_signals: list[dict],
    indicator_values: dict,
    bars_daily: list[dict] | None = None,
    bars_intraday: list[dict] | None = None,
    direction: str = "Bullish",
    symbol: str = "",
    regime_bars_intraday: list[dict] | None = None,
    interval: str | None = None,
    bars_vwap_daily: list[dict] | None = None,
    *,
    momentum: MomentumInput | None = None,
) -> tuple[bool, dict | None]:
    """Fire-gate + match detail in one pass. Returns (fired, detail) where detail is
    the describe_match() dict when fired, else None. Equivalent to calling
    evaluate_from_context() then describe_match(), but the strategy/structure scan is
    only performed on the describe side once the gate passes — no double scan.

    ``symbol`` is threaded through to describe_match so its structure-recompute branch
    (hit only when structure_signals is None) is not silently narrowed to symbol=""."""
    fired = evaluate_from_context(
        trigger_def, omm_result, structure_signals, indicator_values,
        bars_daily=bars_daily, bars_intraday=bars_intraday,
        regime_bars_intraday=regime_bars_intraday,
        interval=interval, bars_vwap_daily=bars_vwap_daily, momentum=momentum,
    )
    if not fired:
        return False, None
    detail = describe_match(
        trigger_def, structure_signals=structure_signals,
        bars_daily=bars_daily, bars_intraday=bars_intraday, symbol=symbol, direction=direction,
        interval=interval, bars_vwap_daily=bars_vwap_daily, momentum=momentum,
    )
    return True, detail


def evaluate_scheduled(
    symbol: str,
    trigger_def: dict,
    bars_daily: list[dict],
    bars_intraday: list[dict],
    regime_bars_intraday: list[dict] | None = None,
    *,
    unknown_as_none: bool = False,
    interval: str | None = None,
    bars_vwap_daily: list[dict] | None = None,
    momentum: MomentumInput | None = None,
    fallback_direction: str | None = None,
) -> bool | None:
    """Watch/scheduler path. Receives raw bars — runs models internally.

    bars_daily: OHLCV daily bars for OMM and daily HMM
    bars_intraday: OHLCV intraday bars for HMM_intraday (may be empty if not needed)
    regime_bars_intraday: A4c -- as evaluate_from_context: when not None the
        HMM_intraday fit uses it.
    interval / bars_vwap_daily: as evaluate_from_context (the VWAP variant and
        its bars). bars_intraday must be COMPLETED bars of ``interval``.
    momentum: as evaluate_from_context; None = not read (the watch's chart
        fetch failed), which counts toward "no reading" below.
    fallback_direction: WATCH-DIRECTION-TO-EVALUATOR -- the watch's own saved
        direction, used for OMM and the strategy gate only when the trigger has
        no direction of its own (omm_direction / strategy_direction).

    unknown_as_none: when True, a reading that could not be TAKEN -- no bars,
        a model that errored or returned nothing, structure detection that
        raised, too few bars for a listed strategy confirmation -- returns
        None instead of False. The strategy-watch loop needs the difference: a
        composite armed for the current entry re-arms on a genuine False, and
        treating a feed blip as False re-armed it and re-sent the same alert
        once the feed recovered. Default False keeps every other caller's
        fail-closed bool unchanged.

    Note: regime_hmm.py only exposes compute_intraday_hmm(); 'HMM_daily' falls back to
    that function on daily bars (requires MIN_BARS=200 daily bars).
    """
    from app.services.regime_omm import compute_omm
    from app.services.market_structure import compute_structure

    if isinstance(trigger_def, dict):
        td = trigger_def
    else:
        td = trigger_def.model_dump()

    primary = td.get("primary", {})
    model = primary.get("model", "OMM")

    # THREE-VALUED AND over the gates, when unknown_as_none is set: any gate
    # that is definitely False makes the whole result False; otherwise any gate
    # with no reading makes it None; otherwise True. A gate with no reading must
    # NOT short-circuit past a later gate that is definitely False -- that left
    # an armed watch armed through a genuine exit, and it then missed the next
    # entry. With the flag off, `no_reading()` returns False at once, exactly the
    # old fail-closed short-circuit.
    had_no_reading = False

    def no_reading() -> bool:
        nonlocal had_no_reading
        had_no_reading = True
        return not unknown_as_none   # True -> the caller returns False now

    # Run appropriate model. primary_met: True / False / None (no reading).
    primary_met: bool | None = False
    if model == "OMM":
        # WATCH-RULE-BAR-PARITY 2.5: the trigger's direction, as the rule path;
        # WATCH-DIRECTION-TO-EVALUATOR: else the watch's own direction.
        omm_result = (
            compute_omm([b["close"] for b in bars_daily], direction=omm_direction(td, fallback_direction))
            if bars_daily else None
        )
        primary_met = None if omm_result is None else _check_primary_omm(td, omm_result)
    elif model == "HMM_intraday":
        _hmm_bars = regime_bars_intraday if regime_bars_intraday is not None else bars_intraday
        if not _hmm_bars:
            logger.warning("evaluate_scheduled: HMM_intraday requested but no intraday bars for %s", symbol)
            primary_met = None
        else:
            try:
                from app.services.regime_hmm import compute_intraday_hmm
                hmm_result = compute_intraday_hmm(_hmm_bars)
                primary_met = None if hmm_result is None else _check_primary_hmm(td, hmm_result)
            except Exception as exc:
                # Deliberate fail-closed: if the HMM model errors we suppress the alert
                # rather than surfacing an error alert, matching the OMM/regime-failure
                # pattern. Logged at WARNING for observability. If this ever needs to
                # become a user-visible error, that is a product decision, not a
                # silent code change.
                logger.warning("evaluate_scheduled: HMM_intraday failed for %s — %s", symbol, exc)
                primary_met = None
    elif model == "HMM_daily":
        # compute_intraday_hmm works on any list[dict] with 'close' keys; use daily bars.
        # Requires MIN_BARS=200 daily bars; callers should ensure sufficient history.
        if not bars_daily:
            primary_met = None
        else:
            try:
                from app.services.regime_hmm import compute_intraday_hmm
                hmm_result = compute_intraday_hmm(bars_daily)
                primary_met = None if hmm_result is None else _check_primary_hmm(td, hmm_result)
            except Exception as exc:
                # Deliberate fail-closed: see the HMM_intraday branch above for rationale.
                logger.warning("evaluate_scheduled: HMM_daily failed for %s — %s", symbol, exc)
                primary_met = None
    elif model == "any":
        primary_met = True

    if primary_met is False:
        return False
    if primary_met is None and no_reading():
        return False

    # Count structure confirmations (only runs if min_confirmations > 0).
    min_conf_count = td.get("min_confirmations", 1)
    if min_conf_count > 0:
        structure_signals: list[dict] = []
        structure_unread = not bars_daily
        if bars_daily:
            try:
                # compute_structure(candles, interval, symbol) is the entry point
                structure_signals = compute_structure(bars_daily, "1D", symbol) or []
            except Exception as exc:
                logger.warning("evaluate_scheduled: structure detection failed for %s — %s", symbol, exc)
                structure_unread = True

        count = _count_confirmations(td, structure_signals, momentum)
        if count < min_conf_count:
            # 3.2: ONE count over structure and momentum. Confirmations that
            # could not be read are "unread": if even all of them matching
            # could not reach the minimum the gate is definitely False;
            # otherwise the shortfall is no reading. A trigger with no momentum
            # confirmation keeps its old rule unchanged (a shortfall only
            # because there was nothing to detect on is no reading).
            confs = [c for c in (td.get("confirmations") or []) if isinstance(c, dict)]
            n_momentum = sum(1 for c in confs if c.get("type") == "momentum")
            if n_momentum == 0:
                reachable = structure_unread
            else:
                unread = (len(confs) - n_momentum if structure_unread else 0) + (n_momentum if momentum is None else 0)
                reachable = unread > 0 and count + unread >= min_conf_count
            if not reachable or no_reading():
                return False

    # Strategy confirmations — independent N-of-M gate for mean-reversion strategies.
    # Evaluated regardless of min_confirmations to ensure the strategy gate is never skipped.
    strategy_conf_list: list[str] = td.get("strategy_confirmations", [])
    min_strategy_conf: int = td.get("min_strategy_confirmations", 1)
    if strategy_conf_list:
        direction = strategy_direction(td, fallback_direction)
        strategy_fired = _check_strategy_signals(
            strategy_conf_list, bars_daily, bars_intraday, direction=direction,
            interval=interval, bars_vwap_daily=bars_vwap_daily,
        )
        if strategy_fired < min_strategy_conf:
            # _matched_strategy_signals silently skips a known strategy with
            # < 60 bars of its kind. It is no reading only if those skipped
            # strategies could still have reached the minimum; otherwise the
            # gate is definitely False. Same bar list as the matcher reads.
            starved = 0
            for key in strategy_conf_list:
                _b = _strategy_bars(key, interval, bars_daily, bars_intraday, bars_vwap_daily)
                if _b is not None and len(_b) < _MIN_STRATEGY_BARS:
                    starved += 1
            if strategy_fired + starved < min_strategy_conf or no_reading():
                return False

    return None if had_no_reading else True


def describe_match(
    trigger_def: dict,
    *,
    structure_signals: list[dict] | None = None,
    indicator_values: dict | None = None,
    bars_daily: list[dict] | None = None,
    bars_intraday: list[dict] | None = None,
    symbol: str = "",
    direction: str = "Bullish",
    interval: str | None = None,
    bars_vwap_daily: list[dict] | None = None,
    momentum: MomentumInput | None = None,
) -> dict:
    """Build a human-readable breakdown of which confirmations/strategies matched.

    Call this AFTER evaluate_from_context/evaluate_scheduled has already confirmed
    the rule fired, to build the alert notification text. Structure signals are
    recomputed from bars_daily+symbol if not passed explicitly (watch/scheduler path).
    """
    td = trigger_def if isinstance(trigger_def, dict) else trigger_def.model_dump()

    if structure_signals is None and bars_daily and td.get("confirmations"):
        try:
            from app.services.market_structure import compute_structure
            structure_signals = compute_structure(bars_daily, "1D", symbol) or []
        except Exception as exc:
            logger.warning("describe_match: structure recompute failed for %s — %s", symbol, exc)
            structure_signals = []

    confs = td.get("confirmations", []) or []
    matched_indexes = _matched_indexes(td, structure_signals or [], momentum)
    structure_idx = [i for i, c in enumerate(confs) if isinstance(c, dict) and not _is_momentum(c)]
    momentum_idx = [i for i, c in enumerate(confs) if _is_momentum(c)]
    structure_matched = [confs[i].get("signal_kind", "") for i in matched_indexes if i in structure_idx]
    momentum_matched = [confs[i].get("signal_kind", "") for i in matched_indexes if i in momentum_idx]

    strategy_keys: list[str] = td.get("strategy_confirmations", [])
    strategy_matched: list[str] = []
    if strategy_keys and (bars_daily or bars_intraday or bars_vwap_daily):
        strategy_matched = _matched_strategy_signals(
            strategy_keys, bars_daily or [], bars_intraday or [], direction,
            interval=interval, bars_vwap_daily=bars_vwap_daily,
        )

    return {
        "structure_matched": structure_matched,
        "structure_total": len(structure_idx),
        "momentum_matched": momentum_matched,
        "momentum_total": len(momentum_idx),
        "matched_indexes": matched_indexes,
        "strategy_matched": strategy_matched,
        "strategy_total": len(strategy_keys),
    }


def format_composite_reason(to_state: str | None, detail: dict) -> str:
    """Build the alert notification reason text from a describe_match() result."""
    parts = [f"Composite Markov trigger: {to_state or 'any'} regime"]
    if detail["structure_total"] and detail["structure_matched"]:
        names = ", ".join(detail["structure_matched"])
        parts.append(f"{len(detail['structure_matched'])}/{detail['structure_total']} structures matched ({names})")
    if detail.get("momentum_total") and detail.get("momentum_matched"):
        names = ", ".join(detail["momentum_matched"])
        parts.append(f"{len(detail['momentum_matched'])}/{detail['momentum_total']} momentum confirmations ({names})")
    if detail["strategy_total"] and detail["strategy_matched"]:
        names = ", ".join(detail["strategy_matched"])
        parts.append(f"{len(detail['strategy_matched'])}/{detail['strategy_total']} mean-reversion strategies fired ({names})")
    return " — ".join(parts)
