import asyncio
import csv
import time
from datetime import date, timedelta
from pathlib import Path

import httpx
from fastapi import APIRouter
from app.schemas import IndexChangeTile, SectorTile
from app.data.market import get_tradier_creds, _fetch_daily_yf, _tradier_get_async
from app.data.sector_names import NORMALIZE
# The ONE curated ETF set (app/data/etfs.py) owns these lists, so the D4
# earnings rule and the sector/index tiles cannot drift apart.
from app.data.etfs import INDEX_ETFS, SECTOR_ETFS

router = APIRouter(prefix='/api', tags=['trading'])

_ETF_NAME: dict[str, str] = {
    "XLK":  "Technology",
    "XLC":  "Comm. Services",
    "XLY":  "Consumer Discretionary",
    "XLI":  "Industrials",
    "XLF":  "Financials",
    "XLP":  "Consumer Staples",
    "XLV":  "Health Care",
    "XLB":  "Materials",
    "XLRE": "Real Estate",
    "XLU":  "Utilities",
    "XLE":  "Energy",
}

_INDEX_NAME: dict[str, str] = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq-100",
}

_SP500_CSV = Path(__file__).parent.parent / "data" / "sp500.csv"

# ── Sector symbol counts ──────────────────────────────────────────────────────
# Rebuilt automatically when sp500.csv's mtime changes (e.g. after the
# liquidity update script runs) — no server restart required.

_counts_cache: dict[str, int] = {}
_counts_mtime: float = 0.0


def _build_sector_counts() -> dict[str, int]:
    if not _SP500_CSV.exists():
        return {}
    counts: dict[str, int] = {}
    with open(_SP500_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            raw = row.get("sector", "").strip()
            s = NORMALIZE.get(raw, raw) if raw else ""
            if s and s != "Unknown":
                counts[s] = counts.get(s, 0) + 1
    return counts


def _get_sector_counts() -> dict[str, int]:
    global _counts_cache, _counts_mtime
    if not _SP500_CSV.exists():
        return {}
    mtime = _SP500_CSV.stat().st_mtime
    if mtime != _counts_mtime:
        _counts_cache = _build_sector_counts()
        _counts_mtime = mtime
    return _counts_cache


# ── Response caches (60 s TTL) ────────────────────────────────────────────────

_CACHE_TTL = 60.0

_sectors_cache: tuple[float, list[SectorTile]] | None = None
_index_cache: tuple[float, list[IndexChangeTile]] | None = None


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
        resp = await _tradier_get_async(
            client,
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
    global _sectors_cache
    now = time.monotonic()
    if _sectors_cache is not None and now - _sectors_cache[0] < _CACHE_TTL:
        return _sectors_cache[1]

    async with httpx.AsyncClient(headers=_tradier_headers()) as client:
        results = await asyncio.gather(
            *[_fetch_etf_change(client, etf) for etf in SECTOR_ETFS],
            return_exceptions=True,
        )
    counts = _get_sector_counts()
    tiles = []
    for item in results:
        if isinstance(item, Exception):
            continue
        etf, pct = item
        name = _ETF_NAME[etf]
        tiles.append(SectorTile(
            key=etf,
            name=name,
            changePct=pct,
            status=_status(pct),
            symbolCount=counts.get(name, 0),
        ))
    _sectors_cache = (now, tiles)
    return tiles


@router.get('/index-changes', response_model=list[IndexChangeTile])
async def get_index_changes() -> list[IndexChangeTile]:
    """Return daily changePct/status for SPY and QQQ — used to colour universe buttons."""
    global _index_cache
    now = time.monotonic()
    if _index_cache is not None and now - _index_cache[0] < _CACHE_TTL:
        return _index_cache[1]

    async with httpx.AsyncClient(headers=_tradier_headers()) as client:
        results = await asyncio.gather(
            *[_fetch_etf_change(client, etf) for etf in INDEX_ETFS],
            return_exceptions=True,
        )
    tiles = []
    for item in results:
        if isinstance(item, Exception):
            continue
        etf, pct = item
        tiles.append(IndexChangeTile(
            key=etf,
            name=_INDEX_NAME[etf],
            changePct=pct,
            status=_status(pct),
        ))
    _index_cache = (now, tiles)
    return tiles
