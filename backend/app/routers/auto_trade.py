from __future__ import annotations

from typing import Literal, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.auto_trader import auto_trader, ArmedStrategy

router = APIRouter(prefix="/auto-trade", tags=["auto-trade"])


class ArmRequest(BaseModel):
    broker:        str
    symbol:        str
    option_symbol: str
    action:        Literal["BUY", "SELL"]
    quantity:      int
    order_type:    Literal["MKT", "LMT"] = "LMT"
    limit_price:   Optional[float] = None
    conid:         Optional[int] = None


@router.post("/arm")
async def arm(req: ArmRequest) -> dict:
    """Arm the auto-trader with the given option order. Fires on next trigger."""
    auto_trader.arm(ArmedStrategy(**req.model_dump()))
    return {"armed": True, "symbol": req.symbol, "option_symbol": req.option_symbol}


@router.delete("/arm")
async def disarm() -> dict:
    """Disarm — cancel the pending auto-trade."""
    auto_trader.disarm()
    return {"armed": False}


@router.post("/fire")
async def fire_now() -> dict:
    """Trigger #1: manually fire the armed strategy immediately."""
    try:
        result = auto_trader.fire()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"order_id": result.order_id, "status": result.status, "broker": result.broker}


@router.get("/status")
async def status() -> dict:
    state = auto_trader.get_state()
    return {
        "armed":  state.armed,
        "symbol": state.strategy.symbol if state.strategy else None,
        "option": state.strategy.option_symbol if state.strategy else None,
        "broker": state.strategy.broker if state.strategy else None,
        "history_count": len(state.history),
        "last_order": state.history[-1] if state.history else None,
    }
