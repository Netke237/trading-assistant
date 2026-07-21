"""Derive an option contract's DTE window from an intended holding period.

An option should never be held to expiry — theta decay accelerates in the final
weeks. The contract's days-to-expiry must therefore exceed the intended hold so
the position can be exited with time value remaining.

One rule, applied uniformly to every horizon preset including Custom:

    min_dte = max(1, round(hold_min * multiplier))
    max_dte = round(hold_max * multiplier)

The bottom clamp only ever engages for the Intraday preset, where a 0-day hold
would otherwise produce an untradeable 0-DTE contract.
"""

import logging

# Monthly option cycles are spaced ~30-35 days apart; a fixed-width DTE window
# can straddle a real expiration by a handful of days on either side (e.g. the
# Semi-annual preset's 180-210d window missing listed 179d/214d expiries).
# Shared by the chain-fetch fallback (market.py's _nearest_expiration_in_window)
# and the contract hard-reject bounds (scan.py's contract_overrides) so a
# contract the fetch accepted as "close enough" isn't then hard-rejected by a
# stricter min_dte/max_dte than the one the fetch actually used.
DTE_WINDOW_TOLERANCE_DAYS = 10


def widened_min_dte(lo: int, hold_max_days: int | None) -> int:
    """Lower hard-reject bound after applying DTE_WINDOW_TOLERANCE_DAYS, floored
    so it can never drop below the holding period itself.

    A flat tolerance subtraction is safe for wide windows (Semi-annual: lo=180,
    hold_max_days=105 — lo-10=170 stays far above hold_max) but not for narrow
    ones (Swing: lo=10, hold_max_days=15 — lo-10=0 would accept a contract that
    expires before the intended hold is even over, violating this module's own
    "dte must exceed the intended hold" rule). Clamping to hold_max_days+1
    guarantees the contract always outlives the hold, regardless of how far the
    flat tolerance would otherwise pull the floor down.

    hold_max_days=None (no holding-horizon override in play) skips the clamp —
    there is no intended hold to protect.
    """
    floor = max(1, lo - DTE_WINDOW_TOLERANCE_DAYS)
    if hold_max_days is not None:
        floor = max(floor, hold_max_days + 1)
    return floor


def dte_window(hold_min: int, hold_max: int, multiplier: float) -> tuple[int, int]:
    """Return the (min_dte, max_dte) contract window for a holding period.

    Args:
        hold_min:   Minimum intended holding period, in calendar days. >= 0.
        hold_max:   Maximum intended holding period, in calendar days. >= hold_min.
        multiplier: DTE-to-holding ratio. Must be > 0.

    Returns:
        (min_dte, max_dte), both >= 1, with max_dte >= min_dte.

    Raises:
        ValueError: on negative holds, a non-positive multiplier, or hold_max < hold_min.
    """
    if hold_min < 0 or hold_max < 0:
        raise ValueError(f"holding period must be non-negative, got ({hold_min}, {hold_max})")
    if hold_max < hold_min:
        raise ValueError(f"hold_max {hold_max} is below hold_min {hold_min}")
    if multiplier <= 0:
        raise ValueError(f"multiplier must be positive, got {multiplier}")

    min_dte = max(1, round(hold_min * multiplier))
    max_dte = round(hold_max * multiplier)
    if max_dte < min_dte:
        max_dte = min_dte
    return min_dte, max_dte


_log = logging.getLogger(__name__)


def resolve_dte_bounds(
    hold_min_days: int | None,
    hold_max_days: int | None,
    multiplier_fn,
    *,
    log_context: str = "",
) -> tuple[int, int] | None:
    """Resolve a (min_dte, max_dte) window from hold days, or None if unavailable.

    `multiplier_fn` is a zero-arg callable (typically `dte_holding_multiplier`
    itself, passed uncalled) rather than an already-resolved float. Both the
    call to `multiplier_fn()` and the call to `dte_window()` happen inside the
    same try/except here — in the original duplicated code, resolving the
    multiplier and computing the window were both wrapped by one try/except at
    each call site, so a non-numeric config value (`float()` raising ValueError
    inside `dte_holding_multiplier()`) degraded gracefully exactly like a
    zero/negative multiplier did. Accepting a callable instead of a float
    preserves that: if this took a pre-resolved `multiplier: float` parameter,
    the caller would have to call `multiplier_fn()` itself *before* this
    function, outside any try/except, silently reintroducing a crash path this
    refactor is supposed to remove, not add.

    Returns None when either hold value is missing (no override requested), or
    when resolving the multiplier or computing the window fails (e.g. a
    misconfigured dte_holding_multiplier — 0, negative, or non-numeric — in
    contract_rules.yaml) — callers should fall back to their own
    fetch/validator defaults rather than 500 a request driven by otherwise-valid
    user input.

    Raises ValueError if hold_max_days < hold_min_days. Ordering should already
    be rejected at the API boundary (ScanRequest's model_validator; the explicit
    check added to /api/contracts in Task 2) before this is ever called — this
    raise is a guardrail against a future caller skipping that check, so a bad
    range fails loudly here instead of being silently absorbed into "no override,
    use defaults" the way it was before this plan.
    """
    if hold_min_days is None or hold_max_days is None:
        return None
    if hold_max_days < hold_min_days:
        raise ValueError(f"hold_max_days {hold_max_days} is below hold_min_days {hold_min_days}")
    try:
        return dte_window(hold_min_days, hold_max_days, multiplier_fn())
    except (ValueError, TypeError) as exc:
        _log.error(
            "%sdte_window computation failed, falling back to config defaults: %s",
            f"{log_context} " if log_context else "", exc,
        )
        return None
