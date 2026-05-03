from __future__ import annotations

import os
from datetime import date
from typing import Optional

import httpx

TIINGO_BASE_URL = "https://api.tiingo.com"
TIINGO_TOKEN = os.getenv("TIINGO_API_TOKEN", "")


def _headers() -> dict:
    return {
        "Authorization": f"Token {TIINGO_TOKEN}",
        "Content-Type": "application/json",
    }


def fetch_historical_candles(
    symbol: str,
    start: date,
    end: date,
) -> list[dict]:
    """
    Returns daily OHLCV bars for `symbol` between `start` and `end` (inclusive).
    Each dict: {time: str (YYYY-MM-DD), open, high, low, close: float, volume: int}
    Uses adjusted prices. Returns [] on any error.
    """
    try:
        resp = httpx.get(
            f"{TIINGO_BASE_URL}/tiingo/daily/{symbol}/prices",
            headers=_headers(),
            params={
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "resampleFreq": "daily",
            },
            timeout=15,
        )
        resp.raise_for_status()
        rows = []
        for bar in resp.json():
            rows.append({
                "time":   bar["date"][:10],
                "open":   round(float(bar["adjOpen"]),   2),
                "high":   round(float(bar["adjHigh"]),   2),
                "low":    round(float(bar["adjLow"]),    2),
                "close":  round(float(bar["adjClose"]),  2),
                "volume": int(bar["adjVolume"]),
            })
        return rows
    except Exception:
        return []
