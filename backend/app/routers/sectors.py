import asyncio
from datetime import date, timedelta

import httpx
from fastapi import APIRouter
from app.schemas import SectorTile
from app.data.market import get_tradier_creds, _fetch_daily_yf

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

def _tradier_headers() -> dict:
    tok, _ = get_tradier_creds()
    return {"Authorization": f"Bearer {tok}", "Accept": "application/json"}


def _status(pct: float) -> str:
    if pct >= 0.4:
        return "PASS"
    if pct <= -0.4:
        return "REJECT"
    return "CAUTION"


def _pct_from_closes(last: float, prev: float) -> float:
    return round((last - prev) / prev * 100, 2) if prev else 0.0


async def _fetch_etf_change(client: httpx.AsyncClient, etf: str) -> tuple[str, float]:
    """
    Fetch the two most recent daily closes for `etf` and return (etf, changePct).
    Tries Tradier first; falls back to yfinance when Tradier is unavailable or
    returns fewer than 2 bars.
    """
    # ── Tradier ──────────────────────────────────────────────────────────────
    try:
        end = date.today()
        start = end - timedelta(days=14)  # 14 calendar days → ~10 trading days
        resp = await client.get(
            f"{get_tradier_creds()[1]}/v1/markets/history",
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
        if len(day_list) >= 2:
            return etf, _pct_from_closes(float(day_list[-1]["close"]), float(day_list[-2]["close"]))
    except Exception:
        pass

    # ── yfinance fallback ────────────────────────────────────────────────────
    try:
        rows = await asyncio.to_thread(_fetch_daily_yf, etf)
        if len(rows) >= 2:
            return etf, _pct_from_closes(rows[-1]["close"], rows[-2]["close"])
    except Exception:
        pass

    return etf, 0.0


@router.get('/sectors', response_model=list[SectorTile])
async def get_sectors() -> list[SectorTile]:
    async with httpx.AsyncClient(headers=_tradier_headers()) as client:
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
