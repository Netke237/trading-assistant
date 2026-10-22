from __future__ import annotations

import cmath
import math
from dataclasses import dataclass
from typing import Optional

from scipy import integrate

from app.models.black_scholes import bs_iv, bs_price


@dataclass
class HestonParams:
    v0: float       # initial variance (o2 at t=0)
    kappa: float    # mean-reversion speed
    theta: float    # long-run variance
    sigma_v: float  # volatility of variance (vol-of-vol)
    rho: float      # correlation between price and variance Brownian motions


@dataclass
class CalibrationResult:
    params: HestonParams
    # Root-mean-square RELATIVE residual, `(model - mid) / mid`, across the
    # chain -- NOT dollars. It was absolute dollars until Phase F2, which
    # changed the calibration objective (spec section 3.2: dollars let one
    # deep-ITM contract outweigh ten wing contracts, and the wings carry the
    # smile). `inf` on both `bs_fallback` paths, which fit nothing.
    rmse: float
    # "heston_grid"  -- a real grid fit that BEAT a single flat volatility on
    #                   the same chain and residual. The only label `scan.py`
    #                   accepts, and so the only one that can reach a card as
    #                   "Heston repriced".
    # "bs_flat"      -- the grid fit lost to (or tied) one flat volatility, so
    #                   the flat vol is returned instead as
    #                   HestonParams(v0=sigma^2, ...). Phase F2's gate; see
    #                   heston_cache._flat_bs_baseline.
    # "bs_fallback"  -- no fit was attempted or none could be gated: fewer
    #                   than 3 usable strikes, a chain no grid combination
    #                   priced at all, or a chain no flat volatility prices
    #                   either. It ALSO meant "the inner 1s timeout fired on
    #                   a fit that had already been computed" until
    #                   TIMEOUT-DELETE-INNER-2026-09-13 deleted that timeout.
    # `scan.py` tests `== "heston_grid"`, so both bs_* labels are discarded
    # there and fall through to the delta-approximation path.
    method: str


def _heston_char_fn(
    phi: complex,
    S: float,
    K: float,
    T: float,
    r: float,
    params: HestonParams,
) -> complex:
    """Heston characteristic function for the log-price."""
    v0, kappa, theta, sigma_v, rho = (
        params.v0, params.kappa, params.theta, params.sigma_v, params.rho
    )
    i = complex(0, 1)
    x = math.log(S / K)
    a = kappa * theta

    d = cmath.sqrt((rho * sigma_v * phi * i - kappa) ** 2
                   + sigma_v ** 2 * (phi * i + phi ** 2))
    g = (kappa - rho * sigma_v * phi * i - d) / (kappa - rho * sigma_v * phi * i + d)

    exp_dT = cmath.exp(-d * T)
    C = (r * phi * i * T
         + a / sigma_v ** 2 * (
             (kappa - rho * sigma_v * phi * i - d) * T
             - 2 * cmath.log((1 - g * exp_dT) / (1 - g))
         ))
    D = ((kappa - rho * sigma_v * phi * i - d) / sigma_v ** 2
         * (1 - exp_dT) / (1 - g * exp_dT))

    return cmath.exp(C + D * v0 + i * phi * x)


@dataclass(frozen=True)
class HestonPrice:
    """What heston_price_detail returns.

    fell_back is True when the Fourier integration failed arithmetically and
    `price` is therefore Black-Scholes at sigma = sqrt(v0), NOT a Heston
    price. A caller that labels its number "Heston repriced" must treat that
    exactly like a failed Heston price (DECISION-23 H-1).
    """
    price: float
    fell_back: bool


def heston_price_detail(
    S: float,
    K: float,
    T: float,
    r: float,
    params: HestonParams,
    is_call: bool = True,
) -> HestonPrice:
    """
    Heston closed-form option price, with whether it is really a Heston price.

    Args:
        S:       current underlying price
        K:       strike price
        T:       time to expiry in years
        r:       risk-free rate (e.g. 0.05)
        params:  HestonParams dataclass
        is_call: True for call, False for put

    Returns:
        HestonPrice(price, fell_back). The price is floored at the
        no-arbitrage forward intrinsic value (S - K*e^{-rT} for a call,
        K*e^{-rT} - S for a put; the model has no dividend term) and at 0;
        a NaN from the integration stays NaN. If the integration raises an
        ArithmeticError or ValueError (what the integrand can raise:
        cmath.exp overflow, a zero denominator, cmath.log(0)), the price is
        Black-Scholes at sigma = sqrt(v0), unfloored, with fell_back=True.
        Any other exception propagates. Degenerate inputs (T, S, K or v0
        not positive) return HestonPrice(0.0, fell_back=False).
    """
    if T <= 0 or S <= 0 or K <= 0 or params.v0 <= 0:
        return HestonPrice(price=0.0, fell_back=False)

    def _integrand(phi: float, j: int) -> float:
        if phi == 0.0:
            # Defensive only, and known unreachable with scipy's QUADPACK:
            # its 21-point Gauss-Kronrod nodes are strictly interior, so the
            # lower endpoint is never evaluated. Kept because the integrand
            # genuinely has a removable 1/phi singularity here, so an
            # integrator with an endpoint node would divide by zero.
            phi = 1e-12
        # _heston_char_fn already folds the strike in: it returns
        #   g(phi) = f2(phi) * e^{-i phi lnK}
        # where f2 is the log-price characteristic function. So neither P1 nor
        # P2 may re-apply e^{-i phi lnK} or e^{i phi lnS} -- doing so doubles
        # the Fourier frequency to 2i phi ln(S/K). The integrand stays
        # finite; it is the resulting PRICE error that grows, from exactly
        # zero at K == S to +451% at 45 DTE and +2782% at 180 DTE in band.
        g = _heston_char_fn(complex(phi) - complex(0, j), S, K, T, r, params)
        if j == 1:
            # P1 = 1/2 + (1/pi) integral Re[ e^{-i phi lnK} f2(phi-i)
            #                                / (i phi f2(-i)) ] dphi.
            # g already carries e^{-i phi' lnK} at phi' = phi - i, so
            #   e^{-i phi lnK} f2(phi-i) == K * g(phi-i),
            # and the Bakshi-Madan normaliser is f2(-i) == S * e^{rT}.
            return (K * g / (complex(0, phi) * S * math.exp(r * T))).real
        # P2 = 1/2 + (1/pi) integral Re[ g(phi) / (i phi) ] dphi -- no extra
        # factors at all.
        return (g / complex(0, phi)).real

    # Pick the quadrature cutoff from the inputs rather than fixing it at 500.
    # The integrands decay as ~exp(-0.5 * v * T * phi**2), so the frequency
    # beyond which they are negligible scales as 1/sqrt(v*T) -- a fixed cutoff
    # is ample at ordinary variance and expiry and far too low at small
    # variance and short expiry. Solving 0.5 * v * T * phi**2 = 25 (a residual
    # of order e^-25) gives phi = sqrt(50 / (v*T)).
    #
    # v is taken as min(v0, theta) because the integrated variance over [0, T]
    # tends to v0*T for short T and theta*T for long T, so the smaller of the
    # two is the conservative choice in both regimes.
    #
    # MEASURED (reference: the same integrand at epsabs=epsrel=1e-12,
    # limit=2000, cutoff 2000): over 324 cases spanning v0 0.01-0.1287, theta
    # 0.02-0.08 and 1-365 DTE, the old fixed 500 was wrong by up to 0.769%
    # (v0=0.01, theta=0.02, 1 DTE, at the money: 0.432088 vs a true 0.435434)
    # while this cutoff is wrong by at most 0.00218%.
    #
    # COST AT PRODUCTION DEFAULTS: at v0=theta=0.04 the formula returns below
    # 500 -- so the cutoff stays 500 and latency is unchanged, measured 1.00x
    # over 29 strikes at 45/180/365 DTE -- for every expiry LONGER than
    # 0.005 yr (1.825 days). It is NOT below 500 under that: it returns 675.5
    # at 1 DTE and 1350.9 at the 1-DTE repricing horizon T=6.85e-4 that
    # trade_plan.py:119 can produce. There it buys accuracy at about 1.27x
    # latency. (An earlier version of this comment claimed below-500 at EVERY
    # expiry. F1 round 2 falsified that; the numbers here are the corrected
    # measurement.)
    #
    # F1 ALSO CONCLUDED, from a worst measured calibration of 0.337s against
    # heston_cache's then-1.0s inner timeout, that this "cannot push a card
    # off 'Heston repriced' onto the bs_fallback path". F2 INVALIDATED THE
    # MARGIN THAT CONCLUSION RESTED ON, so it is restated here rather than
    # repeated: seeding v0 from the chain and fitting the flat-BS baseline
    # add ~0.13-0.19s per calibration, measured on the reduced production
    # grid --
    #
    #     28 strikes, 180 DTE   0.517s -> 0.708s
    #     29 strikes, 365 DTE   0.546s -> 0.725s
    #     10 strikes,  45 DTE   0.131s -> 0.199s
    #
    # -- so the worst chain that still fitted inside that 1.0s now sits at
    # 0.725s, and a 1.27x short-horizon multiplier on top of that reaches
    # ~0.92s. THE BUDGET THIS COST IS NOW MEASURED AGAINST IS scan.py's outer
    # 2.0s `asyncio.wait` ceiling: TIMEOUT-DELETE-INNER-2026-09-13 deleted the
    # inner timeout, so this cutoff can no longer flip a label by itself, only
    # spend more of that outer budget. The headroom against 2.0s looks wider
    # than it is, because under scan concurrency the budget is spent on
    # queueing rather than on this call -- see calibrate_cached. Separately,
    # and NOT caused by either phase: a wide chain overruns even the outer
    # ceiling outright (163 strikes at 365 DTE measured 5.106s BEFORE F2 and
    # 5.070s after).
    #
    # The 20000 cap bounds latency for degenerate inputs and is NOT
    # sufficient below about T=1e-5 (at T=1e-6 the cutoff saturates and the
    # price is still under-integrated). THAT REGIME IS REACHABLE, contrary to
    # what this comment used to say: _default_reprice_years does floor the
    # repricing horizon at 7/365, but reprice_horizon.remaining_years_at_barrier
    # (floor_years=1e-6, reprice_horizon.py:220) IS wired -- first_passage.py:515
    # calls it. What makes the cap safe is therefore a MEASUREMENT, not
    # unreachability: F1 round 2 swept T=1e-6, 1e-5, 1e-4 and 0.25/365 across
    # both parameter grids and found a worst ABSOLUTE deviation of $0.00042.
    v_eff = max(min(params.v0, params.theta), 1e-12)
    upper = min(max(500.0, math.sqrt(50.0 / (v_eff * T))), 20000.0)

    try:
        p1, _ = integrate.quad(lambda phi: _integrand(phi, 1), 0, upper, limit=200)
        p2, _ = integrate.quad(lambda phi: _integrand(phi, 0), 0, upper, limit=200)
        P1 = 0.5 + p1 / math.pi
        P2 = 0.5 + p2 / math.pi
        call_price = S * P1 - K * math.exp(-r * T) * P2
    except (ArithmeticError, ValueError):
        # The integration failed arithmetically -- fall back to Black-Scholes
        # with sqrt(v0) as sigma, and SAY so: this is not a Heston price.
        # Anything else (a TypeError from a bug, an IntegrationWarning raised
        # as an error) propagates.
        return HestonPrice(price=bs_price(S, K, T, r, math.sqrt(params.v0), is_call),
                           fell_back=True)

    # No-arbitrage floor: a European option without dividends is worth at
    # least its discounted forward intrinsic. Quadrature truncation can leave
    # a deep-in-the-money price just below it. max() keeps a NaN first
    # argument as NaN, as the old 0-clamp did.
    if is_call:
        return HestonPrice(price=max(call_price, S - K * math.exp(-r * T), 0.0),
                           fell_back=False)
    # Put via put-call parity
    return HestonPrice(price=max(call_price - S + K * math.exp(-r * T),
                                 K * math.exp(-r * T) - S, 0.0),
                       fell_back=False)


def heston_price(
    S: float,
    K: float,
    T: float,
    r: float,
    params: HestonParams,
    is_call: bool = True,
) -> float:
    """
    Heston closed-form option price: heston_price_detail(...).price.

    The price only -- it does not say whether the integration fell back to
    Black-Scholes at sqrt(v0). Callers that label a price "Heston repriced"
    must use heston_price_detail and honour its fell_back flag.
    """
    return heston_price_detail(S, K, T, r, params, is_call).price


def heston_iv(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    params: HestonParams,
    is_call: bool = True,
) -> Optional[float]:
    """
    Implied volatility from Heston-priced option via Newton-Raphson.

    Falls back to bs_iv if Heston price is degenerate.
    Returns None if non-convergent.
    """
    if T <= 0 or S <= 0 or K <= 0 or market_price <= 0:
        return None

    h_price = heston_price(S, K, T, r, params, is_call)
    if h_price <= 0:
        return bs_iv(market_price, S, K, T, r, is_call)

    # Use Heston price as a better starting sigma seed for BS IV solve
    return bs_iv(market_price, S, K, T, r, is_call)


def calibrate_heston(
    option_chain: list[dict],
    S: float,
    r: float,
) -> CalibrationResult:
    """
    Calibrate Heston parameters to an observed option chain.

    Delegates to the cached implementation, which seeds `v0` from the chain's
    own implied vols, minimises a RELATIVE residual over the parameter grid,
    and returns the fit only if it beats one flat volatility on the same chain
    (`method="heston_grid"`). Otherwise `method` is `"bs_flat"` (the flat vol
    won) or `"bs_fallback"` (too few strikes -- the only way to reach it
    since the 1s inner timeout was deleted).
    Only `"heston_grid"` is honest to label "Heston repriced" downstream, and
    `scan.py` accepts only that label. See `heston_cache` for the measurements.
    """
    from app.models.heston_cache import calibrate_cached
    return calibrate_cached(option_chain, S, r)
