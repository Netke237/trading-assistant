"""Phase F2 — the Heston calibration: seed, objective and baseline gate.

Covers spec section 5.2 (tests 5-8) of
docs/superpowers/plans/2026-09-12-heston-calibration-spec.md, plus the three
mutations that section would not have caught on its own: swapping the
bracketed IV solver back for the Newton loop, reverting the objective to
absolute dollars, and dropping the grid-boundary log.

Every chain here is built from Black-Scholes at a stated volatility, so the
answer each test asserts is known before the calibrator runs.
"""

import json
import logging
import math

import pytest

from app.models.black_scholes import bs_price, bs_iv
from app.models.heston import HestonParams, heston_price
from app.models.heston_cache import (
    _FALLBACK_V0,
    _flat_bs_baseline,
    _run_calibration,
    _seed_v0,
    calibrate_cached,
)
from app.data.market import _compute_iv_bs

# The spec's section 7 reference chain.
S, R = 201.86, 0.05
ATM, SKEW, CURV = 0.345, 0.45, 1.6


def _smile_iv(K: float) -> float:
    m = math.log(K / S)
    return ATM + SKEW * (-m) + CURV * m ** 2


def _chain(dte: int, iv_of_strike, lo: float = 180.0, hi: float = 225.0) -> list[dict]:
    """Strikes every $5 over [lo, hi], mid = BS at `iv_of_strike(K)`, rounded
    to the cent exactly as a real quote is. Puts below spot, calls above —
    the same call/put split the scanner's delta band produces."""
    T = dte / 365.0
    out = []
    k = lo
    while k <= hi + 1e-9:
        is_call = k >= S
        mid = round(bs_price(S, k, T, R, iv_of_strike(k), is_call), 2)
        if mid > 0:
            out.append({"strike": k, "expiry_years": T, "mid_price": mid,
                        "is_call": is_call})
        k += 5.0
    return out


def _calibrate(chain: list[dict]):
    """Call `_run_calibration` directly, past `calibrate_cached`'s 1s
    ThreadPoolExecutor timeout — these tests are about WHAT is calibrated, and
    a timeout would turn every one of them into a `bs_fallback` on a slow CI
    box. `test_heston_perf.py` is where latency is pinned."""
    _run_calibration.cache_clear()
    return _run_calibration("test-key", json.dumps(chain, sort_keys=True), S, R)


def _rel_rmse_of(params: HestonParams, chain: list[dict]) -> float:
    sse = 0.0
    for c in chain:
        p = heston_price(S, c["strike"], c["expiry_years"], R, params, c["is_call"])
        sse += ((p - c["mid_price"]) / c["mid_price"]) ** 2
    return math.sqrt(sse / len(chain))


def _abs_rmse_of(params: HestonParams, chain: list[dict]) -> float:
    sse = 0.0
    for c in chain:
        p = heston_price(S, c["strike"], c["expiry_years"], R, params, c["is_call"])
        sse += (p - c["mid_price"]) ** 2
    return math.sqrt(sse / len(chain))


# --------------------------------------------------------------------------
# Spec test 5 — v0 is seeded FROM THE CHAIN, and is not 0.04
# --------------------------------------------------------------------------

def test_seed_recovers_a_flat_chains_own_variance():
    """A chain generated at one known flat IV states its own v0 outright. The
    seed must recover it — and must not be the hardcoded 0.04 (20% vol) that
    used to be the entire v0 grid for every symbol on every scan."""
    chain = _chain(45, lambda K: 0.35)
    seed = _seed_v0(chain, S, R)

    assert seed == pytest.approx(0.35 ** 2, abs=1e-4), (
        f"a 35% flat chain must seed v0 near {0.35 ** 2:.4f}, got {seed:.4f}"
    )
    assert abs(seed - _FALLBACK_V0) > 0.05, (
        "the seed must come from the chain, not from the old hardcoded 0.04"
    )


def test_calibrated_v0_is_the_chain_seed_and_never_the_old_hardcoded_grid():
    """Spec test 5 end to end: the v0 the calibrator SETTLES on is the solved
    seed. v0 is not searched — it is observable, and the other four
    parameters are what turn it into the chain's smile."""
    chain = _chain(45, _smile_iv)
    result = _calibrate(chain)

    assert result.params.v0 == pytest.approx(_seed_v0(chain, S, R), rel=1e-12)
    assert result.params.v0 == pytest.approx(0.1245, abs=5e-4), (
        "the spec's 45-DTE reference chain states v0 = 0.1245 (35.28% vol)"
    )
    assert result.params.v0 != _FALLBACK_V0


def test_seed_falls_back_only_when_no_strike_inverts():
    """Every mid at or below intrinsic — `_compute_iv_bs` returns None for all
    of them. There is no chain-derived answer, so the old constant is the
    honest last resort rather than a crash or a zero."""
    T = 45 / 365.0
    chain = [{"strike": k, "expiry_years": T, "mid_price": round(max(0.01, S - k), 2),
              "is_call": True} for k in (150.0, 160.0, 170.0)]
    assert _seed_v0(chain, S, R) == _FALLBACK_V0


# --------------------------------------------------------------------------
# Spec test 6 — the unit trap
# --------------------------------------------------------------------------

def test_seed_rejects_the_expiry_years_unit_trap():
    """`_compute_iv_bs` takes `dte` in DAYS; the chain dicts carry
    `expiry_years`. Passing one straight into the other is silent, plausible,
    and catastrophic — it reads a 35% chain as ~670% vol. Both halves are
    asserted so the test fails if the multiplication is dropped AND documents
    what dropping it produces."""
    chain = _chain(45, lambda K: 0.35)

    seed = _seed_v0(chain, S, R)
    assert seed == pytest.approx(0.1225, abs=1e-3), (
        f"expected the 35% chain's own variance, got {seed:.4f}"
    )
    assert seed < 1.0, "a variance above 1.0 means expiry_years was fed in as days"

    trap_ivs = [_compute_iv_bs(c["mid_price"], S, c["strike"], c["expiry_years"],
                               c["is_call"], R) for c in chain]
    trap_ivs = [v for v in trap_ivs if v is not None]
    trap_seed = (sum(trap_ivs) / len(trap_ivs)) ** 2
    assert trap_seed > 40.0, (
        "the trap is only worth pinning because it is enormous — if this "
        "assertion fails, _compute_iv_bs's units changed and _seed_v0's "
        "`* 365.0` must be rechecked"
    )


# --------------------------------------------------------------------------
# The solver is not interchangeable
# --------------------------------------------------------------------------

def test_seed_uses_the_bracketed_solver_not_the_newton_loop():
    """`bs_iv`'s Newton loop returns None across much of a realistically
    skewed chain, and it is always the WINGS it drops — the exact part of the
    smile the seed exists to see. Swapping `_compute_iv_bs` for `bs_iv` would
    still produce a plausible-looking seed from a survivor subset, so assert
    on the coverage gap itself, not just on the number."""
    chain = _chain(45, _smile_iv)

    bracketed = [_compute_iv_bs(c["mid_price"], S, c["strike"],
                                c["expiry_years"] * 365.0, c["is_call"], R)
                 for c in chain]
    newton = [bs_iv(c["mid_price"], S, c["strike"], c["expiry_years"], R, c["is_call"])
              for c in chain]

    solved_bracketed = [v for v in bracketed if v is not None]
    solved_newton = [v for v in newton if v is not None]

    assert len(solved_bracketed) == len(chain), (
        "the bracketed solver is expected to invert every strike on this chain"
    )
    assert len(solved_newton) < len(chain), (
        "this chain is only a useful fixture while the Newton loop still drops "
        "strikes on it — if it stops doing so, bs_iv improved and this test "
        "needs a harder chain, not a weaker assertion"
    )

    seed = _seed_v0(chain, S, R)
    newton_seed = (sum(solved_newton) / len(solved_newton)) ** 2
    assert seed == pytest.approx((sum(solved_bracketed) / len(solved_bracketed)) ** 2,
                                 rel=1e-12)
    assert seed != pytest.approx(newton_seed, rel=1e-6), (
        "the two solvers must disagree here, or this test proves nothing"
    )


# --------------------------------------------------------------------------
# The objective is relative, not absolute dollars
# --------------------------------------------------------------------------

def test_reported_rmse_is_the_relative_residual_of_the_returned_params():
    """`CalibrationResult.rmse` changed units in F2: it is the root-mean-
    square of `(model - mid) / mid`, not of `model - mid`. Recompute both from
    the returned parameters and pin which one the calibrator reported. This
    fails if the objective is reverted to dollars."""
    chain = _chain(45, _smile_iv)
    result = _calibrate(chain)
    assert result.method == "heston_grid"

    relative = _rel_rmse_of(result.params, chain)
    absolute = _abs_rmse_of(result.params, chain)

    assert result.rmse == pytest.approx(relative, abs=1e-6)
    assert not math.isclose(relative, absolute, rel_tol=0.05), (
        "the two objectives must differ materially on this chain, or the "
        "assertion above cannot distinguish them"
    )


def test_objective_selects_the_relative_winner_not_the_dollar_winner():
    """The defect section 3.2 names: in absolute dollars one $40 contract
    outweighs three $2 wing contracts, and the wings are what carry the smile
    the other four parameters exist to fit.

    On real chains the two objectives happen to pick the SAME winner (the
    spec measures this, and it is why section 3.2 is specified as the correct
    objective rather than as a measured improvement) — so a real chain cannot
    discriminate between them and this test does not use one. `heston_price`
    is replaced by a fake whose two answers are rigged so that dollars and
    relative error must disagree:

        params with rho=-0.8   ->  40.00, 3.00, 3.00, 3.00
            abs RMSE sqrt(3/4)   = 0.866   <-- the dollar winner
            rel RMSE sqrt(.75/4) = 0.433
        params with rho=-0.2   ->  36.00, 2.00, 2.00, 2.00
            abs RMSE sqrt(16/4)  = 2.000
            rel RMSE sqrt(.01/4) = 0.050   <-- the relative winner

    Reverting the objective to `(model - mid) ** 2` flips the assertion below.
    """
    import app.models.heston_cache as hc

    T = 45 / 365.0
    chain = [
        {"strike": 160.0, "expiry_years": T, "mid_price": 40.0, "is_call": True},
        {"strike": 215.0, "expiry_years": T, "mid_price": 2.0, "is_call": True},
        {"strike": 220.0, "expiry_years": T, "mid_price": 2.0, "is_call": True},
        {"strike": 225.0, "expiry_years": T, "mid_price": 2.0, "is_call": True},
    ]

    def _rigged(S_, K, T_, r_, params, is_call):
        if params.rho == -0.8:
            return 40.0 if K == 160.0 else 3.0
        return 36.0 if K == 160.0 else 2.0

    original_price, original_baseline = hc.heston_price, hc._flat_bs_baseline
    try:
        hc.heston_price = _rigged
        # Keep the gate out of the way — this test is about which parameters
        # the objective SELECTS, not about whether they survive the baseline.
        hc._flat_bs_baseline = lambda c, s, r_: (999.0, 0.30)
        result = _calibrate(chain)
    finally:
        hc.heston_price, hc._flat_bs_baseline = original_price, original_baseline

    assert result.method == "heston_grid"
    assert result.params.rho == -0.2, (
        "the objective picked the dollar winner — it is minimising "
        "(model - mid), not (model - mid) / mid"
    )
    assert result.rmse == pytest.approx(0.05, abs=1e-6)


def test_no_strike_is_abandoned_on_the_reference_chain():
    """The consequence of weighting relatively, on the real fixture: every
    strike in the band is fit to within a quarter of its own price, wings
    included."""
    chain = _chain(45, _smile_iv)
    result = _calibrate(chain)

    errs = {
        c["strike"]: abs(heston_price(S, c["strike"], c["expiry_years"], R,
                                      result.params, c["is_call"]) - c["mid_price"])
        / c["mid_price"]
        for c in chain
    }
    worst_strike = max(errs, key=errs.get)
    assert errs[worst_strike] < 0.25, (
        f"worst relative error {errs[worst_strike]:.3f} at K={worst_strike:.0f}"
    )


# --------------------------------------------------------------------------
# Spec test 7 — the baseline gate
# --------------------------------------------------------------------------

def test_flat_bs_generated_chain_is_rejected_as_bs_flat():
    """A chain generated FROM Black-Scholes at one flat vol is reproduced
    EXACTLY by that vol, so Heston cannot beat it and must not claim to. This
    is the case that, before F2, shipped a fit 3.27x worse than one flat
    volatility to the card labelled 'Heston repriced'."""
    chain = _chain(45, lambda K: 0.30)
    result = _calibrate(chain)

    assert result.method == "bs_flat", (
        "Heston must not be accepted on a chain a single flat volatility "
        "reproduces by construction"
    )
    assert result.params.v0 == pytest.approx(0.30 ** 2, abs=2e-3), (
        "the returned params must carry the winning flat vol as v0 = sigma^2"
    )
    assert result.params.theta == pytest.approx(result.params.v0, rel=1e-12), (
        "a flat vol has no mean reversion to a different level"
    )
    assert math.isfinite(result.rmse)


def test_smiled_chain_is_accepted_as_heston_grid():
    """The positive half of the gate: a chain with a real skew is what the
    four smile parameters exist for, and Heston beats one flat vol on it by
    2.5x. Measured on the spec's reference chain: rel-RMSE 0.0796 against a
    0.1969 baseline."""
    chain = _chain(45, _smile_iv)
    result = _calibrate(chain)

    baseline_rmse, baseline_sigma = _flat_bs_baseline(chain, S, R)
    assert result.method == "heston_grid"
    assert result.rmse < baseline_rmse, (
        "the gate's whole content: heston_grid is returned only when the fit "
        "beats the flat-BS baseline on the same chain and residual"
    )
    assert result.rmse == pytest.approx(0.0796, abs=2e-3)
    assert baseline_rmse == pytest.approx(0.1969, abs=2e-3)
    assert baseline_sigma == pytest.approx(0.3432, abs=2e-3)


def test_gate_is_strict_so_a_tie_goes_to_the_flat_baseline():
    """Four extra parameters have to EARN their place, not draw for it. The
    tie is engineered by handing the gate a baseline error equal to the fit's
    own, which the real chains never produce exactly."""
    import app.models.heston_cache as hc

    chain = _chain(45, _smile_iv)
    honest = _calibrate(chain)
    assert honest.method == "heston_grid"

    # `honest.rmse` is ROUNDED to 6dp on the way out, so it is not the number
    # the gate actually compared. Recompute the unrounded residual from the
    # winning parameters — the same arithmetic in the same order — so the tie
    # is a real one rather than a near-miss on either side.
    exact_rmse = _rel_rmse_of(honest.params, chain)
    assert exact_rmse == pytest.approx(honest.rmse, abs=1e-6)

    original = hc._flat_bs_baseline
    try:
        hc._flat_bs_baseline = lambda c, s, r_: (exact_rmse, 0.3432)
        tied = _calibrate(chain)
    finally:
        hc._flat_bs_baseline = original

    assert tied.method == "bs_flat", (
        "an exact tie must fall to the simpler model"
    )


def test_ungateable_chain_returns_bs_fallback_not_an_unchecked_fit():
    """If no flat volatility prices the chain at all, the gate cannot run —
    and a fit that was never gated must never be labelled 'Heston repriced'.
    `bs_fallback` is this file's existing 'no honest answer' signal and
    `scan.py` already discards it."""
    import app.models.heston_cache as hc

    chain = _chain(45, _smile_iv)
    original = hc._flat_bs_baseline
    try:
        hc._flat_bs_baseline = lambda c, s, r_: (None, None)
        result = _calibrate(chain)
    finally:
        hc._flat_bs_baseline = original

    assert result.method == "bs_fallback"
    assert result.rmse == float("inf")


def test_ungateable_chain_is_logged_as_rejected_not_as_accepted(caplog):
    """The log line must name the label actually returned. An earlier cut of
    this code decided the verdict AFTER logging, so an ungateable chain — one
    with boundary hits and no baseline — announced "accepted (heston_grid)"
    and then returned bs_fallback. Putting the mislabelling back into the log
    would defeat the point of the log."""
    import app.models.heston_cache as hc

    chain = _chain(45, _smile_iv)
    original = hc._flat_bs_baseline
    try:
        hc._flat_bs_baseline = lambda c, s, r_: (None, None)
        with caplog.at_level(logging.WARNING, logger="app.models.heston_cache"):
            result = _calibrate(chain)
    finally:
        hc._flat_bs_baseline = original

    assert result.method == "bs_fallback"
    messages = [rec.getMessage() for rec in caplog.records]
    assert any("REJECTED (bs_fallback" in m for m in messages), messages
    assert not any("accepted (heston_grid)" in m for m in messages), (
        f"the log claimed a label the call did not return: {messages}"
    )


def test_flat_bs_baseline_recovers_the_generating_volatility():
    """The comparator has to be a real best-fit, not a token one: an
    under-fitted baseline overstates the baseline's error and is the one error
    direction that lets a bad Heston fit through the gate."""
    chain = _chain(45, lambda K: 0.28)
    rmse, sigma = _flat_bs_baseline(chain, S, R)
    assert sigma == pytest.approx(0.28, abs=2e-3)
    assert rmse < 0.01, "a chain generated at one flat vol is reproduced by it"


def test_flat_bs_baseline_reaches_far_beyond_ordinary_volatility():
    """The sweep is geometric over `_compute_iv_bs`'s own [1%, 2000%] bracket
    precisely so the baseline cannot be beaten by default on a violent chain.
    A linear sweep capped at 300% would pin at its ceiling here, report a huge
    baseline error, and wave a bad Heston fit through the gate."""
    T = 45 / 365.0
    chain = [{"strike": k, "expiry_years": T,
              "mid_price": round(bs_price(S, k, T, R, 5.0, k >= S), 2),
              "is_call": k >= S}
             for k in (120.0, 160.0, 200.0, 240.0, 300.0)]
    rmse, sigma = _flat_bs_baseline(chain, S, R)
    assert sigma == pytest.approx(5.0, rel=1e-3), (
        f"a 500%-vol chain must be recovered, got {sigma * 100:.1f}%"
    )
    assert rmse < 0.001


# --------------------------------------------------------------------------
# The grid-boundary log (decision F2-GRID-AND-EDGE-OF-BOX-2026-09-13)
# --------------------------------------------------------------------------

def test_winner_on_a_grid_boundary_is_logged(caplog):
    """Three of five parameters pinning at a boundary is a box that is too
    small, not a fit. F2 deliberately does NOT widen the grid — it makes the
    pinning visible so the widening decision later has evidence from real
    scans instead of one synthetic re-run."""
    chain = _chain(45, _smile_iv)
    with caplog.at_level(logging.WARNING, logger="app.models.heston_cache"):
        result = _calibrate(chain)

    assert result.method == "heston_grid"
    messages = [rec.getMessage() for rec in caplog.records]
    assert any("grid boundary" in m for m in messages), (
        f"expected a boundary warning, got: {messages}"
    )
    boundary_line = next(m for m in messages if "grid boundary" in m)
    for name in ("kappa", "theta", "sigma_v", "rho"):
        assert name in boundary_line, (
            f"{name} pins on this chain and must be named in the log line"
        )
    assert "v0" not in boundary_line.split("grid boundary")[1], (
        "v0 is a single solved seed, so it is on its own boundary by "
        "definition — reporting it would be noise, not evidence"
    )


def test_boundary_log_is_warning_because_info_is_dropped_under_uvicorn():
    """Measured, not stylistic: uvicorn's default logging config configures
    only the `uvicorn*` loggers and leaves the root logger handler-less at
    WARNING, so an `app.*` INFO record never reaches Kenneth's terminal. A
    silent diagnostic is the exact failure this log exists to end."""
    import copy
    import logging.config
    from uvicorn.config import LOGGING_CONFIG

    saved_root = logging.getLogger().manager.loggerDict.copy()
    try:
        logging.config.dictConfig(copy.deepcopy(LOGGING_CONFIG))
        assert not logging.getLogger("app.models.heston_cache").isEnabledFor(logging.INFO)
        assert logging.getLogger("app.models.heston_cache").isEnabledFor(logging.WARNING)
    finally:
        logging.getLogger().manager.loggerDict.clear()
        logging.getLogger().manager.loggerDict.update(saved_root)


def test_rejected_fit_is_logged_with_its_verdict(caplog):
    """A gate that silently downgrades is the same mask the ladder floor was.
    A bs_flat return says so in the log, with both sides of the comparison."""
    chain = _chain(45, lambda K: 0.30)
    with caplog.at_level(logging.WARNING, logger="app.models.heston_cache"):
        result = _calibrate(chain)

    assert result.method == "bs_flat"
    assert any("REJECTED (bs_flat)" in rec.getMessage() for rec in caplog.records)


# --------------------------------------------------------------------------
# Spec test 8 — nothing but heston_grid may be labelled "Heston repriced"
# --------------------------------------------------------------------------

def test_scan_accepts_heston_grid_and_nothing_else():
    """`scan.py` gates on equality with "heston_grid", so `bs_flat` is
    discarded with no call-site change. Pin that the condition is still an
    equality against that one label — widening it to `.startswith("heston")`
    or to an `in` over a list would silently readmit the fit the F2 gate
    exists to reject."""
    import inspect
    import app.routers.scan as scan_module

    source = inspect.getsource(scan_module)
    assert '_calibration_result.method == "heston_grid"' in source, (
        "scan.py must accept the heston_grid label by equality — see spec "
        "section 3.3 and test 8"
    )
    for rejected in ('"bs_flat"', '"bs_fallback"'):
        assert f"_calibration_result.method == {rejected}" not in source
        assert f"_calibration_result.method != {rejected}" not in source


def test_calibrate_cached_thin_chain_still_returns_bs_fallback():
    """The two pre-F2 fallback paths are unchanged and still discarded: fewer
    than three usable strikes never reaches the grid at all."""
    T = 45 / 365.0
    thin = [{"strike": 200.0, "expiry_years": T, "mid_price": 8.0, "is_call": True}]
    result = calibrate_cached(thin, S, R)
    assert result.method == "bs_fallback"
    assert result.rmse == float("inf")
