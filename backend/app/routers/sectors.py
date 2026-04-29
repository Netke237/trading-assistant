from fastapi import APIRouter
from app.schemas import SectorTile
from app.fixtures.sectors import MOCK_SECTORS

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/sectors', response_model=list[SectorTile])
async def get_sectors() -> list[SectorTile]:
    return MOCK_SECTORS
