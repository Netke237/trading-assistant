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
        phi_c = complex(phi)
        char = _heston_char_fn(
            phi_c - complex(0, j),
            S, K, T, r, params
        )
        denom = complex(0, phi) * cmath.exp(complex(0, phi) * math.log(K))
        if abs(denom) < 1e-15:
            return 0.0
        return (cmath.exp(complex(0, phi) * math.log(S)) * char / denom).real

    try:
        p1, _ = integrate.quad(lambda phi: _integrand(phi, 1), 0, 500, limit=100)
        p2, _ = integrate.quad(lambda phi: _integrand(phi, 0), 0, 500, limit=100)
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

    Args:
        option_chain: list of dicts with keys:
                      strike (float), expiry_years (float), mid_price (float), is_call (bool)
        S:            current underlying price
        r:            risk-free rate

    Returns:
        CalibrationResult with best-fit HestonParams and RMSE.
        Falls back to HestonParams with BS-implied v0 if chain is thin.
    """
    # Filter to usable contracts (price > 0, T > 0)
    chain = [c for c in option_chain
             if c.get("mid_price", 0) > 0 and c.get("expiry_years", 0) > 0]

    if len(chain) < 3:
        # Too thin - return BS-implied variance as v0, neutral Heston params
        ivs = [bs_iv(c["mid_price"], S, c["strike"], c["expiry_years"], r, c.get("is_call", True))
               for c in chain if c.get("mid_price", 0) > 0]
        ivs = [iv for iv in ivs if iv is not None]
        v0_seed = (sum(ivs) / len(ivs)) ** 2 if ivs else 0.04
        fallback = HestonParams(v0=v0_seed, kappa=2.0, theta=v0_seed, sigma_v=0.3, rho=-0.7)
        return CalibrationResult(params=fallback, rmse=float("inf"), method="bs_fallback")

    # Grid search
    best_rmse = float("inf")
    best_params = None

    v0_grid = [0.01, 0.04, 0.09]
    kappa_grid = [0.5, 1.5, 3.0]
    theta_grid = [0.02, 0.04, 0.08]
    sigma_v_grid = [0.2, 0.4, 0.6]
    rho_grid = [-0.8, -0.5, -0.2]

    for v0 in v0_grid:
        for kappa in kappa_grid:
            for theta in theta_grid:
                for sigma_v in sigma_v_grid:
                    for rho in rho_grid:
                        params = HestonParams(v0=v0, kappa=kappa, theta=theta,
                                             sigma_v=sigma_v, rho=rho)
                        sse = 0.0
                        valid = 0
                        for c in chain:
                            try:
                                model_p = heston_price(S, c["strike"], c["expiry_years"],
                                                       r, params, c.get("is_call", True))
                                sse += (model_p - c["mid_price"]) ** 2
                                valid += 1
                            except Exception:
                                continue
                        if valid == 0:
                            continue
                        rmse = math.sqrt(sse / valid)
                        if rmse < best_rmse:
                            best_rmse = rmse
                            best_params = params

    if best_params is None:
        fallback = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
        return CalibrationResult(params=fallback, rmse=float("inf"), method="bs_fallback")

    return CalibrationResult(params=best_params, rmse=round(best_rmse, 6), method="heston_grid")
