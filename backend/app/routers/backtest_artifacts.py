"""Shares the application's configured deployment/access boundary."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services import backtest_artifacts
from app.schemas.fresh_backtest import FreshBacktestRequest

router = APIRouter(prefix='/api/backtest-artifacts', tags=['backtest-artifacts'])


@router.get('/fresh/configuration')
async def fresh_configuration():
    from app.schemas.fresh_backtest import SUPPORTED, parameter_contract, signal_functions
    return {'strategies': list(SUPPORTED),
            'parameters': {name: parameter_contract(name) for name in signal_functions()},
            'multi_fields': ['variants', 'min_confirmations', 'variant_params']}


@router.post('/fresh')
async def run_fresh_artifact(request: FreshBacktestRequest, db: AsyncSession = Depends(get_db)):
    from app.services.fresh_backtest import run_fresh
    return await run_fresh(request, db)


@router.get('/{artifact_id}')
async def get_original_artifact(artifact_id: UUID, symbol: str = Query(pattern=r'^[A-Z][A-Z0-9.\-^]{0,14}$'),
                                db: AsyncSession = Depends(get_db)):
    try:
        artifact = await backtest_artifacts.get_artifact(db, str(artifact_id), symbol)
    except backtest_artifacts.ArtifactExpired:
        raise HTTPException(410, 'Backtest artifact expired') from None
    except backtest_artifacts.ArtifactStorageError:
        raise HTTPException(503, 'Backtest artifact storage unavailable') from None
    if artifact is None:
        raise HTTPException(404, 'Backtest artifact not found')
    return artifact
