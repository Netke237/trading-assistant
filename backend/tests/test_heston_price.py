"""Golden invariants for heston_price's Fourier inversion.

These back Phase F1 (docs/superpowers/plans/2026-09-12-heston-calibration-spec.md
section 5.1). Before F1, heston_price's _integrand re-applied
exp(i*phi*lnS) / exp(i*phi*lnK) on top of a characteristic function that
already carried e^{i*phi*ln(S/K)}. The moneyness exponents collected to
2*i*phi*ln(S/K) + j*ln(S/K): a DOUBLED Fourier frequency plus a spurious
(S/K)^j factor on P1, which also never divided by f2(-i) = S*e^{rT}.

The error was exactly zero at K == S -- which is why it survived this long --
and grew monotonically with |ln(S/K)| in both directions, reaching +451% at
45 DTE and +2782% at 180 DTE on strikes INSIDE the |delta| 0.15-0.90 band the
scanner ranks.

Every tolerance below is measured, not guessed, and each test states its own
measured margin to failure.

WHAT THIS FILE IS: seven invariants (one of them parametrised, so pytest
reports more cases than that -- do not read the case count as a count of
independent checks). Four are self-contained invariants needing no external
data; one pins values from an independently written reference; one is a
sensitivity check; one is a structural bounds check.

Deliberately NO reference Heston prices copied from a paper: parameterisation
conventions differ between sources, and a mismatched convention produces a
test that is wrong in the same direction as the code. The reference values in
test_matches_independent_reference_under_real_skew come from a reference
WRITTEN FOR THIS REPO by a different route (see that test's docstring), and
validated by the sigma_v -> 0 collapse before being trusted.

WHY THERE IS A SKEWED-PARAMETER TEST AT ALL (added after an adversarial audit
round): the sigma_v -> 0 and U-shape tests both pin the pricer only where it
degenerates to Black-Scholes, and the monotonicity test constrains shape
rather than level. With only those, INVERTING THE SIGN OF rho -- destroying
the entire skew, which is the only reason to run Heston instead of
Black-Scholes -- still passed every case in this file. The reference pins and
the rho sensitivity check below are what close that hole.
"""
import math

import pytest

from app.models.black_scholes import bs_delta, bs_iv, bs_price
from app.models.heston import HestonParams, heston_price

# The gate-basis spec's reference chain (section 7 of the F1 spec).
S = 201.86
R = 0.05

# Economically meaningful premium floor. Below roughly a cent, the residual
# vol-of-vol left in sigma_v=0.01 dominates the price in RELATIVE terms even
# though it is worth a tiny fraction of a cent absolutely, so a relative-error
# assertion there measures the tolerance of the collapse, not the pricer. Two
# of the 48 grid points in test 1 sit below this floor (7 DTE, 26% and 36%
# out of the money), where Black-Scholes itself prices under a tenth of a cent.
_MIN_PREMIUM = 0.01

# The reference chain's own instantaneous variance (35.88% vol).
_REF_V0 = 0.1287

# Exact number of strikes in the |delta| 0.15-0.90 band on the $5 ladder from
# 140 to 280, at sqrt(_REF_V0) vol, per expiry. Measured, and asserted exactly.
_IN_BAND_COUNTS = {45: 11, 180: 23}

_DTES = (7, 45, 180, 365)
_MONEYNESS = (0.74, 0.89, 0.99, 1.02, 1.14, 1.36)


def _near_bs_params() -> HestonParams:
    """Heston degenerated toward Black-Scholes: variance pinned at its
    long-run level (v0 == theta, so there is nothing to mean-revert toward),
    vol-of-vol as close to zero as the closed form tolerates, and no
    correlation. Heston must then reproduce Black-Scholes at sigma = sqrt(v0).
    sigma_v is 0.01 rather than 0.0 because sigma_v appears in
    _heston_char_fn's denominators. v0 is fixed at the reference chain's own
    variance rather than parametrised -- both call sites want the same value,
    and an unused parameter invites a caller to vary it past the measured
    tolerances quoted below."""
    return HestonParams(v0=_REF_V0, kappa=2.0, theta=_REF_V0, sigma_v=0.01, rho=0.0)


def test_heston_collapses_to_black_scholes_as_vol_of_vol_vanishes():
    """THE test the pre-F1 code failed, and it needs no external reference data.

    With v0 == theta and sigma_v -> 0 the variance process is deterministic, so
    Heston must equal Black-Scholes at sigma = sqrt(v0). Measured worst relative
    error after F1: 0.0139% (45 DTE, 26% OTM put), against the 0.1% bound
    asserted here -- a 7x margin. The pre-F1 code failed this by 83161% (7 DTE,
    14% OTM call: 12.31 against a true 0.0148).
    """
    params = _near_bs_params()
    sigma = math.sqrt(params.v0)
    checked = 0

    for dte in _DTES:
        T = dte / 365
        for mult in _MONEYNESS:
            K = S * mult
            for is_call in (True, False):
                expected = bs_price(S, K, T, R, sigma, is_call)
                actual = heston_price(S, K, T, R, params, is_call)
                if expected < _MIN_PREMIUM:
                    # A relative tolerance is meaningless on a sub-penny
                    # premium, but an ABSOLUTE one is not -- and these are the
                    # two points where the pre-F1 pricer was most spectacularly
                    # wrong in dollars: it returned $35.59 and $26.65 for
                    # options Black-Scholes prices at 8.1e-10 and 6.2e-10. Not
                    # asserting anything here would put the bug's single
                    # largest absolute error in this test's blind spot.
                    assert actual < _MIN_PREMIUM, (
                        f"a worthless option priced at {actual:.6f} at "
                        f"dte={dte} K/S={mult} "
                        f"{'call' if is_call else 'put'} (Black-Scholes: "
                        f"{expected:.3e})"
                    )
                    continue
                checked += 1
                rel = abs(actual - expected) / expected
                assert rel < 1e-3, (
                    f"sigma_v->0 Heston diverged from Black-Scholes by "
                    f"{rel * 100:.4f}% at dte={dte} K/S={mult} "
                    f"{'call' if is_call else 'put'}: got {actual:.6f}, "
                    f"expected {expected:.6f}. The Fourier inversion in "
                    f"heston_price._integrand is wrong -- see "
                    f"docs/superpowers/plans/2026-09-12-heston-calibration-spec.md"
                )

    assert checked == 46, (
        f"expected 46 of 48 grid points above the ${_MIN_PREMIUM} premium "
        f"floor, checked {checked} -- the grid or the floor changed"
    )


def test_heston_put_call_parity_holds():
    """C - P == S - K*e^{-rT}.

    HONEST SCOPE: this is structurally satisfied by heston_price's current
    shape, which prices the call and then DERIVES the put by parity -- the
    pre-F1 code passed this to 1.4e-14 while being wrong by 83161%. So it does
    NOT guard the F1 defect, and it is kept only as a cheap tripwire for a
    future refactor that prices puts on their own integral (at which point
    parity stops being free). Do not read a pass here as evidence the pricer
    is correct; test 1 and test 4 are what carry that.

    Measured worst after F1: 7.3e-10 absolute, against the 1e-6 bound.
    """
    for params in (_near_bs_params(),
                   HestonParams(v0=0.1287, kappa=2.0, theta=0.09,
                                sigma_v=0.5, rho=-0.7)):
        for dte in _DTES:
            T = dte / 365
            for mult in _MONEYNESS:
                K = S * mult
                call = heston_price(S, K, T, R, params, True)
                put = heston_price(S, K, T, R, params, False)
                forward = S - K * math.exp(-R * T)
                assert abs((call - put) - forward) < 1e-6, (
                    f"put-call parity broke at dte={dte} K/S={mult}: "
                    f"C-P={call - put:.9f}, S-Ke^-rT={forward:.9f}"
                )


@pytest.mark.parametrize("dte", (45, 180))
@pytest.mark.parametrize("K", (170.0, 201.86, 235.0))
@pytest.mark.parametrize("is_call", (True, False))
def test_heston_price_is_monotonic_in_spot(dte: int, K: float, is_call: bool):
    """A call is non-decreasing in spot and a put non-increasing -- a
    no-arbitrage invariant, not a numerical nicety.

    This is the invariant reward_risk.py's ladder floor was written to fake
    downstream. Pinned here at the source. The pre-F1 code violated it 153
    times across this same 12-case grid, with drops as large as $4.97 on a
    single spot step.

    Uses the skewed, high-vol-of-vol parameters the calibrator actually
    selects (sigma_v 0.5, rho -0.7) -- a near-Black-Scholes parameter set
    would make this trivially true.
    """
    params = HestonParams(v0=0.1287, kappa=2.0, theta=0.09,
                          sigma_v=0.5, rho=-0.7)
    T = dte / 365
    lo, hi = 0.7 * K, 1.4 * K
    steps = 30

    prev = None
    for n in range(steps + 1):
        spot = lo + (hi - lo) * n / steps
        price = heston_price(spot, K, T, R, params, is_call)
        if prev is not None:
            change = price - prev[1] if is_call else prev[1] - price
            assert change >= 0.0, (
                f"{'call' if is_call else 'put'} price moved the wrong way "
                f"against spot: {prev[1]:.6f} at S={prev[0]:.4f} -> "
                f"{price:.6f} at S={spot:.4f} (K={K}, dte={dte})"
            )
        prev = (spot, price)


def test_no_u_shaped_error_across_the_delta_band_the_scanner_ranks():
    """The pre-F1 error was U-shaped in strike and near-zero only at the money,
    so an at-the-money spot check could not see it.

    This walks the whole band scan.py feeds the calibrator -- |delta| in
    [0.15, 0.90], which is contract_rules.yaml's 0.20/0.85 hard-reject widened
    by _HESTON_DELTA_SAFETY_MARGIN = 0.05 -- and requires every in-band strike
    to sit within 1% of its sigma_v->0 Black-Scholes value. The pre-F1 code
    reached 514% inside this band at 45 DTE (K=180).

    Post-F1 margin to the 1% bound asserted here: worst measured deviation is
    0.0005% (45 DTE, K=215) and 0.0011% (180 DTE, K=185) -- roughly a 900x
    margin.

    NOTE the two percentages in this file are different measurements and are
    not meant to agree: 514%/567% are pre-F1 error against sigma_v -> 0
    Black-Scholes at v0=0.1287 (what THIS test measures), while the 451%/2782%
    in the F1 spec and commit message are pre-F1 error against correct Heston
    at sigma_v=0.5, rho=-0.7 (a skewed chain this test does not use).
    """
    params = _near_bs_params()
    sigma = math.sqrt(params.v0)

    for dte in (45, 180):
        T = dte / 365
        in_band = 0
        for K in range(140, 281, 5):
            is_call = K >= S
            if not 0.15 <= abs(bs_delta(S, K, T, R, sigma, is_call)) <= 0.90:
                continue
            expected = bs_price(S, K, T, R, sigma, is_call)
            if expected < _MIN_PREMIUM:
                continue
            in_band += 1
            actual = heston_price(S, K, T, R, params, is_call)
            rel = abs(actual - expected) / expected
            assert rel < 0.01, (
                f"in-band strike K={K} at {dte} DTE deviates {rel * 100:.2f}% "
                f"from Black-Scholes ({actual:.4f} vs {expected:.4f}) -- the "
                f"U-shaped integrand error is back"
            )
        # EXACT counts, not a floor: at 45 DTE 11 strikes fall in band and at
        # 180 DTE 23 do. A ">= 8" floor would let 15 of the 23 silently drop
        # out of the 180-DTE sweep while still passing -- which is the exact
        # silent coverage loss this assertion exists to prevent.
        assert in_band == _IN_BAND_COUNTS[dte], (
            f"{in_band} strikes fell in the |delta| 0.15-0.90 band at {dte} "
            f"DTE, expected {_IN_BAND_COUNTS[dte]} -- the band, the strike "
            f"ladder or the reference vol changed, and this test is no longer "
            f"covering what it claims to"
        )


def test_no_arbitrage_bounds_hold_across_the_scanner_delta_band():
    """Inside the band scan.py ranks, every price must sit between its
    forward intrinsic and its theoretical cap -- a call in
    [max(S - K*e^{-rT}, 0), S], a put in [max(K*e^{-rT} - S, 0), K*e^{-rT}].

    Measured over the FULL 243-combination calibration grid
    (HESTON_FULL_CALIBRATION=1) x 7 expiries x 61 strikes x both rights:
    ZERO in-band violations. This test runs a reduced parameter set for
    runtime; the full sweep is reproducible from the F1 spec's section 7.

    THE BAND IS COMPUTED AT THE MODEL'S OWN ATM IMPLIED VOL, not at
    sqrt(v0). Those differ whenever v0 != theta, and badly: at v0=0.01,
    kappa=3.0, theta=0.08, sigma_v=0.6, rho=-0.8 and 365 DTE the model's ATM
    implied vol is 23.4% while sqrt(v0) is 10%, so a sqrt(v0) delta filter
    selects [200, 220] where the model's real band is
    [180, 200, 220, 240, 260]. Filtering at the wrong vol would quietly shrink
    this test's coverage on half the grid while the docstring still claimed to
    cover "the band scan.py ranks".

    KNOWN AND DELIBERATELY OUT OF SCOPE, recorded here so a later reader does
    not mistake it for an oversight: OUTSIDE this band, at |delta| == 1.0
    (pure-intrinsic contracts at moneyness 0.005x to 9.9x, which
    contract_rules.yaml rejects long before pricing), quadrature truncation
    leaves prices slightly BELOW forward intrinsic. Measured across the full
    243-combination grid x 7 expiries x moneyness 0.005x-9.9x: worst shortfall
    0.002235, on a $1789.94 deep-in-the-money put at 9.9x moneyness (1.2e-6
    relative). Every one of those points has |delta| == 1.0; in band the count
    is zero.

    (That figure was 0.127316 before the adaptive quadrature cutoff landed --
    the worst case was v0=0.01, kappa=0.5, theta=0.02, sigma_v=0.6, rho=-0.8
    at 1 DTE, i.e. exactly the low-variance/short-expiry regime the fixed
    cutoff of 500 under-integrated. The two defects were the same defect.)

    The high-accuracy reference returns exactly the forward intrinsic at these
    points, so the residual is quadrature truncation, not a formula error. The
    pre-F1 code did not show it only because it was grossly OVER-priced
    everywhere. Tightening heston_price's `max(price, 0.0)` clamp to the true
    no-arbitrage floor would close it, but the F1 spec scopes the put-call
    parity tail as unchanged, and no contract with |delta| == 1.0 reaches a
    card -- so it is logged as an open question, not fixed here.

    HONEST SCOPE, as for the parity test above: this does NOT catch the F1
    defect. The pre-F1 code passes this test -- its errors, though as large as
    +451% in band, all landed INSIDE [forward intrinsic, cap], so the bounds
    never caught it. Kept as a cheap structural guard on a different failure
    mode (a pricer that returns something economically impossible rather than
    merely wrong). The reference pins and the sigma_v -> 0 collapse are what
    carry correctness.
    """
    params_grid = [
        HestonParams(v0=v0, kappa=kappa, theta=theta, sigma_v=sigma_v, rho=rho)
        for v0 in (0.01, 0.09)
        for kappa in (0.5, 3.0)
        for theta in (0.02, 0.08)
        for sigma_v in (0.2, 0.6)
        for rho in (-0.8, -0.2)
    ]

    checked = 0
    for params in params_grid:
        for dte in (30, 180, 365):
            T = dte / 365
            # The model's OWN at-the-money implied volatility, backed out of
            # its own ATM price -- this is the vol whose delta defines the
            # band the scanner ranks for THESE parameters.
            atm = heston_price(S, S, T, R, params, True)
            sigma = bs_iv(atm, S, S, T, R, True) or math.sqrt(params.v0)
            for K in range(120, 321, 20):
                for is_call in (True, False):
                    if not 0.15 <= abs(bs_delta(S, K, T, R, sigma, is_call)) <= 0.90:
                        continue
                    checked += 1
                    price = heston_price(S, K, T, R, params, is_call)
                    discounted_strike = K * math.exp(-R * T)
                    if is_call:
                        floor, cap = max(S - discounted_strike, 0.0), S
                    else:
                        floor, cap = max(discounted_strike - S, 0.0), discounted_strike
                    assert math.isfinite(price), (
                        f"non-finite price at K={K} dte={dte} {params}"
                    )
                    assert price >= floor - 1e-9, (
                        f"price {price:.6f} is below forward intrinsic "
                        f"{floor:.6f} at K={K} dte={dte} "
                        f"{'call' if is_call else 'put'}, {params} -- an "
                        f"in-band arbitrage violation"
                    )
                    assert price <= cap + 1e-9, (
                        f"price {price:.6f} exceeds its cap {cap:.6f} at "
                        f"K={K} dte={dte} {'call' if is_call else 'put'}, "
                        f"{params}"
                    )

    # Exact, not a floor, for the same reason as _IN_BAND_COUNTS above.
    assert checked == 648, (
        f"{checked} in-band contracts were checked, expected 648 -- the band "
        f"filter or the grid changed and this test has quietly stopped "
        f"covering what it claims to"
    )


# --- The skew itself ---------------------------------------------------------
# Everything above either degenerates Heston to Black-Scholes or constrains
# shape rather than level. These two tests pin the model where it actually
# differs from Black-Scholes, which is the only reason it is in this codebase.

# Reference prices at the calibrator's own kind of parameters, computed by an
# INDEPENDENTLY WRITTEN Heston: the classic two-characteristic-function form
# (Heston 1993 with the Albrecher et al. little-trap branch), which reaches P1
# through its own characteristic function at b1 = kappa - rho*sigma_v and
# u1 = +1/2 -- NOT through the Bakshi-Madan shift f2(phi-i)/f2(-i) that
# heston_price uses. Two independent routes to the same number is the point;
# a transcription of this file's own algebra would prove nothing.
#
# That reference was itself validated by the sigma_v -> 0 collapse to
# Black-Scholes before being trusted, and integrated at epsabs=epsrel=1e-12,
# limit=2000, cutoff 2000.
#
# Regenerate with the recipe in the F1 spec's section 7.
_SKEW_PARAMS = HestonParams(v0=_REF_V0, kappa=2.0, theta=0.09,
                            sigma_v=0.5, rho=-0.7)
_REFERENCE_PRICES = {
    # (dte, strike, is_call): independently computed Heston price
    (45, 160.0, False): 0.4632791856029712,
    (45, 180.0, False): 2.439446661543485,
    (45, 195.0, False): 6.386167287970409,
    (45, 205.0, True): 8.905212005363282,
    (45, 225.0, True): 2.418144708635623,
    (45, 250.0, True): 0.21498810395947388,
    (180, 160.0, False): 4.0156529577676,
    (180, 180.0, False): 8.298574096680056,
    (180, 195.0, False): 13.215432341318518,
    (180, 205.0, True): 19.292646257724186,
    (180, 225.0, True): 10.65587422124571,
    (180, 250.0, True): 4.1854259398312195,
}


def test_matches_independent_reference_under_real_skew():
    """Pins heston_price against an independently written reference at the
    kind of parameters heston_cache actually selects (sigma_v 0.5, rho -0.7),
    across 0.79x-1.24x moneyness and two expiries.

    This is the test that makes the skew load-bearing. Without it, inverting
    the sign of rho passed every other check in this file.

    Measured worst relative deviation: 1.9e-9 percent (i.e. 1.9e-11 relative),
    against the 1e-7 relative bound asserted here -- a ~5000x margin. The
    bound is deliberately far looser than the measurement so that a platform's
    quadrature differing in its last bits cannot fail it, while still being
    ~1e7 times tighter than the smallest price change an inverted rho
    produces (1.228x, see the next test).
    """
    for (dte, K, is_call), expected in _REFERENCE_PRICES.items():
        T = dte / 365
        actual = heston_price(S, K, T, R, _SKEW_PARAMS, is_call)
        rel = abs(actual - expected) / expected
        assert rel < 1e-7, (
            f"heston_price disagrees with the independent reference by "
            f"{rel:.3e} relative at dte={dte} K={K} "
            f"{'call' if is_call else 'put'}: got {actual!r}, reference "
            f"{expected!r}"
        )


def test_correlation_sign_is_load_bearing():
    """Inverting rho must materially change prices.

    rho is the whole skew: negative rho fattens the left tail, so it must
    richen out-of-the-money puts and cheapen out-of-the-money calls relative
    to positive rho. A pricer that silently ignores rho -- or applies it with
    the wrong sign -- would still satisfy every Black-Scholes-degenerate check
    in this file, so this asserts the direction AND a minimum magnitude.

    Measured ratios between the rho=-0.7 and rho=+0.7 prices on these 8
    points: 1.228x to 6.465x. The 1.15x bound asserted here sits just under
    the smallest of them.
    """
    down = _SKEW_PARAMS
    up = HestonParams(v0=down.v0, kappa=down.kappa, theta=down.theta,
                      sigma_v=down.sigma_v, rho=-down.rho)

    for dte in (45, 180):
        T = dte / 365
        for K, is_call in ((160.0, False), (180.0, False),
                           (225.0, True), (250.0, True)):
            neg = heston_price(S, K, T, R, down, is_call)
            pos = heston_price(S, K, T, R, up, is_call)
            if is_call:
                # OTM call: positive correlation fattens the RIGHT tail, so it
                # must be worth more than under negative correlation.
                assert pos > neg, (
                    f"OTM call at K={K} dte={dte} is not richer at rho=+0.7 "
                    f"({pos:.6f}) than at rho=-0.7 ({neg:.6f}) -- rho's sign "
                    f"is inverted or ignored"
                )
                ratio = pos / neg
            else:
                # OTM put: negative correlation fattens the LEFT tail.
                assert neg > pos, (
                    f"OTM put at K={K} dte={dte} is not richer at rho=-0.7 "
                    f"({neg:.6f}) than at rho=+0.7 ({pos:.6f}) -- rho's sign "
                    f"is inverted or ignored"
                )
                ratio = neg / pos
            assert ratio > 1.15, (
                f"flipping rho moved the price at K={K} dte={dte} by only "
                f"{ratio:.4f}x -- rho has become nearly inert, which makes "
                f"the whole Heston model pointless here"
            )


def test_short_expiry_low_variance_is_integrated_to_convergence():
    """The quadrature cutoff must adapt to v0 and T.

    The integrands decay as ~exp(-0.5*v*T*phi**2), so the frequency beyond
    which they are negligible scales as 1/sqrt(v*T). heston_price's previous
    FIXED cutoff of 500 was ample at ordinary variance and expiry and too low
    at small variance and short expiry: at v0=0.01, theta=0.02, 1 DTE, at the
    money it returned 0.432088 against a true 0.435434 -- 0.769% low.

    This regime is reachable: v0=0.01 is in heston_cache's grid under
    HESTON_FULL_CALIBRATION, scan.py's heston_chain passes every expiry in the
    fetched chain including weeklies, and F2 will seed v0 from chain IV, so a
    low-IV underlying will reach it by default. None of the other tests in
    this file cover DTE < 7 or v0 < 0.1287, which is precisely why the broken
    cutoff survived them.

    Reference values from the same independent reference as
    test_matches_independent_reference_under_real_skew. Measured worst
    deviation after the fix: 0.0005% against the 0.05% bound here.
    """
    cases = {
        # (v0, theta, dte, strike, is_call): reference price
        (0.01, 0.02, 1, 201.86, True): 0.4354343337275708,
        (0.01, 0.04, 7, 201.86, True): 1.2347988282027984,
        (0.04, 0.02, 2, 205.0, True): 0.21422953128493205,
    }
    for (v0, theta, dte, K, is_call), expected in cases.items():
        params = HestonParams(v0=v0, kappa=2.0, theta=theta,
                              sigma_v=0.5, rho=-0.7)
        actual = heston_price(S, K, dte / 365, R, params, is_call)
        rel = abs(actual - expected) / expected
        assert rel < 5e-4, (
            f"under-integrated at v0={v0} theta={theta} dte={dte} K={K}: got "
            f"{actual!r}, reference {expected!r} ({rel * 100:.4f}% off). The "
            f"quadrature cutoff is no longer adapting to sqrt(v*T)."
        )
