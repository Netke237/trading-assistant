from __future__ import annotations

import math
from typing import Optional

from scipy.stats import norm


def _d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    return (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))


def _d2(S: float, K: float, T: float, r: float, sigma: float) -> float:
    return _d1(S, K, T, r, sigma) - sigma * math.sqrt(T)


def bs_price(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    is_call: bool = True,
) -> float:
    """
    Black-Scholes option price.

    Args:
        S: current underlying price
        K: strike price
        T: time to expiry in years (e.g. 30 days → 30/365)
        r: risk-free rate (e.g. 0.05 for 5%)
        sigma: annualised implied volatility (e.g. 0.25 for 25%)
        is_call: True for call, False for put

    Returns:
        Option fair value in the same currency as S and K.
        Returns 0.0 if inputs are invalid (T <= 0, sigma <= 0, S <= 0, K <= 0).
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1 = _d1(S, K, T, r, sigma)
    d2 = _d2(S, K, T, r, sigma)
    if is_call:
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    else:
        return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def bs_delta(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    is_call: bool = True,
) -> float:
    """
    Black-Scholes delta (dV/dS).
    Range: [0, 1] for calls, [-1, 0] for puts.
    Returns 0.0 on invalid inputs.
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1 = _d1(S, K, T, r, sigma)
    if is_call:
        return float(norm.cdf(d1))
    else:
        return float(norm.cdf(d1) - 1)


def bs_theta(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    is_call: bool = True,
) -> float:
    """
    Black-Scholes theta (dV/dt) per calendar day (negative for long positions).

    Returns the daily decay in the same currency as S and K.
    Returns 0.0 on invalid inputs.
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1 = _d1(S, K, T, r, sigma)
    d2 = _d2(S, K, T, r, sigma)
    # Annual theta
    pdf_d1 = norm.pdf(d1)
    annual: float
    if is_call:
        annual = (
            -(S * pdf_d1 * sigma) / (2 * math.sqrt(T))
            - r * K * math.exp(-r * T) * norm.cdf(d2)
        )
    else:
        annual = (
            -(S * pdf_d1 * sigma) / (2 * math.sqrt(T))
            + r * K * math.exp(-r * T) * norm.cdf(-d2)
        )
    # Convert to per-calendar-day
    return round(annual / 365, 4)


def bs_iv(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    is_call: bool = True,
    tol: float = 1e-6,
    max_iter: int = 100,
) -> Optional[float]:
    """
    Implied volatility via Newton-Raphson iteration.

    Returns the annualised IV that reproduces `market_price`,
    or None if non-convergent or invalid inputs.

    Args:
        market_price: observed option mid-price
        S, K, T, r, is_call: same as bs_price
        tol: convergence tolerance (default 1e-6)
        max_iter: maximum iterations before giving up
    """
    if market_price <= 0 or T <= 0 or S <= 0 or K <= 0:
        return None

    # Initial guess: Brenner-Subrahmanyam approximation
    sigma = math.sqrt(2 * math.pi / T) * market_price / S

    for _ in range(max_iter):
        price = bs_price(S, K, T, r, sigma, is_call)
        if abs(price - market_price) < tol:
            return round(sigma, 6)

        # Vega = S * N'(d1) * sqrt(T)
        d1 = _d1(S, K, T, r, sigma)
        vega = S * norm.pdf(d1) * math.sqrt(T)
        if vega < 1e-10:
            return None  # degenerate — give up

        sigma -= (price - market_price) / vega

        if sigma <= 0:
            return None  # crossed zero — non-convergent

    return None  # did not converge within max_iter
