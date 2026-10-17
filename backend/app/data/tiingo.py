from __future__ import annotations

import asyncio
import os
import math
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from app.data.governor import get_governor, RateLimited, ProviderUnavailable
from app.data.provider_symbols import dash_class_ticker

TIINGO_BASE_URL = "https://api.tiingo.com"
TIINGO_TOKEN = os.getenv("TIINGO_API_TOKEN", "")


def _headers() -> dict:
    return {
        "Authorization": f"Token {TIINGO_TOKEN}",
        "Content-Type": "application/json",
    }


def _retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            seconds = (when - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) else None


async def fetch_historical_candles(
    symbol: str,
    start: date,
    end: date,
    *,
    strict_adjustments: bool = False,
) -> list[dict]:
    """Return daily OHLCV bars for `symbol` between `start` and `end` (inclusive).

    Each dict: raw prices (open/high/low/close/volume) + multi-basis fields
    (adj_factor, split_factor, div_cash, source='tiingo').

    adj_factor = adjClose / close -- multiply raw_close x adj_factor to get
    the fully-adjusted close price.

    Returns [] on invalid data or non-rate-limit HTTP errors. Governor pacing,
    symbol-budget refusals and exhausted HTTP 429 retries remain observable.
    Strict mode also rejects the whole reply if any row lacks finite positive
    raw and adjusted closes; missing adjusted prices are never synthesized.
    """
    symbol = dash_class_ticker(symbol)   # BRK.B -> BRK-B: Tiingo's spelling

    async def request():
        resp = await asyncio.to_thread(
            httpx.get,
            f"{TIINGO_BASE_URL}/tiingo/daily/{symbol}/prices",
            headers=_headers(),
            params={"startDate": start.isoformat(), "endDate": end.isoformat(),
                    "resampleFreq": "daily"},
            timeout=15,
        )
        if resp.status_code == 429:
            raise RateLimited("429 from Tiingo", _retry_after(resp.headers.get("Retry-After")))
        resp.raise_for_status()
        return resp.json()

    try:
        payload = await get_governor().call("tiingo", request, symbol=symbol)
        rows = []
        for bar in payload:
            raw_close = float(bar.get("close", 0) or 0)
            if strict_adjustments:
                adj_close = float(bar.get("adjClose"))
                if not (
                    math.isfinite(raw_close) and raw_close > 0
                    and math.isfinite(adj_close) and adj_close > 0
                ):
                    return []
            else:
                adj_close = float(bar.get("adjClose", raw_close) or raw_close)
            adj_factor = round(adj_close / raw_close, 8) if raw_close != 0 else 1.0
            if strict_adjustments and (not math.isfinite(adj_factor) or adj_factor <= 0):
                return []
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
    except (RateLimited, ProviderUnavailable):
        raise
    except Exception:
        return []
