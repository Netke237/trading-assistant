from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.database import get_db
from app.models.watched_contracts import WatchedContractModel

router = APIRouter(prefix='/api', tags=['trading'])


class WatchedContractAddRequest(BaseModel):
    contract_id: str


@router.get('/watched-contracts', response_model=list[str])
async def get_watched_contracts(db: AsyncSession = Depends(get_db)) -> list[str]:
    result = await db.execute(
        select(WatchedContractModel).order_by(WatchedContractModel.created_at)
    )
    return [row.contract_id for row in result.scalars().all()]


@router.post('/watched-contracts', status_code=status.HTTP_201_CREATED)
async def add_watched_contract(
    body: WatchedContractAddRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    existing = await db.execute(
        select(WatchedContractModel).where(
            WatchedContractModel.contract_id == body.contract_id
        )
    )
    if existing.scalar_one_or_none() is None:
        db.add(WatchedContractModel(contract_id=body.contract_id))
        await db.commit()
    return {"contract_id": body.contract_id}


@router.delete('/watched-contracts/{contract_id:path}', status_code=status.HTTP_204_NO_CONTENT)
async def remove_watched_contract(
    contract_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(WatchedContractModel).where(
            WatchedContractModel.contract_id == contract_id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return  # Already removed — idempotent
    await db.delete(row)
    await db.commit()
