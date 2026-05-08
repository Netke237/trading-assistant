from __future__ import annotations

import os
from datetime import datetime, timezone

import yaml
from functools import lru_cache as _lru_cache
from pathlib import Path as _Path
from fastapi import APIRouter

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
)
from typing import Literal
from app.data.market import (
    fetch_candles, fetch_price, fetch_option_chain,
    fetch_earnings_date, fetch_dividend_date, fetch_company_name,
)
from app.scoring.stock_scorer import score_stock, StockScoreCard
from app.scoring.contract_validator import validate_contract, ContractScoreCard
from app.scoring.entry_quality import assess_entry
from app.scoring.reward_risk import estimate_rr, estimate_targets
from app.models.heston import calibrate_heston
from app.services.audit import new_rec_id, log_event
from app.services.scan_scheduler import ScanScheduler

router = APIRouter(prefix='/api', tags=['scan'])

# ── Scheduler instance ───────────────────────────────────────────────────────

_DEFAULT_CADENCE = 60


def _load_default_cadence() -> int:
    path = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'settings.yaml')
    path = os.path.normpath(path)
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
        "open_interest": c.get("volume", 0),
    }


@router.post('/scan', response_model=ScanResult)
async def run_scan(req: ScanRequest) -> ScanResult:
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

    for symbol in symbols:
        try:
            # Step 1 — Fetch market data
            candles = fetch_candles(symbol)
            price = fetch_price(symbol)
            company = fetch_company_name(symbol) or symbol
            if not price or not candles:
                rejected.append(RejectedCandidate(symbol=symbol, reason="no market data"))
                log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": "no market data"})
                continue

            # Step 2 — Fetch option chain (before scoring so we can derive iv_rank)
            option_type: Literal["C", "P"] = "C" if req.direction == "Bullish" else "P"
            chain = fetch_option_chain(symbol, option_type=option_type)

            # Derive IV rank proxy from ATM contract (current IV as approximation)
            atm = sorted(chain, key=lambda c: abs(float(c.get("strike", 0)) - price)) if chain else []
            iv_rank: float | None = float(atm[0]["ivRank"]) if atm else None

            # Step 3 — Fetch event dates (best-effort; None if Tradier fundamentals unavailable)
            earnings_date = fetch_earnings_date(symbol)
            dividend_date = fetch_dividend_date(symbol)

            # Step 4 — Score the stock with full context
            card: StockScoreCard = score_stock(
                symbol, req.direction, req.horizon, candles,
                earnings_date=earnings_date,
                dividend_date=dividend_date,
                iv_rank=iv_rank,
            )
            if card.status == "REJECT":
                rejected.append(RejectedCandidate(symbol=symbol, reason=f"stock REJECT (score {card.score})"))
                log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": f"stock REJECT (score {card.score})"})
                continue

            # Step 5 — Validate contracts (chain already fetched above)
            if not chain:
                rejected.append(RejectedCandidate(symbol=symbol, reason="no option chain"))
                log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": "no option chain"})
                continue

            augmented = [_augment(c) for c in chain]
            scored = [(validate_contract(c, card.score), c) for c in augmented]

            # Check if all contracts are rejected
            valid_scores = [(s, c) for s, c in scored if s.status != "REJECT"]
            if not valid_scores:
                rejected.append(RejectedCandidate(symbol=symbol, reason="all contracts rejected"))
                log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": "all contracts rejected"})
                continue

            best_score, contract = max(valid_scores, key=lambda x: x[0].score)
            contract_card: ContractScoreCard = best_score

            # Step 6 — Calibrate Heston (best-effort)
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

            # Step 7 — Assess entry quality
            bid = float(contract.get("bid", 0))
            ask = float(contract.get("ask", 0))
            mid = float(contract.get("price", 0))
            entry = assess_entry(bid=bid, ask=ask, mid=mid)

            # Step 8 — Estimate reward-risk
            _rr = _rr_cfg()
            _bull = req.direction == "Bullish"
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
                is_call=(req.direction == "Bullish"),
                heston_params=heston_params,
            )

            targets = estimate_targets(
                stock_price=price,
                base_target_price=target_price,
                strike=strike,
                expiry_years=expiry_years,
                current_premium=premium,
                is_call=(req.direction == "Bullish"),
                heston_params=heston_params,
            )

            # Step 9 — Build TradeCardData
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
                direction=req.direction,
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
                contract=f"{symbol}|{int(strike)}|{contract.get('expiry','TBD')}|{'C' if req.direction=='Bullish' else 'P'}",
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
                    right="C" if req.direction == "Bullish" else "P",
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

            candidates.append(trade_card)
            log_event("trade_card_created", scan_id, {"symbol": symbol, "score": card.score})

        except Exception as e:
            has_exception = True
            rejected.append(RejectedCandidate(symbol=symbol, reason=str(e)))
            log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": str(e)})

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
    )
    _last_result = result
    return result


# ── Continuous scan endpoints ────────────────────────────────────────────────

async def _scheduled_scan() -> ScanResult:
    """Wrapper used by the scheduler. Re-uses the last request configuration."""
    if _last_request is None:
        raise RuntimeError("No previous scan request to repeat")
    return await run_scan(_last_request)


@router.post('/scan/continuous', response_model=ContinuousScanConfig)
async def start_continuous_scan(config: ContinuousScanConfig) -> ContinuousScanConfig:
    """Start (or restart) the continuous scan scheduler."""
    _scheduler.set_cadence(config.cadence_minutes)
    _scheduler.bind(_scheduled_scan)
    await _scheduler.start()
    return config


@router.delete('/scan/continuous')
async def stop_continuous_scan() -> dict:
    """Stop the continuous scan scheduler."""
    await _scheduler.stop()
    return {"status": "stopped"}


@router.get('/scan/continuous/status')
async def continuous_scan_status() -> dict:
    """Get current scheduler status."""
    return _scheduler.get_status()
