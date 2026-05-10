from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.scan_session import ScanSession
from app.schemas import ScanResult, TradeCardData

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/tradecards', response_model=list[TradeCardData])
async def get_tradecards(db: AsyncSession = Depends(get_db)) -> list[TradeCardData]:
    result = await db.execute(select(ScanSession).where(ScanSession.id == "current"))
    row = result.scalar_one_or_none()
    if row is None or not row.last_result_json:
        return []
    try:
        scan = ScanResult.model_validate_json(row.last_result_json)
        return scan.candidates
    except Exception:
        return []
