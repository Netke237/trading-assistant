"""Read-only report API. Reading never dispatches a scan."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import scan_reports as store

router = APIRouter(prefix='/api/scan-reports', tags=['scan reports'])


async def _read(call):
    try:
        return await call
    except store.ScanReportStorageError:
        raise HTTPException(status_code=503, detail='Scan report storage unavailable') from None


@router.get('/legacy')
async def legacy(db: AsyncSession = Depends(get_db)):
    return await _read(store.get_legacy(db))


@router.get('/latest/{category}')
async def latest(category: str, db: AsyncSession = Depends(get_db)):
    if category not in store.CATEGORIES:
        raise HTTPException(status_code=422, detail='Unknown scan category')
    return await _read(store.get_latest(db, category))


@router.get('/runs/{run_id}')
async def run(run_id: str, db: AsyncSession = Depends(get_db)):
    report = await _read(store.get_run(db, run_id))
    if report is None:
        raise HTTPException(status_code=404, detail='Scan report unavailable')
    return report
