from __future__ import annotations

import asyncio
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.schemas import OptionContract, TradeEntry, TradeExit
from app.data.market import fetch_option_chain, fetch_price, fetch_contract_quote_async, fetch_price_async
from app.data.augment import _augment
from app.scoring.contract_validator import dte_holding_multiplier, validate_contract
from app.scoring.dte_window import resolve_dte_bounds, DTE_WINDOW_TOLERANCE_DAYS, widened_min_dte
from app.scoring.trade_plan import build_trade_plan
# Shared with app.routers.scan — both build a trade plan off the same
# reward_risk config so the scan and the per-contract recompute endpoint agree.
from app.services.config_loader import load_reward_risk_cfg as _rr_cfg

router = APIRouter(prefix='/api', tags=['trading'])


class ContractQuoteResponse(BaseModel):
    price: float   # mid price
    delta: float
    theta: float
    ivRank: int
    spread: float
    volume: int


class StockQuoteResponse(BaseModel):
    symbol: str
    price: float


@router.get('/contracts', response_model=list[OptionContract])
async def get_contracts(
    symbol: str = Query(default='AAPL'),
    right: str = Query(default='C'),
    stock_score: int = Query(default=70, ge=0, le=100),
    direction: str = Query(default='Bullish'),
    horizon: str = Query(default='swing'),
    limit: int = Query(default=10, ge=1, le=100),
    max_price: float = Query(default=50.0, ge=0.5, le=500.0),
    hold_min_days: int | None = Query(default=None, ge=0),
    hold_max_days: int | None = Query(default=None, ge=0),
) -> list[OptionContract]:
    opt_type = 'C' if right.upper() == 'C' else 'P'

    dte_bounds: tuple[int, int] | None = None
    contract_overrides: dict | None = None
    if hold_min_days is not None and hold_max_days is not None:
        if hold_max_days < hold_min_days:
            raise HTTPException(
                status_code=422,
                detail=[{
                    "loc": ["query", "hold_max_days"],
                    "msg": "Value error, hold_max_days must be >= hold_min_days",
                    "type": "value_error",
                }],
            )
        dte_bounds = resolve_dte_bounds(
            hold_min_days, hold_max_days, dte_holding_multiplier,
            log_context="GET /api/contracts",
        )
        if dte_bounds is not None:
            # Hard-reject bounds are widened by the same tolerance the chain
            # fetch uses (fetch_option_chain's _nearest_expiration_in_window) —
            # otherwise a contract the fetch accepted as "close enough" (e.g.
            # 179d for a 180-210d window) gets hard-rejected here as
            # dte_too_short. widened_min_dte floors the widened min at
            # hold_max_days+1 so short horizons can't accept a contract that
            # expires before the intended hold is even over. preferred_dte_min/max
            # stay at the true window so scoring still favours contracts closer
            # to the intended hold.
            contract_overrides = {
                "min_dte": widened_min_dte(dte_bounds[0], hold_max_days),
                "max_dte": dte_bounds[1] + DTE_WINDOW_TOLERANCE_DAYS,
                "preferred_dte_min": dte_bounds[0], "preferred_dte_max": dte_bounds[1],
            }

    # 1. Fetch raw option chain
    raw_chain = fetch_option_chain(symbol.upper(), option_type=opt_type, dte_bounds=dte_bounds) or []

    # 2. Fetch current stock price (None if unavailable — _augment handles 0.0 gracefully)
    price: float = fetch_price(symbol.upper()) or 0.0

    results: list[OptionContract] = []
    for c in raw_chain:
        # 3. Augment with computed fields (bid/ask/delta/iv_rank)
        augmented = _augment(c, stock_price=price)

        # 4. Filter by max option price (ask or mid if ask is 0)
        ask = float(augmented.get("ask") or 0)
        if ask <= 0:
            ask = float(augmented.get("price") or 0)
        if ask > max_price:
            continue

        # 5. Score the contract
        score_card = validate_contract(augmented, stock_score, overrides=contract_overrides)

        # 6. Build OptionContract response, merging scored fields
        results.append(OptionContract(
            id=str(c.get("id", "")),
            symbol=str(c.get("symbol", symbol.upper())),
            strike=int(c.get("strike", 0)),
            expiry=str(c.get("expiry", "")),
            right=opt_type,  # type: ignore[arg-type]
            dte=int(c.get("dte", 0)),
            dteTotal=int(c.get("dteTotal", c.get("dte", 0))),
            price=float(c.get("price", 0)),
            delta=float(augmented.get("delta", 0)),
            theta=float(c.get("theta", 0)),
            ivRank=int(augmented.get("iv_rank", 0)),
            ivPercentile=int(c.get("ivPercentile", 0)),
            spread=float(c.get("spread", 0)),
            volume=int(c.get("volume", 0)),
            score=score_card.score,
        ))

    # 7. Sort by score descending (stable — preserves input order for ties)
    results.sort(key=lambda x: x.score, reverse=True)

    # 8. Return top limit contracts
    return results[:limit]


@router.get('/quote/option', response_model=ContractQuoteResponse)
async def get_option_quote(
    symbol: str = Query(...),
    strike: int = Query(...),
    expiry: str = Query(...),
    right: str = Query(...),
) -> ContractQuoteResponse:
    right_upper = right.upper()
    if right_upper not in ('C', 'P'):
        raise HTTPException(status_code=400, detail="right must be C or P")
    contract_id = f"{symbol.upper()}|{strike}|{expiry}|{right_upper}"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            quote = await asyncio.wait_for(
                fetch_contract_quote_async(client, contract_id),
                timeout=8.0,
            )
    except (asyncio.TimeoutError, httpx.TimeoutException):
        raise HTTPException(status_code=504, detail="Quote request timed out")
    if quote is None:
        raise HTTPException(status_code=404, detail="Quote not available")
    if quote.get("expiry") != expiry:
        raise HTTPException(status_code=404, detail="Quote not available for requested expiry")
    return ContractQuoteResponse(
        price=float(quote["price"]),
        delta=float(quote["delta"]),
        theta=float(quote["theta"]),
        ivRank=int(quote["ivRank"]),
        spread=float(quote["spread"]),
        volume=int(quote["volume"]),
    )


@router.get('/quote/stock', response_model=StockQuoteResponse)
async def get_stock_quote(
    symbol: str = Query(...),
) -> StockQuoteResponse:
    async with httpx.AsyncClient(timeout=10) as client:
        price = await fetch_price_async(client, symbol.upper())
    if price is None:
        raise HTTPException(status_code=404, detail="Price not available")
    return StockQuoteResponse(symbol=symbol.upper(), price=price)


class RecomputePlanRequest(BaseModel):
    symbol: str
    direction: Literal["Bullish", "Bearish"]
    stock_price: float = Field(..., gt=0)
    strike: float = Field(..., gt=0)
    dte: int = Field(..., ge=0)
    premium: float = Field(..., gt=0)   # selected contract mid
    delta: float = 0.45
    spread: float = 0.0


class RecomputePlanResponse(BaseModel):
    entry: TradeEntry
    exit: TradeExit
    rrRatio: float
    rrModel: str


@router.post('/contracts/recompute-plan', response_model=RecomputePlanResponse)
async def recompute_plan(req: RecomputePlanRequest) -> RecomputePlanResponse:
    """Recompute the Entry Plan, Exit Plan, reward/risk and sell-to-close targets
    for a user-selected contract.

    Step 6 lets the user override the auto-picked contract. Without recomputing,
    the Exit Plan (premium stop, invalidation, targets) keeps describing the
    original contract. This endpoint runs the SAME math the scan uses
    (build_trade_plan) off the selected contract's premium/delta so every derived
    number matches the contract actually being traded.
    """
    # Derive bid/ask from the mid + spread so assess_entry sees the same
    # spread_pct it would during the scan (spread_pct = (ask-bid)/mid).
    half = max(req.spread, 0.0) / 2
    entry_bid = max(0.01, req.premium - half)
    entry_ask = req.premium + half

    # heston_params intentionally omitted (defaults to None → delta approximation).
    # Unlike the scan pipeline, this endpoint only receives one contract's fields
    # in the request body — no option chain to calibrate against — and it's called
    # interactively from Step 6's contract-override UI, where adding a chain fetch
    # + a multi-second worst-case Heston calibration would be a noticeable
    # click-to-update delay. Known trade-off: this means the same contract can
    # show "Heston repriced" on the initial scan card and "Delta approximation"
    # after a Step 6 override — see docs/superpowers/plans/
    # 2026-07-25-heston-pricing-in-trade-plan.md's "Out of scope" section.
    plan = build_trade_plan(
        direction=req.direction,
        stock_price=req.stock_price,
        strike=req.strike,
        dte=req.dte,
        premium=req.premium,
        delta=req.delta,
        entry_bid=entry_bid,
        entry_ask=entry_ask,
        entry_mid=req.premium,
        rr_cfg=_rr_cfg(),
    )

    return RecomputePlanResponse(
        entry=TradeEntry(
            limit=plan.entry.limit_price,
            maxFill=plan.entry.max_fill,
            orderType=plan.entry.order_type,
        ),
        exit=TradeExit(
            invalidation=plan.invalidation_price,
            premiumStop=plan.premium_stop,
            timeStopDays=plan.time_stop_days,
            target=plan.target_price,
            targets=plan.targets,
        ),
        rrRatio=plan.rr_ratio,
        rrModel=plan.rr_model,
    )
