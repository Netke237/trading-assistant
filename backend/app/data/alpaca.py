"""Alpaca daily bars adapter — Governor-paced, multi-basis.

Data API endpoint is always https://data.alpaca.markets (same for paper and live).
Credentials are read from the credential store (alpaca_live preferred, alpaca_paper fallback).
All calls pass through the Governor so the 200 req/min bucket is enforced.
"""
from __future__ import annotations

import logging
import math
from datetime import date

import httpx

from app.services.credential_store import credential_store
from app.data.governor import get_governor, RateLimited

logger = logging.getLogger(__name__)

_DATA_BASE = "https://data.alpaca.markets"
_BARS_ENDPOINT = f"{_DATA_BASE}/v2/stocks/bars"


class AlpacaClient:
    """Thin wrapper around Alpaca v2 bars endpoint."""

    def __init__(self, key_id: str, secret_key: str, feed: str = "sip") -> None:
        self._headers = {
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret_key,
        }
        self.feed = feed

    async def _get_bars_page(
        self,
        symbols: list[str],
        adjustment: str,
        start: date,
        end: date,
        page_token: str | None,
        feed: str | None = None,
    ) -> dict:
        target_feed = feed if feed is not None else self.feed
        start_str = start.strftime("%Y-%m-%d") if hasattr(start, "strftime") else str(start)[:10]
        end_str = end.strftime("%Y-%m-%d") if hasattr(end, "strftime") else str(end)[:10]
        params: dict = {
            "symbols": ",".join(symbols),
            "timeframe": "1Day",
            "start": start_str,
            "end": end_str,
            "adjustment": adjustment,
            "feed": target_feed,
            "limit": 10_000,
        }
        if page_token:
            params["page_token"] = page_token
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(_BARS_ENDPOINT, headers=self._headers, params=params)
        if resp.status_code == 403 and params.get("feed") == "sip":
            logger.warning(
                "Alpaca SIP feed returned 403 Forbidden (subscription does not permit SIP); falling back to IEX: %s",
                resp.text,
            )
            params["feed"] = "iex"
            self.feed = "iex"
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(_BARS_ENDPOINT, headers=self._headers, params=params)
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", 1.0))
            raise RateLimited("429 from Alpaca", retry_after=retry_after)
        resp.raise_for_status()
        return resp.json()

    async def _fetch_all_pages(
        self,
        symbols: list[str],
        adjustment: str,
        start: date,
        end: date,
        feed: str | None = None,
    ) -> dict[str, list[dict]]:
        result: dict[str, list] = {}
        page_token: str | None = None
        while True:
            pt = page_token
            data = await get_governor().call(
                "alpaca",
                lambda _pt=pt, _feed=feed: self._get_bars_page(
                    symbols, adjustment, start, end, _pt, feed=_feed
                ),
            )
            for sym, bars in (data.get("bars") or {}).items():
                result.setdefault(sym, []).extend(bars)
            page_token = data.get("next_page_token")
            if not page_token:
                break
        return result

    async def fetch_raw(
        self, symbols: list[str], start: date, end: date, feed: str | None = None
    ) -> dict[str, list[dict]]:
        return await self._fetch_all_pages(symbols, "raw", start, end, feed=feed)

    async def fetch_adj(
        self, symbols: list[str], start: date, end: date, feed: str | None = None
    ) -> dict[str, list[dict]]:
        return await self._fetch_all_pages(symbols, "all", start, end, feed=feed)


async def get_alpaca_client(feed: str = "sip") -> AlpacaClient | None:
    """Return a configured AlpacaClient, or None if no keys are set."""
    for slot in ("alpaca_live", "alpaca_paper"):
        creds = credential_store.get(slot) or {}
        if creds.get("key_id") and creds.get("secret_key"):
            return AlpacaClient(
                key_id=creds["key_id"],
                secret_key=creds["secret_key"],
                feed=feed,
            )
    return None


def _normalize_bars(
    raw_bars_by_symbol: dict[str, list[dict]],
    adj_bars_by_symbol: dict[str, list[dict]],
    *,
    strict_adjustments: bool = False,
) -> dict[str, list[dict]]:
    """Merge raw + adjusted bar lists into the multi-basis format.

    Returns symbol -> list of bars with raw prices + adj_factor. Strict mode
    omits a whole symbol when any raw bar lacks valid adjustment evidence.
    """
    result: dict[str, list[dict]] = {}
    for sym, raw_list in raw_bars_by_symbol.items():
        if strict_adjustments:
            adj_map = {b["t"]: b.get("c") for b in adj_bars_by_symbol.get(sym, [])}
        else:
            adj_map = {b["t"]: float(b.get("c", 0) or 0) for b in adj_bars_by_symbol.get(sym, [])}
        bars: list[dict] = []
        for rb in raw_list:
            ts = rb["t"]
            if strict_adjustments:
                try:
                    raw_close = float(rb.get("c"))
                    adj_close = float(adj_map.get(ts))
                except (TypeError, ValueError, OverflowError):
                    break
                if not (
                    math.isfinite(raw_close) and raw_close > 0
                    and math.isfinite(adj_close) and adj_close > 0
                ):
                    break
            else:
                raw_close = float(rb.get("c", 0) or 0)
                adj_close = adj_map.get(ts, raw_close)
            adj_factor = round(adj_close / raw_close, 8) if raw_close != 0 else 1.0
            if strict_adjustments and (not math.isfinite(adj_factor) or adj_factor <= 0):
                break
            bars.append({
                "time":         ts[:10],
                "open":         round(float(rb.get("o", 0) or 0), 4),
                "high":         round(float(rb.get("h", 0) or 0), 4),
                "low":          round(float(rb.get("l", 0) or 0), 4),
                "close":        round(raw_close,                   4),
                "volume":       int(rb.get("v", 0) or 0),
                "adj_factor":   adj_factor,
                "split_factor": 1.0,
                "div_cash":     0.0,
                "source":       "alpaca",
            })
        else:
            result[sym] = bars
    return result


async def fetch_daily_bars_batch(
    symbols: list[str],
    start: date,
    end: date,
    client: AlpacaClient | None = None,
    *,
    strict_adjustments: bool = False,
    feed: str = "sip",
) -> dict[str, list[dict]]:
    """Fetch daily bars for multiple symbols from Alpaca.

    Returns symbol -> list of multi-basis bars. Symbols not returned by Alpaca
    are absent from the result dict. Strict mode also omits symbols with
    incomplete or invalid adjustment data.
    """
    if client is None:
        client = await get_alpaca_client(feed=feed)
    if client is None:
        return {}
    try:
        raw_bars = await client.fetch_raw(symbols, start, end, feed=feed)
        adj_bars = await client.fetch_adj(symbols, start, end, feed=feed)
        return _normalize_bars(raw_bars, adj_bars, strict_adjustments=strict_adjustments)
    except Exception as exc:
        logger.warning("Alpaca batch fetch failed: %s", exc)
        return {}


async def fetch_daily_bars_single(
    symbol: str,
    start: date,
    end: date,
    client: AlpacaClient | None = None,
    *,
    strict_adjustments: bool = False,
    feed: str = "sip",
) -> list[dict]:
    """Fetch daily bars for a single symbol from Alpaca."""
    result = await fetch_daily_bars_batch(
        [symbol],
        start,
        end,
        client=client,
        strict_adjustments=strict_adjustments,
        feed=feed,
    )
    return result.get(symbol, [])
