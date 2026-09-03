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
4. Clamp the result. THE ``max_fraction_of_dte`` PART APPLIES TO THE FALLBACK
   ONLY (see rule 5). Clamp a fallback to at least ``min_days`` and at most
   ``max_fraction_of_dte`` of the contract's remaining life — a table keyed on
   how long you intend to HOLD knows nothing about this contract's expiry, so
   "Annual" on a 30-day contract would otherwise reprice at 80 days, past
   expiry, and price every level at intrinsic value only. When those two bounds
   conflict (a 1-DTE contract, where 0.75 x dte is under a day) the DTE CEILING
   WINS: the floor exists to stop an absurdly short horizon, but letting it push
   the barrier past expiry is the worse error of the two.

   THE ``max_fraction_of_dte`` CEILING DOES NOT APPLY TO ``sim_median``. A simulated median cannot
   exceed the contract's own life — it is a day index inside the simulation —
   so there is nothing to protect against, and clamping it silently overrode an
   OBSERVED number with an arbitrary fraction. On the reference contract the
   simulation said the stop is typically reached on day 26 of 30 and the clamp
   returned 22.5, which valued the contract at the stop as though 7.5 days of
   life were left instead of 4: risk understated by about 3.5% ($5.17 -> $4.99)
   and R:R overstated by about the same (0.2012 -> 0.2084), always in the
   flattering direction, on the number the card bolds as THE measurement — and the card printed "median ~26d" three inches above
   "repriced at 22.5d" with nothing to explain the gap.

5. Whatever the source, the answer is capped half a day short of expiry
   (``_latest_barrier_day``), so there is always some life left to price with.
   A simulated median cannot exceed the contract's life but it can EQUAL it.

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

    Bounds, precisely:

    * A FALLBACK value is clamped to ``[min_days, max_fraction_of_dte * dte]``,
      the ceiling winning when the two conflict — a holding-period table knows
      nothing about this contract's expiry.
    * A usable ``sim_median`` is floored at ``min_days`` and capped half a day
      short of expiry, but ``max_fraction_of_dte`` NEVER applies to it: it
      cannot exceed the contract's life by construction, and overriding a
      measured value with an arbitrary fraction is a worse answer, not a safer
      one. The half-day cap is not that fraction — it only stops a median that
      lands exactly ON expiry from leaving zero life to price with.

    So ``resolve_reprice_days("Swing", None, None, dte=1, sim_median=1.0)`` is
    0.5, and ``(..., dte=30, sim_median=0.1)`` is 1.0. Both bounds do reach the
    simulated median; only the DTE fraction does not.
    """
    cfg = cfg if cfg is not None else load_reprice_horizon_cfg()
    fallback = cfg.get("fallback_days", {}) or {}
    clamp = cfg.get("clamp", {}) or {}
    min_days = float(clamp.get("min_days", 1))
    max_fraction = float(clamp.get("max_fraction_of_dte", 0.75))

    if cfg.get("source", "simulation_median") == "simulation_median" and _usable(sim_median):
        # Returned as observed, NOT clamped to max_fraction_of_dte. See the
        # module docstring: that ceiling exists to protect the FALLBACK from a
        # holding-period table that knows nothing about this contract's expiry,
        # and overriding a measurement with an arbitrary fraction of DTE is a
        # worse answer rather than a safer one.
        #
        # It IS capped just short of expiry, though. A simulated median cannot
        # exceed the contract's life, but it can EQUAL it: the median is a day
        # index plus one, so it ranges 1..dte, and at dte exactly the remaining
        # life collapses to remaining_years_at_barrier's floor and every level
        # prices at intrinsic value only — the outcome the ceiling exists to
        # prevent, arrived at from the other direction. Reachable whenever the
        # simulated median lands on the final day — always the case at dte=1,
        # where the median is exactly 1.0.
        #
        # THE CEILING IS APPLIED LAST, so it wins when it conflicts with the
        # min_days floor — the same precedence the fallback branch below uses,
        # and for the same reason. Written the other way round (`max(min_days,
        # min(median, dte - 0.5))`) the floor won at dte=1, which is where a
        # simulated median is ALWAYS exactly 1.0, so the cap silently did
        # nothing on precisely the contracts it mattered most for: a 1-DTE
        # stop priced at zero remaining life makes the risk leg the whole
        # premium and collapses rr_stock_stop to exactly the typed target
        # percentage — indistinguishable from the greyed constant it is printed
        # beside, on a card whose point is that the two differ.
        return min(max(min_days, float(sim_median)), _latest_barrier_day(dte))

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


def _latest_barrier_day(dte: float) -> float:
    """The latest day a barrier may be said to be reached, so there is always
    some life left to price with. Returns +inf when the DTE is unknown, leaving
    the caller's other bounds to decide.

    Half a day before expiry, EXCEPT on a sub-1-day contract, where a flat
    "dte - 0.5" floored at 0.5 lands at or past expiry — 0.5 on a 0.4-day
    contract — which is the exact outcome this cap exists to prevent, reached
    from the other side. Falling back to half the remaining life keeps it
    strictly inside the contract for any positive DTE. Not reachable through
    the race today (estimate_first_passage refuses dte < 1), but Stage 1 calls
    resolve_reprice_days BEFORE that guard, and this module is documented as the
    single owner of the rule."""
    if dte is None or not _usable(dte) or dte <= 0:
        return float("inf")
    latest = float(dte) - 0.5
    if latest <= 0:
        # Sub-1-day contract: half its remaining life, which is strictly inside
        # it. Taking a min() of the two instead would cap EVERY median at half
        # the DTE — reintroducing the fixed half-life this module exists to
        # replace, on every contract rather than the sub-1-day ones.
        #
        # UNREACHABLE TODAY, and kept anyway so the rule is total. The only
        # caller of _latest_barrier_day is the sim_median branch, and the only
        # way to have a sim_median is to have run the simulation, which
        # estimate_first_passage refuses below dte 1. An earlier version of this
        # comment claimed Stage 1 reached it — Stage 1 passes sim_median=None
        # and takes the fallback branch, which never calls this.
        latest = float(dte) * 0.5
    return latest


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
        if (lo + hi) <= 0:
            # A typed 0-0 range is the same non-information as an empty one, and
            # reachable: HORIZON_PRESETS' Intraday row carries holdMin 0, so
            # zeros do arrive here. Deriving 0 days from it, then flooring to 1,
            # is the made-up-answer-dressed-as-a-derived-one this branch exists
            # to avoid.
            return float(fallback.get("Swing", 7))
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
