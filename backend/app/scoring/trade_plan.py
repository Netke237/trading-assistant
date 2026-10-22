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
from app.scoring.exit_plan import BEARISH_MIN_TARGET_FRACTION
from app.scoring.entry_quality import assess_entry, EntryAssessment, EntryConfig
from app.scoring.reprice_horizon import display_reprice_years
from app.scoring.reward_risk import estimate_rr, estimate_targets, captured_stock_risk


@dataclass
class TradePlan:
    entry: EntryAssessment
    invalidation_price: float        # rounded — for display; the resolved stock stop (piece 3)
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
    # The horizon the target/stop legs were repriced at, in years REMAINING —
    # display_reprice_years(preset, hold_min, hold_max, dte). Exposed so a test
    # can pin it against the Monte Carlo card's Stage 1 horizon directly, rather
    # than inferring agreement from two option prices that happen to match.
    reprice_years: float
    rr_risk_basis: str
    target_source: str
    stock_stop_loss: float | None
    stock_stop_loss_at: float | None


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
    final_stop_price: float,
    target_price: float,
    stop_cost_fraction: float | None,
    target_source: str = "arithmetic",
    heston_params: HestonParams | None = None,
    horizon_preset: str | None = None,
    hold_min: float | None = None,
    hold_max: float | None = None,
    reprice_cfg: dict | None = None,
    quote_live: bool | None = None,
    entry_cfg: EntryConfig | dict | None = None,
) -> TradePlan:
    """Compute the full trade plan for one contract.

    Args:
        direction:   "Bullish" (call) or "Bearish" (put).
        stock_price: current underlying price.
        strike:      option strike.
        dte:         days to expiration.
        premium:     the contract mid used as the risk/target basis (floored by caller).
        entry_bid/entry_ask/entry_mid: feed assess_entry for the Entry Plan.
        rr_cfg:      the reward_risk config block (premium_stop_pct). The
                     bullish/bearish_invalidation_pct keys are NOT read here
                     any more -- see final_stop_price.
        final_stop_price: the stock stop this plan is built around, already
                     resolved by the caller via
                     `app.scoring.exit_plan.resolve_stock_stop` (the wider of
                     the structural level and a 2xATR floor, or that helper's
                     flat-percentage fallback on a degenerate bar feed).
                     REQUIRED and positional-safe by keyword only: defaulting
                     it would let a caller silently fall back to a stop nobody
                     chose, which is the exact failure piece 3 exists to end.
                     Floored at $0.01.
        heston_params: optional calibrated Heston params — when provided,
                     estimate_rr/estimate_targets reprice via Heston (with a
                     per-target delta-approximation fallback); defaults to
                     None (unchanged, delta-approximation-only behaviour).
        horizon_preset: the HOLDING preset key the trader picked — "Intraday",
                     "Swing", "Position", "Quarterly", "SemiAnnual", "Annual" or
                     "Custom". NOT the collapsed scoring horizon: Quarterly,
                     SemiAnnual and Annual all score as "Position" but reprice
                     at 25, 45 and 80 days respectively, so passing the scoring
                     horizon here would quietly give a 200-day hold and a 20-day
                     hold the same repricing time. None means "Swing", matching
                     both presetByKey()'s own default and /first-passage's.
        hold_min/hold_max: the typed hold range, in calendar days. Only read when
                     horizon_preset is "Custom" (which has no table row and
                     derives from the range instead), but pass them always —
                     a "Custom" that arrives on one path and not the other is
                     exactly how the two cards diverge.
        reprice_cfg: the reprice_horizon config block; None loads risk_rules.yaml.
        quote_live:  passed to assess_entry (NO-LIVE-QUOTE plan 3e). False =
                     the entry bid/ask/mid are not a live quote; None = not
                     stated (the scan, whose contracts were live when graded).
    """
    is_call = direction == "Bullish"
    premium = max(float(premium), 0.01)
    premium_stop_pct = rr_cfg["premium_stop_pct"]

    max_move = stock_price * (1 - BEARISH_MIN_TARGET_FRACTION) / 2
    if not is_call and stock_price - target_price > max_move:
        target_price = stock_price - max_move
        target_source = "capped"
    # A displayed target is also the target round-tripped on contract change.
    # Price both callers at that same cents level.
    target_price = round(target_price, 2)
    expiry_years = dte / 365.0

    # THE ONE CALLER THIS PLUMBING WAS WAITING FOR. estimate_rr and
    # estimate_targets have accepted `reprice_years` since the barrier race
    # landed, but nothing passed it, so the Fixed % Ladder kept back-solving at
    # `expiry_years * 0.5` while the Monte Carlo card above it had already moved
    # to the resolved holding horizon — two answers to the same question on one
    # screen. Same function, same arguments as first_passage.py's Stage 1, so
    # the two now agree exactly rather than approximately.
    reprice_years = display_reprice_years(
        horizon_preset, hold_min, hold_max, float(dte), reprice_cfg,
    )

    # PIECE 3: the stock stop is RECEIVED, never derived here. It used to be a
    # flat percentage move off `stock_price` (rr_cfg's bullish/bearish_
    # invalidation_pct), which measured -3% on every symbol in the universe
    # regardless of where its structure sat. `resolve_stock_stop`
    # (scoring/exit_plan.py) now decides it from the bar feed -- the wider of
    # the structural level and a 2xATR floor -- and that decision cannot live
    # here, because this module does contract arithmetic and has never had
    # candles to read structure from. The flat percentage survives only as
    # `resolve_stock_stop`'s degenerate-feed fallback.
    #
    # premium_stop_pct remains a separate, independent concept (the dollar
    # premium_stop alert level below). R/R risk is the FULL premium
    # (TRADING-REVIEW-PHASE-C-RR, decision D5): no protective stop order is
    # placed, so neither the premium stop nor the captured stock-stop fraction
    # bounds the loss. No `protective_stop_order` is passed, so the default
    # applies and rr_risk_basis is "full_premium".
    invalidation_price = max(float(final_stop_price), 0.01)

    if entry_cfg is not None and not isinstance(entry_cfg, EntryConfig):
        from app.services.config_loader import resolve_entry_config
        entry_cfg = resolve_entry_config(entry_cfg)
    entry = assess_entry(bid=entry_bid, ask=entry_ask, mid=entry_mid, config=entry_cfg, quote_live=quote_live)
    # Captured plans price the cents midpoint that is displayed and replayed.
    if captured_stock_risk(premium, stop_cost_fraction) is not None:
        premium = round(premium, 2)

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
        reprice_years=reprice_years,
        risk_fraction=stop_cost_fraction,
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
        reprice_years=reprice_years,
        risk_fraction=stop_cost_fraction,
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
        reprice_years=reprice_years,
        rr_risk_basis=rr.risk_basis,
        target_source=target_source,
        stock_stop_loss=captured_stock_risk(premium, stop_cost_fraction),
        stock_stop_loss_at=(round(invalidation_price, 2)
                            if captured_stock_risk(premium, stop_cost_fraction) is not None else None),
    )
