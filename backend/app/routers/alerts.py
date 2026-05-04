from fastapi import APIRouter
from app.schemas import AlertItem

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/alerts', response_model=list[AlertItem])
async def get_alerts() -> list[AlertItem]:
    return []
