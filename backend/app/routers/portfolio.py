from fastapi import APIRouter
from app.schemas import PortfolioPosition
from app.fixtures.portfolio import MOCK_PORTFOLIO

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/portfolio', response_model=list[PortfolioPosition])
async def get_portfolio() -> list[PortfolioPosition]:
    return MOCK_PORTFOLIO
