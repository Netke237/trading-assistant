"""Monte Carlo first-passage-time estimator for option profit targets.

Two-stage design:

  Stage 1 (display only): given a desired profit % on the option's premium,
  solve backward for the underlying stock price that would deliver it, at a
  fixed reprice horizon (the same dte_at_target convention
  reward_risk.estimate_targets already uses). This number is shown to the
  user as "roughly what stock price gets you there" — it is NOT what
  Stage 2 tests against.

  Stage 2 (the actual estimate): simulate the stock under GBM using an
  ATR-derived volatility and a signal-strength-derived drift, reprice the
  OPTION along every simulated day (shrinking time-to-expiry, not the fixed
  Stage-1 horizon), and record the first day each path's repriced option
  value crosses the profit threshold. This is what makes delta's effect on
  time-to-target implicit and correct instead of a hand-wavy day-count
  conversion: a low-delta contract's repriced value moves less per day for
  the same stock path, so it naturally takes longer, or never happens, in
  the simulation.

sigma_iv (the option's own implied vol, used for repricing) and sigma_stock
(the stock's own ATR-derived realized vol, used to drive the GBM path) are
DELIBERATELY different quantities — never conflate them.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.stats import norm

from app.models.black_scholes import bs_price
from app.scoring.reward_risk import _derive_fallback_sigma
from app.scoring.stock_scorer import _atr


@dataclass
class TargetEstimate:
    pct: float
    stock_price: Optional[float]   # None if unreachable within the Stage-1 bisection bracket
    option_price: float            # premium * (1 + pct) — trivial, kept for display convenience
    probability: float
    expected_days: Optional[float]   # None if probability == 0


@dataclass
class InvalidationEstimate:
    probability: float
    expected_days: Optional[float]


@dataclass
class FirstPassageResult:
    targets: list[TargetEstimate]
    invalidation: InvalidationEstimate
    sigma_stock: float
    mu: float


def _vectorized_bs_price(
    S: np.ndarray, K: float, T: float, r: float, sigma: float, is_call: bool,
) -> np.ndarray:
    """Numpy-vectorized Black-Scholes price — mathematically identical to
    app.models.black_scholes.bs_price, operating on a whole array of spot
    prices at once. bs_price itself cannot be vectorized: its d1/d2 helpers
    use Python's math module (math.log, math.sqrt), which raise on ndarray
    input. Kept private to this module's Monte Carlo hot path — the scalar
    bs_price is still used everywhere else here (Stage 1's bisection, the
    sigma_iv fallback derivation) where call counts are low and duplicating
    the formula isn't worth it. Unit-tested against bs_price for agreement
    (test_first_passage.py) so the two can never silently diverge.
    """
    if T <= 0 or sigma <= 0:
        return np.zeros_like(S, dtype=float)
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if is_call:
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def _solve_target_stock_price(
    stock_price: float,
    strike: float,
    dte_at_target: float,
    r: float,
    sigma_iv: float,
    is_call: bool,
    target_option_price: float,
    max_iter: int = 100,
    tol: float = 1e-4,
) -> Optional[float]:
    """Bisection: find S such that bs_price(S, ...) == target_option_price.

    Bracket is [stock_price * 0.01, stock_price * 5] — scaled to the stock's
    own price rather than a bare absolute floor (which would be nonsensically
    tight for a $500 stock and numerically dicey for a $2 one). bs_price is
    monotonic in S for a fixed-sign option (increasing for calls, decreasing
    for puts), so a target outside the bracket's reachable range genuinely
    isn't reachable at this dte_at_target/sigma_iv — not a solver failure —
    and this returns None rather than a garbage extrapolated price.
    """
    lo, hi = stock_price * 0.01, stock_price * 5.0
    f_lo = bs_price(lo, strike, dte_at_target, r, sigma_iv, is_call)
    f_hi = bs_price(hi, strike, dte_at_target, r, sigma_iv, is_call)

    if is_call:
        if not (f_lo <= target_option_price <= f_hi):
            return None
    else:
        if not (f_hi <= target_option_price <= f_lo):
            return None

    for _ in range(max_iter):
        mid = (lo + hi) / 2
        f_mid = bs_price(mid, strike, dte_at_target, r, sigma_iv, is_call)
        if abs(f_mid - target_option_price) < tol:
            return mid
        higher_than_target = f_mid < target_option_price
        if is_call:
            lo, hi = (mid, hi) if higher_than_target else (lo, mid)
        else:
            lo, hi = (lo, mid) if higher_than_target else (mid, hi)
    return (lo + hi) / 2


def estimate_first_passage(
    *,
    stock_price: float,
    strike: float,
    dte: int,
    premium: float,
    delta: float,
    is_call: bool,
    trend_score: float,
    invalidation_price: float,
    candles: list[dict],
    t1_pct: float,
    t2_pct: float,
    t3_pct: float,
    r: float = 0.05,
    sigma_fallback: float = 0.25,
    max_drift_pct: float = 0.40,
    n_paths: int = 2000,
    sigma_floor: float = 0.10,
    sigma_ceiling: float = 1.50,
    seed: int = 0,
) -> FirstPassageResult:
    """Estimate, for each of t1_pct/t2_pct/t3_pct, the probability and
    expected days to hit that profit level before expiry, plus the same for
    the invalidation price — via Monte Carlo GBM simulation of the stock,
    repricing the option along every simulated day.

    `delta` is accepted for API symmetry with the rest of this codebase's
    trade-plan functions but is not used directly: its effect on time-to-
    target is implicit in the option repricing itself (see module
    docstring), not a separate day-count adjustment.

    `seed` makes this deterministic for a given set of inputs — callers
    (the API endpoint) are expected to derive it from the request's own
    fields so identical button presses return identical answers, while
    genuinely different inputs still get an independent draw. Pass an
    explicit fixed seed in tests.
    """
    del delta  # see docstring — folded in via option repricing, not used directly here

    expiry_years = dte / 365.0
    premium = max(float(premium), 0.01)

    sigma_iv = _derive_fallback_sigma(premium, stock_price, strike, expiry_years, r, is_call, sigma_fallback)

    atr = _atr(candles, 14) if candles else 0.0
    sigma_stock = sigma_floor
    if stock_price > 0:
        sigma_stock = max(sigma_floor, min(sigma_ceiling, (atr / stock_price) * math.sqrt(252)))

    direction_sign = 1.0 if is_call else -1.0
    mu = direction_sign * (trend_score - 50) / 50 * max_drift_pct

    dte_at_target = max(expiry_years * 0.5, 7 / 365)
    pcts = [t1_pct, t2_pct, t3_pct]
    target_option_prices = [premium * (1 + p) for p in pcts]
    target_stock_prices = [
        _solve_target_stock_price(stock_price, strike, dte_at_target, r, sigma_iv, is_call, top)
        for top in target_option_prices
    ]

    # Zero/near-zero DTE guard: this app's Intraday horizon routinely has
    # contracts at or near 0 DTE. A zero-length simulation would either crash
    # (median() on an empty array) or return meaningless stats — skip it
    # outright rather than attempt it.
    if dte < 1:
        targets = [
            TargetEstimate(pct=p, stock_price=sp, option_price=top, probability=0.0, expected_days=None)
            for p, sp, top in zip(pcts, target_stock_prices, target_option_prices)
        ]
        return FirstPassageResult(
            targets=targets,
            invalidation=InvalidationEstimate(probability=0.0, expected_days=None),
            sigma_stock=sigma_stock,
            mu=mu,
        )

    rng = np.random.default_rng(seed)
    n_days = dte
    dt = 1 / 365

    z = rng.standard_normal((n_paths, n_days))
    log_returns = (mu - 0.5 * sigma_stock ** 2) * dt + sigma_stock * math.sqrt(dt) * z
    log_paths = np.cumsum(log_returns, axis=1)
    stock_paths = stock_price * np.exp(log_paths)   # shape (n_paths, n_days); column i = end of day i+1

    option_paths = np.empty_like(stock_paths)
    for day in range(n_days):
        t_remaining = max(expiry_years - (day + 1) * dt, 1e-6)
        option_paths[:, day] = _vectorized_bs_price(stock_paths[:, day], strike, t_remaining, r, sigma_iv, is_call)

    targets: list[TargetEstimate] = []
    for pct, target_stock, target_option in zip(pcts, target_stock_prices, target_option_prices):
        # "Profit" always means the option's own value rose past the target —
        # true for both calls and puts alike, since bs_price already accounts
        # for direction; no separate is_call branch needed here.
        hit_mask = option_paths >= target_option
        ever_hit = hit_mask.any(axis=1)
        probability = float(ever_hit.mean())
        expected_days: Optional[float] = None
        if ever_hit.any():
            first_hit_day = np.argmax(hit_mask, axis=1)   # index of first True per row
            expected_days = float(np.median(first_hit_day[ever_hit]) + 1)   # +1: column 0 == day 1
        targets.append(TargetEstimate(
            pct=pct, stock_price=target_stock, option_price=target_option,
            probability=probability, expected_days=expected_days,
        ))

    # Invalidation is a stock-price barrier already computed by trade_plan.py
    # (delta-linear back-solve) — checked directly against the raw stock
    # path, no option repricing needed.
    stop_hit_mask = stock_paths <= invalidation_price if is_call else stock_paths >= invalidation_price
    stop_ever_hit = stop_hit_mask.any(axis=1)
    stop_probability = float(stop_ever_hit.mean())
    stop_expected_days: Optional[float] = None
    if stop_ever_hit.any():
        stop_first_hit_day = np.argmax(stop_hit_mask, axis=1)
        stop_expected_days = float(np.median(stop_first_hit_day[stop_ever_hit]) + 1)

    return FirstPassageResult(
        targets=targets,
        invalidation=InvalidationEstimate(probability=stop_probability, expected_days=stop_expected_days),
        sigma_stock=sigma_stock,
        mu=mu,
    )
