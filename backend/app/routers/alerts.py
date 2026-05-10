from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.market import fetch_quotes
from app.database import get_db
from app.models.portfolio import PortfolioPositionModel
from app.schemas import AlertItem
from app.services.alert_generator import generate_alerts

router = APIRouter(prefix='/api', tags=['alerts'])


@router.get('/alerts', response_model=list[AlertItem])
async def get_alerts(db: AsyncSession = Depends(get_db)) -> list[AlertItem]:
    result = await db.execute(select(PortfolioPositionModel))
    symbols = list({p.symbol for p in result.scalars().all()})
    quotes = fetch_quotes(symbols)
    current_prices = {sym: q["last"] for sym, q in quotes.items()}
    return await generate_alerts(db, current_prices)