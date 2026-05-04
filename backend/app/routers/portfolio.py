from fastapi import APIRouter
from app.schemas import PortfolioPosition

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/portfolio', response_model=list[PortfolioPosition])
async def get_portfolio() -> list[PortfolioPosition]:
    return []
