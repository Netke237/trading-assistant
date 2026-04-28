from fastapi import APIRouter
from app.schemas import OptionContract
from app.fixtures.contracts import MOCK_CONTRACTS

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/contracts', response_model=list[OptionContract])
async def get_contracts() -> list[OptionContract]:
    return MOCK_CONTRACTS
