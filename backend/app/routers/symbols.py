from fastapi import APIRouter
from app.data.company_names import KNOWN_NAMES

router = APIRouter(prefix='/api', tags=['symbols'])


@router.get('/symbol/{symbol}/info')
async def get_symbol_info(symbol: str) -> dict:
    sym = symbol.upper()
    name = KNOWN_NAMES.get(sym, sym)
    return {"symbol": sym, "name": name}
