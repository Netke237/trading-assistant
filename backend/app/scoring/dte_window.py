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
