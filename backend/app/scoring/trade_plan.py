"""Shared trade-plan builder.

Both the scan pipeline (app.routers.scan) and the per-contract recompute
endpoint (app.routers.contracts) derive a trade's Entry Plan, Exit Plan,
reward/risk and sell-to-close targets from the *selected contract's* premium.
Keeping that arithmetic in one place is deliberate: when the user
overrides the auto-picked contract in Step 6, the Exit Plan must be recomputed
off the new premium — a second, drifting copy of this math is exactly what let
the premium-stop / invalidation / targets keep describing the old contract.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.models.heston import HestonParams
from app.scoring.entry_quality import assess_entry, EntryAssessment
from app.scoring.reward_risk import estimate_rr, estimate_targets


@dataclass
class TradePlan:
    entry: EntryAssessment
    invalidation_price: float        # rounded — for display
    premium_stop: float
    time_stop_days: int
    target_price: float              # rounded — for display
    targets: list
    rr_ratio: float
    rr_model: str
    # Unrounded values, so callers that feed them into further estimate_rr calls
    # (e.g. the scan's runner-up alternatives) match the pre-refactor behaviour
    # exactly instead of drifting by a sub-cent rounding step.
    target_price_raw: float
    invalidation_price_raw: float


def build_trade_plan(
    *,
    direction: str,
    stock_price: float,
    strike: float,
    dte: int,
    premium: float,
    entry_bid: float,
    entry_ask: float,
    entry_mid: float,
    rr_cfg: dict,
    heston_params: HestonParams | None = None,
) -> TradePlan:
    """Compute the full trade plan for one contract.

    Args:
        direction:   "Bullish" (call) or "Bearish" (put).
        stock_price: current underlying price.
        strike:      option strike.
        dte:         days to expiration.
        premium:     the contract mid used as the risk/target basis (floored by caller).
        entry_bid/entry_ask/entry_mid: feed assess_entry for the Entry Plan.
        rr_cfg:      the reward_risk config block (bullish_target_pct,
                     bearish_target_pct, bullish_invalidation_pct,
                     bearish_invalidation_pct, premium_stop_pct).
        heston_params: optional calibrated Heston params — when provided,
                     estimate_rr/estimate_targets reprice via Heston (with a
                     per-target delta-approximation fallback); defaults to
                     None (unchanged, delta-approximation-only behaviour).
    """
    is_call = direction == "Bullish"
    premium = max(float(premium), 0.01)
    premium_stop_pct = rr_cfg["premium_stop_pct"]

    target_price = (
        stock_price * (1 + rr_cfg["bullish_target_pct"]) if is_call
        else stock_price * (1 - rr_cfg["bearish_target_pct"])
    )
    expiry_years = dte / 365.0

    # Invalidation is a stock-price percentage move, mirroring target_price's
    # own formula -- NOT derived from premium_stop_pct/delta (that was a
    # pre-existing bug: bullish_invalidation_pct/bearish_invalidation_pct are
    # documented in risk_rules.yaml as "-3% stock = invalidation" but were
    # never actually read anywhere). premium_stop_pct remains a separate,
    # independent concept (the dollar premium_stop field below, and the
    # risk basis inside estimate_rr/estimate_targets) -- unaffected by this fix.
    invalidation_price = (
        max(stock_price * (1 - rr_cfg["bullish_invalidation_pct"]), 0.01) if is_call
        else stock_price * (1 + rr_cfg["bearish_invalidation_pct"])
    )

    entry = assess_entry(bid=entry_bid, ask=entry_ask, mid=entry_mid)

    rr = estimate_rr(
        stock_price=stock_price,
        target_price=target_price,
        invalidation_price=invalidation_price,
        strike=strike,
        expiry_years=expiry_years,
        current_premium=premium,
        is_call=is_call,
        heston_params=heston_params,
        premium_stop_pct=premium_stop_pct,
    )

    targets = estimate_targets(
        stock_price=stock_price,
        base_target_price=target_price,
        strike=strike,
        expiry_years=expiry_years,
        current_premium=premium,
        is_call=is_call,
        heston_params=heston_params,
        premium_stop_pct=premium_stop_pct,
    )

    return TradePlan(
        entry=entry,
        invalidation_price=round(invalidation_price, 2),
        premium_stop=round(premium * premium_stop_pct, 2),
        time_stop_days=max(3, int(dte * 0.4)),
        target_price=round(target_price, 2),
        targets=targets,
        rr_ratio=rr.rr_ratio,
        rr_model=rr.model_used,
        target_price_raw=target_price,
        invalidation_price_raw=invalidation_price,
    )
