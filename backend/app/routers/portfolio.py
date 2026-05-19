import asyncio
from datetime import date

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.portfolio import PortfolioPositionModel
from app.schemas import PortfolioPositionCreate, PortfolioPositionSchema
from app.services.portfolio_risk import check_position_risk, PortfolioPosition as RiskPosition
from app.data.market import fetch_contract_quote_async

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/portfolio', response_model=list[PortfolioPositionSchema])
async def get_portfolio(db: AsyncSession = Depends(get_db)) -> list[PortfolioPositionSchema]:
    result = await db.execute(select(PortfolioPositionModel).order_by(PortfolioPositionModel.created_at))
    positions = result.scalars().all()
    schemas = [PortfolioPositionSchema.from_orm_model(p) for p in positions]

    if not schemas:
        return schemas

    # Enrich with live option quotes — all positions fetched concurrently
    today = date.today()
    async with httpx.AsyncClient(timeout=10) as client:
        quotes = await asyncio.gather(
            *[fetch_contract_quote_async(client, s.contract) for s in schemas],
            return_exceptions=True,
        )

    for schema, quote in zip(schemas, quotes):
        # dteRemaining from contract string: SYMBOL|STRIKE|EXPIRY|C/P
        parts = schema.contract.split("|")
        if len(parts) >= 3:
            try:
                schema.dteRemaining = max(0, (date.fromisoformat(parts[2]) - today).days)
            except ValueError:
                pass

        if isinstance(quote, dict) and quote:
            schema.currentPrice = quote.get("price") or 0.0
            schema.delta        = quote.get("delta")
            schema.theta        = quote.get("theta")
            schema.ivRank       = quote.get("ivRank")
            if schema.entryPrice:
                schema.pnlDollar = round(
                    (schema.currentPrice - schema.entryPrice) * 100 * schema.qty, 2
                )
                schema.pnlPct = round(
                    (schema.currentPrice - schema.entryPrice) / schema.entryPrice * 100, 2
                )

    return schemas


@router.post('/portfolio', response_model=PortfolioPositionSchema, status_code=status.HTTP_201_CREATED)
async def add_position(
    body: PortfolioPositionCreate,
    db: AsyncSession = Depends(get_db),
) -> PortfolioPositionSchema:
    # Duplicate contract check → 409
    existing = await db.execute(
        select(PortfolioPositionModel).where(PortfolioPositionModel.contract == body.contract)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Position with contract '{body.contract}' already exists.",
        )

    # Fetch existing portfolio for risk check
    result = await db.execute(select(PortfolioPositionModel))
    db_positions = result.scalars().all()
    portfolio = [
        RiskPosition(
            symbol=p.symbol,
            contract_id=p.contract,
            contracts=p.qty,
            entry_premium=p.entry_price,
            current_price=p.entry_price,
            capital_at_risk=p.entry_price * p.qty * 100,
        )
        for p in db_positions
    ]

    risk = check_position_risk(
        symbol=body.symbol,
        contract_id=body.contract,
        proposed_contracts=body.qty,
        entry_premium=body.entryPrice,
        current_price=body.entryPrice,
        portfolio=portfolio,
        portfolio_value=body.portfolioValue,
    )
    if not risk.approved:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=" ".join(risk.reasons),
        )

    position = PortfolioPositionModel(
        rec_id=body.recId,
        symbol=body.symbol,
        contract=body.contract,
        direction=body.direction,
        entry_price=body.entryPrice,
        qty=body.qty,
        entry_date=body.entryDate,
        stop=body.stop,
        targets=body.targets,
        dte_total=body.dteTotal,
    )
    db.add(position)
    await db.commit()
    await db.refresh(position)
    return PortfolioPositionSchema.from_orm_model(position)


@router.delete('/portfolio/{rec_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_position(rec_id: str, db: AsyncSession = Depends(get_db)) -> None:
    result = await db.execute(
        select(PortfolioPositionModel).where(PortfolioPositionModel.rec_id == rec_id)
    )
    position = result.scalar_one_or_none()
    if position is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Position with rec_id '{rec_id}' not found.",
        )
    await db.delete(position)
    await db.commit()
