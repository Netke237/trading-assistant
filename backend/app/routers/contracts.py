from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas import (
    OptionContract, RrModel, TradeEntry, TradeExit, ContractScoreBreakdown,
    FinalStopIn,
    DteDetail, DeltaDetail, IvRankDetail, LiquidityDetail, SpreadDetail,
    ContractExplanation,
)
from app.data.market import (
    fetch_option_chain_async, fetch_contract_quote_async, fetch_price_async,
    fetch_candles_async, _compute_iv_bs,
)
from app.data.augment import _augment, opt_float, opt_int
from app.data.strike import format_strike, parse_strike_text
from app.scoring.contract_validator import (
    CONTRACT_OVERRIDE_KEYS, dte_holding_multiplier, effective_contract_overrides, effective_dte_limits,
    is_finite_rule_value,
    validate_contract,
)
from app.scoring.dte_window import resolve_dte_bounds, widen_contract_overrides_for_dte, widened_min_dte
from app.scoring.trade_plan import build_trade_plan
from app.scoring.structural_stop import find_structural_stop
from app.scoring.stop_cost import compute_stop_cost
from app.scoring.first_passage import estimate_first_passage
from app.scoring.exit_plan import compute_final_stop, compute_target_row
from app.scoring.reward_risk import estimate_rr
from app.scoring.stock_scorer import _atr
# Shared with app.routers.scan — both build a trade plan off the same
# reward_risk config so the scan and the per-contract recompute endpoint agree.
from app.services.config_loader import load_reward_risk_cfg as _rr_cfg
from app.services.config_loader import load_first_passage_cfg as _fp_cfg
from app.services.config_loader import load_exit_plan_cfg as _ep_cfg
from app.services.config_loader import resolve_target_r_multiple
from app.services.config_loader import merge_reward_risk_overrides as _merge_rr_cfg
from app.services.config_loader import resolve_entry_config

router = APIRouter(prefix='/api', tags=['trading'])


class ContractQuoteResponse(BaseModel):
    price: float   # mid price
    delta: float
    theta: float
    # An IV RANK, or None when no rank source answered -- which is the
    # common case, and was already reachable before the Phase A split via
    # fetch_contract_quote_async's price-only fallback path
    # (PHASE-A-NULL-IVRANK-2026-09-06). The absolute level rides in `iv`.
    ivRank: Optional[int] = None
    iv: Optional[float] = None
    spread: float
    volume: int
    # NO-LIVE-QUOTE (plan 3c), from the chain row: quoteLive True only for a
    # two-sided quote, in session, no older than quote_liveness.max_age_minutes;
    # quoteState 'live' | 'one_sided' | 'session_closed' | 'stale'. None means
    # the row carried no state, which only a fixture produces.
    quoteLive: Optional[bool] = None
    quoteState: Optional[str] = None


class StockQuoteResponse(BaseModel):
    symbol: str
    price: float


def _safe_detail(model_cls, raw):
    """Mirror of scan.py's `_safe`: build a detail model from the scorer's raw
    dict, keeping only the keys the model declares, and returning None rather
    than raising when the scorer emitted nothing for that component."""
    if not isinstance(raw, dict):
        return None
    fields = model_cls.model_fields
    try:
        return model_cls(**{k: v for k, v in raw.items() if k in fields})
    except Exception:
        return None


def _contract_rules_error(msg: str) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail=[{"loc": ["query", "contract_rules"], "msg": f"Value error, {msg}", "type": "value_error"}],
    )


def _parse_contract_rules(raw: str | None) -> dict[str, float | int]:
    """Decode and check the `contract_rules` query parameter.

    Keys validate_contract() does not read are ignored, as the scan ignores
    them. Every key it does read must carry a finite JSON number -- stricter
    than the scan, whose cast also takes numeric strings, but the scan's own
    recording only ever produces finite numbers, so anything else is a
    malformed request, and a 422 beats a table silently graded on the YAML."""
    if raw is None or raw == "":
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, RecursionError):
        raise _contract_rules_error("contract_rules must be a JSON object")
    if not isinstance(parsed, dict):
        raise _contract_rules_error("contract_rules must be a JSON object")
    for key in CONTRACT_OVERRIDE_KEYS & parsed.keys():
        if not is_finite_rule_value(parsed[key]):
            raise _contract_rules_error(f"contract_rules.{key} must be a finite number")
    return effective_contract_overrides(parsed)


def _parse_strikes(raw: str | None) -> set[int | float] | None:
    """`strikes=187,187.5` -> {187, 187.5}, canonical strikes (EXACT-STRIKE:
    `187.0` is 187, 22.5 never matches 22). Items are stripped and empty items
    dropped (`187,` and `187, 190` parse); a list empty after that, `strikes=`
    included, is absent (None). Any item `parse_strike_text` refuses -- sign,
    exponent, underscore, more than 5 integer or 3 decimal digits, 0 -- is a
    422, never a 500."""
    if raw is None:
        return None
    items = [p.strip() for p in raw.split(",")]
    items = [p for p in items if p]
    if not items:
        return None
    try:
        return {parse_strike_text(p) for p in items}
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail=[{"loc": ["query", "strikes"], "msg": "Value error, strikes must be comma-separated strikes, e.g. 187 or 187.5", "type": "value_error"}],
        )


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
    # JSON object: the scan's ScanResult.contract_rules, sent back by Step 6.
    # Absent = contract_rules.yaml, which is what every caller got before
    # 2026-09-29. Without it Step 6 graded a Loose-profile scan's contracts
    # against the YAML's liquidity floor (vol 50 / OI 200) and listed the
    # trade card's own contract as REJECT, score 0 -- or dropped it from the
    # table entirely, all rows tying at 0 and `limit` cutting in strike order.
    # (`max_price` and `limit` still apply, and the scan has neither, so the
    # card's contract can still be absent here; it is no longer graded apart.)
    contract_rules: str | None = Query(default=None),
    # The Watchlist asks for a starred contract's own expiry and strikes
    # (WATCHLIST-SCAN-CONTRACT-RULES). Both absent = the behaviour above,
    # exactly. `expiry`: fetch that expiry's chain and keep only its rows.
    # `strikes`: comma-separated exact strikes; keep only those, and apply
    # neither `max_price` nor `limit` -- the caller asked for specific
    # contracts, so nothing may cut them (a 150-strike chain ties a
    # hard-rejected star at 0 and `limit` cut it in strike order). Grading is
    # unchanged by either: the same hold-widened overrides apply.
    expiry: str | None = Query(default=None),
    strikes: str | None = Query(default=None),
) -> list[OptionContract]:
    opt_type = 'C' if right.upper() == 'C' else 'P'

    rules = _parse_contract_rules(contract_rules)
    expiry = expiry or None
    strike_set = _parse_strikes(strikes)
    dte_bounds: tuple[int, int] | None = None
    contract_overrides: dict | None = dict(rules) or None
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
            # Widened ON TOP of the scan's rules, exactly as scan.py does, so a
            # recorded min_dte/preferred_dte_* is replaced here as it was there.
            contract_overrides = widen_contract_overrides_for_dte(dict(rules), dte_bounds[0], dte_bounds[1], hold_max_days)

    # 1. Fetch raw option chain
    async with httpx.AsyncClient(timeout=8) as client:
        if expiry is None:
            raw_chain = await fetch_option_chain_async(
                client, symbol.upper(), option_type=opt_type, dte_bounds=dte_bounds,
                min_dte_floor=widened_min_dte(dte_bounds[0], hold_max_days) if dte_bounds is not None else None,
                # No hold window: pick within the min_dte/max_dte (and nearest the
                # preferred DTE band) the table is graded with below, as scan.py
                # does, so the fetched expiry is not certain to be rejected as
                # dte_too_short or dte_too_long.
                dte_limits=effective_dte_limits(rules) if dte_bounds is None else None,
            ) or []
        else:
            # The caller's expiry, not the hold-days window's: a listed E is
            # fetched, an unlisted one (expired / delisted) falls back to the
            # plain first-expiry->=21-days chain, filtered to [] below. The
            # hold-day bounds above still widen the GRADING overrides.
            raw_chain = await fetch_option_chain_async(
                client, symbol.upper(), option_type=opt_type, expiry=expiry, dte_bounds=None,
            ) or []
            if not raw_chain:
                # An empty chain for an asked-for expiry is a Tradier outage /
                # timeout (swallowed into []), an expirations list with nothing
                # >= 21 days, or a listed E with no quoted strikes. Say so: a
                # 200 [] would read as "not in the chain" for every star.
                raise HTTPException(
                    status_code=503,
                    detail=f"Option chain unavailable for {symbol.upper()} {expiry}. Try again shortly.",
                )

        # 2. Fetch current stock price.
        price: float = await fetch_price_async(client, symbol.upper()) or 0.0

    # ROUND 6 finding 1. Without a price this endpoint CANNOT agree with the scan,
    # so it must not answer. The scan's twin of this path rejects the symbol
    # outright on a missing price (`if not price or not candles` -> "no market
    # data", scan.py:502) and never reaches its Black-Scholes resolution. Here the
    # request used to continue with price 0.0, which disabled the ATM inversion
    # AND _augment's BS-delta fallback, so every row came back iv=None ->
    # iv_basis="none" -> _score_iv_rank's neutral 50. Nothing hard-rejects on a
    # null IV, so the table was POPULATED, not empty: Step 6 listed "IV -" and a
    # contract score points away from the card built by the scan, the user sorted
    # and picked on it, and applyPickedContract copied that score and a null iv
    # onto the trade card. Same user-visible defect this project ruled BLOCKING in
    # rounds 4 and 5, reached through the price fetch instead of the chain.
    #
    # Failing loudly is the honest mirror of the scan's own behaviour: a degraded
    # answer the user cannot distinguish from a good one is worse than no answer.
    if price <= 0:
        raise HTTPException(
            status_code=503,
            detail=(
                f"No current price for {symbol.upper()}; contract IV and delta "
                "cannot be computed consistently with the scan. Try again shortly."
            ),
        )

    # ROUND 4 finding 2. The SCAN inverts Black-Scholes for the ATM contract when
    # no vendor IV arrived and fills the strikes that have none (routers/scan.py's
    # resolution block); this endpoint did not, and it feeds STEP 6's table while
    # the scan feeds the STEP 7 card. Same contract, two different IVs and — via
    # _score_iv_rank's neutral-50-on-None — two different CONTRACT SCORES: Step 6
    # listed "IV —" and a score three points off the card the user then acts from.
    # Ranking a table on a score that is not the scored contract's is a wrong
    # number in front of a user, so the fallback is mirrored here rather than
    # left to the deferred de-duplication of the two resolvers (which would not
    # have closed this: what differs is the MISSING FALLBACK, not the arithmetic).
    #
    # ROUND 5 finding 1. The trigger must be the ATM CONTRACT's own lack of a
    # reading, not the whole chain's. `not any(c.get("iv") ...)` fired only when
    # EVERY strike was empty, so a chain whose yfinance backfill filled the wings
    # but missed the ATM strike skipped the inversion here while the scan ran it
    # -- reproducing the very Step-6-vs-Step-7 split round 4 recorded as closed
    # (verified: Step 6 showed "IV —" with an IV sub-score of 50 against the
    # card's 33.2% and 39, and picking that row copied the null onto the card).
    _atm = (
        min(raw_chain, key=lambda c: abs(float(c.get("strike", 0)) - price))
        if raw_chain else None
    )
    if _atm is not None and _atm.get("ivRank") is None and not _atm.get("iv"):
        _iv_bs = _compute_iv_bs(
            mid=float(_atm.get("price", 0)),
            S=price,
            K=float(_atm.get("strike", price)),
            dte=int(_atm.get("dte", 30)),
            is_call=(opt_type == "C"),
        )
        if _iv_bs is not None:
            for c in raw_chain:
                if not c.get("iv"):
                    # An inversion yields an ABSOLUTE volatility, never a
                    # rank — it can only ever feed `iv`.
                    c["iv"] = round(_iv_bs * 100, 1)
                    c["implied_volatility"] = round(_iv_bs, 4)

    results: list[OptionContract] = []
    for c in raw_chain:
        # 3. Augment with computed fields (bid/ask/delta/iv_rank)
        augmented = _augment(c, stock_price=price)

        # 4. Filter by max option price (ask or mid if ask is 0) -- not when
        # specific strikes were asked for.
        if strike_set is None:
            ask = float(augmented.get("ask") or 0)
            if ask <= 0:
                ask = float(augmented.get("price") or 0)
            if ask > max_price:
                continue

        # 5. Score the contract. Label mode (NO-LIVE-QUOTE plan 3c): a row
        # whose quote is not live is graded as a live one, capped at CAUTION
        # and flagged, so an off-hours Step 6 / Watchlist still lists it.
        score_card = validate_contract(
            augmented, stock_score, overrides=contract_overrides, quote_mode="label",
        )

        # 6. Build OptionContract response, merging scored fields
        results.append(OptionContract(
            id=str(c.get("id", "")),
            symbol=str(c.get("symbol", symbol.upper())),
            # The row's exact strike (EXACT-STRIKE): every chain row carries a
            # valid one or was dropped by the builder.
            strike=c["strike"],
            expiry=str(c.get("expiry", "")),
            right=opt_type,  # type: ignore[arg-type]
            dte=int(c.get("dte", 0)),
            dteTotal=int(c.get("dteTotal", c.get("dte", 0))),
            price=float(c.get("price", 0)),
            delta=float(augmented.get("delta", 0)),
            theta=float(c.get("theta", 0)),
            # Send the two quantities RAW and unresolved: `ivRank` only ever
            # a rank, `iv` only ever an absolute level, either or both
            # None. `augmented["iv_rank"]` is the RESOLVED figure the scorer
            # needed and would blur the two back together on the wire
            # (PHASE-A-NULL-IVRANK-2026-09-06).
            ivRank=opt_int(c.get("ivRank")),
            iv=opt_float(c.get("iv")),
            ivPercentile=opt_int(c.get("ivPercentile")),
            spread=float(c.get("spread", 0)),
            volume=int(c.get("volume", 0)),
            score=score_card.score,
            contractConfidence=score_card.status,
            # ContractScoreCard.breakdown is the SCORER's dataclass (dte_score,
            # iv_rank_score, ...), not the wire model. scan.py:864 already maps
            # one to the other for the trade card; the same mapping is needed
            # here, or the field is a validation error rather than a fix.
            breakdown=ContractScoreBreakdown(
                dteFit=score_card.breakdown.dte_score,
                delta=score_card.breakdown.delta_score,
                ivAttractiveness=score_card.breakdown.iv_rank_score,
                liquidity=score_card.breakdown.liquidity_score,
                spread=score_card.breakdown.spread_score,
                dteDetail=      _safe_detail(DteDetail,       score_card.detail.get("dte")),
                deltaDetail=    _safe_detail(DeltaDetail,     score_card.detail.get("delta")),
                ivDetail=       _safe_detail(IvRankDetail,    score_card.detail.get("iv_rank")),
                liquidityDetail=_safe_detail(LiquidityDetail, score_card.detail.get("liquidity")),
                spreadDetail=   _safe_detail(SpreadDetail,    score_card.detail.get("spread")),
            ),
            explanation=ContractExplanation.model_validate(score_card.explanation) if score_card.explanation else None,
            noLiveQuote=score_card.no_live_quote,
            quoteState=score_card.quote_state,
        ))

    # 7. Sort by score descending (stable — preserves input order for ties)
    results.sort(key=lambda x: x.score, reverse=True)

    # Filtered AFTER scoring: the ATM Black-Scholes fill above reads the whole
    # chain, so a non-ATM star's IV (and score) match the unfiltered call's.
    if expiry is not None:
        results = [r for r in results if r.expiry == expiry]
    if strike_set is not None:
        return [r for r in results if r.strike in strike_set]

    # 8. Return top limit contracts
    return results[:limit]


@router.get('/quote/option', response_model=ContractQuoteResponse)
async def get_option_quote(
    symbol: str = Query(...),
    # Strike TEXT (EXACT-STRIKE): `int` made 22.5 a 422. Parsed exactly; the
    # id carries format_strike, so an integer strike's id is unchanged.
    strike: str = Query(...),
    expiry: str = Query(...),
    right: str = Query(...),
) -> ContractQuoteResponse:
    try:
        strike_value = parse_strike_text(strike)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail=[{"loc": ["query", "strike"], "msg": "Value error, strike must be a strike price, e.g. 187 or 187.5", "type": "value_error"}],
        )
    right_upper = right.upper()
    if right_upper not in ('C', 'P'):
        raise HTTPException(status_code=400, detail="right must be C or P")
    contract_id = f"{symbol.upper()}|{format_strike(strike_value)}|{expiry}|{right_upper}"
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
        ivRank=opt_int(quote.get("ivRank")),
        iv=opt_float(quote.get("iv")),
        spread=float(quote["spread"]),
        volume=int(quote["volume"]),
        quoteLive=quote.get("quoteLive"),
        quoteState=quote.get("quoteState"),
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
    # NUMERIC-API-INPUTS T2: every float on this body is finite or a 422.
    model_config = ConfigDict(allow_inf_nan=False)

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
    rr_target_r_multiple: float | None = Field(default=None, gt=0, le=10, allow_inf_nan=False)
    target_stock_price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    target_source: Literal["structural_snap", "arithmetic", "flat_fallback", "capped"] | None = None
    rr_bullish_invalidation_pct: float | None = Field(default=None, gt=0, le=1.0)
    rr_bearish_invalidation_pct: float | None = Field(default=None, gt=0, le=1.0)
    # Optional Entry Quality overrides — mirrors the same keys the scan endpoint
    # accepts in ScanRequest.overrides, so a contract override recompute honors
    # Step 3 Entry Quality parameters (APP-AUDIT-B-ENTRY-OVERRIDES).
    entry_spread_tolerance_pct: float | None = Field(default=None, ge=0, le=1.0, allow_inf_nan=False)
    entry_max_slippage_pct: float | None = Field(default=None, ge=0, le=1.0, allow_inf_nan=False)
    entry_min_premium: float | None = Field(default=None, ge=0, le=100.0, allow_inf_nan=False)
    # The HOLDING preset key and typed hold range, feeding the repricing
    # horizon behind the Fixed % Ladder. Same names, same meaning and the same
    # "absent means Swing" default as FirstPassageRequest below — a Step-6
    # contract override must not reprice the ladder at a different horizon from
    # the Monte Carlo card sitting beside it on the same screen.
    horizon_preset: str | None = None
    hold_min: float | None = Field(default=None, ge=0)
    hold_max: float | None = Field(default=None, ge=0)
    # Piece 3: the stock stop the card already carries (`exit.finalStop`),
    # round-tripped so a contract override cannot move it. See the endpoint
    # body for why this is echoed rather than re-derived. None = the card has
    # none, and the flat percentage applies.
    # FinalStopIn, the request-only subclass (NUMERIC-API-INPUTS T2): the
    # response's TradeExit.finalStop stays FinalStopOut and serialises it as one.
    final_stop: FinalStopIn | None = None
    # NO-LIVE-QUOTE (plan 3e): False when the premium/spread above did not come
    # from a live quote (the entry plan then reads CAUTION, "no live quote --
    # entry priced off the last close"). None = not stated: today's behaviour.
    quote_live: bool | None = None


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
            "rr_target_r_multiple": req.rr_target_r_multiple,
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
    _entry_overrides = {
        k: v for k, v in {
            "entry_spread_tolerance_pct": req.entry_spread_tolerance_pct,
            "entry_max_slippage_pct": req.entry_max_slippage_pct,
            "entry_min_premium": req.entry_min_premium,
        }.items() if v is not None
    }

    try:
        _rr_cfg_merged = _merge_rr_cfg(_rr_overrides)
        _entry_cfg = resolve_entry_config(_entry_overrides) if _entry_overrides else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    _flat_fallback_pct = (
        _rr_cfg_merged["bullish_invalidation_pct"] if req.direction == "Bullish"
        else _rr_cfg_merged["bearish_invalidation_pct"]
    )

    # ── Piece 3: the stock stop survives a Step 6 contract override ───────────
    # The stop is a STOCK level: which contract is being traded has no bearing
    # on where the structure sits, so an override must not move it. The card
    # sends back the block the scan already resolved and this endpoint uses its
    # price and echoes it verbatim -- `mergePlan` replaces `exit` wholesale, so
    # an endpoint returning no stop would wipe `finalStop` and drop
    # `invalidation` to a flat percentage for exactly the cards a user
    # hand-picked a contract on.
    #
    # DELIBERATELY NOT re-derived from a fresh candle fetch. That would add a
    # network round trip to an interactive endpoint whose whole design (see the
    # Heston note above) is "one contract's fields in the body, no chain", and
    # a feed that has moved on since the scan would hand back a DIFFERENT stop
    # -- the override silently moving the level, which is the failure this part
    # exists to prevent.
    #
    # ABSENT means the card has no resolved stop to preserve: a scan session
    # persisted before piece 3, or a symbol whose bar feed was too thin. Fall
    # back to the same flat percentage `resolve_stock_stop` uses, and echo no
    # block -- "not computed", never a structural level that was never found.
    if req.final_stop is not None:
        _stock_stop_price = req.final_stop.price
    else:
        _stock_stop_price = (
            max(req.stock_price * (1 - _flat_fallback_pct), 0.01)
            if req.direction == "Bullish"
            else req.stock_price * (1 + _flat_fallback_pct)
        )

    _multiple = resolve_target_r_multiple(_rr_overrides)
    _target = req.target_stock_price
    _source = req.target_source if _target is not None else None
    if _target is None:
        _target = req.stock_price + (1 if req.direction == "Bullish" else -1) * _multiple * abs(req.stock_price - _stock_stop_price)
        _source = "arithmetic" if req.final_stop is not None else "flat_fallback"
    _cost_fraction = None
    if req.final_stop is not None:
        cost = compute_stop_cost(
            stop_price=round(req.final_stop.price, 2), stock_price=req.stock_price,
            strike=req.strike, dte=req.dte, premium=round(req.premium, 2),
            is_call=req.direction == "Bullish", iv_pct=None, horizon_preset=req.horizon_preset,
        )
        if cost is not None:
            _cost_fraction = cost.fraction

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
        horizon_preset=req.horizon_preset,
        hold_min=req.hold_min,
        hold_max=req.hold_max,
        final_stop_price=_stock_stop_price,
        target_price=_target,
        target_source=_source or "arithmetic",
        stop_cost_fraction=_cost_fraction,
        quote_live=req.quote_live,
        entry_cfg=_entry_cfg,
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
            finalStop=req.final_stop,
            stockStopLoss=plan.stock_stop_loss,
            stockStopLossAt=plan.stock_stop_loss_at,
            rrRiskBasis=plan.rr_risk_basis,
            targetSource=plan.target_source,
        ),
        rrRatio=plan.rr_ratio,
        rrModel=plan.rr_model,
    )


class StopCostOut(BaseModel):
    """What this contract's own stop costs, priced with Black-Scholes at
    today's remaining life (spec §2.1, docs/superpowers/plans/
    2026-09-02-gate-basis-spec.md). Every figure the card prints is here, so
    the card renders and never computes.

    `passMaxFraction` is echoed for auditability: the threshold moved with the
    basis (0.80 / 0.70 / 0.60), and a badge that showed only a verdict would
    leave no way to tell which line produced it.
    """
    lossDollar:      float    # premium − valueAtStop, per share
    valueAtStop:     float    # BS(stop, K, today's dte, r, iv) — the printed input
    fraction:        float    # lossDollar / premium, clamped to [0, 1]
    status:          Literal["PASS", "CAUTION"]
    passMaxFraction: float
    # ECHOED INPUTS, both per share and quantized to cents. The presenter takes
    # this block and nothing else (spec §3), so the premium the gate priced at
    # and the stop it priced to have to travel with the verdict — otherwise the
    # card composes its equation from `contractDetails.mid` and whatever
    # `sharedStop` holds at render time, which are not necessarily the two
    # numbers this block was computed from.
    premium:         float
    stopPrice:       float
    basis:           Literal["bs_today"]


def _stop_cost_out(cost) -> Optional[StopCostOut]:
    """Adapt app.scoring.stop_cost.StopCost onto the wire model. None in →
    None out: `stopCost: null` is the card's "not computed" state, which must
    never render as a silent PASS."""
    if cost is None:
        return None
    return StopCostOut(
        lossDollar=cost.loss_dollar,
        valueAtStop=cost.value_at_stop,
        fraction=cost.fraction,
        status=cost.status,
        passMaxFraction=cost.pass_max_fraction,
        premium=cost.premium,
        stopPrice=cost.stop_price,
        basis=cost.basis,
    )


class StructuralStopRequest(BaseModel):
    # NUMERIC-API-INPUTS T2: every float on this body is finite or a 422.
    model_config = ConfigDict(allow_inf_nan=False)

    symbol:      str
    direction:   Literal["Bullish", "Bearish"]
    stock_price: float = Field(..., gt=0)

    # The contract, OPTIONAL — this endpoint is not options-specific (see the
    # handler's docstring) and the stocks-mode card calls it with no contract
    # at all, so the stop-cost block is simply omitted there.
    #
    # `strike`, `dte` and `premium` are present together or not at all: a
    # PARTIAL set is a 422, never a silently skipped gate, because a contract
    # with no verdict reads exactly like an unremarkable one (spec §2.1).
    #
    # `iv` sits INSIDE that set but stays independently optional, which is the
    # one place this departs from the spec's literal four-field grouping. The
    # spec's §2.4 reason for shipping the contract's IV was that the gate
    # needs it; under the chosen architecture the gate runs HERE, where the
    # premium is already in hand and one bracketed inversion recovers the IV
    # (app.scoring.stop_cost). Requiring it would have meant 422-ing every
    # contract whose vendor quote carries no IV — the common case — for a
    # number this endpoint can derive.
    strike:  Optional[float] = Field(default=None, gt=0)
    dte:     Optional[int]   = Field(default=None, ge=0)
    premium: Optional[float] = Field(default=None, gt=0)
    # ABSOLUTE implied volatility in PERCENT, 0-100 — the unit of
    # ContractDetails.iv and ContractQuoteResponse.iv, which is what a caller
    # actually holds, NOT the decimal Black-Scholes takes. Bounded well above
    # 1.0 so a decimal-convention slip (0.35 for 35%) is a loud 422 rather
    # than a silent 0.35%-vol reprice, which would report almost the whole
    # premium as lost at any stop.
    iv:      Optional[float] = Field(default=None, gt=1.0, le=500.0)
    # Picks the horizon whose pass_max_fraction applies. Absent means Swing,
    # the app's own default preset — same convention as FirstPassageRequest.
    # Either domain is accepted (the seven presets or the three scoring
    # horizons, labels and display strings included); app.scoring.stop_cost's
    # horizon_key collapses them the same way the card does.
    horizon_preset: Optional[str] = None

    @model_validator(mode="after")
    def _contract_set_is_all_or_nothing(self) -> "StructuralStopRequest":
        present = [f for f in ("strike", "dte", "premium") if getattr(self, f) is not None]
        if present and len(present) != 3:
            missing = [f for f in ("strike", "dte", "premium") if getattr(self, f) is None]
            raise ValueError(
                "strike, dte and premium must be sent together or not at all; "
                f"missing {', '.join(missing)}"
            )
        if self.iv is not None and not present:
            raise ValueError("iv requires strike, dte and premium")
        return self


class StructuralStopResponse(BaseModel):
    available:   bool
    price:       Optional[float] = None
    source:      Optional[Literal["order_block", "swing_low", "swing_high"]] = None
    confidence:  Optional[int] = None
    distancePct: Optional[float] = None
    # None whenever the gate has no honest answer: no contract was sent, no
    # structural level was found, or the arithmetic refused (unsolvable IV,
    # sub-cent premium, expiring contract). "Not computed", never a PASS.
    stopCost:    Optional[StopCostOut] = None


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

    stop_price = round(stop.price, 2)

    # Priced at the ROUNDED stop, the one the card prints. The equation on the
    # badge reads "$5.20 premium − $1.49 at $185.87": pricing at a level half a
    # cent away from the one printed beside it would make that line not add up.
    cost = None
    # All three or none — the validator above guarantees it; spelled out here
    # so the guard does not silently depend on a rule enforced elsewhere.
    if req.strike is not None and req.dte is not None and req.premium is not None:
        cost = compute_stop_cost(
            stop_price=stop_price,
            stock_price=req.stock_price,
            strike=req.strike,
            dte=req.dte,
            premium=req.premium,
            is_call=(req.direction == "Bullish"),
            iv_pct=req.iv,
            horizon_preset=req.horizon_preset,
        )

    return StructuralStopResponse(
        available=True,
        price=stop_price,
        source=stop.source,
        confidence=stop.confidence,
        distancePct=round(stop.distance_pct, 2),
        stopCost=_stop_cost_out(cost),
    )


class FirstPassageRequest(BaseModel):
    # NUMERIC-API-INPUTS T2: every float on this body is finite or a 422.
    model_config = ConfigDict(allow_inf_nan=False)

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
    # NUMERIC-API-INPUTS T2: every float on this body is finite or a 422.
    model_config = ConfigDict(allow_inf_nan=False)

    target_r_multiple: float | None = Field(default=None, gt=0, le=10, allow_inf_nan=False)
    symbol:      str
    direction:   Literal["Bullish", "Bearish"]
    entry_price: float = Field(..., gt=0)
    strike:      float = Field(..., gt=0)
    dte:         int = Field(..., ge=0)
    premium:     float = Field(..., gt=0)
    trend_score: float = Field(..., ge=0, le=100)
    # The contract is already mandatory here, so there is no all-or-nothing
    # set to police — only these two are new. Same units and same meaning as
    # on StructuralStopRequest: `iv` is ABSOLUTE volatility in PERCENT and is
    # solved from the premium when absent; an absent preset means Swing.
    iv:             Optional[float] = Field(default=None, gt=1.0, le=500.0)
    horizon_preset: Optional[str] = None


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
    # The same gate as /contracts/structural-stop's, evaluated against THIS
    # stop — the wider of the structural level and the ATR floor. The two
    # endpoints disagreeing is correct, not a bug: a wider stop costs more of
    # the premium, and this is the number that applies once an Arithmetic Plan
    # has been run (spec §2.2).
    #
    # Note `contractPrice` above answers a DIFFERENT question and cannot serve
    # this one: it is the exit-plan pipeline's repriced value at the stop, from
    # estimate_rr — Heston-or-BS, at the horizon the pipeline reprices to.
    # This block is deliberately Black-Scholes at TODAY's date, no theta.
    stopCost:             Optional[StopCostOut] = None


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

    stop_price = round(final_stop.price, 2)
    stop_cost = compute_stop_cost(
        stop_price=stop_price,
        stock_price=req.entry_price,
        strike=req.strike,
        dte=req.dte,
        premium=req.premium,
        is_call=is_call,
        iv_pct=req.iv,
        horizon_preset=req.horizon_preset,
    )

    stop_out = ExitPlanStopOut(
        price=stop_price,
        source=final_stop.source,
        contractPrice=stop_priced.estimated_exit_premium,
        rrModel=stop_priced.model_used,
        structuralSource=final_stop.structural.source if final_stop.structural else None,
        structuralConfidence=final_stop.structural.confidence if final_stop.structural else None,
        structuralPrice=structural_price,
        atrFloorPrice=atr_floor_price,
        distanceDollar=abs(structural_price - atr_floor_price) if structural_price is not None else None,
        stopCost=_stop_cost_out(stop_cost),
    )

    targets_out: list[ExitPlanTargetRowOut] = []
    ratios = ep_cfg["target"]["rr_ratios"]
    if req.target_r_multiple is not None:
        step = ratios[1] - ratios[0] if len(ratios) > 1 else 1.0
        ratios = [req.target_r_multiple + step * i for i in range(len(ratios))]
    for rr_ratio in ratios:
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
