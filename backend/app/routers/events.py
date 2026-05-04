from fastapi import APIRouter
from app.schemas import UpcomingEvent

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/events', response_model=list[UpcomingEvent])
async def get_events() -> list[UpcomingEvent]:
    return []
