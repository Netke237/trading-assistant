from fastapi import APIRouter
from app.schemas import UpcomingEvent
from app.fixtures.events import MOCK_EVENTS

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/events', response_model=list[UpcomingEvent])
async def get_events() -> list[UpcomingEvent]:
    return MOCK_EVENTS
