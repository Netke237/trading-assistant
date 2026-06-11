from __future__ import annotations

import os
from datetime import date

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
    """Return daily OHLCV bars for `symbol` between `start` and `end` (inclusive).

    Each dict: raw prices (open/high/low/close/volume) + multi-basis fields
    (adj_factor, split_factor, div_cash, source='tiingo').

    adj_factor = adjClose / close -- multiply raw_close x adj_factor to get
    the fully-adjusted close price.

    Returns [] on any error (network, auth, symbol not found).
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
            raw_close = float(bar.get("close", 0) or 0)
            adj_close = float(bar.get("adjClose", raw_close) or raw_close)
            adj_factor = round(adj_close / raw_close, 8) if raw_close != 0 else 1.0
            rows.append({
                "time":         bar["date"][:10],
                "open":         round(float(bar.get("open", 0) or 0),   4),
                "high":         round(float(bar.get("high", 0) or 0),   4),
                "low":          round(float(bar.get("low",  0) or 0),   4),
                "close":        round(raw_close,                         4),
                "volume":       int(bar.get("volume", 0) or 0),
                "adj_factor":   adj_factor,
                "split_factor": round(float(bar.get("splitFactor", 1.0) or 1.0), 8),
                "div_cash":     round(float(bar.get("divCash",      0.0) or 0.0), 4),
                "source":       "tiingo",
            })
        return rows
    except Exception:
        return []
