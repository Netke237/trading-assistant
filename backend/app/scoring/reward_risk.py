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
    invalidation_price: float,
    strike: float,
    expiry_years: float,
    current_premium: float,
    is_call: bool,
    r: float = 0.05,
    heston_params: HestonParams | None = None,
    sigma_fallback: float = 0.25,
) -> RrResult:
    model_used: RrModel

    if heston_params is not None:
        dte_at_target = max(expiry_years * 0.5, 7 / 365)
        exit_premium = heston_price(target_price, strike, dte_at_target, r, heston_params, is_call)
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

    risk = current_premium
    reward = exit_premium - current_premium

    if reward <= 0 or risk <= 0:
        return RrResult(rr_ratio=0.0, model_used=model_used, estimated_exit_premium=exit_premium)

    rr_ratio = round(reward / risk, 2)
    return RrResult(
        rr_ratio=rr_ratio,
        model_used=model_used,
        estimated_exit_premium=round(exit_premium, 2),
    )