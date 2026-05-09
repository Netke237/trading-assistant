from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.portfolio import PortfolioPositionModel
from app.schemas import PortfolioPositionCreate, PortfolioPositionSchema
from app.services.portfolio_risk import check_position_risk, PortfolioPosition as RiskPosition

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/portfolio', response_model=list[PortfolioPositionSchema])
async def get_portfolio(db: AsyncSession = Depends(get_db)) -> list[PortfolioPositionSchema]:
    result = await db.execute(select(PortfolioPositionModel).order_by(PortfolioPositionModel.created_at))
    positions = result.scalars().all()
    return [PortfolioPositionSchema.from_orm_model(p) for p in positions]


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
