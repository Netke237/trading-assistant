from __future__ import annotations

import asyncio
import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.schemas import OptionContract
from app.data.market import fetch_option_chain, fetch_price, fetch_contract_quote_async, fetch_price_async
from app.data.augment import _augment
from app.scoring.contract_validator import dte_holding_multiplier, validate_contract
from app.scoring.dte_window import dte_window

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
    if hold_min_days is not None and hold_max_days is not None and hold_max_days >= hold_min_days:
        try:
            dte_bounds = dte_window(hold_min_days, hold_max_days, dte_holding_multiplier())
            contract_overrides = {
                "min_dte": dte_bounds[0], "max_dte": dte_bounds[1],
                "preferred_dte_min": dte_bounds[0], "preferred_dte_max": dte_bounds[1],
            }
        except ValueError:
            # A misconfigured dte_holding_multiplier (0 or negative in contract_rules.yaml)
            # would otherwise 500 this endpoint. Fall back to the fetch/validator defaults.
            dte_bounds = None
            contract_overrides = None

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
