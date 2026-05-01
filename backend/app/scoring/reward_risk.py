from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.models.heston import HestonParams


@dataclass
class RrResult:
    rr_ratio: float
    model_used: str


def estimate_rr(
    stock_price: float,
    target_price: float,
    invalidation_price: float,
    strike: float,
    expiry_years: float,
    current_premium: float,
    is_call: bool,
    heston_params: Optional[HestonParams] = None,
) -> RrResult:
    """
    Estimate reward-to-risk ratio for an option trade.
    """
    reward = abs(target_price - stock_price)
    risk = abs(stock_price - invalidation_price)
    rr = round(reward / risk, 2) if risk > 0 else 0.0
    return RrResult(rr_ratio=rr, model_used="Delta approximation")
