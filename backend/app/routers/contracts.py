from __future__ import annotations

import asyncio
import hashlib
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.schemas import OptionContract, RrModel, TradeEntry, TradeExit
from app.data.market import fetch_option_chain_async, fetch_contract_quote_async, fetch_price_async, fetch_candles_async
from app.data.augment import _augment
from app.scoring.contract_validator import dte_holding_multiplier, validate_contract
from app.scoring.dte_window import resolve_dte_bounds, widen_contract_overrides_for_dte
from app.scoring.trade_plan import build_trade_plan
from app.scoring.structural_stop import find_structural_stop
from app.scoring.first_passage import estimate_first_passage
from app.scoring.exit_plan import compute_final_stop, compute_target_row
from app.scoring.reward_risk import estimate_rr
from app.scoring.stock_scorer import _atr
# Shared with app.routers.scan — both build a trade plan off the same
# reward_risk config so the scan and the per-contract recompute endpoint agree.
from app.services.config_loader import load_reward_risk_cfg as _rr_cfg
from app.services.config_loader import load_first_passage_cfg as _fp_cfg
from app.services.config_loader import load_exit_plan_cfg as _ep_cfg
from app.services.config_loader import merge_reward_risk_overrides as _merge_rr_cfg

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
            # Hard-reject AND soft-score preferred-band bounds are both widened
            # by the same DTE_WINDOW_TOLERANCE_DAYS -- see
            # widen_contract_overrides_for_dte's docstring for why the two must
            # move together, not just the hard bound.
            contract_overrides = widen_contract_overrides_for_dte({}, dte_bounds[0], dte_bounds[1], hold_max_days)

    # 1. Fetch raw option chain
    async with httpx.AsyncClient(timeout=8) as client:
        raw_chain = await fetch_option_chain_async(
            client, symbol.upper(), option_type=opt_type, dte_bounds=dte_bounds
        ) or []

        # 2. Fetch current stock price (None if unavailable — _augment handles 0.0 gracefully)
        price: float = await fetch_price_async(client, symbol.upper()) or 0.0

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
            contractConfidence=score_card.status,
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
    # Accepted for backward compatibility with the frontend, which still sends
    # it on every call -- no longer consumed here since invalidation is
    # computed off the strike/stock-price relationship, not the contract's
    # delta (build_trade_plan's signature dropped this parameter).
    delta: float = 0.45
    spread: float = 0.0
    # Optional per-request reward/risk overrides — mirrors the same keys the
    # scan endpoint accepts in ScanRequest.overrides, so a contract override
    # recompute (Step 6/7) honors whatever R/R tuning the trader set on Step 3
    # instead of silently reverting to risk_rules.yaml's defaults.
    rr_bullish_target_pct: float | None = Field(default=None, gt=0, le=2.0)
    rr_bearish_target_pct: float | None = Field(default=None, gt=0, le=2.0)
    rr_bullish_invalidation_pct: float | None = Field(default=None, gt=0, le=1.0)
    rr_bearish_invalidation_pct: float | None = Field(default=None, gt=0, le=1.0)


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
    (build_trade_plan) off the selected contract's premium so every derived
    number matches the contract actually being traded.
    """
    # Derive bid/ask from the mid + spread so assess_entry sees the same
    # spread_pct it would during the scan (spread_pct = (ask-bid)/mid).
    half = max(req.spread, 0.0) / 2
    entry_bid = max(0.01, req.premium - half)
    entry_ask = req.premium + half

    _rr_overrides = {
        k: v for k, v in {
            "rr_bullish_target_pct":       req.rr_bullish_target_pct,
            "rr_bearish_target_pct":       req.rr_bearish_target_pct,
            "rr_bullish_invalidation_pct": req.rr_bullish_invalidation_pct,
            "rr_bearish_invalidation_pct": req.rr_bearish_invalidation_pct,
        }.items() if v is not None
    }

    # heston_params intentionally omitted (defaults to None → BS reprice fallback).
    # Unlike the scan pipeline, this endpoint only receives one contract's fields
    # in the request body — no option chain to calibrate against — and it's called
    # interactively from Step 6's contract-override UI, where adding a chain fetch
    # + a multi-second worst-case Heston calibration would be a noticeable
    # click-to-update delay. Known trade-off: this means the same contract can
    # show "Heston repriced" on the initial scan card and "BS repriced (IV-derived)"
    # after a Step 6 override — see docs/superpowers/plans/
    # 2026-07-25-heston-pricing-in-trade-plan.md's "Out of scope" section.
    try:
        _rr_cfg_merged = _merge_rr_cfg(_rr_overrides)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    plan = build_trade_plan(
        direction=req.direction,
        stock_price=req.stock_price,
        strike=req.strike,
        dte=req.dte,
        premium=req.premium,
        entry_bid=entry_bid,
        entry_ask=entry_ask,
        entry_mid=req.premium,
        rr_cfg=_rr_cfg_merged,
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


class StructuralStopRequest(BaseModel):
    symbol:      str
    direction:   Literal["Bullish", "Bearish"]
    stock_price: float = Field(..., gt=0)


class StructuralStopResponse(BaseModel):
    available:   bool
    price:       Optional[float] = None
    source:      Optional[Literal["order_block", "swing_low", "swing_high"]] = None
    confidence:  Optional[int] = None
    distancePct: Optional[float] = None


@router.post('/contracts/structural-stop', response_model=StructuralStopResponse)
async def structural_stop(req: StructuralStopRequest) -> StructuralStopResponse:
    """On-demand structural (order block / swing) invalidation lookup for one symbol.

    Deliberately its own endpoint, not folded into recompute-plan: this is fired
    only by an explicit user action ("Check structure") on the trade card, never
    on every contract swap, so it never adds latency to the scan or to Step 6
    contract overrides.

    NOT options-specific despite the /contracts/ prefix (a legacy namespace
    artefact): find_structural_stop() takes only candles, direction and a
    reference price. The stocks-mode StockPositionCard calls this same endpoint
    for its own "Check structure" affordance — do not fork an alias route.
    """
    async with httpx.AsyncClient(timeout=8) as client:
        candles = await fetch_candles_async(client, req.symbol.upper())

    stop = find_structural_stop(candles, req.direction, req.stock_price)
    if stop is None:
        return StructuralStopResponse(available=False)

    return StructuralStopResponse(
        available=True,
        price=round(stop.price, 2),
        source=stop.source,
        confidence=stop.confidence,
        distancePct=round(stop.distance_pct, 2),
    )


class FirstPassageRequest(BaseModel):
    symbol:             str
    direction:          Literal["Bullish", "Bearish"]
    stock_price:        float = Field(..., gt=0)
    strike:             float = Field(..., gt=0)
    dte:                int = Field(..., ge=0)
    premium:            float = Field(..., gt=0)
    delta:              float = 0.45
    trend_score:        float = Field(..., ge=0, le=100)
    invalidation_price:  float = Field(..., gt=0)
    t1_pct: Optional[float] = Field(default=None, gt=0)
    t2_pct: Optional[float] = Field(default=None, gt=0)
    t3_pct: Optional[float] = Field(default=None, gt=0)
    # The barrier race's third barrier. lt=1 because a 100% premium stop is a
    # total loss, which makes the barrier unreachable-by-definition rather than
    # a stop. None resolves to risk_rules.yaml's reward_risk.premium_stop_pct,
    # matching how t1/t2/t3_pct already resolve.
    premium_stop_pct: Optional[float] = Field(default=None, gt=0, lt=1)
    # Feed resolve_reprice_days()'s fallback. Optional so existing callers keep
    # working; absent means "Swing", the app's own default preset.
    horizon_preset: Optional[str] = None
    hold_min: Optional[float] = Field(default=None, ge=0)
    hold_max: Optional[float] = Field(default=None, ge=0)


class FirstPassageTargetOut(BaseModel):
    pct:          float
    stockPrice:   Optional[float] = None
    optionPrice:  float
    probability:  float
    expectedDays: Optional[float] = None


class FirstPassageInvalidationOut(BaseModel):
    probability:  float
    expectedDays: Optional[float] = None


class BarrierRaceOutcomeOut(BaseModel):
    """One target's row of the race. The four p* fields are an ATTRIBUTION —
    every simulated path is counted exactly once, so they sum to 1.0."""
    targetPct:              float
    targetOptionPrice:      float

    pTargetFirst:           float
    pStockStopFirst:        float
    pPremiumStopFirst:      float
    pNeither:               float

    daysTarget:             Optional[float] = None
    daysStockStop:          Optional[float] = None
    daysPremiumStop:        Optional[float] = None
    # The unconditional median day ANY path reaches the stock stop — the basis
    # of repriceDaysStockStop, and a different statistic from daysStockStop.
    daysAnyPathReachedStop: Optional[float] = None

    # The four shares allocated to hundredths, summing to exactly 1.00. The
    # card prints THESE in its edge chain and derives its whole-percent labels
    # from them, so the chain, the labels and the total cannot disagree. The
    # raw p* fields above stay raw — the bars are drawn from those.
    # REQUIRED, deliberately — no defaults. With `= 0.0` here, dropping these
    # from _race_out was invisible: Pydantic filled them, the TypeScript side
    # declares them required so tsc saw nothing, and the card rendered four
    # labels of "0%" under the copy "every row sums to 100%" beside an edge
    # chain whose four multipliers were all zero and whose total was not.
    weightTargetFirst:      float
    weightStockStopFirst:   float
    weightPremiumStopFirst: float
    weightNeither:          float
    terminalMean:           Optional[float] = None

    rewardDollar:           float
    repriceDaysStockStop:   float
    stopRepricedValue:      Optional[float] = None
    riskStockStop:          Optional[float] = None
    riskPremiumStop:        float
    rrStockStop:            Optional[float] = None   # the measurement
    # Constant by construction (pct / premium_stop_pct), so it is taken from
    # that definition rather than by dividing the two rounded dollar legs.
    # None only when premium_stop_pct is non-positive, which this endpoint
    # rejects at validation but the scoring default cannot.
    rrPremiumStop:          Optional[float] = None
    edgePerContract:        Optional[float] = None


class BarrierRaceOut(BaseModel):
    outcomes:          list[BarrierRaceOutcomeOut]
    premiumStopPrice:  float
    premiumStopPct:    float
    stockStopPrice:    float
    # The premium every printed chain subtracts, already quantized to cents.
    # The card prints this rather than re-rounding its own copy: Python's
    # round() is banker's rounding and JavaScript's toFixed() is not, so on an
    # exact half-cent the two disagree and the chain stops adding up.
    premiumUsed:       float
    # False when the contract's own IV could not be backed out of its quote, so
    # the simulation ran on a generic fallback volatility. The card caveats
    # every number rather than presenting a confident dollar edge.
    # Required for the same reason: defaulting it to True suppressed the
    # unsolvable-IV caveat on exactly the contracts that need it.
    ivSolved:          bool
    nPaths:            int


class FirstPassageResponse(BaseModel):
    targets:      list[FirstPassageTargetOut]
    invalidation: FirstPassageInvalidationOut
    # None when the simulation was refused (dte < 1). The card must render
    # "not simulated - contract expires today", never four zeroes.
    race:         Optional[BarrierRaceOut] = None


@router.post('/contracts/first-passage', response_model=FirstPassageResponse)
async def first_passage(req: FirstPassageRequest) -> FirstPassageResponse:
    """On-demand Monte Carlo first-passage-time estimate for one contract's
    profit targets and invalidation price: probability and expected days to
    hit each before expiry.

    Deliberately its own endpoint, fired only by the trade card's "Estimate"
    button — never part of the scan or Step 6 contract overrides, for the
    same latency reasons as recompute-plan and structural-stop.

    This is a decision-support estimate, not a guarantee: it depends on a
    signal-strength-derived drift assumption and ATR-derived volatility, not
    just market data. Laying groundwork for alerting on these levels is
    deliberately deferred — see alert_generator.py's existing TP_HIT/
    STOP_REACHED logic, which already fires once a trade using these targets
    is sent to the portfolio; a pre-execution ("watch without sending to a
    broker") alert is a separate future step, not built here.
    """
    rr_cfg = _rr_cfg()
    fp_cfg = _fp_cfg()
    t1_pct = req.t1_pct if req.t1_pct is not None else rr_cfg["target_t1_pct"]
    t2_pct = req.t2_pct if req.t2_pct is not None else rr_cfg["target_t2_pct"]
    t3_pct = req.t3_pct if req.t3_pct is not None else rr_cfg["target_t3_pct"]
    premium_stop_pct = (
        req.premium_stop_pct if req.premium_stop_pct is not None else rr_cfg["premium_stop_pct"]
    )

    async with httpx.AsyncClient(timeout=8) as client:
        candles = await fetch_candles_async(client, req.symbol.upper())

    # Deterministic per-request seed: identical inputs (same contract, same
    # price, same targets) return an identical answer instead of visibly
    # different Monte Carlo noise on repeated button presses; genuinely
    # different inputs (a new day, a moved price) still get an independent
    # draw. dte stands in for "expiry" here — it already changes day to day
    # for the same contract and is what the request actually carries.
    # Python's built-in hash() is salted per-process (PYTHONHASHSEED) for str/tuple
    # security reasons, so it is NOT stable across restarts/reloads/workers despite
    # looking deterministic within a single run — use a fixed-algorithm hash instead
    # so "identical inputs" genuinely means identical output everywhere, always.
    # premium_stop_pct is DELIBERATELY NOT in the key, which is a departure from
    # barrier-race spec 2.3. The spec's stated reason for including it — that
    # otherwise "moving the premium stop returns a bit-identical answer and the
    # card appears frozen" — is not true of the implementation: the premium stop
    # is a post-hoc barrier applied to already-simulated option_paths, so at a
    # FIXED seed, moving it already changes premium_stop_price,
    # p_premium_stop_first, the risk leg and the edge. test_barrier_race.py's
    # test_same_seed_reproduces_and_a_moved_premium_stop_changes_the_answer
    # asserts exactly that, at seed 42.
    #
    # What including it actually bought was the opposite of determinism. The
    # client sends premiumStopPctFromDollars(overlay.premiumStop, premium) — a
    # raw quotient of a scan-time dollar field over the LIVE premium — so this
    # float moves whenever the quote moves a cent. Every such move re-rolled the
    # entire simulation, shifting the Monte Carlo card's target probabilities
    # (which have nothing to do with the premium stop) by ~2 points between two
    # Estimate clicks a minute apart on an unchanged contract, with nothing on
    # screen to explain it. A seed exists to stop unrelated numbers moving; this
    # made them move on an unrelated input.
    seed_key = (
        f"{req.symbol.upper()}|{req.strike}|{req.dte}|{round(req.stock_price, 2)}"
        f"|{t1_pct}|{t2_pct}|{t3_pct}"
    )
    seed = int(hashlib.sha256(seed_key.encode()).hexdigest(), 16) % (2 ** 32)

    result = estimate_first_passage(
        stock_price=req.stock_price,
        strike=req.strike,
        dte=req.dte,
        premium=req.premium,
        delta=req.delta,
        is_call=(req.direction == "Bullish"),
        trend_score=req.trend_score,
        invalidation_price=req.invalidation_price,
        candles=candles,
        t1_pct=t1_pct,
        t2_pct=t2_pct,
        t3_pct=t3_pct,
        premium_stop_pct=premium_stop_pct,
        horizon_preset=req.horizon_preset,
        hold_min=req.hold_min,
        hold_max=req.hold_max,
        max_drift_pct=fp_cfg["max_drift_pct"],
        n_paths=fp_cfg["n_paths"],
        sigma_floor=fp_cfg["sigma_floor"],
        sigma_ceiling=fp_cfg["sigma_ceiling"],
        seed=seed,
    )

    return FirstPassageResponse(
        targets=[
            FirstPassageTargetOut(
                pct=t.pct,
                stockPrice=round(t.stock_price, 2) if t.stock_price is not None else None,
                optionPrice=round(t.option_price, 2),
                probability=round(t.probability, 4),
                expectedDays=t.expected_days,
            )
            for t in result.targets
        ],
        invalidation=FirstPassageInvalidationOut(
            probability=round(result.invalidation.probability, 4),
            expectedDays=result.invalidation.expected_days,
        ),
        race=_race_out(result.race),
    )


def _race_out(race: Optional[BarrierRaceResult]) -> Optional[BarrierRaceOut]:
    """Map the scoring layer's BarrierRaceResult onto the wire shape.

    Money is already quantized to cents by first_passage (so the printed
    arithmetic chains add up); only the probabilities are rounded here, to the
    same 4 places the existing target/invalidation probabilities use."""
    if race is None:
        return None
    return BarrierRaceOut(
        outcomes=[
            BarrierRaceOutcomeOut(
                targetPct=o.target_pct,
                targetOptionPrice=round(o.target_option_price, 2),
                pTargetFirst=round(o.p_target_first, 4),
                pStockStopFirst=round(o.p_stock_stop_first, 4),
                pPremiumStopFirst=round(o.p_premium_stop_first, 4),
                pNeither=round(o.p_neither, 4),
                daysTarget=o.days_target,
                daysStockStop=o.days_stock_stop,
                daysPremiumStop=o.days_premium_stop,
                daysAnyPathReachedStop=o.days_any_path_reached_stop,
                weightTargetFirst=o.weight_target,
                weightStockStopFirst=o.weight_stock_stop,
                weightPremiumStopFirst=o.weight_premium_stop,
                weightNeither=o.weight_neither,
                terminalMean=round(o.terminal_mean, 2) if o.terminal_mean is not None else None,
                rewardDollar=o.reward_dollar,
                repriceDaysStockStop=round(o.reprice_days_stock_stop, 2),
                stopRepricedValue=o.stop_repriced_value,
                riskStockStop=o.risk_stock_stop,
                riskPremiumStop=o.risk_premium_stop,
                # NOT rounded to 4dp. reward $0.51 / risk $1.01 is 0.504950,
                # which 4dp rounding turns into 0.505 and toFixed(2) then
                # renders as "0.51" — beside the very division that produces
                # 0.50, on the number the card bolds as THE measurement.
                rrStockStop=o.rr_stock_stop,
                rrPremiumStop=o.rr_premium_stop,
                edgePerContract=round(o.edge_per_contract, 2) if o.edge_per_contract is not None else None,
            )
            for o in race.outcomes
        ],
        premiumStopPrice=round(race.premium_stop_price, 2),
        premiumStopPct=race.premium_stop_pct,
        stockStopPrice=round(race.stock_stop_price, 2),
        premiumUsed=race.premium_used,
        ivSolved=race.iv_solved,
        nPaths=race.n_paths,
    )


class ExitPlanRequest(BaseModel):
    symbol:      str
    direction:   Literal["Bullish", "Bearish"]
    entry_price: float = Field(..., gt=0)
    strike:      float = Field(..., gt=0)
    dte:         int = Field(..., ge=0)
    premium:     float = Field(..., gt=0)
    trend_score: float = Field(..., ge=0, le=100)


class ExitPlanStopOut(BaseModel):
    price:                float
    source:               Literal["structural", "atr_widened"]
    contractPrice:        float
    rrModel:              RrModel
    structuralSource:     Optional[Literal["order_block", "swing_low", "swing_high"]] = None
    structuralConfidence: Optional[int] = None
    structuralPrice:      Optional[float] = None
    atrFloorPrice:        float
    distanceDollar:       Optional[float] = None


class ExitPlanTargetRowOut(BaseModel):
    rrRatio:         float
    arithmeticPrice: float
    price:           float
    tpSource:        Literal["arithmetic", "structural_snap"]
    structuralPrice: Optional[float] = None
    contractPrice:   float
    rrModel:         RrModel
    probability:     float
    expectedDays:    Optional[float] = None
    qualityGood:     bool
    qualityReasons:  list[str]
    distanceDollar:  Optional[float] = None
    toleranceDollar: float


class ExitPlanResponse(BaseModel):
    stop:    ExitPlanStopOut
    targets: list[ExitPlanTargetRowOut]
    atr:     float


@router.post('/contracts/exit-plan', response_model=ExitPlanResponse)
async def exit_plan(req: ExitPlanRequest) -> ExitPlanResponse:
    """Compute the exit-plan pipeline for one contract: a structurally-grounded
    final stop (the wider of the structural invalidation and an ATR floor),
    one target row per configured R:R ratio (arithmetic, snapped onto a real
    structural level when one falls close enough), each repriced to an
    approximate contract price and run through the Monte Carlo first-passage
    engine for probability/expected days, plus a composite quality flag.

    Deliberately its own endpoint, fired only by the trade card's/portfolio
    editor's "Compute Exit Plan" button — never part of the scan pipeline.

    heston_params intentionally omitted from every reprice call below, same
    trade-off as recompute_plan (this endpoint also serves one contract with
    no option chain to calibrate against, from an interactive single-click
    UI where a multi-second Heston calibration would be a visible delay) —
    see docs/superpowers/plans/2026-07-25-heston-pricing-in-trade-plan.md's
    "Out of scope" section.
    """
    ep_cfg = _ep_cfg()
    fp_cfg = _fp_cfg()
    is_call = req.direction == "Bullish"
    expiry_years = req.dte / 365.0

    async with httpx.AsyncClient(timeout=8) as client:
        candles = await fetch_candles_async(client, req.symbol.upper())

    # Fewer than 2 candles means _atr can't form even one true range (returns
    # 0.0) and find_structural_stop's own len<10 guard also returns None — the
    # ATR floor collapses to entry_price exactly, silently producing a
    # zero-width "final stop" and, downstream, every target row landing on
    # entry_price too. That's meaningfully different from "computed, but no
    # structural level was found nearby" (a real, valid atr_widened result) —
    # reject explicitly rather than return a plan built on no data at all.
    if len(candles) < 2:
        raise HTTPException(
            status_code=422,
            detail="insufficient price history to compute an exit plan",
        )

    atr = _atr(candles, 14)

    # A flat/duplicated candle feed (stale or repeated upstream data) passes
    # the len(candles) < 2 guard above but still collapses the ATR floor to
    # 0 — the exact zero-width-stop/every-target-lands-on-entry-price outcome
    # that guard exists to prevent, just reached a different way. Reject
    # explicitly rather than return a "computed" plan built on no real range.
    if atr <= 0:
        raise HTTPException(
            status_code=422,
            detail="insufficient price history to compute an exit plan",
        )

    final_stop = compute_final_stop(
        candles, req.direction, req.entry_price, atr,
        ep_cfg["stop"]["atr_multiplier"],
    )

    stop_priced = estimate_rr(
        stock_price=req.entry_price, target_price=final_stop.price,
        invalidation_price=final_stop.price, strike=req.strike,
        expiry_years=expiry_years, current_premium=req.premium, is_call=is_call,
    )

    structural_price = round(final_stop.structural.price, 2) if final_stop.structural else None
    atr_floor_price = round(final_stop.atr_floor_price, 2)

    stop_out = ExitPlanStopOut(
        price=round(final_stop.price, 2),
        source=final_stop.source,
        contractPrice=stop_priced.estimated_exit_premium,
        rrModel=stop_priced.model_used,
        structuralSource=final_stop.structural.source if final_stop.structural else None,
        structuralConfidence=final_stop.structural.confidence if final_stop.structural else None,
        structuralPrice=structural_price,
        atrFloorPrice=atr_floor_price,
        distanceDollar=abs(structural_price - atr_floor_price) if structural_price is not None else None,
    )

    targets_out: list[ExitPlanTargetRowOut] = []
    for rr_ratio in ep_cfg["target"]["rr_ratios"]:
        row = compute_target_row(
            candles, req.direction, req.entry_price, final_stop, atr,
            rr_ratio, ep_cfg["target"]["structural_snap"]["atr_multiplier"],
        )
        tp_priced = estimate_rr(
            stock_price=req.entry_price, target_price=row.price,
            invalidation_price=final_stop.price, strike=req.strike,
            expiry_years=expiry_years, current_premium=req.premium, is_call=is_call,
        )

        # Convert the target's repriced contract value into an equivalent
        # "% of current premium" so it can be fed through the existing
        # first_passage engine (which is built around percent-of-premium
        # targets, not raw stock-price ones) without duplicating its GBM
        # simulation / per-day option-repricing loop.
        pct = (tp_priced.estimated_exit_premium - req.premium) / req.premium if req.premium > 0 else 0.0

        if pct <= 0:
            # The repriced contract value at this target's stock price is at
            # or below the CURRENT premium (time decay at dte_at_target
            # outweighing the favorable move — plausible for a long-dated,
            # low-delta, ATR-widened stop). first_passage's "probability of
            # ever crossing target_option_price" would be trivially ~1 at
            # ~day 1 here, since day 1's simulated repriced price is already
            # at/above a threshold that isn't actually above today's real
            # premium — a misleading "high-probability profit target" for a
            # row that isn't currently a profit at all. Report it as
            # unscoreable rather than run a simulation whose answer would be
            # a numerically-correct but semantically-false near-certainty.
            probability, expected_days = 0.0, None
        else:
            seed_key = (
                f"{req.symbol.upper()}|{req.strike}|{req.dte}|{round(req.entry_price, 2)}"
                f"|{rr_ratio}|{round(row.price, 2)}"
            )
            seed = int(hashlib.sha256(seed_key.encode()).hexdigest(), 16) % (2 ** 32)

            fp_result = estimate_first_passage(
                stock_price=req.entry_price, strike=req.strike, dte=req.dte,
                premium=req.premium, delta=0.45, is_call=is_call,
                trend_score=req.trend_score, invalidation_price=final_stop.price,
                candles=candles, t1_pct=pct, t2_pct=pct, t3_pct=pct,
                # This loop runs once PER TARGET ROW with t1=t2=t3, and reads
                # only .targets[0]. Leaving the race on would run three full
                # attributions, a Black-Scholes reprice and a median over a
                # 2000-row array for every row, and discard all of it.
                compute_race=False,
                max_drift_pct=fp_cfg["max_drift_pct"], n_paths=fp_cfg["n_paths"],
                sigma_floor=fp_cfg["sigma_floor"], sigma_ceiling=fp_cfg["sigma_ceiling"],
                seed=seed,
            )
            fp_target = fp_result.targets[0]
            probability, expected_days = fp_target.probability, fp_target.expected_days

        targets_out.append(ExitPlanTargetRowOut(
            rrRatio=row.rr_ratio,
            arithmeticPrice=round(row.arithmetic_price, 2),
            price=round(row.price, 2),
            tpSource=row.tp_source,
            structuralPrice=round(row.structural.price, 2) if row.structural else None,
            contractPrice=round(tp_priced.estimated_exit_premium, 2),
            rrModel=tp_priced.model_used,
            probability=round(probability, 4),
            expectedDays=expected_days,
            qualityGood=row.quality_good,
            qualityReasons=row.quality_reasons,
            distanceDollar=round(row.distance_dollar, 2) if row.distance_dollar is not None else None,
            toleranceDollar=round(row.tolerance_dollar, 2),
        ))

    return ExitPlanResponse(stop=stop_out, targets=targets_out, atr=round(atr, 2))
