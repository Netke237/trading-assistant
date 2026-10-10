"""Heston calibration: seed, objective, and the baseline gate (Phase F2).

Read `docs/superpowers/plans/2026-09-12-heston-calibration-spec.md` section 3
before changing anything here. Three things in this file were defects, and all
three fed the same number -- the exit premium in the target ladder and the
numerator of the R/R ratio on any card labelled "Heston repriced":

  1. `v0_grid = [0.04]` -- ONE hardcoded seed, 20% vol, every symbol, every
     scan. `v0` is the INSTANTANEOUS variance and the chain states it
     directly; on the spec's 45-DTE reference chain the chain's own IV says
     0.1245 (35.28% vol) and no setting of the shipped code could reach it.
     F2 solves it out of the chain's own mids instead (`_seed_v0`).
  2. The objective was absolute dollars, so one $20 in-the-money contract
     outweighed ten $1 wing contracts -- and the wings carry the smile that
     the other four Heston parameters exist to fit. Now relative.
  3. Nothing checked whether Heston was worth using at all. Post-F1 with the
     hardcoded seed the fit was 3.27x (45 DTE) and 1.34x (180 DTE) WORSE than
     a single flat volatility, and shipped to the card anyway. `_flat_bs_
     baseline` is now the comparator and the gate returns `method="bs_flat"`
     when Heston loses, which `scan.py` discards exactly as it discards
     `bs_fallback`.

Measured on the spec's section 7 reference chain, relative RMSE, post-F1
pricer, in-band strikes only:

    45 DTE (10 strikes)    shipped v0=[0.04]  0.6388   flat-BS  0.1969  REJECT
                           chain seed 0.1245  0.0796   flat-BS  0.1969  ACCEPT
    180 DTE (28 strikes)   shipped v0=[0.04]  0.6566   flat-BS  0.3965  REJECT
                           chain seed 0.1645  0.3163   flat-BS  0.3965  ACCEPT
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
from dataclasses import replace
from functools import lru_cache
from typing import Optional

from app.models.heston import HestonParams, CalibrationResult, heston_price
from app.models.black_scholes import bs_iv, bs_price
from app.data.market import _compute_iv_bs

_log = logging.getLogger(__name__)

_USE_FULL_GRID = os.getenv("HESTON_FULL_CALIBRATION", "").lower() in ("1", "true")

# The seed of last resort: used ONLY when not one strike on the chain inverts.
# This is the value that used to be the whole v0 grid.
_FALLBACK_V0 = 0.04

# Bracket for the flat-BS baseline's single volatility, and the two-stage
# search over it: a coarse sweep to find the basin, then a golden-section
# contraction inside it. Deliberately not a scipy minimiser -- the global
# sweep is what keeps this honest on a chain whose objective is not unimodal,
# and an under-fitted baseline is the one error direction that MATTERS here:
# it overstates the baseline's error and lets a bad Heston fit through the
# gate. Erring the other way only costs Heston a fit it did not deserve.
#
# THE EVALUATION BUDGET IS LOAD-BEARING, not a micro-optimisation.
# `bs_price` calls `scipy.stats.norm.cdf` twice per price, ~35us each, so the
# baseline's cost is (evals x strikes x 70us). A first cut at 200 sweep steps
# plus 40 ternary iterations came to 280 evals and took 0.608s on the 28-
# strike 180-DTE reference chain -- 53% of the whole calibration, pushing it
# from 0.547s to 1.156s -- which, while this file still had its own 1.0s
# inner timeout, turned every long-dated fit into a discarded `bs_fallback`.
# That timeout is gone (see `calibrate_cached`), so the budget no longer
# decides a LABEL; it still decides how much of scan.py's outer 2.0s ceiling
# one calibration spends, which is the same pressure one layer out. F2 must
# not cost Heston the chains it used to price. 24 sweep points + 2 + 20 golden-section
# steps = 46 evals reaches the same sigma to ~1e-3 (the objective is
# quadratic at its minimum, so that is ~1e-6 in rel-RMSE -- far below any
# margin the gate decides on) for a sixth of the work.
#
# The sweep is GEOMETRIC, and the bracket is `_compute_iv_bs`'s own. A linear
# sweep has to choose between resolution near a typical 30% vol and reach into
# the wings: 24 linear steps to 300% are 12.5 vol points apart, and raising the
# ceiling to the solver's 2000% would make them 83 points apart. Log spacing is
# 1.38x per step everywhere, so the basin is bracketed as tightly at 15% vol as
# at 1500%, and the ceiling costs nothing. It matters in one direction only,
# which is the dangerous one: a baseline that could not reach the chain's true
# best sigma would OVERSTATE the baseline's error and let a bad Heston fit
# through the gate.
_BASELINE_SIGMA_LO, _BASELINE_SIGMA_HI = 0.01, 20.0
_BASELINE_COARSE_STEPS = 24
_BASELINE_REFINE_ITERS = 20
_BASELINE_SWEEP_RATIO = (_BASELINE_SIGMA_HI / _BASELINE_SIGMA_LO) ** (1.0 / _BASELINE_COARSE_STEPS)
_INV_PHI = (math.sqrt(5.0) - 1.0) / 2.0


def _iv_surface_key(option_chain: list[dict], S: float, r: float) -> str:
    payload = str(sorted(
        (c.get("strike"), c.get("expiry_years"), c.get("mid_price"))
        for c in option_chain
    )) + f"|S={round(S, 2)}|r={round(r, 4)}"
    return hashlib.md5(payload.encode()).hexdigest()


def _seed_v0(chain: list[dict], S: float, r: float) -> float:
    """Solve `v0` out of the chain: the mean implied vol of every strike that
    inverts, squared.

    THE SOLVER IS NOT INTERCHANGEABLE. `_compute_iv_bs` is a BRACKETED solve
    (scipy brentq); `bs_iv` is a Newton loop that returns None on most of a
    realistically skewed chain -- measured 8/10 at 45 DTE and 18/28 at 180 DTE
    on the spec's reference chains, and it is always the WINGS it drops, which
    is exactly the part of the smile this seed is meant to see.
    `_compute_iv_bs` solves 10/10 and 28/28 on the same two chains.

    MEAN, NOT ATM -- and that is one measurement, not a law. The mean beat the
    ATM strike on both reference chains (45 DTE rel-RMSE 0.0796 vs 0.0919;
    180 DTE 0.3163 vs 0.3744), which is the OPPOSITE of what theory predicts,
    because the 180-DTE delta band reaches far enough into the wings to pull
    the mean up toward the smile. Decision F2-V0-SEED-2026-09-13 ships the
    measured winner and records the ATM alternative as UNMEASURED on real
    chains, in the same register as Phase A's seeded IV thresholds.

    THE UNIT TRAP, pinned by `test_seed_rejects_the_expiry_years_unit_trap`:
    `_compute_iv_bs` takes `dte` in DAYS. The chain dicts carry
    `expiry_years`. Feeding one to the other yields a seed of v0 = 45.23
    (672% vol) instead of 0.1245 on the 45-DTE reference chain -- measured,
    not hypothesised. Hence the `* 365.0` below, and hence a float rather than
    an int: rounding would lose sub-day expiries, and `_compute_iv_bs` only
    ever divides `dte` by 365.0.
    """
    ivs: list[float] = []
    for c in chain:
        mid = c.get("mid_price", 0.0)
        expiry_years = c.get("expiry_years", 0.0)
        if mid <= 0 or expiry_years <= 0:
            continue
        iv = _compute_iv_bs(mid, S, c["strike"], expiry_years * 365.0,
                            c.get("is_call", True), r)
        if iv is not None and iv > 0:
            ivs.append(iv)
    if not ivs:
        return _FALLBACK_V0
    return (sum(ivs) / len(ivs)) ** 2


def _rel_rmse(model_prices: list[float], mids: list[float]) -> float:
    """Root-mean-square RELATIVE residual, `(model - mid) / mid`.

    Absolute dollars let one deep in-the-money contract dominate the whole
    objective; the wings, which carry the smile, contributed almost nothing.
    See spec section 3.2 -- vega weighting was the other candidate and was
    rejected there (it needs a per-strike IV solve inside the hot loop for a
    weighting relative error already approximates on this chain shape).
    """
    n = len(mids)
    return math.sqrt(sum(((p - m) / m) ** 2 for p, m in zip(model_prices, mids)) / n)


def _flat_bs_baseline(
    chain: list[dict], S: float, r: float,
) -> tuple[Optional[float], Optional[float]]:
    """The model Heston has to justify replacing: ONE flat volatility for the
    whole chain, fitted on the same residual. Returns `(rel_rmse, sigma)`, or
    `(None, None)` if not one strike prices.

    NOT "BS at each contract's own IV" -- the phrase the standing plan used.
    That reproduces every mid BY CONSTRUCTION (measured RMSE 0.000005), so
    nothing can beat it and the gate would reject Heston always. It is also
    not a model: it predicts nothing for a strike or a date nobody quoted,
    which is exactly what repricing at a stop asks for.
    """
    mids = [c["mid_price"] for c in chain]
    if not mids:
        return None, None

    def objective(sigma: float) -> float:
        prices = []
        for c in chain:
            try:
                prices.append(bs_price(S, c["strike"], c["expiry_years"], r, sigma,
                                       c.get("is_call", True)))
            except Exception:
                return float("inf")
        try:
            return _rel_rmse(prices, mids)
        except Exception:
            return float("inf")

    best_sigma, best_err = _BASELINE_SIGMA_LO, float("inf")
    for i in range(_BASELINE_COARSE_STEPS + 1):
        sigma = _BASELINE_SIGMA_LO * _BASELINE_SWEEP_RATIO ** i
        err = objective(sigma)
        if err < best_err:
            best_err, best_sigma = err, sigma

    if not math.isfinite(best_err):
        return None, None

    # Golden section inside the winning bracket -- one step of the sweep to
    # either side. One new evaluation per iteration, against two for a ternary
    # contraction at the same contraction rate.
    lo = max(_BASELINE_SIGMA_LO, best_sigma / _BASELINE_SWEEP_RATIO)
    hi = min(_BASELINE_SIGMA_HI, best_sigma * _BASELINE_SWEEP_RATIO)
    c, d = hi - _INV_PHI * (hi - lo), lo + _INV_PHI * (hi - lo)
    f_c, f_d = objective(c), objective(d)
    for _ in range(_BASELINE_REFINE_ITERS):
        if f_c < f_d:
            hi, d, f_d = d, c, f_c
            c = hi - _INV_PHI * (hi - lo)
            f_c = objective(c)
        else:
            lo, c, f_c = c, d, f_d
            d = lo + _INV_PHI * (hi - lo)
            f_d = objective(d)

    # Return the best sigma actually EVALUATED, never the bracket midpoint:
    # the midpoint has not been priced, and the gate must compare Heston
    # against a number the baseline really achieved.
    for sigma, err in ((c, f_c), (d, f_d)):
        if err < best_err:
            best_err, best_sigma = err, sigma
    return best_err, best_sigma


def _boundary_hits(params: HestonParams, grids: dict[str, list[float]]) -> list[str]:
    """Which of the winning parameters sit on an edge of their own grid.

    A winner on a boundary is not a minimum -- it is the search hitting the
    wall of the box. On the spec's reference chains all four searched
    parameters pin (kappa at its floor, theta at its ceiling, sigma_v at its
    ceiling, rho at its floor), and the winning combination also violates the
    Feller condition (2*kappa*theta = 0.08 < sigma_v**2 = 0.36), which says
    the same thing a second way.

    READ THAT CAREFULLY AGAINST THE PARAGRAPH BELOW, because the two look
    contradictory and are not. On a two-rung grid the COUNT is vacuous -- four
    of four always pin. What the reference chains actually observed, and what
    Feller corroborates, is the SIDE pattern: the winner ran to the extremes
    in a consistent direction. The side IS informative on two rungs where the
    count is not.

    This function reports both -- the strings it returns name the side, e.g.
    "kappa=0.5 (grid min)" -- and the gate below therefore suppresses both.
    That is a deliberate cost, not an oversight: the problem being fixed was
    per-symbol VOLUME, which a side-only line would not have reduced, and
    BOUNDARY-LOG-GATE-ON-GRID-2026-09-13 explicitly refused the side-only
    reshape as "more code for evidence nobody has asked a question of yet".
    The side pattern is logged as lost in that decision's open question rather
    than quietly preserved here.

    Decision F2-GRID-AND-EDGE-OF-BOX-2026-09-13 deliberately does NOT widen
    the grid in F2 -- that is a latency decision and a separate change, and
    the baseline gate below already makes a bad fit harmless. This function is
    the one thing F2 does about it: it turns "three of five pinned on one
    synthetic chain" into evidence that accumulates from Kenneth's real scans,
    which is what the widening decision needs and does not have.

    A DIMENSION WITH FEWER THAN THREE RUNGS IS SKIPPED, and that threshold is
    the whole of BOUNDARY-LOG-GATE-ON-GRID-2026-09-13. Two rungs have no
    interior: EVERY value is simultaneously the min or the max, so a hit is
    not a finding about the fit, it is arithmetic about the grid. Enumerated
    on the grid that actually ships, all 16 combinations hit all four searched
    dimensions -- the count is ALWAYS 4 and only the side ever varies, so the
    line reports nothing that could have come out differently. That is also
    why the threshold is a gate rather than a filter on the output: with two
    rungs the diagnostic fired on every accepted fit, roughly 500 WARNING
    lines per S&P 500 scan, in the same stream as the ladder-floor warning
    that exists so a pricer regression gets NOTICED.

    So on today's grid this returns [] and the diagnostic is silent -- which
    is correct, because today's output carries no information. It wakes up by
    itself the moment a dimension gains a third rung, which is exactly when
    F2-GRID-AND-EDGE-OF-BOX wants the evidence. Under
    HESTON_FULL_CALIBRATION=1 the count already discriminates: 80 of 81
    combinations hit at least one boundary, 16 of 81 hit all four, and one
    hits none.

    `v0_grid` is skipped under the same rule without needing a special case:
    it is a single solved seed, on its own boundary by definition, and
    reporting it would be noise rather than evidence.
    """
    hits: list[str] = []
    for name, grid in grids.items():
        if len(grid) < 3:
            continue
        value = getattr(params, name)
        if value == min(grid):
            hits.append(f"{name}={value:g} (grid min)")
        elif value == max(grid):
            hits.append(f"{name}={value:g} (grid max)")
    return hits


@lru_cache(maxsize=256)
def _run_calibration(iv_key: str, chain_repr: str, S: float, r: float) -> CalibrationResult:
    import json
    chain = json.loads(chain_repr)

    # v0 is SOLVED, not searched: it is the instantaneous variance and the
    # chain states it. The smile the chain also carries is not discarded --
    # every strike of it is the calibration target below, and reproducing that
    # smile out of this one scalar is precisely what the other four parameters
    # are for. Giving each strike its own variance would not be a better
    # Heston fit; it would be Black-Scholes at each contract's own IV, which
    # is no model at all (see `_flat_bs_baseline`).
    v0_seed = _seed_v0(chain, S, r)

    if _USE_FULL_GRID:
        kappa_grid   = [0.5, 1.5, 3.0]
        theta_grid   = [0.02, 0.04, 0.08]
        sigma_v_grid = [0.2, 0.4, 0.6]
        rho_grid     = [-0.8, -0.5, -0.2]
    else:
        kappa_grid   = [0.5, 3.0]
        theta_grid   = [0.02, 0.08]
        sigma_v_grid = [0.2, 0.6]
        rho_grid     = [-0.8, -0.2]
    # One seed on BOTH paths. HESTON_FULL_CALIBRATION used to widen v0 to
    # [0.01, 0.04, 0.09], whose top rung is still 30% vol -- so the "full"
    # grid could not seed the reference chain either. A solved v0 does not
    # want alternatives to search over; the other four dimensions still do.
    v0_grid = [v0_seed]

    grids = {"v0": v0_grid, "kappa": kappa_grid, "theta": theta_grid,
             "sigma_v": sigma_v_grid, "rho": rho_grid}

    best_rmse = float("inf")
    best_params = None
    best_chain: list[dict] = []

    for v0 in v0_grid:
        for kappa in kappa_grid:
            for theta in theta_grid:
                for sigma_v in sigma_v_grid:
                    for rho in rho_grid:
                        params = HestonParams(v0=v0, kappa=kappa, theta=theta,
                                              sigma_v=sigma_v, rho=rho)
                        sse = 0.0
                        priced: list[dict] = []
                        for c in chain:
                            mid = c.get("mid_price", 0.0)
                            if mid <= 0:
                                continue
                            try:
                                model_p = heston_price(S, c["strike"], c["expiry_years"],
                                                       r, params, c.get("is_call", True))
                                sse += ((model_p - mid) / mid) ** 2
                                priced.append(c)
                            except Exception:
                                continue
                        if not priced:
                            continue
                        rmse = math.sqrt(sse / len(priced))
                        if rmse < best_rmse:
                            best_rmse = rmse
                            best_params = params
                            best_chain = priced

    if best_params is None:
        fallback = HestonParams(v0=v0_seed, kappa=2.0, theta=v0_seed, sigma_v=0.3, rho=-0.7)
        return CalibrationResult(params=fallback, rmse=float("inf"), method="bs_fallback")

    # The comparison runs on exactly the strikes the WINNING parameters
    # priced, not on the whole chain. Heston is allowed to skip a strike its
    # integration cannot handle; letting it skip the hard ones and then
    # scoring the baseline on all of them would hand Heston a gate it did not
    # pass.
    baseline_rmse, baseline_sigma = _flat_bs_baseline(best_chain, S, r)

    # Decide the verdict BEFORE logging it. The log line names the label this
    # call actually returns; anything else would reintroduce, in the log, the
    # very mislabelling this phase exists to remove.
    if baseline_rmse is None:
        # No flat volatility priced this chain at all, so the gate cannot be
        # run -- and an ungated fit must never be labelled "Heston repriced".
        # bs_fallback is this file's existing "no honest answer" signal and
        # scan.py already discards it.
        result = CalibrationResult(
            params=HestonParams(v0=v0_seed, kappa=2.0, theta=v0_seed,
                                sigma_v=0.3, rho=-0.7),
            rmse=float("inf"), method="bs_fallback",
        )
    elif baseline_rmse <= best_rmse:
        # Heston did not beat one flat volatility. Ties go to the baseline:
        # four extra parameters have to EARN their place, not draw for it.
        result = CalibrationResult(
            params=HestonParams(v0=baseline_sigma ** 2, kappa=2.0,
                                theta=baseline_sigma ** 2, sigma_v=0.3, rho=-0.7),
            rmse=round(baseline_rmse, 6), method="bs_flat",
        )
    else:
        result = CalibrationResult(params=best_params, rmse=round(best_rmse, 6),
                                   method="heston_grid")

    hits = _boundary_hits(best_params, grids)

    # WARNING, not INFO, and that is measured rather than stylistic: the app
    # runs under uvicorn's default logging config, which configures only the
    # `uvicorn*` loggers and leaves the root logger handler-less at WARNING.
    # An `app.*` INFO record is therefore DROPPED, and a silent diagnostic is
    # the exact failure mode these two lines exist to end.
    #
    # VOLUME, and it changed with BOUNDARY-LOG-GATE-ON-GRID-2026-09-13. This
    # used to fire on every calibration THAT REACHED THIS LINE -- roughly one
    # line per calibrated symbol per scan, and UP TO ~500 on an S&P 500 run
    # rather than 500: `scan.py` only reaches the Heston block for symbols
    # with a non-REJECT contract, and the `best_params is None` return above
    # leaves before the log either way. It fired because `_boundary_hits` was
    # tautological on the two-rung grid and so `hits` was never empty. It is
    # now empty on that grid by construction, which leaves this condition
    # equal to `result.method != "heston_grid"`: a line per REJECTED fit,
    # and silence while the gate is accepting. Rejections are the signal
    # worth a WARNING; an accepted fit reporting a boundary it could not
    # have avoided was not.
    # The boundary half of the line returns on its own the day the grid gains
    # a third rung anywhere -- see `_boundary_hits`.
    if hits or result.method != "heston_grid":
        _log.warning(
            "Heston calibration on %d strikes: rel-RMSE %.4f vs flat-BS baseline %s "
            "-> %s; v0 seed %.4f (%.2f%% vol)%s",
            len(best_chain), best_rmse,
            f"{baseline_rmse:.4f}" if baseline_rmse is not None else "unavailable",
            {"heston_grid": "accepted (heston_grid)",
             "bs_flat": "REJECTED (bs_flat)",
             "bs_fallback": "REJECTED (bs_fallback: no flat-BS baseline, "
                            "so the fit could not be gated)"}[result.method],
            v0_seed, math.sqrt(v0_seed) * 100.0,
            f"; winner on grid boundary: {'; '.join(hits)}" if hits else "",
        )

    return result


def calibrate_cached(
    option_chain: list[dict],
    S: float,
    r: float,
) -> CalibrationResult:
    import json

    chain = [c for c in option_chain
             if c.get("mid_price", 0) > 0 and c.get("expiry_years", 0) > 0]

    if len(chain) < 3:
        return CalibrationResult(params=_thin_chain_params(chain, S, r),
                                 rmse=float("inf"), method="bs_fallback")

    iv_key = _iv_surface_key(chain, S, r)
    chain_repr = json.dumps(chain, sort_keys=True)

    # CALLED DIRECTLY, ON THIS THREAD. There used to be a
    # `ThreadPoolExecutor(max_workers=1)` here with a 1.0s
    # `future.result(timeout=...)` on it. It bounded nothing and cost real
    # fits, and BOTH halves of that are measured rather than argued:
    #
    #   IT NEVER BOUNDED LATENCY. Both returns sat inside the `with`, so
    #   `pool.__exit__` -> `shutdown(wait=True)` ran before either reached the
    #   caller, blocking for the whole grid search regardless. The timeout
    #   changed the RESULT (`bs_fallback` instead of the fit that had just
    #   been computed) and nothing else.
    #
    #   IT DISCARDED FITS IT HAD ALREADY COMPUTED. On a staggered 40-symbol
    #   scan slice driven through scan.py's own machinery, with the outer
    #   2.0s guard removed so that this timeout was the only thing in play:
    #   BEFORE, 40 of 40 symbols returned `bs_fallback` (median wait 17.7s,
    #   minimum 3.75s -- not one anywhere near 1.0s); AFTER, the same 40
    #   return `heston_grid` (median 16.8s, minimum 3.66s). Same work, same
    #   wall time, 40 fits kept instead of 40 thrown away. Both halves
    #   measured with the SAME contention model, so this is a before/after
    #   rather than two readings; `scripts/heston_latency_probe.py` is the
    #   after half and the before half reconstructs this block verbatim.
    #
    # WHAT THIS DOES NOT DO, stated plainly because the measurement refused
    # to support the more flattering version: on the box this was measured on
    # it moves no card at all. With scan.py's real 2.0s outer guard in place,
    # all 40 symbols are abandoned there BOTH before and after -- median wait
    # 2.01s, none completing in time. The gain is conditional on hardware
    # where a calibration finishes inside 2.0s under scan concurrency, and
    # this box (4 cores, 2.1GHz Xeon) has none: calibration is GIL-bound, so
    # `_HESTON_EXECUTOR` buys no parallelism (2 threads measured 2.58x one
    # thread's wall time, 4 threads 5.52x, 8 threads 11.34x, on 4 IDLE cores)
    # and the 2.0s is spent queueing rather than calibrating. Deleting this
    # timeout is a precondition for fixing that, not the fix; the fix is
    # logged against main as its own item. See TIMEOUT-DELETE-INNER-2026-09-13.
    #
    # What still bounds the scan is scan.py's `asyncio.wait` ceiling, which
    # bounds the SCAN rather than this call: it does not cancel, so the
    # calibration keeps running and populates the lru_cache for the next
    # scan. A synchronous caller of `calibrate_heston` outside the scan
    # pipeline has no ceiling at all -- it did not have one before either,
    # for the `shutdown(wait=True)` reason above.
    result = _run_calibration(iv_key, chain_repr, S, r)
    return replace(result, params=replace(result.params))


def _thin_chain_params(chain: list[dict], S: float, r: float) -> HestonParams:
    """The crude IV-seed guess behind `calibrate_cached`'s thin-chain return.

    Deliberately still `bs_iv` and still `expiry_years`, i.e. UNCHANGED from
    what shipped. It had a second caller until the inner timeout was deleted
    -- the timeout branch returned this too. What it returns is discarded by
    `scan.py` before it can reach a card (it accepts `method == "heston_grid"` only), so nothing this
    returns is ever shown; rewriting it onto the bracketed solver would be
    changing code that has no reachable output, which is the over-fixing the
    audit rule forbids. It is a named function rather than the two duplicated
    blocks it used to be so that the two paths cannot drift apart.
    """
    ivs = [bs_iv(c["mid_price"], S, c["strike"], c["expiry_years"], r, c.get("is_call", True))
           for c in chain if c.get("mid_price", 0) > 0]
    ivs = [iv for iv in ivs if iv is not None]
    v0_seed = (sum(ivs) / len(ivs)) ** 2 if ivs else _FALLBACK_V0
    return HestonParams(v0=v0_seed, kappa=2.0, theta=v0_seed, sigma_v=0.3, rho=-0.7)
