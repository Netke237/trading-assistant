from __future__ import annotations

from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.services.auto_trader import auto_trader, ArmedStrategy

router = APIRouter(prefix="/auto-trade", tags=["auto-trade"])


class ArmRequest(BaseModel):
    broker:          Literal["ibkr_paper", "tradier_paper", "alpaca_paper", "tastytrade_paper"]
    symbol:          str
    option_symbol:   str
    action:          Literal["BUY", "SELL"]
    quantity:        int = Field(..., ge=1)
    order_type:      Literal["MKT", "LMT"] = "LMT"
    limit_price:     Optional[float] = None
    conid:           Optional[int] = None
    entry_premium:   float = 0.0   # set to actual option mid; exposure check is skipped if 0
    portfolio_value: float = 50_000.0
    # Piece 4 — the per-trade premium stop from the card being armed. Omitted
    # or null inherits auto_trade.premium_stop_pct. Bounded here as well as on
    # the portfolio schemas: this endpoint reaches the same sizing arithmetic
    # without ever passing through PortfolioPositionCreate.
    premium_stop_pct: Optional[float] = Field(default=None, gt=0, lt=1)


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
async def fire_now(db: AsyncSession = Depends(get_db)) -> dict:
    """Trigger #1: manually fire the armed strategy with a live exposure check."""
    from app.models.portfolio import PortfolioPositionModel
    from app.services.portfolio_risk import orm_positions_to_risk
    if not auto_trader.get_state().armed:
        raise HTTPException(status_code=400, detail="AutoTrader not armed — cannot fire")
    result_q = await db.execute(select(PortfolioPositionModel))
    orm_positions = result_q.scalars().all()
    portfolio_snapshot = orm_positions_to_risk(orm_positions)
    try:
        result = auto_trader.fire(
            portfolio_snapshot=portfolio_snapshot,
            portfolio_value=None,  # fire() reads portfolio_value from strategy under lock
        )
    except (ValueError, RuntimeError) as exc:
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
