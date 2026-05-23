from fastapi import APIRouter, Query
from app.schemas import OptionContract
from app.data.market import fetch_option_chain

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/contracts', response_model=list[OptionContract])
async def get_contracts(
    symbol: str = Query(default='AAPL'),
    right: str = Query(default='C'),
) -> list[OptionContract]:
    opt_type = 'C' if right.upper() == 'C' else 'P'
    return fetch_option_chain(symbol.upper(), option_type=opt_type) or []
