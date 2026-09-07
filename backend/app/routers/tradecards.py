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
    except Exception:
        return []
    # This endpoint reads the row DIRECTLY rather than going through
    # routers/scan.restore_from_db, so it needs the same refusal: a result
    # persisted before the IV basis split carries raw implied volatility x100
    # under `ivRank`, the name of a percentile, with nothing on the record
    # saying so. Serving those cards puts "IV rank 45" on the card the user acts
    # from for a 45% absolute IV -- the exact defect Phase A removes -- and the
    # basis is not recoverable, so they are dropped rather than relabelled
    # (PHASE-A-NULL-IVRANK-2026-09-06). Empty here means "run a scan", which is
    # what the caller already renders when no scan has been run.
    if scan.schema_version is None:
        return []
    return scan.candidates
