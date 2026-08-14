"""Fetch 20-day average dollar volume for every symbol in sp500.csv and write
the result back with updated 'liquidity' and 'sector' columns.

Sector names are normalised to match the canonical names used by the sector
heatmap (sectors.py _ETF_NAME).  Symbols still showing 'Unknown' after
normalisation are looked up individually via yfinance .info — this is slow
(~1–2 s per symbol) so it only runs for unknown symbols.

Run from repo root:
    python backend/scripts/update_sp500_liquidity.py [--dry-run] [--force]

    --dry-run   Fetch and report, but do not write sp500.csv.
    --force     Write even if the zero-liquidity fraction looks suspiciously
                high (data-quality sanity check would otherwise abort with a
                non-zero exit code). Use only when you've checked the WARN
                output above and are confident the low numbers are real.
"""
from __future__ import annotations

import argparse
import csv
import shutil
import sys
import time
from pathlib import Path

# Allow running from repo root: python backend/scripts/update_sp500_liquidity.py
sys.path.insert(0, str(Path(__file__).parent.parent))
from app.data.sector_names import NORMALIZE as CANONICAL_NAMES  # noqa: E402

import yfinance as yf

CSV_PATH = Path(__file__).parent.parent / "app" / "data" / "sp500.csv"
BACKUP_PATH = CSV_PATH.with_suffix(".csv.bak")
PERIOD = "1mo"   # ~20 trading days

# A human runs this script (unlike sp500_update_service.py's unattended nightly
# path), so the sanity check here surfaces as a loud warning + non-zero exit
# rather than silently aborting — the operator can inspect the WARN lines
# above and re-run with --force if the low liquidity numbers are legitimate.
ZERO_LIQUIDITY_WARN_THRESHOLD = 0.5


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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Fetch and report, but do not write sp500.csv.")
    parser.add_argument(
        "--force", action="store_true",
        help="Write even if the zero-liquidity fraction is suspiciously high.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

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

    for row in rows:
        sym = row["symbol"]
        if liquidity.get(sym, 0.0) == 0.0:
            print(f"  WARN {sym}: liquidity=0 (data unavailable)")

    written = sum(1 for r in rows if liquidity.get(r["symbol"], 0) > 0)
    still_unknown = sum(1 for r in rows if r["sector"] == "Unknown")
    zero_count = len(rows) - written
    zero_fraction = (zero_count / len(rows)) if rows else 0.0

    print(f"\n{written}/{len(rows)} symbols have liquidity > 0.")
    if still_unknown:
        print(f"WARNING: {still_unknown} symbols still have Unknown sector.")

    if zero_fraction > ZERO_LIQUIDITY_WARN_THRESHOLD and not args.force:
        print(
            f"\nERROR: {zero_count}/{len(rows)} symbols ({zero_fraction:.0%}) returned "
            f"liquidity=0 — this looks like a bad fetch (rate-limited, yfinance outage, "
            f"or schema change), not real data.\n"
            f"Refusing to overwrite {CSV_PATH} with this. Re-run with --force if you've "
            f"checked the WARN lines above and are confident this is legitimate.",
            file=sys.stderr,
        )
        return 1

    if args.dry_run:
        print(f"\nDry run — {CSV_PATH} was NOT written.")
        return 0

    # ── 4. Backup, then write ────────────────────────────────────────────────
    if CSV_PATH.exists():
        shutil.copy2(CSV_PATH, BACKUP_PATH)
        print(f"Backed up existing file to: {BACKUP_PATH}")

    fieldnames = ["symbol", "sector", "liquidity"]
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            sym = row["symbol"]
            writer.writerow({"symbol": sym, "sector": row["sector"], "liquidity": liquidity.get(sym, 0.0)})

    print(f"\nDone. Updated: {CSV_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
