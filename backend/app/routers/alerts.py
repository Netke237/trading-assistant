from fastapi import APIRouter
from app.schemas import AlertItem
from app.fixtures.alerts import MOCK_ALERTS

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/alerts', response_model=list[AlertItem])
async def get_alerts() -> list[AlertItem]:
    return MOCK_ALERTS
