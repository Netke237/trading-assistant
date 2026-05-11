from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta
from typing import Iterable as _Iterable
from typing import Literal, Optional

import httpx

TRADIER_BASE_URL = os.getenv("TRADIER_BASE_URL", "https://api.tradier.com")
TRADIER_TOKEN = os.getenv("TRADIER_API_TOKEN", "")


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {TRADIER_TOKEN}",
        "Accept": "application/json",
    }


# -- Per-symbol async fetchers (all take httpx.AsyncClient) --------------------

async def fetch_candles(client: httpx.AsyncClient, symbol: str, bars: int = 120) -> list[dict]:
    try:
        end = date.today()
        start = end - timedelta(days=200)
        resp = await client.get(
            f"{TRADIER_BASE_URL}/v1/markets/history",
            headers=_headers(),
            params={
                "symbol": symbol,
                "interval": "daily",
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        history = resp.json().get("history")
        if not history:
            return []
        day_list = history.get("day", [])
        if isinstance(day_list, dict):
            day_list = [day_list]
        rows = []
        for d in day_list[-bars:]:
            rows.append({
                "time": d["date"],
                "open": round(float(d["open"]), 2),
                "high": round(float(d["high"]), 2),
                "low": round(float(d["low"]), 2),
                "close": round(float(d["close"]), 2),
                "volume": int(d["volume"]),
            })
        return rows
    except Exception:
        return []


async def fetch_option_chain(
    client: httpx.AsyncClient,
    symbol: str,
    expiry: Optional[str] = None,
    option_type: Literal["C", "P"] = "C",
) -> list[dict]:
    try:
        exp_resp = await client.get(
            f"{TRADIER_BASE_URL}/v1/markets/options/expirations",
            headers=_headers(),
            params={"symbol": symbol, "includeAllRoots": "true"},
            timeout=10.0,
        )
        exp_resp.raise_for_status()
        expirations = exp_resp.json().get("expirations")
        if not expirations:
            return []
        dates = expirations.get("date", [])
        if isinstance(dates, str):
            dates = [dates]
        if not dates:
            return []

        target_exp = expiry if expiry in dates else dates[0]

        chain_resp = await client.get(
            f"{TRADIER_BASE_URL}/v1/markets/options/chains",
            headers=_headers(),
            params={
                "symbol": symbol,
                "expiration": target_exp,
                "greeks": "true",
            },
            timeout=10.0,
        )
        chain_resp.raise_for_status()
        options_data = chain_resp.json().get("options")
        if not options_data:
            return []
        contracts = options_data.get("option", [])
        if isinstance(contracts, dict):
            contracts = [contracts]

        today = date.today()
        try:
            exp_date = date.fromisoformat(target_exp)
        except ValueError:
            return []
        dte = max(0, (exp_date - today).days)

        tradier_type = "call" if option_type == "C" else "put"
        result = []
        for c in contracts:
            if c.get("option_type") != tradier_type:
                continue
            bid = float(c.get("bid") or 0)
            ask = float(c.get("ask") or 0)
            if ask <= 0:
                continue
            mid = round((bid + ask) / 2, 2)
            spread = round(ask - bid, 2)
            volume = int(c.get("volume") or 0)
            oi = int(c.get("open_interest") or 0)
            strike = float(c.get("strike") or 0)
            iv = float(c.get("implied_volatility") or 0)
            greeks = c.get("greeks") or {}
            delta = float(greeks.get("delta") or 0)
            theta = float(greeks.get("theta") or 0)
            result.append({
                "id": f"{symbol}|{int(strike)}|{target_exp}|{option_type}",
                "symbol": symbol,
                "strike": int(strike),
                "expiry": target_exp,
                "right": option_type,
                "dte": dte,
                "dteTotal": dte,
                "price": mid,
                "delta": round(delta, 4),
                "theta": round(theta, 4),
                "ivRank": int(round(iv * 100)),
                "ivPercentile": 0,
                "spread": spread,
                "volume": volume,
                "open_interest": oi,
                "score": 0,
            })
        return result
    except Exception:
        return []


async def fetch_quotes(client: httpx.AsyncClient, symbols: list[str]) -> dict[str, dict]:
    try:
        resp = await client.get(
            f"{TRADIER_BASE_URL}/v1/markets/quotes",
            headers=_headers(),
            params={"symbols": ",".join(symbols)},
            timeout=10.0,
        )
        resp.raise_for_status()
        quote_data = resp.json().get("quotes", {}).get("quote", [])
        if isinstance(quote_data, dict):
            quote_data = [quote_data]
        result = {}
        for q in quote_data:
            sym = q.get("symbol", "")
            last = q.get("last") or q.get("close") or 0
            prev = q.get("prevclose") or last
            if sym and last:
                result[sym] = {
                    "last": float(last),
                    "prevclose": float(prev),
                    "average_volume": int(q.get("average_volume") or 0),
                    "week_52_high": float(q.get("week_52_high") or 0),
                    "week_52_low": float(q.get("week_52_low") or 0),
                }
        return result
    except Exception:
        return {}


async def fetch_events(client: httpx.AsyncClient, symbol: str) -> dict[str, Optional[date]]:
    result: dict[str, Optional[date]] = {"earnings_date": None, "dividend_date": None}
    try:
        resp = await client.get(
            f"{TRADIER_BASE_URL}/beta/markets/fundamentals/calendars",
            headers=_headers(),
            params={"symbols": symbol},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data or not isinstance(data, list):
            return result
        today = date.today()
        for entry in data:
            for r in entry.get("results", []):
                earnings_str = r.get("tables", {}).get("earnings", {}).get("report_date")
                if earnings_str:
                    try:
                        d = date.fromisoformat(earnings_str)
                        if d >= today and result["earnings_date"] is None:
                            result["earnings_date"] = d
                    except ValueError:
                        pass
                div_str = r.get("tables", {}).get("dividend", {}).get("ex_dividend_date")
                if div_str:
                    try:
                        d = date.fromisoformat(div_str)
                        if d >= today and result["dividend_date"] is None:
                            result["dividend_date"] = d
                    except ValueError:
                        pass
        return result
    except Exception:
        return result


async def fetch_company_name(client: httpx.AsyncClient, symbol: str) -> Optional[str]:
    try:
        resp = await client.get(
            f"{TRADIER_BASE_URL}/beta/markets/fundamentals/company",
            headers=_headers(),
            params={"symbols": symbol},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data or not isinstance(data, list):
            return None
        for entry in data:
            for result in entry.get("results", []):
                name = result.get("tables", {}).get("company_profile", {}).get("company_name")
                if name:
                    return name
        return None
    except Exception:
        return None


async def fetch_news(client: httpx.AsyncClient, symbols: list[str], limit: int = 20) -> list[dict]:
    try:
        resp = await client.get(
            f"{TRADIER_BASE_URL}/v1/markets/news",
            headers=_headers(),
            params={"symbols": ",".join(symbols), "limit": limit},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        articles = data.get("news", {}).get("article", [])
        if isinstance(articles, dict):
            articles = [articles]
        result = []
        for i, a in enumerate(articles):
            art_symbols = a.get("symbols", "")
            symbol = art_symbols.split(",")[0].strip() if art_symbols else symbols[0]
            result.append({
                "id":        str(a.get("id", i)),
                "symbol":    symbol,
                "headline":  a.get("title", ""),
                "source":    a.get("source", ""),
                "timestamp": a.get("datetime", ""),
                "sentiment": "neutral",
            })
        return result
    except Exception:
        return []


# -- Backward-compatible wrappers (thin around fetch_events) -------------------

async def fetch_earnings_date(client: httpx.AsyncClient, symbol: str) -> Optional[date]:
    events = await fetch_events(client, symbol)
    return events["earnings_date"]


async def fetch_dividend_date(client: httpx.AsyncClient, symbol: str) -> Optional[date]:
    events = await fetch_events(client, symbol)
    return events["dividend_date"]


# -- Batch helpers -------------------------------------------------------------

def _chunked(lst: list, n: int) -> _Iterable:
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


async def fetch_batch_quotes(
    client: httpx.AsyncClient,
    symbols: list[str],
    semaphore: asyncio.Semaphore,
) -> dict[str, dict]:
    batches = list(_chunked(symbols, 50))
    async def _safe(batch):
        async with semaphore:
            try:
                return await fetch_quotes(client, batch)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    retry_after = int(e.response.headers.get("Retry-After", 10))
                    await asyncio.sleep(retry_after)
                    return await fetch_quotes(client, batch)
                raise
    results = await asyncio.gather(*[_safe(b) for b in batches], return_exceptions=True)
    merged: dict[str, dict] = {}
    for r in results:
        if isinstance(r, dict):
            merged.update(r)
    return merged


async def fetch_batch_candles(
    client: httpx.AsyncClient,
    symbols: list[str],
    semaphore: asyncio.Semaphore,
    bars: int = 120,
) -> dict[str, list[dict]]:
    async def _safe(sym):
        async with semaphore:
            try:
                return sym, await fetch_candles(client, sym, bars)
            except Exception:
                return sym, []
    results = await asyncio.gather(*[_safe(s) for s in symbols], return_exceptions=True)
    out: dict[str, list[dict]] = {}
    for item in results:
        if isinstance(item, tuple):
            sym, candles = item
            out[sym] = candles
    return out


# -- Pre-filter (quote data only -- no candles, no option chains) --------------

def _prefilter_score(q: dict) -> float:
    last = float(q.get("last", 0))
    high = float(q.get("week_52_high", 0))
    low = float(q.get("week_52_low", 0))
    if not all([last, high, low]) or high <= low:
        return 0.0

    range_pct = (last - low) / (high - low)

    if range_pct < 0.3:
        drift = 0.5 - (0.3 - range_pct)
    elif range_pct > 0.7:
        drift = 0.5 - (range_pct - 0.7)
    else:
        drift = 0.5 + (0.5 - abs(range_pct - 0.5))

    vol_score = min(1.0, float(q.get("average_volume", 0)) / 10_000_000)

    return (drift * 0.6) + (vol_score * 0.4)


def prefilter_candidates(
    quotes: dict[str, dict],
    filters: dict | None = None,
    max_candidates: int = 75,
) -> list[str]:
    scored: list[tuple[str, float]] = []
    for sym, q in quotes.items():
        last = q.get("last", 0)
        vol = q.get("average_volume", 0)
        high = q.get("week_52_high", 0)

        if not last or not high:
            continue
        if vol < 500_000:
            continue

        if filters:
            min_price = filters.get("min_price")
            max_price = filters.get("max_price")
            if min_price is not None and last < min_price:
                continue
            if max_price is not None and last > max_price:
                continue

        score = _prefilter_score(q)
        if score <= 0:
            continue
        scored.append((sym, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [sym for sym, _ in scored[:max_candidates]]
