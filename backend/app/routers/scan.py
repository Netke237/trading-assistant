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
)
from typing import Literal
from app.data.market import (
    fetch_candles_async, fetch_price_async, fetch_option_chain_async,
    fetch_company_name_async, fetch_fundamentals_calendar,
    _extract_earnings_date, _extract_dividend_date,
    TRADIER_BASE_URL, TRADIER_TOKEN,
)
from app.scoring.stock_scorer import score_stock, StockScoreCard
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


def _augment(c: dict) -> dict:
    mid = float(c.get("price", 0))
    spread = float(c.get("spread", 0))
    return {
        **c,
        "bid": round(max(0.01, mid - spread / 2), 2),
        "ask": round(mid + spread / 2, 2),
    }


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


_SCAN_CONCURRENCY = 10


async def _process_symbol(
    symbol: str,
    direction: str,
    horizon: str,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    scan_id: str,
) -> TradeCardData | RejectedCandidate:
    """Process one symbol: fetch data, score stock, validate contracts, build trade card."""
    async with sem:
        # ── Fetch all market data ──────────────────────────────────────────────
        candles = await fetch_candles_async(client, symbol)
        price = await fetch_price_async(client, symbol)
        company = await fetch_company_name_async(client, symbol)
        company = company or symbol

        if not price or not candles:
            log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": "no market data"})
            return RejectedCandidate(symbol=symbol, reason="no market data")

        option_type: Literal["C", "P"] = "C" if direction == "Bullish" else "P"
        chain = await fetch_option_chain_async(client, symbol, option_type=option_type)

        # Combined single call for earnings + dividend (deduplicated)
        fund_data = await fetch_fundamentals_calendar(client, symbol)
        earnings_date = _extract_earnings_date(fund_data)
        dividend_date = _extract_dividend_date(fund_data)

    # ── Scoring (CPU-bound, outside semaphore) ─────────────────────────────────

    atm = sorted(chain, key=lambda c: abs(float(c.get("strike", 0)) - price)) if chain else []
    iv_rank: float | None = float(atm[0]["ivRank"]) if atm else None

    card: StockScoreCard = score_stock(
        symbol, direction, horizon, candles,
        earnings_date=earnings_date,
        dividend_date=dividend_date,
        iv_rank=iv_rank,
    )
    if card.status == "REJECT":
        log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": f"stock REJECT (score {card.score})"})
        return RejectedCandidate(symbol=symbol, reason=f"stock REJECT (score {card.score})")

    if not chain:
        log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": "no option chain"})
        return RejectedCandidate(symbol=symbol, reason="no option chain")

    augmented = [_augment(c) for c in chain]
    scored = [(validate_contract(c, card.score), c) for c in augmented]

    valid_scores = [(s, c) for s, c in scored if s.status != "REJECT"]
    if not valid_scores:
        log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": "all contracts rejected"})
        return RejectedCandidate(symbol=symbol, reason="all contracts rejected")

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
    )

    targets = estimate_targets(
        stock_price=price,
        base_target_price=target_price,
        strike=strike,
        expiry_years=expiry_years,
        current_premium=premium,
        is_call=(direction == "Bullish"),
        heston_params=heston_params,
    )

    # ── Build TradeCardData ────────────────────────────────────────────────────
    from datetime import date as _date
    next_event_days = None
    next_event_label = None
    if earnings_date:
        next_event_days = max(0, (earnings_date - _date.today()).days)
        next_event_label = "Earnings"
    elif dividend_date:
        next_event_days = max(0, (dividend_date - _date.today()).days)
        next_event_label = "Dividend"

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
            _process_symbol(symbol, req.direction, req.horizon, client, semaphore, scan_id)
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
    max_candidates: int = _settings.get("scan", {}).get("shortlist_max_candidates", 10)
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
