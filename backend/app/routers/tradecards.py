from fastapi import APIRouter
from app.schemas import TradeCardData
from app.fixtures.tradecards import MOCK_CANDIDATE_CARDS

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/tradecards', response_model=list[TradeCardData])
async def get_tradecards() -> list[TradeCardData]:
    return MOCK_CANDIDATE_CARDS
