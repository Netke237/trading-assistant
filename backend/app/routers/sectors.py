import asyncio
from datetime import date, timedelta

import httpx
from fastapi import APIRouter
from app.schemas import SectorTile
from app.data.market import TRADIER_BASE_URL, TRADIER_TOKEN

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

_HEADERS = {
    "Authorization": f"Bearer {TRADIER_TOKEN}",
    "Accept": "application/json",
}


def _status(pct: float) -> str:
    if pct >= 0.4:
        return "PASS"
    if pct <= -0.4:
        return "REJECT"
    return "CAUTION"


async def _fetch_etf_change(client: httpx.AsyncClient, etf: str) -> tuple[str, float]:
    """
    Fetch the two most recent daily closes for `etf` and return (etf, changePct).
    Uses the same OHLCV history endpoint as the index charts so the result is
    consistent whether the market is open, closed, or pre-market.
    """
    try:
        end = date.today()
        start = end - timedelta(days=14)  # 14 calendar days → ~10 trading days
        resp = await client.get(
            f"{TRADIER_BASE_URL}/v1/markets/history",
            params={
                "symbol": etf,
                "interval": "daily",
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
            timeout=10,
        )
        resp.raise_for_status()
        history = resp.json().get("history") or {}
        day_list = history.get("day", [])
        if isinstance(day_list, dict):
            day_list = [day_list]
        if len(day_list) < 2:
            return etf, 0.0
        last_close = float(day_list[-1]["close"])
        prev_close = float(day_list[-2]["close"])
        pct = (last_close - prev_close) / prev_close * 100 if prev_close else 0.0
        return etf, round(pct, 2)
    except Exception:
        return etf, 0.0


@router.get('/sectors', response_model=list[SectorTile])
async def get_sectors() -> list[SectorTile]:
    async with httpx.AsyncClient(headers=_HEADERS) as client:
        results = await asyncio.gather(
            *[_fetch_etf_change(client, etf) for etf in SECTOR_ETFS],
            return_exceptions=True,
        )
    tiles = []
    for item in results:
        if isinstance(item, Exception):
            continue
        etf, pct = item
        tiles.append(SectorTile(
            key=etf,
            name=_ETF_NAME[etf],
            changePct=pct,
            status=_status(pct),
        ))
    return tiles
