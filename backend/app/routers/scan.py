from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import httpx
import yaml
from functools import lru_cache as _lru_cache
from pathlib import Path as _Path
from fastapi import APIRouter, Depends

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import AsyncSessionLocal, get_db
from app.models.scan_session import ScanSession
import json as _json

_RR_CONFIG_PATH = _Path(__file__).parent.parent.parent / "config" / "risk_rules.yaml"

# NOTE: lru_cache caches this at first call. Restart the backend to pick up
# changes to risk_rules.yaml (premium_stop_pct, target %, etc.).
@_lru_cache(maxsize=1)
def _rr_cfg() -> dict:
    import yaml as _yaml
    with open(_RR_CONFIG_PATH) as f:
        return _yaml.safe_load(f)["reward_risk"]

from app.schemas import (
    ScanRequest, ScanResult, RejectedCandidate, TradeCardData,
    ScoreBreakdown, ContractScoreBreakdown, ContractDetails, TradeEntry, TradeExit,
    ScanDelta, ContinuousScanConfig, ScanState,
    AlternativeContract,
    TrendDetail, PullbackDetail, TriggerDetail, EventDetail, VolDetail,
)
from typing import Literal
from app.data.market import (
    fetch_candles_async, fetch_price_async, fetch_option_chain_async,
    fetch_company_name_async, fetch_fundamentals_calendar,
    fetch_market_cap_async, fetch_calendar_dates_async,
    _extract_earnings_date, _extract_dividend_date,
    _compute_iv_bs,
    TRADIER_BASE_URL, TRADIER_TOKEN,
)
from app.models.black_scholes import bs_delta  # kept for other callers in this module
from app.data.augment import _augment
from app.scoring.stock_scorer import score_stock, StockScoreCard
from app.scoring.signal_confidence import load_gate_cfg, compute_confidence
from app.data import confidence_cache
from app.scoring.contract_validator import validate_contract, ContractScoreCard
from app.scoring.entry_quality import assess_entry
from app.scoring.reward_risk import estimate_rr, estimate_targets
from app.models.heston import calibrate_heston
from app.services.audit import new_rec_id, log_event
from app.services.scan_scheduler import ScanScheduler

router = APIRouter(prefix='/api', tags=['scan'])

# Load settings once at module level (patchable in tests via app.routers.scan._settings)
_settings: dict = yaml.safe_load(
    (_Path(__file__).parent.parent.parent / "config" / "settings.yaml").read_text()
)

# ── Scheduler instance ───────────────────────────────────────────────────────

_DEFAULT_CADENCE = 60


def _load_default_cadence() -> int:
    # 3 levels up from app/routers/scan.py → backend/ → backend/config/settings.yaml
    path = str((_Path(__file__).parent.parent.parent / "config" / "settings.yaml").resolve())
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        return int(data.get('scan', {}).get('cadence_minutes', _DEFAULT_CADENCE))
    return _DEFAULT_CADENCE


_scheduler = ScanScheduler(cadence_minutes=_load_default_cadence())
_last_request: ScanRequest | None = None
_last_result: ScanResult | None = None


# ── Helpers ──────────────────────────────────────────────────────────────────

_ORDER = {"REJECT": 0, "CAUTION": 1, "PASS": 2}


def _rule_score(card: StockScoreCard, name: str) -> int:
    for r in card.rules:
        if r.name == name:
            return r.score
    return 50


def _final_status(s1: str, s2: str, s3: str) -> str:
    return min([s1, s2, s3], key=lambda s: _ORDER.get(s, 1))


def _resolve_gate(req: ScanRequest) -> dict:
    """Confidence gate = YAML default, overridden by any per-scan request values."""
    gate = dict(load_gate_cfg())
    cb = getattr(req, "confidence_caution_below", None)
    rb = getattr(req, "confidence_reject_below", None)
    if cb is not None:
        gate["cautionBelow"] = cb
    if rb is not None:
        gate["rejectBelow"] = rb
    return gate


def _compute_deltas(current: ScanResult, previous: ScanResult | None) -> list[ScanDelta]:
    """Compare current candidates with previous run and compute rank/score deltas."""
    if previous is None or not previous.candidates:
        return []

    prev_by_symbol = {c.symbol: (idx, c.stockScore) for idx, c in enumerate(previous.candidates)}
    deltas: list[ScanDelta] = []

    for new_rank, cand in enumerate(current.candidates):
        if cand.symbol in prev_by_symbol:
            old_rank, old_score = prev_by_symbol[cand.symbol]
            deltas.append(ScanDelta(
                symbol=cand.symbol,
                rank_delta=old_rank - new_rank,
                score_delta=cand.stockScore - old_score,
            ))

    return deltas


def _alt_reason(alt: dict, primary: dict, *, is_call: bool) -> str:
    alt_strike = float(alt.get("strike", 0))
    pri_strike = float(primary.get("strike", 0))
    alt_dte    = int(alt.get("dte", 0))
    pri_dte    = int(primary.get("dte", 0))

    parts: list[str] = []
    if alt_dte > pri_dte + 7:
        parts.append("longer DTE — more time for thesis to develop")
    elif alt_dte < pri_dte - 7:
        parts.append("shorter DTE — lower theta cost")

    if is_call:
        if alt_strike < pri_strike - 1:
            parts.append("lower strike — higher delta, more directional exposure")
        elif alt_strike > pri_strike + 1:
            parts.append("higher strike — lower cost, higher leverage if stock moves strongly")
    else:
        if alt_strike > pri_strike + 1:
            parts.append("higher strike — higher delta for downside move")
        elif alt_strike < pri_strike - 1:
            parts.append("lower strike — lower cost, higher leverage on further decline")

    return "; ".join(parts) if parts else "similar profile — alternative liquidity/spread characteristics"


# Kept at 3 to stay below Tradier's rate-limit threshold.
# 10 concurrent × 5 calls = 50 simultaneous requests caused severe throttling (50-78s/symbol).
# 3 concurrent × 5 calls = 15 simultaneous requests → consistent ~4-6s/symbol.
_SCAN_CONCURRENCY = 3


def _safe(model_cls, d: dict | None):
    """Construct a Pydantic detail model from a dict, ignoring unknown keys."""
    if not d:
        return None
    try:
        known = {f: d[f] for f in model_cls.model_fields if f in d}
        return model_cls(**known)
    except Exception:
        return None


async def _process_symbol(
    symbol: str,
    direction: str,
    horizon: str,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    scan_id: str,
    *,
    min_price: float | None = None,
    max_price: float | None = None,
    min_cap_usd: float | None = None,
    max_cap_usd: float | None = None,
    overrides: dict | None = None,
    gate: dict | None = None,
) -> TradeCardData | RejectedCandidate:
    """Process one symbol: fetch data, score stock, validate contracts, build trade card.

    Two-pass fetch: pass 1 fetches candles/price/fundamentals (no chain) and pre-screens
    the stock scorer.  ~70-80% of symbols are rejected here, avoiding the expensive option
    chain fetch entirely.  Pass 2 fetches the chain only for survivors.
    """
    option_type: Literal["C", "P"] = "C" if direction == "Bullish" else "P"

    # ── Pass 1: core data — no option chain ───────────────────────────────────
    async with sem:
        candles, price, company, fund_data = await asyncio.gather(
            fetch_candles_async(client, symbol),
            fetch_price_async(client, symbol),
            fetch_company_name_async(client, symbol),
            fetch_fundamentals_calendar(client, symbol),
        )
        company = company or symbol

        if not price or not candles:
            log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": "no market data"})
            return RejectedCandidate(symbol=symbol, reason="no market data")

        # ── Price filter ───────────────────────────────────────────────────────
        if min_price is not None and price < min_price:
            return RejectedCandidate(symbol=symbol, reason=f"price filter (${price:.2f} < ${min_price:.2f} min)")
        if max_price is not None and price > max_price:
            return RejectedCandidate(symbol=symbol, reason=f"price filter (${price:.2f} > ${max_price:.2f} max)")

        # ── Market-cap filter ──────────────────────────────────────────────────
        if min_cap_usd is not None or max_cap_usd is not None:
            market_cap = await fetch_market_cap_async(symbol)
            if market_cap is not None:
                if min_cap_usd is not None and market_cap < min_cap_usd:
                    cap_b = market_cap / 1e9
                    min_b = min_cap_usd / 1e9
                    return RejectedCandidate(symbol=symbol, reason=f"cap filter (${cap_b:.1f}B < ${min_b:.1f}B min)")
                if max_cap_usd is not None and market_cap > max_cap_usd:
                    cap_b = market_cap / 1e9
                    max_b = max_cap_usd / 1e9
                    return RejectedCandidate(symbol=symbol, reason=f"cap filter (${cap_b:.1f}B > ${max_b:.1f}B max)")

        earnings_date = _extract_earnings_date(fund_data)
        dividend_date = _extract_dividend_date(fund_data)

    # ── yfinance calendar fallback (outside semaphore, has its own rate limiter) ─
    if earnings_date is None or dividend_date is None:
        yf_earn, yf_div = await fetch_calendar_dates_async(symbol)
        if earnings_date is None:
            earnings_date = yf_earn
        if dividend_date is None:
            dividend_date = yf_div

    # ── Pre-screen: score without IV rank ─────────────────────────────────────
    # iv_rank is unknown until the chain is fetched (pass 2). Score with None to gate
    # on trend/pullback/trigger/event — the components that drive most rejections.
    # ~70-80% of symbols exit here, saving the option chain fetch entirely.
    card_pre: StockScoreCard = score_stock(
        symbol, direction, horizon, candles,
        earnings_date=earnings_date,
        dividend_date=dividend_date,
        iv_rank=None,
        overrides=overrides,
    )
    if card_pre.status == "REJECT":
        bd = {r.name: r.score for r in card_pre.rules}
        log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": f"stock REJECT (score {card_pre.score})"})
        return RejectedCandidate(symbol=symbol, reason=f"stock REJECT (score {card_pre.score})", breakdown=bd)

    # ── Pass 2: fetch option chain only for survivors ─────────────────────────
    async with sem:
        chain = await fetch_option_chain_async(client, symbol, option_type=option_type)

    if not chain:
        log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": "no option chain"})
        return RejectedCandidate(symbol=symbol, reason="no option chain")

    # ── Final score with IV rank from chain ───────────────────────────────────
    atm = sorted(chain, key=lambda c: abs(float(c.get("strike", 0)) - price))
    iv_rank: float | None = float(atm[0]["ivRank"]) if atm else None

    # Tradier returns implied_volatility=0 when no data — compute via Black-Scholes inversion
    if (iv_rank is None or iv_rank == 0) and atm:
        c0 = atm[0]
        iv_bs = _compute_iv_bs(
            mid=float(c0.get("price", 0)),
            S=price,
            K=float(c0.get("strike", price)),
            dte=int(c0.get("dte", 30)),
            is_call=(option_type == "C"),
        )
        if iv_bs is not None:
            iv_rank = round(iv_bs * 100, 1)
            for c in chain:
                if c.get("ivRank") is None or c.get("ivRank") == 0:
                    c["ivRank"] = int(iv_rank)
                    c["implied_volatility"] = round(iv_bs, 4)

    # ── Signal confidence (cached; computed in a thread to avoid blocking loop) ─
    _conf: int | None = None
    _conf_n: int = 0
    if gate is not None:
        _ck = confidence_cache.cache_key(symbol, direction, horizon)
        _cached = confidence_cache.get_cached(_ck)
        if _cached is None:
            _res = await asyncio.to_thread(
                compute_confidence, candles, direction=direction, horizon=horizon
            )
            _cached = {"confidence": _res.confidence, "sample_size": _res.sample_size}
            confidence_cache.set_cached(_ck, _cached)
        _conf = _cached["confidence"]
        _conf_n = _cached["sample_size"]

    card: StockScoreCard = score_stock(
        symbol, direction, horizon, candles,
        earnings_date=earnings_date,
        dividend_date=dividend_date,
        iv_rank=iv_rank,
        overrides=overrides,
        confidence=_conf,
        confidence_gate=gate,
        confidence_sample_size=_conf_n,
    )
    if card.status == "REJECT":
        bd = {r.name: r.score for r in card.rules}
        log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": f"stock REJECT (score {card.score})"})
        return RejectedCandidate(symbol=symbol, reason=f"stock REJECT (score {card.score})", breakdown=bd)

    augmented = [_augment(c, stock_price=price) for c in chain]
    scored = [(validate_contract(c, card.score, overrides=overrides), c) for c in augmented]

    valid_scores = [(s, c) for s, c in scored if s.status != "REJECT"]
    if not valid_scores:
        reason_counts: dict[str, int] = {}
        for s, _ in scored:
            for r in s.reject_reasons:
                reason_counts[r] = reason_counts.get(r, 0) + 1
        if reason_counts:
            detail = ", ".join(
                f"{r}({n})" for r, n in sorted(reason_counts.items(), key=lambda x: -x[1])
            )
            reject_reason = f"contracts rejected: {detail}"
        else:
            reject_reason = "all contracts rejected"
        log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": reject_reason})
        return RejectedCandidate(symbol=symbol, reason=reject_reason)

    valid_scores.sort(key=lambda x: x[0].score, reverse=True)
    best_score, contract = valid_scores[0]
    contract_card: ContractScoreCard = best_score
    runner_ups = valid_scores[1:3]

    # ── Heston calibration ─────────────────────────────────────────────────────
    heston_chain = [
        {
            "strike": float(c.get("strike", 0)),
            "expiry_years": c.get("dte", 30) / 365.0,
            "mid_price": float(c.get("price", 0)),
            "is_call": c.get("right", "C") == "C",
        }
        for c in chain
        if float(c.get("price", 0)) > 0
    ]
    heston_result = calibrate_heston(heston_chain, price, r=0.05)
    heston_params = heston_result.params

    # ── Entry quality ──────────────────────────────────────────────────────────
    bid = float(contract.get("bid", 0))
    ask = float(contract.get("ask", 0))
    mid = float(contract.get("price", 0))
    entry = assess_entry(bid=bid, ask=ask, mid=mid)

    # ── Reward-risk ────────────────────────────────────────────────────────────
    _rr = _rr_cfg()
    _bull = direction == "Bullish"
    target_price = price * (1 + _rr["bullish_target_pct"]) if _bull else price * (1 - _rr["bearish_target_pct"])
    invalidation_price = price * (1 - _rr["bullish_invalidation_pct"]) if _bull else price * (1 + _rr["bearish_invalidation_pct"])
    strike = float(contract.get("strike", price))
    expiry_years = contract.get("dte", 30) / 365.0
    premium = float(contract.get("price", 0.10))

    rr = estimate_rr(
        stock_price=price,
        target_price=target_price,
        invalidation_price=invalidation_price,
        strike=strike,
        expiry_years=expiry_years,
        current_premium=premium,
        is_call=(direction == "Bullish"),
        heston_params=heston_params,
        premium_stop_pct=_rr["premium_stop_pct"],
    )

    targets = estimate_targets(
        stock_price=price,
        base_target_price=target_price,
        strike=strike,
        expiry_years=expiry_years,
        current_premium=premium,
        is_call=(direction == "Bullish"),
        heston_params=heston_params,
        premium_stop_pct=_rr["premium_stop_pct"],
    )

    # ── Build TradeCardData ────────────────────────────────────────────────────
    from datetime import date as _date
    next_event_days = None
    next_event_label = None
    for ev_date, ev_label in [(earnings_date, "Earnings"), (dividend_date, "Dividend")]:
        if ev_date is None:
            continue
        days = max(0, (ev_date - _date.today()).days)
        if next_event_days is None or days < next_event_days:
            next_event_days = days
            next_event_label = ev_label

    # Build a name → detail lookup for rich ScoreBreakdown fields
    rule_detail = {r.name: r.detail for r in card.rules}

    trade_card = TradeCardData(
        symbol=symbol,
        company=company,
        price=price,
        direction=direction,
        status=card.status,
        stockScore=card.score,
        stockConfidence=card.status,
        stockBreakdown=ScoreBreakdown(
            trend=_rule_score(card, "trend"),
            pullback=_rule_score(card, "pullback"),
            trigger=_rule_score(card, "trigger"),
            event=_rule_score(card, "event"),
            volatility=_rule_score(card, "vol"),
            trendDetail=    _safe(TrendDetail,    rule_detail.get("trend")),
            pullbackDetail= _safe(PullbackDetail, rule_detail.get("pullback")),
            triggerDetail=  _safe(TriggerDetail,  rule_detail.get("trigger")),
            eventDetail=    _safe(EventDetail,    rule_detail.get("event")),
            volDetail=      _safe(VolDetail,      rule_detail.get("vol")),
        ),
        nextEventDays=next_event_days,
        nextEventLabel=next_event_label,
        contract=f"{symbol}|{int(strike)}|{contract.get('expiry','TBD')}|{'C' if direction=='Bullish' else 'P'}",
        contractScore=contract_card.score,
        contractConfidence=contract_card.status,
        contractBreakdown=ContractScoreBreakdown(
            dteFit=contract_card.breakdown.dte_score,
            delta=contract_card.breakdown.delta_score,
            ivAttractiveness=contract_card.breakdown.iv_rank_score,
            liquidity=contract_card.breakdown.liquidity_score,
            spread=contract_card.breakdown.spread_score,
        ),
        contractDetails=ContractDetails(
            strike=int(strike),
            expiry=contract.get("expiry", "TBD"),
            right="C" if direction == "Bullish" else "P",
            mid=round(premium, 2),
            delta=float(contract.get("delta", 0.45)),
            theta=float(contract.get("theta", -0.05)),
            ivRank=int(contract.get("ivRank", 50)),
            ivPercentile=int(contract.get("ivPercentile", 0) or 0),
            dte=int(contract.get("dte", 30)),
        ),
        entry=TradeEntry(
            limit=round(entry.limit_price, 2),
            maxFill=round(entry.max_fill, 2),
            orderType=entry.order_type,
        ),
        exit=TradeExit(
            invalidation=round(invalidation_price, 2),
            premiumStop=round(premium * _rr["premium_stop_pct"], 2),
            timeStopDays=max(3, int(contract.get("dte", 30) * 0.4)),
            target=round(target_price, 2),
            targets=targets,
        ),
        rrRatio=rr.rr_ratio,
        rrModel=rr.model_used,
        finalStatus=_final_status(card.status, contract_card.status, entry.quality_status),
        confidence=(_conf_rule.detail.get("confidence") if (_conf_rule := next((r for r in card.rules if r.name == "confidence"), None)) else None),
        confidenceText=(_conf_rule.detail.get("interpretation") if _conf_rule else None),
    )

    alts: list[AlternativeContract] = []
    for alt_card, alt_c in runner_ups:
        alt_strike = float(alt_c.get("strike", price))
        alt_expiry_years = alt_c.get("dte", 30) / 365.0
        alt_premium = float(alt_c.get("price", 0.10))
        alt_rr = estimate_rr(
            stock_price=price,
            target_price=target_price,
            invalidation_price=invalidation_price,
            strike=alt_strike,
            expiry_years=alt_expiry_years,
            current_premium=alt_premium,
            is_call=(direction == "Bullish"),
            heston_params=heston_params,
            premium_stop_pct=_rr["premium_stop_pct"],
        )
        alts.append(AlternativeContract(
            symbol=symbol,
            strike=int(alt_strike),
            expiry=alt_c.get("expiry", "TBD"),
            right="C" if direction == "Bullish" else "P",
            dte=int(alt_c.get("dte", 30)),
            mid=round(float(alt_c.get("price", 0)), 2),
            delta=round(float(alt_c.get("delta", 0.45)), 3),
            theta=round(float(alt_c.get("theta", -0.05)), 3),
            ivRank=int(alt_c.get("ivRank", 50)),
            score=alt_card.score,
            contractConfidence=alt_card.status,
            contractBreakdown=ContractScoreBreakdown(
                dteFit=alt_card.breakdown.dte_score,
                delta=alt_card.breakdown.delta_score,
                ivAttractiveness=alt_card.breakdown.iv_rank_score,
                liquidity=alt_card.breakdown.liquidity_score,
                spread=alt_card.breakdown.spread_score,
            ),
            rrRatio=alt_rr.rr_ratio,
            rrModel=alt_rr.model_used,
            reason=_alt_reason(alt_c, contract, is_call=(direction == "Bullish")),
        ))
    trade_card.alternatives = alts
    trade_card.alternativesCount = len(alts)

    log_event("trade_card_created", scan_id, {"symbol": symbol, "score": card.score})
    return trade_card


async def _upsert_session(
    db: AsyncSession,
    req: ScanRequest | None,
    result: ScanResult | None,
    status: str,
) -> None:
    """Persist scan state to the DB as a single row with id='current'."""
    await db.merge(
        ScanSession(
            id="current",
            status=status,
            last_result_json=result.model_dump_json() if result else None,
            last_request_json=req.model_dump_json() if req else None,
        )
    )
    await db.commit()


async def restore_from_db() -> str | None:
    """Restore _last_request and _last_result from DB on startup.

    Returns the stored status string so the caller can auto-resume the scheduler.
    """
    global _last_request, _last_result
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(ScanSession).where(ScanSession.id == "current"))
        except Exception:
            # Table may not exist (e.g., test_app.py with no DB)
            return None
        row = result.scalar_one_or_none()
        if row is None:
            return None
        if row.last_result_json:
            _last_result = ScanResult.model_validate_json(row.last_result_json)
        if row.last_request_json:
            _last_request = ScanRequest.model_validate_json(row.last_request_json)
        return row.status


@router.post('/scan', response_model=ScanResult)
async def run_scan(req: ScanRequest, db: AsyncSession = Depends(get_db)) -> ScanResult:
    global _last_request, _last_result
    _last_request = req
    scan_id = new_rec_id()
    log_event("scan_started", scan_id, {"universe": req.universe, "direction": req.direction})

    # Expand preset universe strings to individual ticker lists
    from app.data.universe_presets import expand_universe, PresetUnavailableError
    from fastapi import HTTPException

    try:
        symbols = expand_universe(req.universe)
    except PresetUnavailableError as e:
        raise HTTPException(status_code=400, detail=str(e))

    gate = _resolve_gate(req)

    candidates: list[TradeCardData] = []
    rejected: list[RejectedCandidate] = []
    has_exception = False

    semaphore = asyncio.Semaphore(_SCAN_CONCURRENCY)
    async with httpx.AsyncClient(
        base_url=httpx.URL(TRADIER_BASE_URL),
        headers={
            "Authorization": f"Bearer {TRADIER_TOKEN}",
            "Accept": "application/json",
        },
        timeout=httpx.Timeout(10.0),
    ) as client:
        tasks = [
            _process_symbol(
                symbol, req.direction, req.horizon, client, semaphore, scan_id,
                min_price=req.min_price,
                max_price=req.max_price,
                min_cap_usd=req.min_cap_usd,
                max_cap_usd=req.max_cap_usd,
                overrides=dict(req.overrides) if req.overrides else None,
                gate=gate,
            )
            for symbol in symbols
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            has_exception = True
            rejected.append(RejectedCandidate(symbol="unknown", reason=str(result)))
        elif isinstance(result, RejectedCandidate):
            rejected.append(result)
        elif isinstance(result, TradeCardData):
            candidates.append(result)

    # ── Shortlist cap ─────────────────────────────────────────────────────────
    max_candidates: int = int(
        req.overrides.get(
            "shortlist_max_candidates",
            _settings.get("scan", {}).get("shortlist_max_candidates", 10),
        )
    )
    original_count: int = len(candidates)
    shortlist_truncated: bool = original_count > max_candidates
    candidates = candidates[:max_candidates]

    # Determine state: PARTIAL if some exceptions occurred but we still got candidates
    state: ScanState = 'COMPLETED'
    if has_exception and candidates:
        state = 'PARTIAL'
    elif has_exception and not candidates:
        state = 'FAILED'

    deltas = _compute_deltas(
        ScanResult(scan_id=scan_id, timestamp=datetime.now(timezone.utc).isoformat(), candidates=candidates, rejected=rejected),
        _last_result,
    )

    result = ScanResult(
        scan_id=scan_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        candidates=candidates,
        rejected=rejected,
        state=state,
        previous_run_id=_last_result.scan_id if _last_result else None,
        deltas=deltas,
        shortlist_truncated=shortlist_truncated,
        original_count=original_count,
    )
    _last_result = result
    await _upsert_session(db, req=_last_request, result=result, status="complete")
    return result


# ── Continuous scan endpoints ────────────────────────────────────────────────

async def _scheduled_scan() -> ScanResult:
    """Wrapper used by the scheduler. Re-uses the last request configuration."""
    if _last_request is None:
        raise RuntimeError("No previous scan request to repeat")
    async with AsyncSessionLocal() as db:
        return await run_scan(_last_request, db)


@router.post('/scan/continuous', response_model=ContinuousScanConfig)
async def start_continuous_scan(
    config: ContinuousScanConfig, db: AsyncSession = Depends(get_db)
) -> ContinuousScanConfig:
    """Start (or restart) the continuous scan scheduler."""
    _scheduler.set_cadence(config.cadence_minutes)
    _scheduler.bind(_scheduled_scan)
    await _scheduler.start()
    await _upsert_session(db, req=_last_request, result=_last_result, status="running")
    return config


@router.delete('/scan/continuous')
async def stop_continuous_scan(db: AsyncSession = Depends(get_db)) -> dict:
    """Stop the continuous scan scheduler."""
    await _scheduler.stop()
    await _upsert_session(db, req=_last_request, result=_last_result, status="stopped")
    return {"status": "stopped"}


@router.get('/scan/continuous/status')
async def continuous_scan_status() -> dict:
    """Get current scheduler status."""
    return _scheduler.get_status()
