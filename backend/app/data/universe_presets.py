from __future__ import annotations
import csv
from pathlib import Path
from app.data.sector_names import NORMALIZE as _NORMALIZE_SECTOR

class PresetUnavailableError(ValueError):
    """Raised when a requested preset is not embedded in this deployment."""
    pass

# Maps sector ETF keys to the canonical sector names used in sp500.csv.
# Keys arrive as "SECTOR:XLK" from the frontend to avoid collision with real tickers.
SECTOR_ETF_TO_NAME: dict[str, str] = {
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

# NDX100 — embed directly (101 tickers as of 2025-Q1)
NDX100 = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "TSLA", "AVGO",
    "COST", "NFLX", "ASML", "AMD", "AZN", "TMUS", "PEP", "ADBE", "LIN", "QCOM",
    "INTC", "INTU", "AMAT", "TXN", "AMGN", "ISRG", "MU", "BKNG", "VRTX", "LRCX",
    "REGN", "KLAC", "MELI", "PANW", "SNPS", "CDNS", "CRWD", "ORLY", "MAR", "FTNT",
    "ABNB", "CTAS", "WDAY", "MRVL", "MNST", "PYPL", "NXPI", "KDP", "PCAR", "ROST",
    "CPRT", "ODFL", "AEP", "PAYX", "CHTR", "DXCM", "IDXX", "FANG", "FAST", "EXC",
    "VRSK", "GEHC", "BKR", "CTSH", "XEL", "BIIB", "GFS", "EA", "LULU", "CDW",
    "DLTR", "ZS", "ON", "ILMN", "WBD", "SGEN", "SBUX", "TEAM", "ANSS", "CEG",
    "TTWO", "ENPH", "DDOG", "ALGN", "LCID", "PDD", "RIVN", "OKTA", "SIRI", "MRNA",
    "ZM", "EBAY", "MTCH", "NTES", "JD", "MCHP", "HON", "CSCO", "ADSK", "GILD",
    "ADI", "CMCSA",
]

# DOW30 — embed directly
DOW30 = [
    "AAPL", "AMGN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS", "DOW",
    "GS", "HD", "HON", "IBM", "INTC", "JNJ", "JPM", "KO", "MCD", "MMM",
    "MRK", "MSFT", "NKE", "PG", "TRV", "UNH", "V", "VZ", "WBA", "WMT",
]

_SP500_CSV = Path(__file__).parent / "sp500.csv"


def _load_sp500() -> list[str]:
    if not _SP500_CSV.exists():
        raise PresetUnavailableError("SP500 CSV file not found at backend/app/data/sp500.csv")
    with open(_SP500_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [row["symbol"].strip() for row in reader if row.get("symbol", "").strip()]



def _load_sp500_by_sector(sector_name: str) -> list[str]:
    if not _SP500_CSV.exists():
        raise PresetUnavailableError("SP500 CSV file not found at backend/app/data/sp500.csv")
    symbols: list[str] = []
    with open(_SP500_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sym = row.get("symbol", "").strip()
            raw = row.get("sector", "").strip()
            canonical = _NORMALIZE_SECTOR.get(raw, raw)
            if sym and canonical == sector_name:
                symbols.append(sym)
    if not symbols:
        raise PresetUnavailableError(
            f"No symbols found for sector '{sector_name}' in sp500.csv. "
            "Run backend/scripts/update_sp500_liquidity.py to populate sector data."
        )
    return symbols


PRESET_UNIVERSES: dict[str, list[str] | None] = {
    "SP500": None,     # loaded lazily from CSV
    "NDX100": NDX100,
    "DOW30": DOW30,
    "RUSSELL2000": None,  # not available — raise error
    "STOXX600": None,     # not available — raise error
    "DAX40": None,        # not available — raise error
}

_UNAVAILABLE = {"RUSSELL2000", "STOXX600", "DAX40"}


def expand_universe(universe: list[str]) -> list[str]:
    """
    Expand any preset keys in `universe` to constituent ticker lists.
    Non-preset strings (individual tickers, custom symbols) pass through unchanged.
    Raises PresetUnavailableError if a preset is flagged as unavailable.
    """
    result: list[str] = []
    seen: set[str] = set()

    for item in universe:
        if item in _UNAVAILABLE:
            raise PresetUnavailableError(
                f"Preset {item} not available in this deployment. "
                f"Available presets: SP500, NDX100, DOW30."
            )
        if item.startswith("SECTOR:"):
            etf_key = item[7:]  # "SECTOR:XLK" → "XLK"
            sector_name = SECTOR_ETF_TO_NAME.get(etf_key)
            if sector_name is None:
                raise PresetUnavailableError(f"Unknown sector ETF key: {etf_key}")
            tickers = _load_sp500_by_sector(sector_name)
        elif item == "SP500":
            tickers = _load_sp500()
        elif item in PRESET_UNIVERSES and PRESET_UNIVERSES[item] is not None:
            tickers = PRESET_UNIVERSES[item]  # type: ignore[assignment]
        else:
            tickers = [item]  # individual ticker — pass through

        for t in tickers:
            if t not in seen:
                seen.add(t)
                result.append(t)

    return result
