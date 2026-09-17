"""Conviction-based position sizing — the single source of the multiplier.

This module exists because the formula used to live in two places that had
drifted apart:

    auto_trader.py   max(min_mult, min(1.0, conv / full))      # clamp
    stock_scan.py    min_mult + (1 - min_mult) * frac          # ramp

Those agree only at the endpoints. Under the shipped config (min_mult 0.5,
full_conviction_pct 40) the clamp form binds for every conviction from 0 to
20, so the whole bottom half of the conviction scale produced one identical
position size, and the two paths sized the same setup up to 1.5x apart at
conviction 20 — the scan card showing one number while the auto-trader
executed another.

The ramp is the form kept, because that is what a floor is for: it rescales
conviction onto [min_mult, 1] so every distinct conviction maps to a distinct
size while still guaranteeing the floor. Risk appetite is expressed through
min_mult, not through the shape of the curve.

Both callers now import this function. Do not re-inline it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def conviction_mult(conviction_pct: float, sizing: Mapping[str, Any]) -> float:
    """Return the position-size multiplier for `conviction_pct`, in [min_mult, 1].

    `sizing` is the `regime_sizing` block of scoring_rules.yaml. When the block
    is disabled or absent the multiplier is 1.0 (size unchanged).

    Conviction is clamped into [0, full_conviction_pct] before scaling, so a
    headwind (negative conviction) floors at min_mult rather than going below
    it, and conviction above full_conviction_pct caps at 1.0.
    """
    if not sizing.get("enabled", False):
        return 1.0

    full = float(sizing.get("full_conviction_pct", 40) or 0.0)
    # Clamped into [0, 1]: min_mult is a floor on a multiplier, so a
    # misconfigured value must never let this scale a position *up*.
    lo = max(0.0, min(1.0, float(sizing.get("min_mult", 0.5))))

    # full == 0 would divide by zero; treat "no conviction scale" as no
    # conviction, which floors the multiplier at min_mult.
    frac = max(0.0, min(conviction_pct / full, 1.0)) if full else 0.0

    return lo + (1.0 - lo) * frac
