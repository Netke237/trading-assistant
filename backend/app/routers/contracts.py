from fastapi import APIRouter, Query
from app.schemas import OptionContract
from app.data.market import fetch_option_chain

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/contracts', response_model=list[OptionContract])
async def get_contracts(symbol: str = Query(default='AAPL')) -> list[OptionContract]:
    return fetch_option_chain(symbol.upper(), option_type='C') or []
