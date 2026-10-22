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
    _boundary_hits,
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
    """Call `_run_calibration` directly, past `calibrate_cached`'s chain
    filtering and cache key — these tests are about WHAT is calibrated.
    `test_heston_perf.py` is where latency is pinned. This used to also matter
    for dodging `calibrate_cached`'s inner 1s ThreadPoolExecutor timeout, which
    would have turned every one of these into a `bs_fallback` on a slow CI box;
    TIMEOUT-DELETE-INNER-2026-09-13 deleted that timeout, so that hazard is
    gone and this is now a directness convenience only."""
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
# The grid-boundary log — gated on rung count by
# BOUNDARY-LOG-GATE-ON-GRID-2026-09-13, which superseded the logging half of
# F2-GRID-AND-EDGE-OF-BOX-2026-09-13.
#
# The test these replace asserted that kappa, theta, sigma_v and rho were all
# named in the boundary line. That assertion could not fail: on a two-rung
# grid every value is both a min and a max, so all four are ALWAYS named. It
# passed for the same reason it was worthless.
# --------------------------------------------------------------------------

# Transcriptions of the two grids `_run_calibration` builds. A transcription
# proves nothing on its own, so
# `test_the_transcriptions_match_the_grids_the_source_really_builds` captures
# the real dicts out of a live calibration and asserts these against them —
# without it, widening the source grid would leave the tests below asserting a
# distribution the source can no longer produce, and passing.
#
# `v0` is the one entry that is NOT a copy of a source literal: the source
# builds `[_seed_v0(...)]`, solved out of the chain. Only `len() == 1` matters
# to the gate, so a stand-in value is honest here and the pinning test checks
# the length rather than the value.
SHIPPED_GRID = {"v0": [0.09], "kappa": [0.5, 3.0], "theta": [0.02, 0.08],
                "sigma_v": [0.2, 0.6], "rho": [-0.8, -0.2]}
FULL_GRID = {"v0": [0.09], "kappa": [0.5, 1.5, 3.0], "theta": [0.02, 0.04, 0.08],
             "sigma_v": [0.2, 0.4, 0.6], "rho": [-0.8, -0.5, -0.2]}


def _params_from(combo: dict) -> HestonParams:
    return HestonParams(v0=combo["v0"], kappa=combo["kappa"], theta=combo["theta"],
                        sigma_v=combo["sigma_v"], rho=combo["rho"])


def _every_combo(grid: dict):
    import itertools
    names = list(grid)
    for values in itertools.product(*(grid[n] for n in names)):
        yield dict(zip(names, values))


def _grids_the_source_builds(monkeypatch, full: bool) -> dict:
    """The `grids` dict `_run_calibration` really constructs, captured out of a
    live calibration rather than retyped.

    `_run_calibration` builds the grids as locals and hands them to
    `_boundary_hits`, so spying on that one call is the only seam that sees
    them without reaching into the function's source."""
    import app.models.heston_cache as hc

    captured: dict = {}
    real = hc._boundary_hits

    def spy(params, grids):
        captured.clear()
        captured.update(grids)
        return real(params, grids)

    monkeypatch.setattr(hc, "_USE_FULL_GRID", full)
    monkeypatch.setattr(hc, "_boundary_hits", spy)
    _calibrate(_chain(45, _smile_iv))
    assert captured, "_boundary_hits was never reached, so nothing was captured"
    return dict(captured)


def test_the_transcriptions_match_the_grids_the_source_really_builds(monkeypatch):
    """SHIPPED_GRID and FULL_GRID are this module's copies of source literals,
    and every test below reasons about the copies. Without this test the copies
    could drift from the source silently — and the failure would be the
    quietest kind: widen the real full grid and
    `test_a_third_rung_makes_the_diagnostic_discriminate_again` would go on
    asserting an 81-combination histogram the source can no longer produce,
    and pass.

    `v0` is checked by LENGTH only, deliberately: the source solves it out of
    the chain (`[_seed_v0(...)]`), so its value is not a literal to match and
    only its single rung is what the gate turns on."""
    for full, transcription, label in ((False, SHIPPED_GRID, "shipped"),
                                       (True, FULL_GRID, "HESTON_FULL_CALIBRATION")):
        real = _grids_the_source_builds(monkeypatch, full)

        assert set(real) == set(transcription), (
            f"{label} grid: dimensions differ — source {sorted(real)} vs "
            f"transcription {sorted(transcription)}"
        )
        assert {k: len(v) for k, v in real.items()} == \
               {k: len(v) for k, v in transcription.items()}, (
            f"{label} grid: rung COUNTS differ, which is exactly what the gate "
            f"turns on — source { {k: len(v) for k, v in real.items()} }"
        )
        for name, rungs in real.items():
            if name == "v0":
                assert len(rungs) == 1, f"v0 must stay one solved rung, got {rungs}"
                continue
            assert rungs == transcription[name], (
                f"{label} grid: {name} is {rungs} in the source but "
                f"{transcription[name]} here"
            )


def test_two_rung_grid_reports_nothing_because_it_can_report_nothing_else():
    """The reason the gate exists, pinned by enumeration rather than argued.

    Two rungs have no interior, so a boundary hit is arithmetic about the
    grid and not a finding about the fit. Every one of the 16 combinations the
    shipped grid can return is checked: if ANY of them produced a hit, the
    diagnostic would be reporting something it decided before the chain was
    seen. Reverting the gate to `len(grid) < 2` fails this on the first
    combination.
    """
    combos = list(_every_combo(SHIPPED_GRID))
    assert len(combos) == 16, "the shipped grid is 2**4 searched combinations"
    for combo in combos:
        hits = _boundary_hits(_params_from(combo), SHIPPED_GRID)
        assert hits == [], (
            f"{combo} reported {hits}; on a two-rung grid every value is both "
            f"the min and the max, so this can only ever be noise"
        )


def test_a_third_rung_makes_the_diagnostic_discriminate_again():
    """The other half: the gate must not be so tight that widening the grid
    leaves it silent, because the widening decision is the log's only consumer.

    On the three-rung grid the count genuinely varies — which is the whole
    difference between evidence and arithmetic. The exact distribution is
    asserted, so tightening the gate to `len(grid) < 4` fails here rather than
    passing quietly.

    It does NOT catch the gate being loosened back to `len(grid) < 2`, and
    saying otherwise would be the same empty claim this whole change exists to
    remove: every dimension of the full grid has three rungs, so a `< 2`
    threshold skips nothing a `< 3` threshold skipped and this test cannot
    tell them apart. That direction is covered by
    `test_two_rung_grid_reports_nothing_because_it_can_report_nothing_else`
    and by `test_an_accepted_fit_on_the_shipped_grid_logs_nothing`, both of
    which do fail under it.
    """
    from collections import Counter

    counts = Counter(len(_boundary_hits(_params_from(c), FULL_GRID))
                     for c in _every_combo(FULL_GRID))
    assert sum(counts.values()) == 81, "the full grid is 3**4 combinations"
    assert counts == {0: 1, 1: 8, 2: 24, 3: 32, 4: 16}, (
        f"the full grid must produce a SPREAD of hit counts, got {dict(counts)}"
    )
    assert sum(n for h, n in counts.items() if h >= 1) == 80
    assert counts[4] == 16


def test_an_interior_winner_is_not_a_boundary_and_an_edge_one_names_its_side():
    """A hit has to mean the search reached the wall of the box. The middle
    rung is the only value on the full grid that is neither edge, so it is the
    one case that distinguishes a real check from `return everything`."""
    interior = _boundary_hits(
        _params_from({"v0": 0.09, "kappa": 1.5, "theta": 0.04,
                      "sigma_v": 0.4, "rho": -0.5}), FULL_GRID)
    assert interior == [], f"every value is a middle rung, got {interior}"

    edges = _boundary_hits(
        _params_from({"v0": 0.09, "kappa": 0.5, "theta": 0.08,
                      "sigma_v": 0.4, "rho": -0.2}), FULL_GRID)
    joined = "; ".join(edges)
    assert "kappa=0.5 (grid min)" in joined, joined
    assert "theta=0.08 (grid max)" in joined, joined
    assert "rho=-0.2 (grid max)" in joined, joined
    assert "sigma_v" not in joined, (
        f"sigma_v sat on the middle rung and must not be reported: {joined}"
    )


def test_v0_is_never_reported_because_one_rung_is_its_own_boundary():
    """v0 is solved, not searched. It is on its own boundary by definition, so
    naming it would be noise under either threshold — and it stays skipped by
    the same rule rather than by a special case."""
    for grid in (SHIPPED_GRID, FULL_GRID):
        hits = _boundary_hits(_params_from({"v0": 0.09, "kappa": 0.5, "theta": 0.08,
                                            "sigma_v": 0.2, "rho": -0.8}), grid)
        assert not any(h.startswith("v0") for h in hits), hits


def test_an_accepted_fit_on_the_shipped_grid_logs_nothing(caplog):
    """End-to-end on the grid `_run_calibration` actually builds, rather than
    on this module's copy of it.

    Note what this does and does not pin: it pins that NO searched dimension
    of the shipped grid has three rungs (any that did would put a boundary
    line on this accepted fit), not the grid's particular values — the gate
    turns on rung COUNT, so the values are not what it depends on.

    Before this change the same chain produced a boundary warning on every
    accepted fit — roughly 500 per S&P 500 scan, in the stream where the
    ladder-floor warning has to be noticed. Silence on an accepted fit IS the
    shipped behaviour now; a WARNING here means the gate is off, or that the
    grid grew a third rung without the volume question being reopened.
    """
    chain = _chain(45, _smile_iv)
    with caplog.at_level(logging.WARNING, logger="app.models.heston_cache"):
        result = _calibrate(chain)

    assert result.method == "heston_grid", (
        "this chain must be ACCEPTED, or the silence below would be the "
        "rejection path rather than the boundary gate"
    )
    messages = [rec.getMessage() for rec in caplog.records]
    assert messages == [], (
        f"an accepted fit on the shipped grid must log nothing: {messages}"
    )


def test_the_full_grid_really_does_wake_the_diagnostic(monkeypatch, caplog):
    """`FULL_GRID` above is this module's transcription of the
    HESTON_FULL_CALIBRATION branch, and a transcription proves nothing about
    the code. This runs the real branch on the same chain.

    It is the load-bearing test of the whole decision: the gate is only
    defensible because the diagnostic RETURNS when the grid is widened. If
    this passes for the wrong reason — silence — the gate is just a deletion
    with extra steps.
    """
    import app.models.heston_cache as hc

    monkeypatch.setattr(hc, "_USE_FULL_GRID", True)
    chain = _chain(45, _smile_iv)
    with caplog.at_level(logging.WARNING, logger="app.models.heston_cache"):
        result = _calibrate(chain)

    assert result.method == "heston_grid"
    messages = [rec.getMessage() for rec in caplog.records]
    boundary = [m for m in messages if "grid boundary" in m]
    assert boundary, (
        f"widening the grid must bring the diagnostic back, got: {messages}"
    )
    named = boundary[0].split("grid boundary")[1]
    assert "v0" not in named, (
        f"v0 is one solved rung and must stay unreported: {named}"
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


def test_rejected_fit_on_the_full_grid_logs_one_line_with_its_numbers(monkeypatch, caplog):
    """DECISION-23 H-2 (H4): the rejected-fit WARNING under
    HESTON_FULL_CALIBRATION=1 (the three-rung grid) was asserted nowhere, so a
    mutation dropping or garbling it survived. This pins its CONTENT, not just
    its presence: the strike count, the verdict, and both sides of the
    comparison, each recomputed here independently of the calibrator.

    The fit's rel-RMSE is the minimum over every full-grid combination at the
    chain's own seeded v0 (re-derived with this module's `_rel_rmse_of`, which
    sums in the calibrator's order); the baseline is `_flat_bs_baseline` on
    the same strikes. Removing the line, changing its count, its verdict or
    either number fails one assertion below."""
    import app.models.heston_cache as hc

    monkeypatch.setattr(hc, "_USE_FULL_GRID", True)
    chain = _chain(45, lambda K: 0.30)
    with caplog.at_level(logging.WARNING, logger="app.models.heston_cache"):
        result = _calibrate(chain)

    assert result.method == "bs_flat"
    warnings = [rec for rec in caplog.records
                if rec.name == "app.models.heston_cache" and rec.levelno == logging.WARNING]
    assert len(warnings) == 1, [rec.getMessage() for rec in warnings]
    message = warnings[0].getMessage()

    v0 = hc._seed_v0(chain, S, R)
    full = dict(FULL_GRID, v0=[v0])
    best_rmse = min(_rel_rmse_of(_params_from(combo), chain)
                    for combo in _every_combo(full))
    baseline_rmse, _sigma = _flat_bs_baseline(chain, S, R)
    assert baseline_rmse is not None

    assert f"Heston calibration on {len(chain)} strikes:" in message, message
    assert "REJECTED (bs_flat)" in message, message
    assert f"rel-RMSE {best_rmse:.4f} vs flat-BS baseline {baseline_rmse:.4f}" in message, message


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
