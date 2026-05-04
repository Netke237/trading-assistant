from fastapi import APIRouter
from app.schemas import TradeCardData

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/tradecards', response_model=list[TradeCardData])
async def get_tradecards() -> list[TradeCardData]:
    return []
