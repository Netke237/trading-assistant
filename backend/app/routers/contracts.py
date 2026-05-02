from fastapi import APIRouter, Query
from typing import Optional
from app.schemas import OptionContract
from app.data.market import fetch_option_chain
from app.fixtures.contracts import MOCK_CONTRACTS

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/contracts', response_model=list[OptionContract])
async def get_contracts(symbol: str = Query(default='AAPL')) -> list[OptionContract]:
    contracts = fetch_option_chain(symbol.upper(), option_type='C')
    if not contracts:
        return MOCK_CONTRACTS
    return contracts
