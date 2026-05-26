from __future__ import annotations

from fastapi import APIRouter, Query

from app.schemas import OptionContract
from app.data.market import fetch_option_chain, fetch_price
from app.data.augment import _augment
from app.scoring.contract_validator import validate_contract

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/contracts', response_model=list[OptionContract])
async def get_contracts(
    symbol: str = Query(default='AAPL'),
    right: str = Query(default='C'),
    stock_score: int = Query(default=70, ge=0, le=100),
    direction: str = Query(default='Bullish'),
    horizon: str = Query(default='swing'),
    limit: int = Query(default=10, ge=1, le=100),
    max_price: float = Query(default=50.0, ge=0.5, le=500.0),
) -> list[OptionContract]:
    opt_type = 'C' if right.upper() == 'C' else 'P'

    # 1. Fetch raw option chain
    raw_chain = fetch_option_chain(symbol.upper(), option_type=opt_type) or []

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
        score_card = validate_contract(augmented, stock_score, overrides=None)

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
