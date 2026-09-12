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

Every tolerance below is measured, not guessed, and the margin to the nearest
real failure is stated per test. Deliberately NO reference Heston prices copied
from a paper: parameterisation conventions differ between sources, and a
mismatched convention produces a test that is wrong in the same direction as
the code. These are all self-contained invariants.
"""
import math

import pytest

from app.models.black_scholes import bs_delta, bs_price
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

_DTES = (7, 45, 180, 365)
_MONEYNESS = (0.74, 0.89, 0.99, 1.02, 1.14, 1.36)


def _near_bs_params(v0: float = 0.1287) -> HestonParams:
    """Heston degenerated toward Black-Scholes: variance pinned at its
    long-run level (v0 == theta, so there is nothing to mean-revert toward),
    vol-of-vol as close to zero as the closed form tolerates, and no
    correlation. Heston must then reproduce Black-Scholes at sigma = sqrt(v0).
    sigma_v is 0.01 rather than 0.0 because sigma_v appears in
    _heston_char_fn's denominators."""
    return HestonParams(v0=v0, kappa=2.0, theta=v0, sigma_v=0.01, rho=0.0)


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
                if expected < _MIN_PREMIUM:
                    continue
                actual = heston_price(S, K, T, R, params, is_call)
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
        assert in_band >= 8, (
            f"only {in_band} strikes fell in the |delta| 0.15-0.90 band at "
            f"{dte} DTE -- the band or the strike ladder changed, and this "
            f"test is no longer covering what it claims to"
        )


def test_no_arbitrage_bounds_hold_across_the_scanner_delta_band():
    """Inside the band scan.py ranks, every price must sit between its
    forward intrinsic and its theoretical cap -- a call in
    [max(S - K*e^{-rT}, 0), S], a put in [max(K*e^{-rT} - S, 0), K*e^{-rT}].

    Measured over the FULL 243-combination calibration grid
    (HESTON_FULL_CALIBRATION=1) x 7 expiries x 61 strikes x both rights:
    43659 in-band contracts, ZERO violations, worst shortfall 0.0. This test
    runs a reduced parameter set for runtime; the full sweep is reproducible
    from the F1 spec's section 7.

    HONEST SCOPE, as for the parity test above: this does NOT catch the F1
    defect. The pre-F1 code passes this test -- its errors, though as large as
    +451% in band, all landed INSIDE [forward intrinsic, cap], so the bounds
    never caught it. Kept as a cheap structural guard on a different failure
    mode (a pricer that returns something economically impossible rather than
    merely wrong). Test 1 and test 4 are what carry correctness.

    KNOWN AND DELIBERATELY OUT OF SCOPE, recorded here so a later reader does
    not mistake it for an oversight: OUTSIDE this band, at |delta| == 1.0
    (pure-intrinsic contracts at moneyness from 0.005x to 9.9x, which
    contract_rules.yaml rejects long before pricing), quadrature truncation
    leaves prices up to 0.127 BELOW forward intrinsic on a $200.86 option
    (6e-4 relative; 0.0005 at the production default v0=0.04). The
    high-accuracy reference returns exactly the forward intrinsic there, so
    the residual is quadrature error, not a formula error. The pre-F1 code
    did not show it only because it was grossly OVER-priced everywhere.
    Tightening heston_price's `max(price, 0.0)` clamp to the true
    no-arbitrage floor would close it, but the F1 spec scopes the put-call
    parity tail as unchanged, and no contract with |delta| == 1.0 reaches a
    card -- so it is logged as an open question, not fixed here.
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
        sigma = math.sqrt(params.v0)
        for dte in (30, 180, 365):
            T = dte / 365
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

    assert checked > 500, (
        f"only {checked} in-band contracts were actually checked -- the band "
        f"filter or the grid changed and this test has quietly stopped "
        f"covering what it claims to"
    )
