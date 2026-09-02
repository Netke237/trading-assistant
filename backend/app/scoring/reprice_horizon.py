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
   level at intrinsic value only.
"""
from __future__ import annotations

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
    expiry. Returns a float number of days, always >= ``clamp.min_days`` and,
    when ``dte`` is positive, always <= ``max_fraction_of_dte * dte``.
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
    if dte is not None and _usable(dte) and dte > 0:
        days = min(days, max_fraction * float(dte))
    return max(min_days, days)


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
        lo = float(hold_min) if _usable(hold_min) else 0.0
        hi = float(hold_max) if _usable(hold_max) else lo
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


def _usable(x: Optional[float]) -> bool:
    if x is None:
        return False
    try:
        v = float(x)
    except (TypeError, ValueError):
        return False
    return v == v and v not in (float("inf"), float("-inf"))
