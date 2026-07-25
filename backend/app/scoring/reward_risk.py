from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from app.models.heston import HestonParams, heston_price

RrModel = Literal["Heston repriced", "Delta approximation"]


@dataclass
class RrResult:
    rr_ratio: float
    model_used: RrModel
    estimated_exit_premium: float


def estimate_rr(
    stock_price: float,
    target_price: float,
    invalidation_price: float,   # reserved: kept for call-site symmetry; risk is now premium * premium_stop_pct, not invalidation-based
    strike: float,
    expiry_years: float,
    current_premium: float,
    is_call: bool,
    r: float = 0.05,
    heston_params: HestonParams | None = None,
    sigma_fallback: float = 0.25,
    premium_stop_pct: float = 0.60,   # fraction of premium at risk (stop-loss basis)
) -> RrResult:
    model_used: RrModel
    heston_ok = False

    if heston_params is not None:
        dte_at_target = max(expiry_years * 0.5, 7 / 365)
        try:
            heston_exit_premium = heston_price(target_price, strike, dte_at_target, r, heston_params, is_call)
        except Exception:
            heston_exit_premium = 0.0
        heston_ok = heston_exit_premium > 0

    if heston_ok:
        exit_premium = heston_exit_premium
        model_used = "Heston repriced"
    else:
        if is_call:
            delta = 0.5 if target_price > strike else 0.3
        else:
            delta = 0.5 if target_price < strike else 0.3
        price_move = abs(target_price - stock_price)
        exit_premium = current_premium + delta * price_move
        model_used = "Delta approximation"

    exit_premium = max(exit_premium, 0.01)

    risk = current_premium * premium_stop_pct   # only risk the stop-loss fraction
    reward = exit_premium - current_premium

    if reward <= 0 or risk <= 0:
        return RrResult(rr_ratio=0.0, model_used=model_used, estimated_exit_premium=round(exit_premium, 2))

    rr_ratio = round(reward / risk, 2)
    return RrResult(
        rr_ratio=rr_ratio,
        model_used=model_used,
        estimated_exit_premium=round(exit_premium, 2),
    )


def estimate_targets(
    stock_price: float,
    base_target_price: float,   # T1 = the existing single target
    strike: float,
    expiry_years: float,
    current_premium: float,
    is_call: bool,
    r: float = 0.05,
    heston_params: HestonParams | None = None,
    sigma_fallback: float = 0.25,
    premium_stop_pct: float = 0.60,
) -> list:
    """
    Build 3 target levels: T1=base, T2=base*1.5 move, T3=base*2.0 move.
    For Bullish calls: T2 = stock_price + 1.5 * (T1 - stock_price)
    For Bearish puts:  T2 = stock_price - 1.5 * (stock_price - T1)
    Each level repriced via Heston if available, else delta approximation.

    premium_stop_pct: fraction of current_premium used as risk basis for R/R (default 0.60).
    """
    from app.schemas import TargetLevel as TargetLevelSchema, PricingMethod

    move = abs(base_target_price - stock_price)
    direction_sign = 1 if base_target_price > stock_price else -1

    targets_prices = [
        stock_price + direction_sign * move,          # T1
        stock_price + direction_sign * move * 1.5,    # T2
        stock_price + direction_sign * move * 2.0,    # T3
    ]

    results = []
    prev_opt_price = None  # only meaningful once T1 has been priced — see below
    for t_price in targets_prices:
        dte_at_target = max(expiry_years * 0.5, 7 / 365)
        opt_price = None
        method: PricingMethod

        if heston_params is not None:
            try:
                opt_price = heston_price(t_price, strike, dte_at_target, r, heston_params, is_call)
                method = PricingMethod.HESTON
            except Exception:
                opt_price = None
                method = PricingMethod.UNAVAILABLE
        else:
            opt_price = None
            method = PricingMethod.DELTA_APPROX

        # T1/T2/T3 share dte_at_target and only differ in t_price, so a
        # correctly-priced option must be monotonically increasing ACROSS
        # THAT LADDER — a Heston price that comes out lower than the
        # previous level's chosen price is a numerical-integration artifact
        # (see this task's intro), not a real option value. This must NEVER
        # be compared against current_premium: current_premium is priced at
        # the full expiry_years, a longer tenor than dte_at_target, so a
        # legitimate T1 price can be lower than current_premium purely from
        # time decay — prev_opt_price starts at None so T1 is never checked
        # against anything. Guard only the Heston case; the pure
        # delta-approximation path is untouched.
        non_monotonic = (
            method == PricingMethod.HESTON
            and opt_price is not None
            and prev_opt_price is not None
            and opt_price < prev_opt_price
        )

        if opt_price is None or opt_price <= 0 or non_monotonic:
            delta = 0.5 if (is_call and t_price > strike) or (not is_call and t_price < strike) else 0.3
            price_move = abs(t_price - stock_price)
            opt_price = max(0.01, current_premium + delta * price_move)
            method = PricingMethod.DELTA_APPROX

        prev_opt_price = opt_price

        reward = opt_price - current_premium
        risk_basis = current_premium * premium_stop_pct
        rr = round(reward / risk_basis, 2) if risk_basis > 0 and reward > 0 else 0.0

        results.append(TargetLevelSchema(
            targetPrice=round(t_price, 2),
            stockPrice=round(t_price, 2),
            estimatedOptionPrice=round(opt_price, 2),
            pricingMethod=method,
            rrContribution=rr,
        ))

    return results