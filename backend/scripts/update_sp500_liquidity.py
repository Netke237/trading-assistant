"""Fetch 20-day average dollar volume for every symbol in sp500.csv and write
the result back with updated 'liquidity' and 'sector' columns.

Sector names are normalised to match the canonical names used by the sector
heatmap (sectors.py _ETF_NAME).  Symbols still showing 'Unknown' after
normalisation are looked up individually via yfinance .info — this is slow
(~1–2 s per symbol) so it only runs for unknown symbols.

Run from repo root:
    python backend/scripts/update_sp500_liquidity.py
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

# Allow running from repo root: python backend/scripts/update_sp500_liquidity.py
sys.path.insert(0, str(Path(__file__).parent.parent))
from app.data.sector_names import NORMALIZE as CANONICAL_NAMES  # noqa: E402

import yfinance as yf

CSV_PATH = Path(__file__).parent.parent / "app" / "data" / "sp500.csv"
PERIOD = "1mo"   # ~20 trading days


def _yf_key(symbol: str) -> str:
    """Yahoo Finance uses hyphens for tickers that contain dots (BRK.B → BRK-B)."""
    return symbol.replace(".", "-")


def _calc_dollar_vol(data, key: str, single: bool) -> float:
    """Extract avg daily dollar volume (millions) from a yf.download DataFrame."""
    if single:
        closes  = data["Close"].dropna()
        volumes = data["Volume"].dropna()
    else:
        closes  = data[key]["Close"].dropna()
        volumes = data[key]["Volume"].dropna()
    if len(closes) == 0 or len(volumes) == 0:
        return 0.0
    return round(float((closes * volumes).mean()) / 1_000_000, 2)


def fetch_liquidity(symbols: list[str]) -> dict[str, float]:
    """Return {symbol: avg_daily_dollar_volume_millions} for all symbols."""
    yf_syms = [_yf_key(s) for s in symbols]
    sym_map  = {_yf_key(s): s for s in symbols}

    print(f"Downloading {PERIOD} OHLCV for {len(yf_syms)} symbols via yfinance…")
    data = yf.download(
        tickers=yf_syms,
        period=PERIOD,
        auto_adjust=True,
        progress=True,
        group_by="ticker",
    )

    result: dict[str, float] = {}
    is_single = len(yf_syms) == 1

    for yf_sym in yf_syms:
        orig = sym_map[yf_sym]
        try:
            result[orig] = _calc_dollar_vol(data, yf_sym, is_single)
        except Exception as exc:
            print(f"  WARN {orig}: {exc}", file=sys.stderr)
            result[orig] = 0.0

    # Retry any zeros individually (batch download can silently drop some tickers)
    zeros = [s for s, v in result.items() if v == 0.0]
    if zeros:
        print(f"\nRetrying {len(zeros)} zero-result symbols individually…")
        for orig in zeros:
            yf_sym = _yf_key(orig)
            try:
                d = yf.download(yf_sym, period=PERIOD, auto_adjust=True, progress=False)
                result[orig] = _calc_dollar_vol(d, yf_sym, True)
            except Exception:
                result[orig] = 0.0

    return result


def fetch_sectors_for_unknowns(symbols: list[str]) -> dict[str, str]:
    """
    Fetch sector via yfinance .info for each symbol.  Slow — only call this
    for symbols whose sector is still 'Unknown' after name normalisation.
    Returns {symbol: canonical_sector_name}.
    """
    result: dict[str, str] = {}
    total = len(symbols)
    for i, sym in enumerate(symbols, 1):
        print(f"  Fetching sector {i}/{total}: {sym}…", end="\r", flush=True)
        try:
            info = yf.Ticker(_yf_key(sym)).info
            raw = info.get("sector") or ""
            result[sym] = CANONICAL_NAMES.get(raw, "Unknown") if raw else "Unknown"
        except Exception:
            result[sym] = "Unknown"
        if i % 10 == 0:
            time.sleep(0.5)  # avoid rate-limiting
    print()  # newline after progress line
    return result


def main() -> None:
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8")))
    symbols = [r["symbol"] for r in rows]

    # ── 1. Normalise existing sector names ───────────────────────────────────
    for row in rows:
        raw = row.get("sector", "").strip()
        row["sector"] = CANONICAL_NAMES.get(raw, raw) if raw else "Unknown"

    # ── 2. Fetch sector for remaining unknowns ───────────────────────────────
    unknowns = [r["symbol"] for r in rows if r["sector"] == "Unknown"]
    if unknowns:
        print(f"\n{len(unknowns)} symbols have Unknown sector — fetching from yfinance…")
        fetched = fetch_sectors_for_unknowns(unknowns)
        sector_map = {r["symbol"]: r["sector"] for r in rows}
        sector_map.update(fetched)
        for row in rows:
            row["sector"] = sector_map[row["symbol"]]
    else:
        print("All sectors already populated — skipping yfinance sector fetch.")

    # ── 3. Fetch liquidity ───────────────────────────────────────────────────
    liquidity = fetch_liquidity(symbols)

    # ── 4. Write back ────────────────────────────────────────────────────────
    fieldnames = ["symbol", "sector", "liquidity"]
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            sym = row["symbol"]
            liq = liquidity.get(sym, 0.0)
            if liq == 0.0:
                print(f"  WARN {sym}: liquidity=0 (data unavailable)")
            writer.writerow({"symbol": sym, "sector": row["sector"], "liquidity": liq})

    written = sum(1 for r in rows if liquidity.get(r["symbol"], 0) > 0)
    still_unknown = sum(1 for r in rows if r["sector"] == "Unknown")
    print(f"\nDone. {written}/{len(rows)} symbols have liquidity > 0.")
    if still_unknown:
        print(f"WARNING: {still_unknown} symbols still have Unknown sector.")
    print(f"Updated: {CSV_PATH}")


if __name__ == "__main__":
    main()
