"""Build backend/app/data/sector_overrides.csv: a sector for every symbol in the
app's S&P 500 list (sp500.csv) and its NDX 100 list (universe_presets.NDX100).

Sources (decision T1-H0A-SOURCES-2026-10-09, STOCKS-HORIZON-T1 H0a):

- S&P 500 names: the "GICS Sector" column of the Wikipedia page "List of S&P 500
  companies" (table id="constituents"), parsed with BeautifulSoup and the
  standard html.parser. source = "wikipedia-gics".
- NDX-only names (in NDX100, not in that table): yfinance `.info["sector"]`, the
  source update_sp500_liquidity.py already uses. source = "yfinance".

Every name is mapped through sector_names.NORMALIZE. A name that maps to nothing
canonical is an error naming it. A symbol neither source resolves is printed as
unmatched and never written as "Unknown".

sector_map.sector_for_symbol reads this file only where sp500.csv says Unknown;
the daily sp500.csv updater never writes it. Re-running is a manual refresh.

Run from repo root (needs internet):
    python backend/scripts/fill_sectors.py [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import date
from pathlib import Path
from typing import Callable

# Allow running from repo root: python backend/scripts/fill_sectors.py
sys.path.insert(0, str(Path(__file__).parent.parent))
from app.data.sector_names import NORMALIZE  # noqa: E402
from app.data.universe_presets import NDX100  # noqa: E402

import httpx  # noqa: E402
import yfinance as yf  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

DATA_DIR = Path(__file__).parent.parent / "app" / "data"
SP500_CSV = DATA_DIR / "sp500.csv"
OVERRIDES_CSV = DATA_DIR / "sector_overrides.csv"
WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
USER_AGENT = "bamendjou-trading-assistant/1.0 (https://github.com/Netke237/trading-assistant)"
FIELDNAMES = ["symbol", "sector", "source", "as_of"]


class UnknownSectorError(ValueError):
    """A source's sector name maps to no canonical sector."""


def csv_key(symbol: str) -> str:
    """The sp500.csv spelling: upper case, class shares with a dot (BRK-B → BRK.B)."""
    return symbol.strip().upper().replace("-", ".")


def _yf_key(symbol: str) -> str:
    """Yahoo Finance uses hyphens for tickers that contain dots (BRK.B → BRK-B),
    as update_sp500_liquidity._yf_key."""
    return symbol.replace(".", "-")


def canonical_sector(raw: str, symbol: str, source: str) -> str:
    name = NORMALIZE.get(raw.strip())
    if name is None:
        raise UnknownSectorError(
            f"{source}: sector {raw!r} for {symbol} maps to no canonical sector "
            f"(add it to app/data/sector_names.NORMALIZE)"
        )
    return name


def parse_sp500_constituents(html: str) -> dict[str, str]:
    """{csv symbol: canonical sector} from the Wikipedia constituents table."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="constituents")
    if table is None:
        raise ValueError('no table with id="constituents" in the S&P 500 page')
    rows = table.find_all("tr")
    header = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])] if rows else []
    try:
        sym_col = header.index("Symbol")
        sec_col = header.index("GICS Sector")
    except ValueError:
        raise ValueError(f'constituents table header lacks "Symbol"/"GICS Sector": {header}') from None
    out: dict[str, str] = {}
    for row in rows[1:]:
        cells = row.find_all("td")
        if len(cells) <= max(sym_col, sec_col):
            continue
        sym = csv_key(cells[sym_col].get_text(strip=True))
        if not sym:
            continue
        out[sym] = canonical_sector(cells[sec_col].get_text(strip=True), sym, "wikipedia-gics")
    if not out:
        raise ValueError("constituents table has no rows")
    return out


def yfinance_sector(symbol: str) -> str | None:
    """Canonical sector from yfinance `.info`, or None when the fetch fails or is empty."""
    try:
        raw = (yf.Ticker(_yf_key(symbol)).info or {}).get("sector") or ""
    except Exception as exc:  # network, delisted, rate limit
        print(f"  WARN yfinance {symbol}: {exc}", file=sys.stderr)
        return None
    if not raw.strip():
        return None
    return canonical_sector(raw, symbol, "yfinance")


def build_overrides(
    sp500_symbols: list[str],
    ndx_symbols: list[str],
    sp500_gics: dict[str, str],
    as_of: str,
    fetch_sector: Callable[[str], str | None] | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    """Rows for every resolvable symbol of sp500 ∪ ndx (sorted), and the unmatched symbols (sorted)."""
    fetch = fetch_sector or yfinance_sector
    ndx = {csv_key(s) for s in ndx_symbols}
    universe = sorted({csv_key(s) for s in sp500_symbols} | ndx)
    rows: list[dict[str, str]] = []
    unmatched: list[str] = []
    for sym in universe:
        if sym in sp500_gics:
            sector, source = sp500_gics[sym], "wikipedia-gics"
        elif sym in ndx:
            sector, source = fetch(sym), "yfinance"
        else:
            sector, source = None, ""
        if sector is None:
            unmatched.append(sym)
        else:
            rows.append({"symbol": sym, "sector": sector, "source": source, "as_of": as_of})
    return rows, unmatched


def fetch_wikipedia_html() -> str:
    resp = httpx.get(WIKIPEDIA_URL, headers={"User-Agent": USER_AGENT}, timeout=30.0, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def _read_sp500() -> dict[str, str]:
    with SP500_CSV.open(newline="", encoding="utf-8") as f:
        return {csv_key(r["symbol"]): (r.get("sector") or "").strip() for r in csv.DictReader(f) if r.get("symbol")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Fetch and report, but do not write the CSV.")
    args = parser.parse_args(argv)

    sp500 = _read_sp500()
    print(f"Fetching {WIKIPEDIA_URL} ...")
    gics = parse_sp500_constituents(fetch_wikipedia_html())
    print(f"  {len(gics)} constituents with a GICS sector.")

    def _paced(sym: str) -> str | None:
        time.sleep(0.3)  # avoid yfinance rate limiting
        return yfinance_sector(sym)

    rows, unmatched = build_overrides(list(sp500), NDX100, gics, date.today().isoformat(), _paced)

    by_source: dict[str, int] = {}
    for r in rows:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1
    print(f"\n{len(rows)} rows: " + ", ".join(f"{k}={v}" for k, v in sorted(by_source.items())))
    if unmatched:
        print(f"UNMATCHED ({len(unmatched)}; not written):")
        for sym in unmatched:
            csv_sector = sp500.get(sym)
            note = "not in sp500.csv" if csv_sector is None else f"sp500.csv sector: {csv_sector or 'empty'}"
            print(f"  {sym}  ({note})")
    else:
        print("UNMATCHED: none")

    if args.dry_run:
        print(f"\nDry run: {OVERRIDES_CSV} was NOT written.")
        return 0
    with OVERRIDES_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {OVERRIDES_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
