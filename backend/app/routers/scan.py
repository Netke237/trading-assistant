from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from app.schemas import (
    ScanRequest, ScanResult, RejectedCandidate, TradeCardData,
    ScoreBreakdown, ContractScoreBreakdown, ContractDetails, TradeEntry, TradeExit,
)
from app.data.market import fetch_candles, fetch_price, fetch_option_chain
from app.scoring.stock_scorer import score_stock, StockScoreCard
from app.scoring.contract_validator import validate_contract, ContractScoreCard
from app.scoring.entry_quality import assess_entry
from app.scoring.reward_risk import estimate_rr
from app.models.heston import calibrate_heston
from app.services.audit import new_rec_id, log_event

router = APIRouter(prefix='/api', tags=['scan'])


_ORDER = {"REJECT": 0, "CAUTION": 1, "PASS": 2}


def _rule_score(card: StockScoreCard, name: str) -> int:
    for r in card.rules:
        if r.name == name:
            return r.score
    return 50


def _final_status(s1: str, s2: str, s3: str) -> str:
    return min([s1, s2, s3], key=lambda s: _ORDER.get(s, 1))


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
    scan_id = new_rec_id()
    log_event("scan_started", scan_id, {"universe": req.universe, "direction": req.direction})

    candidates: list[TradeCardData] = []
    rejected: list[RejectedCandidate] = []

    for symbol in req.universe:
        try:
            # Step 1 — Fetch market data
            candles = fetch_candles(symbol)
            price = fetch_price(symbol)
            if not price or not candles:
                rejected.append(RejectedCandidate(symbol=symbol, reason="no market data"))
                log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": "no market data"})
                continue

            # Step 2 — Score the stock
            card: StockScoreCard = score_stock(symbol, req.direction, req.horizon, candles)
            if card.status == "REJECT":
                rejected.append(RejectedCandidate(symbol=symbol, reason=f"stock REJECT (score {card.score})"))
                log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": f"stock REJECT (score {card.score})"})
                continue

            # Step 3 — Fetch and validate contracts
            chain = fetch_option_chain(symbol)
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

            # Step 4 — Calibrate Heston (best-effort)
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

            # Step 5 — Assess entry quality
            bid = float(contract.get("bid", 0))
            ask = float(contract.get("ask", 0))
            mid = float(contract.get("price", 0))
            entry = assess_entry(bid=bid, ask=ask, mid=mid)

            # Step 6 — Estimate reward-risk
            target_price = price * (1.08 if req.direction == "Bullish" else 0.92)
            invalidation_price = price * (0.97 if req.direction == "Bullish" else 1.03)
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

            # Step 7 — Build TradeCardData
            trade_card = TradeCardData(
                symbol=symbol,
                company=symbol,
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
                    premiumStop=round(premium * 0.6, 2),
                    timeStopDays=max(3, int(contract.get("dte", 30) * 0.4)),
                    target=round(target_price, 2),
                ),
                rrRatio=rr.rr_ratio,
                rrModel=rr.model_used,
                finalStatus=_final_status(card.status, contract_card.status, entry.quality_status),
            )

            candidates.append(trade_card)
            log_event("trade_card_created", scan_id, {"symbol": symbol, "score": card.score})

        except Exception as e:
            rejected.append(RejectedCandidate(symbol=symbol, reason=str(e)))
            log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": str(e)})

    return ScanResult(
        scan_id=scan_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        candidates=candidates,
        rejected=rejected,
    )
