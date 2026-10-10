import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field, StrictInt, ValidationError, field_validator, model_validator

from app.database import get_db
from app.models.watched_contracts import WatchedContractModel
from app.scoring.contract_validator import CONTRACT_OVERRIDE_KEYS, is_finite_rule_value

router = APIRouter(prefix='/api', tags=['trading'])

_log = logging.getLogger(__name__)


class ContractGradingModel(BaseModel):
    """The grading inputs Step 6 sent to /api/contracts for a row when it was
    starred, so the Watchlist grades the contract the same way.

    contract_rules: the scan's recorded overrides (a delta on the live
    contract_rules.yaml); {} = the scan overrode nothing, None = not recorded.
    Same acceptance rule as /api/contracts' `contract_rules`: every key the
    validator reads must be a finite number (is_finite_rule_value), unknown
    keys are dropped before storing."""
    contract_rules: Optional[dict[str, Any]] = None
    hold_min_days: Optional[StrictInt] = Field(default=None, ge=0)
    hold_max_days: Optional[StrictInt] = Field(default=None, ge=0)
    stock_score: Optional[StrictInt] = Field(default=None, ge=0, le=100)

    @field_validator('contract_rules')
    @classmethod
    def _rules_finite(cls, v: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if v is None:
            return None
        for key in CONTRACT_OVERRIDE_KEYS & v.keys():
            if not is_finite_rule_value(v[key]):
                raise ValueError(f'contract_rules.{key} must be a finite number')
        return {k: val for k, val in v.items() if k in CONTRACT_OVERRIDE_KEYS}

    @model_validator(mode='after')
    def _hold_pair(self) -> 'ContractGradingModel':
        if (self.hold_min_days is None) != (self.hold_max_days is None):
            raise ValueError('hold_min_days and hold_max_days must be given together')
        if self.hold_min_days is not None and self.hold_max_days < self.hold_min_days:
            raise ValueError('hold_max_days must be >= hold_min_days')
        return self


class WatchedContractAddRequest(BaseModel):
    contract_id: str
    # Three shapes, told apart by model_fields_set: absent -> an existing row's
    # grading is left alone; an object -> stored / overwritten; explicit null
    # -> an existing row's grading is cleared.
    grading: Optional[ContractGradingModel] = None


class WatchedContractDetail(BaseModel):
    contract_id: str
    grading: Optional[ContractGradingModel] = None


@router.get('/watched-contracts', response_model=list[str])
async def get_watched_contracts(db: AsyncSession = Depends(get_db)) -> list[str]:
    result = await db.execute(
        select(WatchedContractModel).order_by(WatchedContractModel.created_at)
    )
    return [row.contract_id for row in result.scalars().all()]


def _stored_grading(row: WatchedContractModel) -> Optional[ContractGradingModel]:
    """The row's grading, or None when it is NULL or no longer validates
    (a hand-edited DB) -- served as "no grading", never a 500."""
    if row.grading is None:
        return None
    try:
        return ContractGradingModel.model_validate(row.grading)
    except ValidationError:
        _log.warning("watched contract %s: stored grading invalid, served as null", row.contract_id)
        return None


@router.get('/watched-contracts/detail', response_model=list[WatchedContractDetail])
async def get_watched_contracts_detail(db: AsyncSession = Depends(get_db)) -> list[WatchedContractDetail]:
    result = await db.execute(
        select(WatchedContractModel).order_by(WatchedContractModel.created_at)
    )
    return [
        WatchedContractDetail(contract_id=row.contract_id, grading=_stored_grading(row))
        for row in result.scalars().all()
    ]


@router.post('/watched-contracts', status_code=status.HTTP_201_CREATED)
async def add_watched_contract(
    body: WatchedContractAddRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    grading_given = 'grading' in body.model_fields_set
    grading = body.grading.model_dump() if body.grading is not None else None
    existing = await db.execute(
        select(WatchedContractModel).where(
            WatchedContractModel.contract_id == body.contract_id
        )
    )
    row = existing.scalar_one_or_none()
    if row is None:
        db.add(WatchedContractModel(contract_id=body.contract_id, grading=grading))
        await db.commit()
    elif grading_given:
        # Step 6 decides "starred" from local state, which can diverge from the
        # server (cleared storage, a second device): a click can POST for a row
        # that already exists with NULL or stale grading, so it overwrites.
        row.grading = grading
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
