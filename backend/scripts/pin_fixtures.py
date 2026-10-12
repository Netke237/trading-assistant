"""
One-shot fixture downloader. Run from repo root:

    cd backend
    python scripts/pin_fixtures.py

Writes backend/tests/fixtures/{SYMBOL}_candles.json for each symbol.
Requires TIINGO_API_TOKEN in environment.
"""
import asyncio
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.data.tiingo import fetch_historical_candles

SYMBOLS = ["AAPL", "MSFT", "NVDA", "SPY"]
END = date(2025, 4, 30)
START = END - timedelta(days=365)   # ~1 year of daily bars

OUT_DIR = Path(__file__).parent.parent / "tests" / "fixtures"
OUT_DIR.mkdir(parents=True, exist_ok=True)

async def main():
    for sym in SYMBOLS:
        bars = await fetch_historical_candles(sym, START, END)
        if not bars:
            print(f"WARNING: no data for {sym}")
            continue
        out_path = OUT_DIR / f"{sym}_candles.json"
        out_path.write_text(json.dumps(bars, indent=2))
        print(f"{sym}: {len(bars)} bars → {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
