"""The repricing horizon — "how far ahead do we reprice an option when we ask
what it is worth AT a barrier".

Spec: docs/superpowers/plans/2026-09-02-barrier-race-spec.md §2.2 (decision Q2).

This module is the ONLY place that rule lives. Before this existed, two call
sites each hardcoded ``dte_at_target = max(expiry_years * 0.5, 7 / 365)`` — a
fixed half-life that ignores both how long the user actually intends to hold
and what the simulation itself observed.

The rule, in order:

1. If the Monte Carlo produced a conditional median number of days to that
   specific barrier, use it. It is the best available estimate of *when* the
   barrier gets hit, measured on the same paths that decided *whether* it does.
2. Otherwise fall back to a per-preset table, keyed on the HOLDING preset
   (Intraday…Annual), never on the collapsed scoring horizon.
3. ``Custom`` has no table row: derive it from the typed hold range.
4. Clamp to at least ``min_days`` and at most ``max_fraction_of_dte`` of the
   contract's remaining life — repricing past expiry silently prices every
   level at intrinsic value only. When those two bounds conflict (a 1-DTE
   contract, where 0.75 x dte is under a day) the DTE CEILING WINS: the floor
   exists to stop an absurdly short horizon, but letting it push the barrier
   past expiry is the worse error of the two.

DAYS ELAPSED, NOT TIME REMAINING. Everything this module returns is a number of
days UNTIL a barrier is reached, counted forward from today. Black-Scholes wants
the opposite — time to expiry REMAINING at that moment. Converting between them
is ``remaining_years_at_barrier`` below, and it is not optional: feeding elapsed
days straight into ``bs_price`` inverts theta, so the LATER the simulation says a
stop gets hit the MORE the contract appears to be worth at it.
"""
from __future__ import annotations

import math
from typing import Optional

from app.services.config_loader import load_reprice_horizon_cfg

# Every key HORIZON_PRESETS (frontend/lib/horizonPresets.ts:34) can send us.
# "Custom" is deliberately absent from fallback_days — it derives instead.
_CUSTOM = "Custom"


def resolve_reprice_days(
    preset: Optional[str],
    hold_min: Optional[float],
    hold_max: Optional[float],
    dte: float,
    sim_median: Optional[float],
    cfg: Optional[dict] = None,
) -> float:
    """Days ahead to reprice at, for one barrier.

    ``sim_median`` is the simulation's own conditional median days to THAT
    barrier (``None`` when no path reached it). ``dte`` is calendar days to
    expiry. Returns a number of days ELAPSED until the barrier — never a time
    to expiry; see the module docstring and ``remaining_years_at_barrier``.

    Bounds: when ``dte`` is positive the result is always
    <= ``max_fraction_of_dte * dte``, so the barrier can never land at or past
    expiry; otherwise it is always >= ``clamp.min_days``. The ceiling wins when
    the two conflict.
    """
    cfg = cfg if cfg is not None else load_reprice_horizon_cfg()
    fallback = cfg.get("fallback_days", {}) or {}
    clamp = cfg.get("clamp", {}) or {}
    min_days = float(clamp.get("min_days", 1))
    max_fraction = float(clamp.get("max_fraction_of_dte", 0.75))

    days: Optional[float] = None

    if cfg.get("source", "simulation_median") == "simulation_median" and _usable(sim_median):
        days = float(sim_median)   # type: ignore[arg-type]

    if days is None:
        days = _fallback_days(preset, hold_min, hold_max, fallback, cfg)

    # Clamp. The DTE ceiling only applies when we actually know the DTE — a
    # non-positive or non-finite dte means "unknown", and silently collapsing
    # to min_days there would be a worse answer than the preset's own.
    #
    # The ceiling is applied LAST, so it wins when it conflicts with the floor.
    # On a 1-DTE contract 0.75 x dte is 0.75 of a day and min_days is 1: letting
    # the floor win there puts the barrier exactly AT expiry, leaving zero
    # remaining life and pricing every level at intrinsic value only — the very
    # thing max_fraction_of_dte exists to prevent.
    days = max(min_days, days)
    if dte is not None and _usable(dte) and dte > 0:
        days = min(days, max_fraction * float(dte))
    return days


def _fallback_days(
    preset: Optional[str],
    hold_min: Optional[float],
    hold_max: Optional[float],
    fallback: dict,
    cfg: dict,
) -> float:
    """The per-preset table, or Custom's derivation from the typed range."""
    if preset == _CUSTOM:
        custom = cfg.get("custom", {}) or {}
        fraction = float(custom.get("fraction", 0.5))
        lo = float(hold_min) if _usable(hold_min) else None
        hi = float(hold_max) if _usable(hold_max) else None
        if lo is None and hi is None:
            # "Custom" with nothing typed carries no information at all.
            # Deriving from a 0-0 range would silently return 0 days (then the
            # floor, so 1) — a made-up answer dressed as a derived one. Fall
            # through to the table's own default instead.
            return float(fallback.get("Swing", 7))
        lo = lo if lo is not None else hi
        hi = hi if hi is not None else lo
        # Chosen over snapping to the nearest preset: a manual 30-35 day range
        # sits between Position and Quarterly and either snap moves the
        # repriced loss by real money. scoringHorizonForHold already sets the
        # precedent of deriving from the typed range.
        return ((lo + hi) / 2.0) * fraction

    if preset in fallback:
        return float(fallback[preset])

    # Unknown/absent preset: Swing is the app's own default horizon
    # (presetByKey falls back to HORIZON_PRESETS[1], which is Swing).
    return float(fallback.get("Swing", 7))


def remaining_years_at_barrier(
    dte: float, days_to_barrier: float, floor_years: float = 1e-6,
) -> float:
    """Time to expiry REMAINING, in years, at the moment a barrier is reached.

    ``days_to_barrier`` is what resolve_reprice_days returns: days ELAPSED from
    today until the barrier. Black-Scholes wants what is left after that, so the
    conversion is ``dte - days_to_barrier``, never ``days_to_barrier`` itself.

    THE TRAP THIS EXISTS FOR: passing elapsed days into bs_price's ``T`` inverts
    theta. A stop hit on day 2 of a 60-day contract would be priced as if two
    days of life remained (worth ~nothing, so the risk leg swallows the whole
    premium), while a stop hit on day 45 would be priced as if 45 days remained
    (worth MORE than the earlier one). Both wrong, and wrong in the direction
    that overstates risk on exactly the fast stop-outs that matter most.

    Floors at ``floor_years`` rather than returning zero or negative: bs_price
    returns 0.0 for T <= 0, which is intrinsic value, and that is the right
    answer at expiry — but the floor keeps the call in the pricing branch so a
    barrier clamped to the very end of the contract still prices continuously.
    """
    if not _usable(dte) or not _usable(days_to_barrier):
        return floor_years
    return max((float(dte) - float(days_to_barrier)) / 365.0, floor_years)


def _usable(x: Optional[float]) -> bool:
    """Finite and numeric. math.isfinite rather than an identity check against
    the infinities: it also rejects NaN (which compares equal to nothing,
    itself included) and accepts numpy scalars, which arrive here from the
    simulation's own medians."""
    if x is None:
        return False
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False
