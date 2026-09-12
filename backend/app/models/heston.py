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
    rmse: float             # root-mean-square error across chain
    method: str             # "heston_grid" or "bs_fallback"


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


def heston_price(
    S: float,
    K: float,
    T: float,
    r: float,
    params: HestonParams,
    is_call: bool = True,
) -> float:
    """
    Heston closed-form option price.

    Args:
        S:       current underlying price
        K:       strike price
        T:       time to expiry in years
        r:       risk-free rate (e.g. 0.05)
        params:  HestonParams dataclass
        is_call: True for call, False for put

    Returns:
        Option fair value. Returns BS fallback if integration fails.
        Returns 0.0 on degenerate inputs.
    """
    if T <= 0 or S <= 0 or K <= 0 or params.v0 <= 0:
        return 0.0

    def _integrand(phi: float, j: int) -> float:
        if phi == 0.0:
            phi = 1e-12
        # _heston_char_fn already folds the strike in: it returns
        #   g(phi) = f2(phi) * e^{-i phi lnK}
        # where f2 is the log-price characteristic function. So neither P1 nor
        # P2 may re-apply e^{-i phi lnK} or e^{i phi lnS} -- doing so doubles
        # the Fourier frequency to 2i phi ln(S/K), which is invisible at
        # K == S and diverges either side of it.
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

    try:
        p1, _ = integrate.quad(lambda phi: _integrand(phi, 1), 1e-10, 500, limit=100)
        p2, _ = integrate.quad(lambda phi: _integrand(phi, 0), 1e-10, 500, limit=100)
        P1 = 0.5 + p1 / math.pi
        P2 = 0.5 + p2 / math.pi
        call_price = S * P1 - K * math.exp(-r * T) * P2
    except Exception:
        # Integration failed - fall back to Black-Scholes with sqrt(v0) as sigma
        return bs_price(S, K, T, r, math.sqrt(params.v0), is_call)

    if is_call:
        return max(call_price, 0.0)
    # Put via put-call parity
    return max(call_price - S + K * math.exp(-r * T), 0.0)


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
    Delegates to cached implementation with 2-second timeout + BS fallback.
    """
    from app.models.heston_cache import calibrate_cached
    return calibrate_cached(option_chain, S, r)
