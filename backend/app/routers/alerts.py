from fastapi import APIRouter
from app.schemas import AlertItem
from app.services.alert_generator import generate_alerts

router = APIRouter(prefix='/api', tags=['alerts'])


@router.get('/alerts', response_model=list[AlertItem])
async def get_alerts() -> list[AlertItem]:
    return generate_alerts()
