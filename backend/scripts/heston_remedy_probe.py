"""Costs the three fix directions for the GIL finding.

Run: cd backend && .venv/bin/python scripts/heston_remedy_probe.py

`scripts/heston_latency_probe.py` established the DIAGNOSIS -- calibration is
GIL-bound, `_HESTON_EXECUTOR` gives negative parallelism, and 40 of 40 symbols
are abandoned at scan.py's 2.0s guard. It deliberately costed no remedy. The
open question it left on main names three directions and says of all three
"none costed yet". This script costs them, on the same box, against the same
40-symbol slice, so they can be compared as numbers rather than as arguments:

  (a) PROCESS POOL   -- real parallelism, but `CalibrationResult` has to
                        pickle and the IPC round trip has to be paid on a
                        job of roughly half a second.
  (b) SERIALISE      -- `_HESTON_CONCURRENCY = 1`, deliberately, and re-budget
                        the guard. Fewer symbols priced, but honestly.
  (c) CHEAPER PRICER -- make one calibration fit the budget under contention.

(c) is measured through a PROTOTYPE pricer, `_vec_prices`, which is NOT a merge
candidate and is not wired into anything. It exists to answer one question --
how much headroom is actually there -- and it is reported with its ACCURACY
against the shipped `heston_price` next to its speed, because a fast pricer
that moves the number is not a remedy, it is a different defect.

The prototype changes two things and nothing else:

  1. A COMPOSITE GAUSS-LEGENDRE RULE instead of scipy's adaptive QUADPACK, so
     the nodes are known in advance and the integrand can be evaluated as one
     numpy array op instead of a few hundred Python callbacks. This is the
     change that makes 2 possible; on its own it mostly moves work from Python
     into C. The panel count is NOT fixed -- see `_PANEL_NODES`.
  2. THE CHARACTERISTIC FUNCTION IS COMPUTED ONCE PER (EXPIRY, PARAMETER SET)
     AND REUSED ACROSS EVERY STRIKE. `_heston_char_fn` folds the strike in as
     the single factor `exp(i phi ln(S/K))` -- everything expensive in it
     (the complex sqrt, the two logs, the exp) depends only on phi, T and the
     five parameters. The shipped code recomputes all of it per strike, so a
     40-strike chain does 40x the work it needs to. That is the headroom.

The arithmetic the prototype does NOT change: same adaptive cutoff `upper`,
same `0.5 + p/pi`, same `S*P1 - K*e^{-rT}*P2`, same put-call parity tail, same
`max(price, 0.0)` clamp. Measurement 3 reports the deviation that remains.

MEASURED ON THIS BOX (4 cores, 2.1GHz Xeon, CPython 3.11.15, GIL enabled --
`sys._is_gil_enabled` is absent, so the free-threaded escape hatch the open
question asked about does not exist on this venv, and backend/Dockerfile's
`FROM python:3.11-slim` says the same about the container): every table this
script prints is written up, with the reasoning, in
docs/superpowers/plans/2026-09-14-heston-gil-remedy-costing.md. Numbers from
any other box are the point of this script.

RUN IT WITH `-W ignore`. The SHIPPED pricer emits scipy IntegrationWarnings at
the sub-daily expiries measurement 2 sweeps -- a pre-existing behaviour this
script only surfaces -- and they bury the tables.
"""
import argparse
import asyncio
import concurrent.futures
import math
import multiprocessing
import statistics
import sys
import time
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.special import ndtr, roots_legendre

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.models.heston import (
    HestonParams, CalibrationResult, calibrate_heston, heston_price,
)
from app.models import heston_cache as hc
from app.models.heston_cache import _run_calibration, _seed_v0, _flat_bs_baseline

# One definition of the reference chain, imported rather than copied: the
# diagnosis probe and this one MUST measure the same shapes or the before/after
# is two readings rather than a comparison.
from heston_latency_probe import chain, SPOT, R


# ── (c) the prototype pricer ────────────────────────────────────────────────

# THE QUADRATURE RULE IS COMPOSITE, AND BOTH HALVES OF THAT ARE MEASURED
# RATHER THAN STYLISTIC.
#
# A FIXED NODE COUNT IS NOT SAFE. The integrand carries the strike as
# `exp(i phi ln(S/K))`, so its phase runs to `upper * max|ln(S/K)|`: about 110
# radians (18 oscillations) on any expiry a real chain carries, and about 4500
# radians (710 oscillations) at the 1e-6-year `floor_years` that
# `reprice_horizon.remaining_years_at_barrier` -- reached from `trade_plan`'s
# `display_reprice_years` -- can hand `reward_risk`'s `heston_price` call.
# Measured against the shipped pricer, one fixed
# 512-point rule resolves the first and is out by $0.24 on the second, and a
# fixed 128 is out by $5.29. So the rule has to scale with the oscillation
# count.
#
# A SINGLE GAUSS-LEGENDRE RULE CANNOT SCALE THAT FAR. Building an n-point rule
# is O(n^2) in both numpy and scipy on this box -- measured 0.007s at 512,
# 0.42s at 4096 and 6.58s at 16384 -- and numpy's additionally allocates an
# n x n companion matrix. A one-off 6.6s inside a 2.0s scan budget is not a
# remedy.
#
# So: a SMALL fixed rule, applied over as many panels as the oscillation count
# asks for. The 24-point rule is built once per process and every panel reuses
# it, so widening the range costs an array reshape rather than a new solve.
_PANEL_NODES = 24
_OSC_PER_PANEL = 2.0
_MAX_PANELS = 4096


def _charexp(u: np.ndarray, T: float, r: float, p: HestonParams) -> np.ndarray:
    """The STRIKE-INDEPENDENT half of `_heston_char_fn`: exp(C + D*v0).

    Same formulation as the shipped scalar version, term for term -- the same
    `g` (not the Albrecher "little trap" reciprocal), so the branch cuts are
    the shipped ones too. Deviating here would make measurement 3 compare two
    different models rather than two implementations of one.
    """
    i = 1j
    kappa, theta, sv, rho, v0 = p.kappa, p.theta, p.sigma_v, p.rho, p.v0
    a = kappa * theta
    d = np.sqrt((rho * sv * u * i - kappa) ** 2 + sv ** 2 * (u * i + u ** 2))
    num = kappa - rho * sv * u * i - d
    g = num / (kappa - rho * sv * u * i + d)
    exp_dT = np.exp(-d * T)
    C = r * u * i * T + a / sv ** 2 * (num * T - 2 * np.log((1 - g * exp_dT) / (1 - g)))
    D = num / sv ** 2 * (1 - exp_dT) / (1 - g * exp_dT)
    return np.exp(C + D * v0)


@lru_cache(maxsize=8)
def _gauss_legendre(nodes: int) -> tuple[np.ndarray, np.ndarray]:
    """The one small rule every panel reuses, built once per process.

    `scipy.special.roots_legendre`, not `numpy.polynomial.legendre.leggauss`:
    numpy's builds an n x n companion matrix and calls `eigvalsh` on it. At the
    24 nodes used here either is instant; the choice matters only because an
    earlier version of this prototype scaled ONE rule up to 16384 nodes, where
    numpy's is a 2GB allocation and scipy's still measured 6.58s.
    """
    x, w = roots_legendre(nodes)
    return np.asarray(x), np.asarray(w)


def _panels_for(upper: float, max_abs_x: float) -> int:
    """How many panels the oscillation count asks for. See the block comment
    above `_PANEL_NODES` for why this is not a constant."""
    osc = upper * max_abs_x / (2.0 * math.pi)
    return int(min(max(1, math.ceil(osc / _OSC_PER_PANEL)), _MAX_PANELS))


def _composite_rule(upper: float, panels: int) -> tuple[np.ndarray, np.ndarray]:
    """`panels` equal sub-intervals of [0, upper], each carrying the same
    cached 24-point Gauss-Legendre rule, flattened to one node/weight pair."""
    x, w = _gauss_legendre(_PANEL_NODES)
    edges = np.linspace(0.0, upper, panels + 1)
    a, b = edges[:-1, None], edges[1:, None]
    half = (b - a) / 2.0
    return (((a + b) / 2.0 + half * x).ravel(), (half * w).ravel())


def _vec_prices(S: float, strikes: np.ndarray, is_calls: np.ndarray,
                T: float, r: float, p: HestonParams,
                panels: int | None = None) -> np.ndarray:
    """Every strike of ONE expiry, priced against ONE parameter set, in one
    array op. Returns the same quantity `heston_price` returns, per strike.

    THE K-FACTORISATION, since it is the whole point and is easy to get wrong:
    `_heston_char_fn(u)` returns `charexp(u) * exp(i*u*x)` with `x = ln(S/K)`.
    For the P1 integrand the shipped code evaluates it at `u = phi - i`, and
    `exp(i*(phi-i)*x) = e^x * exp(i*phi*x) = (S/K) * exp(i*phi*x)`. The `K` the
    shipped integrand multiplies by and the `S` it divides by therefore cancel
    against that `S/K` EXACTLY, leaving `charexp(phi-i) * exp(i*phi*x)
    / (i*phi*e^{rT})` -- strike-free except for the one oscillatory factor.
    P2 is the same with `u = phi` and no prefactor at all.

    NOT REPRODUCED, and it matters if this is ever promoted out of a probe:
    `heston_price`'s degenerate-input guard (`T <= 0 or S <= 0 or K <= 0 or
    v0 <= 0 -> 0.0`) and its `except Exception -> bs_price` tail. Every caller
    here is a chain `calibrate_cached` has already filtered to `mid_price > 0`
    and `expiry_years > 0`, against a solved `v0` that is positive by
    construction, so neither is reachable from this script -- which is exactly
    why a merge candidate would have to put them back rather than inherit this
    file's luck.
    """
    v_eff = max(min(p.v0, p.theta), 1e-12)
    upper = min(max(500.0, math.sqrt(50.0 / (v_eff * T))), 20000.0)

    K = np.asarray(strikes, dtype=float)
    x = np.log(S / K)
    if panels is None:
        panels = _panels_for(upper, float(np.max(np.abs(x))))
    phi, w = _composite_rule(upper, panels)

    ce1 = _charexp(phi - 1j, T, r, p)
    ce0 = _charexp(phi + 0j, T, r, p)
    inv = 1.0 / (1j * phi)

    osc = np.exp(1j * np.outer(x, phi))                      # (M, N)

    p1 = (osc * (ce1 * inv / math.exp(r * T))).real @ w
    p2 = (osc * (ce0 * inv)).real @ w
    P1 = 0.5 + p1 / math.pi
    P2 = 0.5 + p2 / math.pi

    disc = K * math.exp(-r * T)
    call = S * P1 - disc * P2
    return np.maximum(np.where(is_calls, call, call - S + disc), 0.0)


def _calibrate_vec(chain_in: list[dict], S: float, r: float,
                   panels: int | None = None, baseline=_flat_bs_baseline
                   ) -> CalibrationResult:
    """`heston_cache._run_calibration` with `_vec_prices` swapped in for the
    per-strike `heston_price` loop, and NOTHING else changed: same solved v0
    seed, same two-rung grid, same relative-RMSE objective, same flat-BS
    baseline gate, same three labels. The chain is grouped by expiry because
    `_charexp` is reusable only within one T.

    The shipped version's per-strike `except Exception: continue` is dropped
    rather than reproduced, and that is a REAL difference to hold against the
    prototype, not a tidy-up: `heston_price` catches its own integration
    failures internally and returns `bs_price`, so the shipped except is
    already unreachable (logged against main by F2 round 2 as mutation M11),
    and a whole-array op cannot skip one strike anyway.
    """
    grouped: dict[float, list[int]] = {}
    for idx, c in enumerate(chain_in):
        grouped.setdefault(c["expiry_years"], []).append(idx)

    mids = np.array([c["mid_price"] for c in chain_in], dtype=float)
    v0_seed = _seed_v0(chain_in, S, r)

    kappa_grid, theta_grid = [0.5, 3.0], [0.02, 0.08]
    sigma_v_grid, rho_grid = [0.2, 0.6], [-0.8, -0.2]

    best_rmse, best_params = float("inf"), None
    for kappa in kappa_grid:
        for theta in theta_grid:
            for sigma_v in sigma_v_grid:
                for rho in rho_grid:
                    params = HestonParams(v0=v0_seed, kappa=kappa, theta=theta,
                                          sigma_v=sigma_v, rho=rho)
                    model = np.empty_like(mids)
                    for T, idxs in grouped.items():
                        model[idxs] = _vec_prices(
                            S,
                            np.array([chain_in[i]["strike"] for i in idxs]),
                            np.array([chain_in[i].get("is_call", True) for i in idxs]),
                            T, r, params, panels,
                        )
                    rmse = math.sqrt(float(np.mean(((model - mids) / mids) ** 2)))
                    if rmse < best_rmse:
                        best_rmse, best_params = rmse, params

    if best_params is None:                                   # pragma: no cover
        fb = HestonParams(v0=v0_seed, kappa=2.0, theta=v0_seed, sigma_v=0.3, rho=-0.7)
        return CalibrationResult(params=fb, rmse=float("inf"), method="bs_fallback")

    baseline_rmse, baseline_sigma = baseline(chain_in, S, r)
    if baseline_rmse is None:
        fb = HestonParams(v0=v0_seed, kappa=2.0, theta=v0_seed, sigma_v=0.3, rho=-0.7)
        return CalibrationResult(params=fb, rmse=float("inf"), method="bs_fallback")
    if baseline_rmse <= best_rmse:
        return CalibrationResult(
            params=HestonParams(v0=baseline_sigma ** 2, kappa=2.0,
                                theta=baseline_sigma ** 2, sigma_v=0.3, rho=-0.7),
            rmse=round(baseline_rmse, 6), method="bs_flat")
    return CalibrationResult(params=best_params, rmse=round(best_rmse, 6),
                             method="heston_grid")


# ── (c) continued: the baseline gate, which becomes the bottleneck ──────────

def _bs_vec(S: float, K: np.ndarray, T: np.ndarray, r: float,
            sigma: float, is_call: np.ndarray) -> np.ndarray:
    """`black_scholes.bs_price` over a whole chain at one volatility.

    `scipy.special.ndtr` is exactly what `scipy.stats.norm.cdf` calls through
    to (`norm_gen._cdf` is `return sc.ndtr(x)`), so this is the same function
    with the per-call distribution machinery skipped, not a different one --
    measurement 2c reports the agreement rather than resting on that.
    """
    sq = np.sqrt(T)
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sq)
    d2 = d1 - sigma * sq
    disc = K * np.exp(-r * T)
    return np.where(is_call,
                    S * ndtr(d1) - disc * ndtr(d2),
                    disc * ndtr(-d2) - S * ndtr(-d1))


def _flat_bs_baseline_vec(chain_in: list[dict], S: float, r: float):
    """`heston_cache._flat_bs_baseline` with the per-strike Python loop
    replaced by one array op, and NOTHING else changed: same geometric coarse
    sweep, same bracket, same golden-section contraction, same "return the
    best sigma actually EVALUATED" rule.

    The shipped version's two `except Exception` guards are dropped: `bs_price`
    returns 0.0 rather than raising on invalid input, and `_rel_rmse` is
    arithmetic over a chain whose mids `calibrate_cached` has already filtered
    to > 0.
    """
    K = np.array([c["strike"] for c in chain_in], dtype=float)
    T = np.array([c["expiry_years"] for c in chain_in], dtype=float)
    is_call = np.array([c.get("is_call", True) for c in chain_in])
    mids = np.array([c["mid_price"] for c in chain_in], dtype=float)
    if not len(mids):
        return None, None

    def objective(sigma: float) -> float:
        p = _bs_vec(S, K, T, r, sigma, is_call)
        return math.sqrt(float(np.mean(((p - mids) / mids) ** 2)))

    best_sigma, best_err = hc._BASELINE_SIGMA_LO, float("inf")
    for i in range(hc._BASELINE_COARSE_STEPS + 1):
        sigma = hc._BASELINE_SIGMA_LO * hc._BASELINE_SWEEP_RATIO ** i
        err = objective(sigma)
        if err < best_err:
            best_err, best_sigma = err, sigma
    if not math.isfinite(best_err):
        return None, None

    lo = max(hc._BASELINE_SIGMA_LO, best_sigma / hc._BASELINE_SWEEP_RATIO)
    hi = min(hc._BASELINE_SIGMA_HI, best_sigma * hc._BASELINE_SWEEP_RATIO)
    c, d = hi - hc._INV_PHI * (hi - lo), lo + hc._INV_PHI * (hi - lo)
    f_c, f_d = objective(c), objective(d)
    for _ in range(hc._BASELINE_REFINE_ITERS):
        if f_c < f_d:
            hi, d, f_d = d, c, f_c
            c = hi - hc._INV_PHI * (hi - lo)
            f_c = objective(c)
        else:
            lo, c, f_c = c, d, f_d
            d = lo + hc._INV_PHI * (hi - lo)
            f_d = objective(d)
    for sigma, err in ((c, f_c), (d, f_d)):
        if err < best_err:
            best_err, best_sigma = err, sigma
    return best_err, best_sigma


def measure_baseline() -> None:
    print()
    print("=" * 78)
    print("2c. THE BASELINE GATE VECTORISED -- the floor measurement 2b exposed")
    print("=" * 78)
    print("  Measurement 2b showed the gate is 65-83% of what is left once the")
    print("  grid search is vectorised, so the pricer work alone caps out where")
    print("  2b's 'total' column sits. This is the same gate over arrays.")
    print(f"\n  {'DTE':>5} {'strikes':>8} {'shipped':>9} {'vectorised':>11} "
          f"{'speedup':>8} {'d(sigma)':>10} {'d(rel-RMSE)':>12}")
    for dte in (30, 45, 180, 365):
        for n in (15, 25, 40):
            c = chain(dte, n)
            t0 = time.perf_counter()
            e_a, s_a = _flat_bs_baseline(c, SPOT, R)
            ta = time.perf_counter() - t0
            t0 = time.perf_counter()
            e_b, s_b = _flat_bs_baseline_vec(c, SPOT, R)
            tb = time.perf_counter() - t0
            print(f"  {dte:>5} {len(c):>8} {ta:>8.4f}s {tb:>10.4f}s {ta / tb:>7.1f}x "
                  f"{abs(s_a - s_b):>10.2e} {abs(e_a - e_b):>12.2e}")

    print("\n  STEP 1 ALONE -- the vectorised gate against the SHIPPED pricer.")
    print("  The gate is 65-83% of a calibration only AFTER the grid search is")
    print("  vectorised (2b); against the shipped pricer the grid search still")
    print("  dominates, so removing the gate's cost barely moves the total. This")
    print("  is the table that stops '136x on a function' being read as '136x on")
    print("  a calibration'.")
    print(f"  {'DTE':>5} {'strikes':>8} {'shipped':>9} {'step 1':>8} {'speedup':>8}  labels")
    for dte in (30, 45, 180, 365):
        for n in (15, 25, 40):
            c = chain(dte, n)
            _run_calibration.cache_clear()
            t0 = time.perf_counter()
            a = calibrate_heston(c, SPOT, R)
            ta = time.perf_counter() - t0
            _real = hc._flat_bs_baseline
            hc._flat_bs_baseline = _flat_bs_baseline_vec
            try:
                _run_calibration.cache_clear()
                t0 = time.perf_counter()
                b = calibrate_heston(c, SPOT, R)
                tb = time.perf_counter() - t0
            finally:
                hc._flat_bs_baseline = _real
            agree = "same" if a.method == b.method else f"DIFFER {a.method}/{b.method}"
            print(f"  {dte:>5} {len(c):>8} {ta:>8.3f}s {tb:>7.3f}s {ta / tb:>7.2f}x  "
                  f"{agree}, rel-RMSE {a.rmse:.4f} vs {b.rmse:.4f}")

    print("\n  Whole calibration with BOTH halves vectorised, against shipped:")
    print(f"  {'DTE':>5} {'strikes':>8} {'shipped':>9} {'both':>8} {'speedup':>8}  labels")
    for dte in (30, 45, 180, 365):
        for n in (15, 25, 40):
            c = chain(dte, n)
            _run_calibration.cache_clear()
            t0 = time.perf_counter()
            a = calibrate_heston(c, SPOT, R)
            ta = time.perf_counter() - t0
            t0 = time.perf_counter()
            b = _calibrate_vec2(c, SPOT, R)
            tb = time.perf_counter() - t0
            agree = "same" if a.method == b.method else f"DIFFER {a.method}/{b.method}"
            print(f"  {dte:>5} {len(c):>8} {ta:>8.3f}s {tb:>7.3f}s {ta / tb:>7.1f}x  "
                  f"{agree}, rel-RMSE {a.rmse:.4f} vs {b.rmse:.4f}")
    print("\n  What is LEFT is `_seed_v0`: a bracketed brentq per strike,")
    print("  measured at 0.010-0.032s in 2b and untouched by either change.")


def _calibrate_vec2(chain_in: list[dict], S: float, r: float) -> CalibrationResult:
    """`_calibrate_vec` with the vectorised gate as well -- everything this
    prototype can vectorise, so the projected floor is a MEASUREMENT rather
    than the sum of two separate speedups. `_seed_v0` is deliberately left
    alone: it is a bracketed brentq per strike and is the next floor, not this
    one."""
    return _calibrate_vec(chain_in, S, r, baseline=_flat_bs_baseline_vec)


# ── the shared 40-symbol slice ──────────────────────────────────────────────

def _slice_spec(n_symbols: int) -> list[tuple[float, list[dict], float]]:
    """The SAME 40 symbols for every arrangement, built once.

    `heston_latency_probe.measure_scan` draws its shapes from `random` inside
    the coroutine, which is fine when there is one arrangement to measure and
    useless when there are nine: an arrangement that happened to draw thinner
    chains would look faster. Built up front and reused, so the only thing
    that differs between arrangements is the arrangement.
    """
    import random
    rng = random.Random(7)
    out = []
    for i in range(n_symbols):
        spot = 80.0 + i * 3.7
        out.append((
            rng.uniform(0.15, 0.45),                      # chain-fetch stand-in
            chain(rng.choice([30, 45, 60, 90, 180]),
                  rng.choice([15, 25, 40]), spot),
            spot,
        ))
    return out


async def _run_slice(spec, guard, concurrency, executor, fn, scan_concurrency) -> dict:
    """One arrangement, driven exactly as scan.py drives the real thing.

    The fetch semaphore is released BEFORE the calibration block, as
    `_process_symbol` does (`async with sem:` closes at scan.py:600, the
    calibration is at scan.py:728-816), so in-flight calibrations are capped
    by the Heston semaphore alone. Holding it across the calibration would cap
    them at `_SCAN_CONCURRENCY` and understate the queueing -- the error that
    the diagnosis probe's round 2 caught and corrected.
    """
    heston_sem = asyncio.Semaphore(concurrency)
    scan_sem = asyncio.Semaphore(scan_concurrency)
    loop = asyncio.get_running_loop()
    results: list[tuple[float, str]] = []

    async def calibrate(c, spot):
        async with heston_sem:
            return await loop.run_in_executor(executor, fn, c, spot, 0.05)

    async def symbol(fetch_s, c, spot):
        async with scan_sem:
            await asyncio.sleep(fetch_s)
        t0 = time.perf_counter()
        task = asyncio.ensure_future(calibrate(c, spot))
        done, _ = await asyncio.wait({task}, timeout=guard)
        dt = time.perf_counter() - t0
        if task in done:
            results.append((dt, task.result().method))
        else:
            task.add_done_callback(lambda f: f.exception())
            results.append((dt, "abandoned"))

    t0 = time.perf_counter()
    await asyncio.gather(*(symbol(*s) for s in spec))
    wall = time.perf_counter() - t0
    times = [t for t, _ in results]
    priced = sum(1 for _, m in results if m == "heston_grid")
    return {"wall": wall, "times": times, "priced": priced, "n": len(results)}


def _print_row(label: str, res: dict) -> None:
    t = res["times"]
    print(f"  {label:<34} {res['wall']:>6.1f}s  "
          f"{statistics.median(t):>7.2f}s  {max(t):>7.2f}s  "
          f"{res['priced']:>3}/{res['n']}  "
          f"{100.0 * res['priced'] / res['n']:>5.1f}%")


# ── 1. threads vs processes ─────────────────────────────────────────────────

def measure_pools(spec) -> None:
    print("=" * 78)
    print("1. THREADS vs PROCESSES -- does direction (a) actually parallelise?")
    print("=" * 78)
    # EVERY JOB IS THE SAME SHAPE, differing only in the spot it is priced at.
    # `spec`'s chains vary in DTE and strike count by design -- that is what
    # makes it a realistic slice -- but a pool's WALL TIME is set by its
    # slowest member, so feeding it mixed shapes measures the draw rather than
    # the pool. The spot offset is what keeps `_run_calibration`'s lru_cache
    # from turning every job after the first into a 1ms hit; it is the same
    # device `heston_latency_probe.measure_threads` uses.
    work = [(chain(45, 25, SPOT + i * 1.13), SPOT + i * 1.13) for i in range(8)]

    _run_calibration.cache_clear()
    t0 = time.perf_counter()
    calibrate_heston(work[0][0], work[0][1], R)
    solo = time.perf_counter() - t0
    print(f"\n  1 call, no pool: {solo:.3f}s   (the yardstick both columns use)")
    print(f"\n  {'workers':>8}  {'threads':>18}  {'processes':>18}")

    ctx = multiprocessing.get_context("spawn")
    for n in (2, 4, 8):
        jobs = work[:n]
        _run_calibration.cache_clear()
        t0 = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
            list(pool.map(lambda j: calibrate_heston(j[0], j[1], R), jobs))
        th = time.perf_counter() - t0

        # Pre-warmed: the pool is built and every worker made to import scipy
        # BEFORE the clock starts. Production pays that once at process start,
        # not per scan, so folding it in here would slander direction (a).
        # It is reported separately below.
        with concurrent.futures.ProcessPoolExecutor(max_workers=n, mp_context=ctx) as pool:
            t_warm = time.perf_counter()
            list(pool.map(_warmup, range(n)))
            warm = time.perf_counter() - t_warm
            t0 = time.perf_counter()
            list(pool.map(_proc_job, jobs))
            pr = time.perf_counter() - t0
        print(f"  {n:>8}  {th:>9.3f}s {th / solo:>6.2f}x  "
              f"{pr:>9.3f}s {pr / solo:>6.2f}x   (pool warmup {warm:.1f}s)")
    print("\n  1.00x = perfectly parallel.  N.00x = fully serialised.")


def _warmup(_i: int) -> int:
    """Forces a spawned worker to import scipy/numpy before it is timed."""
    heston_price(100.0, 100.0, 0.25, R, HestonParams(0.04, 2.0, 0.04, 0.3, -0.7), True)
    return 0


def _proc_job(job) -> str:
    c, spot = job
    return calibrate_heston(c, spot, R).method


# ── 2. the prototype pricer: accuracy first, then speed ─────────────────────

def measure_pricer(spec) -> None:
    print()
    print("=" * 78)
    print("2. PROTOTYPE PRICER -- direction (c). ACCURACY FIRST.")
    print("=" * 78)
    print("  Deviation of _vec_prices from the shipped heston_price over 48")
    print("  parameter sets (the 16 shipped grid combinations x three v0 seeds)")
    print("  x 10 expiries x a 13-rung moneyness ladder. A pricer that is fast")
    print("  and wrong is not a remedy, so this table comes before the speed one.")
    print()
    print("  THE EXPIRY LIST IS THE POINT. A FIXED node count is most stressed")
    print("  where the adaptive cutoff `upper` runs past its 500 floor -- short")
    print("  expiry and small variance -- because the integrand then oscillates")
    print("  over a wider range for the same node budget. So the ladder reaches")
    print("  below the scan's own horizons: 1e-6 yr is `reprice_horizon`'s")
    print("  `floor_years` and 6.85e-4 the 1-DTE repricing horizon, both named")
    print("  in heston.py's own cutoff comment as reachable. The `panels` rows")
    print("  below are FIXED counts and the `adaptive` row is `_panels_for`;")
    print("  compare them, that comparison IS the finding.")
    print(f"\n  {'panels':>7} {'nodes':>6} {'max abs $':>11} {'max rel':>10} "
          f"{'worst at':>30} {'sweep s':>9}")

    combos = [HestonParams(v0=v0, kappa=k, theta=th, sigma_v=sv, rho=rh)
              for v0 in (0.01, 0.1245, 0.40)
              for k in (0.5, 3.0) for th in (0.02, 0.08)
              for sv in (0.2, 0.6) for rh in (-0.8, -0.2)]
    ks = np.array([SPOT * m for m in
                   (0.85, 0.88, 0.91, 0.94, 0.97, 1.0, 1.03, 1.06,
                    1.09, 1.12, 1.15, 1.20, 1.25)])
    calls = ks >= SPOT
    expiries = [1e-6, 6.85e-4, 1 / 365, 7 / 365, 21 / 365, 30 / 365,
                45 / 365, 90 / 365, 180 / 365, 1.0]

    ref: dict = {}
    for T in expiries:
        for pi, p in enumerate(combos):
            ref[(T, pi)] = np.array([
                heston_price(SPOT, float(k), T, R, p, bool(ic))
                for k, ic in zip(ks, calls)])

    for panels in (4, 16, 64, None):
        worst_abs, worst_rel, where = 0.0, 0.0, ""
        t0 = time.perf_counter()
        for T in expiries:
            for pi, p in enumerate(combos):
                got = _vec_prices(SPOT, ks, calls, T, R, p, panels)
                exp = ref[(T, pi)]
                d = np.abs(got - exp)
                # Relative to a one-cent floor: a deep-OTM strike worth
                # $0.0001 would otherwise turn a $1e-9 absolute agreement into
                # a 1e-5 "relative error" and hide the real signal. One cent is
                # the tick a real quote is rounded to, so below it the absolute
                # column is the honest one.
                rel = d / np.maximum(exp, 0.01)
                j = int(np.argmax(rel))
                if rel[j] > worst_rel:
                    worst_rel, worst_abs = float(rel[j]), float(d[j])
                    where = (f"T={T:.2e} K={ks[j]:.0f} v0={p.v0:g} "
                             f"th={p.theta:g}")
        sweep = time.perf_counter() - t0
        label = "adaptive" if panels is None else str(panels)
        nlabel = "varies" if panels is None else str(panels * _PANEL_NODES)
        print(f"  {label:>7} {nlabel:>6} {worst_abs:>11.6f} {worst_rel:>9.2e} "
              f"{where:>30} {sweep:>8.2f}s")

    print("\n  PER EXPIRY, with the adaptive rule, worst over all 48 parameter")
    print("  sets -- so the boundary a fixed count would cross is visible:")
    print(f"  {'T (years)':>12} {'DTE':>8} {'nodes':>7} {'max abs $':>11} {'max rel':>10}")
    max_x = float(np.max(np.abs(np.log(SPOT / ks))))
    for T in expiries:
        wa, wr, n_used = 0.0, 0.0, 0
        for pi, p in enumerate(combos):
            v_eff = max(min(p.v0, p.theta), 1e-12)
            upper = min(max(500.0, math.sqrt(50.0 / (v_eff * T))), 20000.0)
            n_used = max(n_used, _panels_for(upper, max_x) * _PANEL_NODES)
            got = _vec_prices(SPOT, ks, calls, T, R, p)
            exp = ref[(T, pi)]
            d = np.abs(got - exp)
            rel = d / np.maximum(exp, 0.01)
            j = int(np.argmax(rel))
            if rel[j] > wr:
                wr, wa = float(rel[j]), float(d[j])
        print(f"  {T:>12.3e} {T * 365:>8.4f} {n_used:>7} {wa:>11.6f} {wr:>9.2e}")
    print("\n  The two sub-daily rows are NOT a chain: no quote carries them.")
    print("  They reach `heston_price` through the exit-premium repricing call,")
    print("  and the chain is: trade_plan.py:119 passes display_reprice_years(...)")
    print("  as `reprice_years`; reward_risk sets dte_at_target = reprice_years")
    print("  and prices with it (reward_risk.py:131 and :222); and")
    print("  display_reprice_years is remaining_years_at_barrier(...), whose")
    print("  floor_years default is 1e-6 -- NOT the 7/365 that")
    print("  `_default_reprice_years` floors at, which applies only when no")
    print("  reprice_years is supplied. So that is the regime a fixed node")
    print("  count gets wrong, and it lands on a CARD.")

    print("\n  Speed, one whole calibration (grid + baseline gate), adaptive rule:")
    print(f"  {'DTE':>5} {'strikes':>8} {'shipped':>9} {'prototype':>10} {'speedup':>8}  labels")
    for dte in (30, 45, 90, 180, 365):
        for n in (15, 25, 40):
            c = chain(dte, n)
            _run_calibration.cache_clear()
            t0 = time.perf_counter()
            a = calibrate_heston(c, SPOT, R)
            ta = time.perf_counter() - t0
            t0 = time.perf_counter()
            b = _calibrate_vec(c, SPOT, R)
            tb = time.perf_counter() - t0
            agree = "same" if a.method == b.method else f"DIFFER {a.method}/{b.method}"
            print(f"  {dte:>5} {len(c):>8} {ta:>8.3f}s {tb:>9.3f}s {ta / tb:>7.1f}x  "
                  f"{agree}, rel-RMSE {a.rmse:.4f} vs {b.rmse:.4f}")


def measure_split() -> None:
    """Where the prototype's REMAINING time goes.

    Worth its own table because it decides what a second change would be worth:
    `_flat_bs_baseline` is untouched by the pricer work -- it is a scalar
    Python loop over `bs_price`, 47 evaluations x every strike, each costing
    two `scipy.stats.norm.cdf` calls -- so once the grid search stops being the
    bottleneck the gate becomes it. A remedy that only halves the smaller half
    is not worth building.
    """
    print()
    print("=" * 78)
    print("2b. WHERE THE PROTOTYPE'S REMAINING TIME GOES")
    print("=" * 78)
    print(f"  {'DTE':>5} {'strikes':>8} {'grid':>9} {'baseline':>9} {'seed':>8} "
          f"{'total':>8} {'baseline share':>15}")
    for dte in (30, 45, 180, 365):
        for n in (15, 25, 40):
            c = chain(dte, n)
            t0 = time.perf_counter()
            _seed_v0(c, SPOT, R)
            t_seed = time.perf_counter() - t0
            t0 = time.perf_counter()
            _flat_bs_baseline(c, SPOT, R)
            t_base = time.perf_counter() - t0
            t0 = time.perf_counter()
            _calibrate_vec(c, SPOT, R)
            t_all = time.perf_counter() - t0
            t_grid = t_all - t_base - t_seed
            print(f"  {dte:>5} {len(c):>8} {t_grid:>8.3f}s {t_base:>8.3f}s "
                  f"{t_seed:>7.3f}s {t_all:>7.3f}s {100 * t_base / t_all:>13.0f}%")
    print("\n  'grid' is the 16-combination search the prototype vectorised.")
    print("  'baseline' and 'seed' are UNCHANGED scalar code it calls into.")


# ── 3. the same slice under every arrangement ───────────────────────────────

async def measure_arrangements(spec, guard: float) -> None:
    from app.routers import scan as scan_mod

    print()
    print("=" * 78)
    print(f"3. THE SAME {len(spec)}-SYMBOL SLICE UNDER EVERY ARRANGEMENT "
          f"(guard {guard}s)")
    print("=" * 78)
    sc = scan_mod._SCAN_CONCURRENCY
    hc_n = scan_mod._HESTON_CONCURRENCY
    print(f"  {'arrangement':<34} {'wall':>6}  {'median':>7}  {'max':>7}  "
          f"{'priced':>6}  {'cover':>5}")

    _run_calibration.cache_clear()
    with concurrent.futures.ThreadPoolExecutor(max_workers=hc_n) as pool:
        _print_row(f"threads x{hc_n} (TODAY)",
                   await _run_slice(spec, guard, hc_n, pool, calibrate_heston, sc))

    _run_calibration.cache_clear()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        _print_row("(b) serialised, threads x1",
                   await _run_slice(spec, guard, 1, pool, calibrate_heston, sc))

    ctx = multiprocessing.get_context("spawn")
    for n in (4, hc_n):
        _run_calibration.cache_clear()
        with concurrent.futures.ProcessPoolExecutor(max_workers=n, mp_context=ctx) as pool:
            list(pool.map(_warmup, range(n)))
            _print_row(f"(a) processes x{n}",
                       await _run_slice(spec, guard, n, pool, calibrate_heston, sc))

    # STEP 1 ALONE: the SHIPPED pricer with only the gate vectorised. Patched
    # on `heston_cache` rather than passed, because `_run_calibration` resolves
    # `_flat_bs_baseline` as a module global -- which is also why this is the
    # honest way to measure it: it is exactly the substitution the real change
    # would make. Set once around the whole arrangement, not per call, so no
    # worker thread ever sees it mid-swap.
    _run_calibration.cache_clear()
    _real_baseline = hc._flat_bs_baseline
    hc._flat_bs_baseline = _flat_bs_baseline_vec
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=hc_n) as pool:
            _print_row(f"(c) step 1 ONLY: gate, threads x{hc_n}",
                       await _run_slice(spec, guard, hc_n, pool, calibrate_heston, sc))
    finally:
        hc._flat_bs_baseline = _real_baseline

    _run_calibration.cache_clear()
    with concurrent.futures.ThreadPoolExecutor(max_workers=hc_n) as pool:
        _print_row(f"(c) step 2 ONLY: pricer, threads x{hc_n}",
                   await _run_slice(spec, guard, hc_n, pool, _calibrate_vec, sc))

    _run_calibration.cache_clear()
    with concurrent.futures.ThreadPoolExecutor(max_workers=hc_n) as pool:
        _print_row(f"(c) BOTH: pricer + gate, threads x{hc_n}",
                   await _run_slice(spec, guard, hc_n, pool, _calibrate_vec2, sc))

    _run_calibration.cache_clear()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        _print_row("(c)+(b) prototype, threads x1",
                   await _run_slice(spec, guard, 1, pool, _calibrate_vec, sc))

    ctx2 = multiprocessing.get_context("spawn")
    with concurrent.futures.ProcessPoolExecutor(max_workers=4, mp_context=ctx2) as pool:
        list(pool.map(_warmup, range(4)))
        _print_row("(c)+(a) prototype, processes x4",
                   await _run_slice(spec, guard, 4, pool, _calibrate_vec, sc))

    print("\n  'priced' counts symbols returning heston_grid inside the guard --")
    print("  the only label scan.py accepts, so the only one that reaches a card.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", choices=("pools", "pricer", "arrangements"))
    ap.add_argument("--symbols", type=int, default=40)
    ap.add_argument("--guard", type=float, default=2.0)
    args = ap.parse_args()

    import logging
    logging.disable(logging.CRITICAL)

    spec = _slice_spec(args.symbols)
    print(f"box: {len(__import__('os').sched_getaffinity(0))} cores, "
          f"CPython {'.'.join(map(str, sys.version_info[:3]))}, GIL "
          f"{getattr(sys, '_is_gil_enabled', lambda: 'enabled (pre-3.13 build)')()}")
    if args.only in (None, "pools"):
        measure_pools(spec)
    if args.only in (None, "pricer"):
        measure_pricer(spec)
        measure_split()
        measure_baseline()
    if args.only in (None, "arrangements"):
        asyncio.run(measure_arrangements(spec, args.guard))


if __name__ == "__main__":
    main()
