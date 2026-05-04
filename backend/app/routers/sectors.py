from fastapi import APIRouter
from app.schemas import SectorTile
from app.data.market import fetch_quotes

router = APIRouter(prefix='/api', tags=['trading'])

SECTOR_ETFS = ["XLK", "XLC", "XLY", "XLI", "XLF", "XLP", "XLV", "XLB", "XLRE", "XLU", "XLE"]

_ETF_NAME: dict[str, str] = {
    "XLK": "Technology",
    "XLC": "Comm. Services",
    "XLY": "Consumer Discretionary",
    "XLI": "Industrials",
    "XLF": "Financials",
    "XLP": "Consumer Staples",
    "XLV": "Health Care",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLU": "Utilities",
    "XLE": "Energy",
}


def _status(pct: float) -> str:
    if pct >= 0.4:
        return "PASS"
    if pct <= -0.4:
        return "REJECT"
    return "CAUTION"


@router.get('/sectors', response_model=list[SectorTile])
async def get_sectors() -> list[SectorTile]:
    quotes = fetch_quotes(SECTOR_ETFS)
    if not quotes:
        return []
    tiles = []
    for etf in SECTOR_ETFS:
        q = quotes.get(etf)
        if q is None:
            continue
        last = q["last"]
        prev = q["prevclose"]
        pct = (last - prev) / prev * 100 if prev else 0.0
        tiles.append(SectorTile(
            key=etf,
            name=_ETF_NAME[etf],
            changePct=round(pct, 2),
            status=_status(pct),
        ))
    return tiles
