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


def _count_confirmations(trigger_def: dict, structure_signals: list[dict], indicator_values: dict) -> int:
    """Count how many confirmation conditions are met."""
    confirmations = trigger_def.get("confirmations", [])
    if not confirmations:
        return 0
    count = 0
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
                    count += 1
                    break
        elif conf_type == "momentum":
            val = indicator_values.get(signal_kind)
            if val is not None and val >= min_conf:
                count += 1
    return count


_MR_STRATEGY_LOOKBACK = 3   # bars scanned to detect a recent signal


def _check_strategy_signals(
    strategy_keys: list[str],
    bars_daily: list[dict],
    bars_intraday: list[dict],
) -> int:
    """Return how many of the given mean-reversion strategies fired within the last few bars."""
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

    count = 0
    for key in strategy_keys:
        entry = _FNS.get(key)
        if entry is None:
            continue
        fn, bar_type = entry
        bars = bars_intraday if bar_type == "intraday" else bars_daily
        if len(bars) < 60:
            continue
        for i in range(len(bars) - _MR_STRATEGY_LOOKBACK, len(bars)):
            slice_bars = bars[max(0, i - 119): i + 1]
            try:
                if fn(slice_bars) is not None:
                    count += 1
                    break
            except Exception:
                pass
    return count


def evaluate_from_context(
    trigger_def: dict,
    omm_result,              # OmmResult dataclass | None
    structure_signals: list[dict],
    indicator_values: dict,
) -> bool:
    """Alert/WebSocket path. Receives pre-computed model outputs — no I/O.

    trigger_def: CompositeTriggerDef serialized as dict (or the Pydantic model)
    omm_result: OmmResult dataclass from compute_omm() — attribute access (.state, .conviction_pct, .p_stay)
    structure_signals: list of market structure signal dicts from market_structure.py
    indicator_values: dict of indicator name → value for momentum confirmations
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
    elif model in ("HMM_intraday", "HMM_daily"):
        # For the alert path, hmm result is passed via omm_result slot (caller must adapt)
        # In practice, alert path uses OMM only — HMM is for watch path
        logger.warning("evaluate_from_context: HMM model requested but only OMM result provided; skipping")
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
            logger.warning("evaluate_scheduled: HMM_daily failed for %s — %s", symbol, exc)
            return False
    elif model == "any":
        primary_met = True

    if not primary_met:
        return False

    # Count confirmations using structure detection on daily bars
    min_conf_count = td.get("min_confirmations", 1)
    if min_conf_count == 0:
        return True

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
    strategy_conf_list: list[str] = td.get("strategy_confirmations", [])
    min_strategy_conf: int = td.get("min_strategy_confirmations", 1)
    if strategy_conf_list:
        strategy_fired = _check_strategy_signals(strategy_conf_list, bars_daily, bars_intraday)
        if strategy_fired < min_strategy_conf:
            return False

    return True
