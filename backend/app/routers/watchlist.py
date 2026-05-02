from fastapi import APIRouter
from app.schemas import WatchlistRow
from app.fixtures.watchlist import MOCK_WATCHLIST
from app.data.market import fetch_quotes

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/watchlist', response_model=list[WatchlistRow])
async def get_watchlist() -> list[WatchlistRow]:
    try:
        symbols = [row['symbol'] for row in MOCK_WATCHLIST]
        quotes = fetch_quotes(symbols)
    except Exception:
        quotes = {}

    if not quotes:
        return MOCK_WATCHLIST

    result = []
    for row in MOCK_WATCHLIST:
        sym = row.symbol
        price = quotes[sym]['last'] if sym in quotes else row.price
        result.append(WatchlistRow(**{**row.model_dump(), 'price': price}))
    return result
