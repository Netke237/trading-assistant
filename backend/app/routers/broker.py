from __future__ import annotations

from typing import Literal, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.data.ibkr_paper import BrokerOrder
from app.services.broker_router import build_router_from_credentials

router = APIRouter(prefix="/broker", tags=["broker"])

BrokerKey = Literal["ibkr_paper", "tradier_paper", "alpaca_paper"]


class StockOrderRequest(BaseModel):
    broker: BrokerKey
    symbol: str
    action: Literal["BUY", "SELL"]
    quantity: int
    order_type: Literal["MKT", "LMT"] = "LMT"
    limit_price: Optional[float] = None
    tif: Literal["DAY", "GTC"] = "DAY"


class OptionOrderRequest(BaseModel):
    broker: BrokerKey
    symbol: str
    option_symbol: str
    action: Literal["BUY", "SELL"]
    quantity: int
    order_type: Literal["MKT", "LMT"] = "LMT"
    limit_price: Optional[float] = None
    tif: Literal["DAY", "GTC"] = "DAY"
    conid: Optional[int] = None


@router.post("/stock-order")
async def place_stock_order(req: StockOrderRequest) -> dict:
    """Place a paper stock order on the specified broker."""
    router_ = build_router_from_credentials()
    order = BrokerOrder(
        symbol=req.symbol,
        action=req.action,
        quantity=req.quantity,
        order_type=req.order_type,
        limit_price=req.limit_price,
        tif=req.tif,
        sec_type="STK",
    )
    try:
        result = router_.execute(req.broker, order)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"order_id": result.order_id, "status": result.status, "broker": result.broker}


@router.post("/option-order")
async def place_option_order(req: OptionOrderRequest) -> dict:
    """Place a paper options order on the specified broker."""
    router_ = build_router_from_credentials()
    order = BrokerOrder(
        symbol=req.symbol,
        action=req.action,
        quantity=req.quantity,
        order_type=req.order_type,
        limit_price=req.limit_price,
        tif=req.tif,
        conid=req.conid,
        sec_type="OPT",
        option_symbol=req.option_symbol,
    )
    try:
        result = router_.execute(req.broker, order)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"order_id": result.order_id, "status": result.status, "broker": result.broker}


@router.get("/status")
async def broker_status() -> dict:
    """Return which brokers are configured (no credentials exposed)."""
    r = build_router_from_credentials()
    ibkr_ok   = "ibkr_paper"   in r._adapters
    trad_ok   = "tradier_paper" in r._adapters
    alpaca_ok = "alpaca_paper"  in r._adapters
    return {
        "ibkr_paper":    {"configured": ibkr_ok},
        "tradier_paper": {"configured": trad_ok},
        "alpaca_paper":  {"configured": alpaca_ok},
        "ibkr_live":     {"configured": False, "enabled": False, "note": "Locked — not yet activated"},
        "alpaca_live":   {"configured": False, "enabled": False, "note": "Locked — not yet activated"},
    }
