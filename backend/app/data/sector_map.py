from __future__ import annotations

import csv
import functools
from pathlib import Path

from app.data.sector_names import NORMALIZE

_SP500_CSV = Path(__file__).parent / "sp500.csv"

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
    out: dict[str, str] = {}
    try:
        with open(_SP500_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sym = (row.get("symbol") or "").strip().upper()
                sec = (row.get("sector") or "").strip()
                if sym and sec:
                    out[sym] = sec
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
