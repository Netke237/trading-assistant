"""Composite trigger evaluator — two paths.

evaluate_from_context: WebSocket/alert path — receives pre-computed model outputs.
evaluate_scheduled:    Watch/scheduler path — receives raw bars, runs models internally.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.composite_trigger import CompositeTriggerDef

logger = logging.getLogger(__name__)


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


def _matched_confirmations(trigger_def: dict, structure_signals: list[dict], indicator_values: dict) -> list[str]:
    """Return the signal_kind of each confirmation condition that is met."""
    confirmations = trigger_def.get("confirmations", [])
    matched: list[str] = []
    for conf in confirmations:
        signal_kind = conf.get("signal_kind", "")
        direction = conf.get("direction")  # 'Bullish', 'Bearish', or None
        min_conf = conf.get("min_confidence", 60)
        conf_type = conf.get("type", "structure")

        if conf_type == "structure":
            for sig in structure_signals:
                kind_match = sig.get("kind", "") == signal_kind or sig.get("type", "") == signal_kind
                # market_structure.py uses lowercase directions; trigger def may use title case — compare case-insensitively
                sig_dir = sig.get("direction", "")
                dir_match = direction is None or sig_dir.lower() == direction.lower()
                conf_match = sig.get("confidence", 0) >= min_conf
                if kind_match and dir_match and conf_match:
                    matched.append(signal_kind)
                    break
        elif conf_type == "momentum":
            val = indicator_values.get(signal_kind)
            if val is not None and val >= min_conf:
                matched.append(signal_kind)
    return matched


def _count_confirmations(trigger_def: dict, structure_signals: list[dict], indicator_values: dict) -> int:
    """Count how many confirmation conditions are met."""
    return len(_matched_confirmations(trigger_def, structure_signals, indicator_values))


_MR_STRATEGY_LOOKBACK = 3   # bars scanned to detect a recent signal


def _matched_strategy_signals(
    strategy_keys: list[str],
    bars_daily: list[dict],
    bars_intraday: list[dict],
    direction: str = "Bullish",
) -> list[str]:
    """Return which of the given mean-reversion strategies fired within the last few bars."""
    from app.services.strategy_engine import (
        mean_reversion_rsi_signal,
        mean_reversion_bb_signal,
        mean_reversion_vwap_signal,
    )

    _FNS: dict[str, tuple] = {
        "mean_reversion_rsi":  (mean_reversion_rsi_signal,  "daily"),
        "mean_reversion_bb":   (mean_reversion_bb_signal,   "daily"),
        "mean_reversion_vwap": (mean_reversion_vwap_signal, "intraday"),
    }

    matched: list[str] = []
    for key in strategy_keys:
        entry = _FNS.get(key)
        if entry is None:
            continue
        fn, bar_type = entry
        bars = bars_intraday if bar_type == "intraday" else bars_daily
        if len(bars) < 60:
            logger.debug("_matched_strategy_signals: skipping %s — insufficient bars (%d)", key, len(bars))
            continue
        for i in range(len(bars) - _MR_STRATEGY_LOOKBACK, len(bars)):
            slice_bars = bars[max(0, i - 119): i + 1]
            try:
                if fn(slice_bars, direction=direction) is not None:
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
) -> int:
    """Return how many of the given mean-reversion strategies fired within the last few bars."""
    return len(_matched_strategy_signals(strategy_keys, bars_daily, bars_intraday, direction))


def evaluate_from_context(
    trigger_def: dict,
    omm_result,              # OmmResult dataclass | None
    structure_signals: list[dict],
    indicator_values: dict,
    bars_daily: list[dict] | None = None,
    bars_intraday: list[dict] | None = None,
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
    indicator_values: dict of indicator name → value for momentum confirmations
    bars_daily: OHLCV daily bars — needed if trigger_def sets strategy_confirmations,
        OR if primary.model == "HMM_daily" (used to fit the HMM directly)
    bars_intraday: OHLCV intraday bars — needed if trigger_def sets strategy_confirmations,
        OR if primary.model == "HMM_intraday" (used to fit the HMM directly)
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
        if not bars_intraday:
            logger.warning("evaluate_from_context: HMM_intraday requested but no intraday bars supplied; skipping")
            return False
        try:
            from app.services.regime_hmm import compute_intraday_hmm
            hmm_result = compute_intraday_hmm(bars_intraday)
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
        count = _count_confirmations(td, structure_signals, indicator_values)
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
        )
        if strategy_fired < min_strategy_conf:
            return False

    return True


def evaluate_scheduled(
    symbol: str,
    trigger_def: dict,
    bars_daily: list[dict],
    bars_intraday: list[dict],
) -> bool:
    """Watch/scheduler path. Receives raw bars — runs models internally.

    bars_daily: OHLCV daily bars for OMM and daily HMM
    bars_intraday: OHLCV intraday bars for HMM_intraday (may be empty if not needed)

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

    # Run appropriate model
    primary_met = False
    if model == "OMM":
        if not bars_daily:
            return False
        closes = [b["close"] for b in bars_daily]
        omm_result = compute_omm(closes)
        primary_met = _check_primary_omm(td, omm_result)
    elif model == "HMM_intraday":
        if not bars_intraday:
            logger.warning("evaluate_scheduled: HMM_intraday requested but no intraday bars for %s", symbol)
            return False
        try:
            from app.services.regime_hmm import compute_intraday_hmm
            hmm_result = compute_intraday_hmm(bars_intraday)
            primary_met = _check_primary_hmm(td, hmm_result)
        except Exception as exc:
            # Deliberate fail-closed: if the HMM model errors we suppress the alert
            # (return False) rather than surfacing an error alert, matching the OMM/
            # regime-failure pattern. Logged at WARNING for observability. If this
            # ever needs to become a user-visible error, that is a product decision,
            # not a silent code change.
            logger.warning("evaluate_scheduled: HMM_intraday failed for %s — %s", symbol, exc)
            return False
    elif model == "HMM_daily":
        # compute_intraday_hmm works on any list[dict] with 'close' keys; use daily bars.
        # Requires MIN_BARS=200 daily bars; callers should ensure sufficient history.
        if not bars_daily:
            return False
        try:
            from app.services.regime_hmm import compute_intraday_hmm
            hmm_result = compute_intraday_hmm(bars_daily)
            primary_met = _check_primary_hmm(td, hmm_result)
        except Exception as exc:
            # Deliberate fail-closed: see the HMM_intraday branch above for rationale.
            logger.warning("evaluate_scheduled: HMM_daily failed for %s — %s", symbol, exc)
            return False
    elif model == "any":
        primary_met = True

    if not primary_met:
        return False

    # Count structure confirmations (only runs if min_confirmations > 0).
    min_conf_count = td.get("min_confirmations", 1)
    if min_conf_count > 0:
        structure_signals: list[dict] = []
        if bars_daily:
            try:
                # compute_structure(candles, interval, symbol) is the entry point
                structure_signals = compute_structure(bars_daily, "1D", symbol) or []
            except Exception as exc:
                logger.warning("evaluate_scheduled: structure detection failed for %s — %s", symbol, exc)

        count = _count_confirmations(td, structure_signals, {})
        if count < min_conf_count:
            return False

    # Strategy confirmations — independent N-of-M gate for mean-reversion strategies.
    # Evaluated regardless of min_confirmations to ensure the strategy gate is never skipped.
    strategy_conf_list: list[str] = td.get("strategy_confirmations", [])
    min_strategy_conf: int = td.get("min_strategy_confirmations", 1)
    if strategy_conf_list:
        direction: str = td.get("direction") or "Bullish"
        strategy_fired = _check_strategy_signals(strategy_conf_list, bars_daily, bars_intraday, direction=direction)
        if strategy_fired < min_strategy_conf:
            return False

    return True


def describe_match(
    trigger_def: dict,
    *,
    structure_signals: list[dict] | None = None,
    indicator_values: dict | None = None,
    bars_daily: list[dict] | None = None,
    bars_intraday: list[dict] | None = None,
    symbol: str = "",
    direction: str = "Bullish",
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

    structure_matched = _matched_confirmations(td, structure_signals or [], indicator_values or {})

    strategy_keys: list[str] = td.get("strategy_confirmations", [])
    strategy_matched: list[str] = []
    if strategy_keys and (bars_daily or bars_intraday):
        strategy_matched = _matched_strategy_signals(strategy_keys, bars_daily or [], bars_intraday or [], direction)

    return {
        "structure_matched": structure_matched,
        "structure_total": len(td.get("confirmations", [])),
        "strategy_matched": strategy_matched,
        "strategy_total": len(strategy_keys),
    }


def format_composite_reason(to_state: str | None, detail: dict) -> str:
    """Build the alert notification reason text from a describe_match() result."""
    parts = [f"Composite Markov trigger: {to_state or 'any'} regime"]
    if detail["structure_total"] and detail["structure_matched"]:
        names = ", ".join(detail["structure_matched"])
        parts.append(f"{len(detail['structure_matched'])}/{detail['structure_total']} structures matched ({names})")
    if detail["strategy_total"] and detail["strategy_matched"]:
        names = ", ".join(detail["strategy_matched"])
        parts.append(f"{len(detail['strategy_matched'])}/{detail['strategy_total']} mean-reversion strategies fired ({names})")
    return " — ".join(parts)
