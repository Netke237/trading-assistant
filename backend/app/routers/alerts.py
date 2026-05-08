from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import AlertItem
from app.services.alert_generator import generate_alerts

router = APIRouter(prefix='/api', tags=['alerts'])


@router.get('/alerts', response_model=list[AlertItem])
async def get_alerts(db: AsyncSession = Depends(get_db)) -> list[AlertItem]:
    # TODO: wire to Tradier price feed for real-time prices
    current_prices: dict[str, float] = {}
    return await generate_alerts(db, current_prices)