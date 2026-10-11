from __future__ import annotations

import csv
import functools
from pathlib import Path

from app.data.sector_names import NORMALIZE

_SP500_CSV = Path(__file__).parent / "sp500.csv"
# Built by scripts/fill_sectors.py (Wikipedia GICS for S&P names, yfinance for
# NDX-only names). Read only where sp500.csv says Unknown; the daily sp500.csv
# updater never writes this file.
_OVERRIDES_CSV = Path(__file__).parent / "sector_overrides.csv"

# Reverse of routers.sectors._ETF_NAME: canonical sector name → ETF symbol.
_NAME_TO_ETF: dict[str, str] = {
    "Technology": "XLK",
    "Comm. Services": "XLC",
    "Consumer Discretionary": "XLY",
    "Industrials": "XLI",
    "Financials": "XLF",
    "Consumer Staples": "XLP",
    "Health Care": "XLV",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Energy": "XLE",
}


@functools.lru_cache(maxsize=1)
def _symbol_to_raw_sector() -> dict[str, str]:
    """symbol -> raw sector: the sp500.csv sector unless it is Unknown, else the override."""
    out: dict[str, str] = {}
    for path in (_SP500_CSV, _OVERRIDES_CSV):
        try:
            with open(path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    sym = (row.get("symbol") or "").strip().upper()
                    sec = (row.get("sector") or "").strip()
                    if sym and sec and sec != "Unknown":
                        out.setdefault(sym, sec)
        except FileNotFoundError:
            pass
    return out


def sector_for_symbol(symbol: str) -> tuple[str | None, str | None]:
    """Return (canonical_sector_name, sector_etf) or (None, None) if unknown."""
    raw = _symbol_to_raw_sector().get(symbol.strip().upper())
    if not raw:
        return None, None
    name = NORMALIZE.get(raw, raw)
    return name, _NAME_TO_ETF.get(name)
