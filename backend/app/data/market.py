from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Literal, Optional

import httpx

TRADIER_BASE_URL = os.getenv("TRADIER_BASE_URL", "https://api.tradier.com")
TRADIER_TOKEN = os.getenv("TRADIER_API_TOKEN", "")


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {TRADIER_TOKEN}",
        "Accept": "application/json",
    }


# ── Original synchronous functions (kept for backwards compat) ────────────────


def fetch_candles(symbol: str, bars: int = 120) -> list[dict]:
    """
    Returns up to `bars` daily OHLCV bars for `symbol`, newest last.
    Each dict: {time: str (YYYY-MM-DD), open, high, low, close: float, volume: int}
    Returns [] on any error.
    """
    try:
        end = date.today()
        start = end - timedelta(days=300)
        resp = httpx.get(
            f"{TRADIER_BASE_URL}/v1/markets/history",
            headers=_headers(),
            params={
                "symbol": symbol,
                "interval": "daily",
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
            timeout=10,
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


def fetch_price(symbol: str) -> Optional[float]:
    try:
        resp = httpx.get(
            f"{TRADIER_BASE_URL}/v1/markets/quotes",
            headers=_headers(),
            params={"symbols": symbol},
            timeout=10,
        )
        resp.raise_for_status()
        quote = resp.json().get("quotes", {}).get("quote", {})
        if isinstance(quote, list):
            quote = quote[0]
        last = quote.get("last") or quote.get("close")
        return round(float(last), 2) if last else None
    except Exception:
        return None


def fetch_option_chain(
    symbol: str,
    expiry: Optional[str] = None,
    option_type: Literal["C", "P"] = "C",
) -> list[dict]:
    try:
        exp_resp = httpx.get(
            f"{TRADIER_BASE_URL}/v1/markets/options/expirations",
            headers=_headers(),
            params={"symbol": symbol, "includeAllRoots": "true"},
            timeout=10,
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

        _today = date.today()
        if expiry and expiry in dates:
            target_exp = expiry
        else:
            target_exp = next(
                (d for d in dates if (date.fromisoformat(d) - _today).days >= 14),
                None,
            )
            if target_exp is None:
                return []

        chain_resp = httpx.get(
            f"{TRADIER_BASE_URL}/v1/markets/options/chains",
            headers=_headers(),
            params={
                "symbol": symbol,
                "expiration": target_exp,
                "greeks": "true",
            },
            timeout=10,
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
        seen: set[str] = set()
        return [c for c in result if not (c["id"] in seen or seen.add(c["id"]))]  # type: ignore[func-returns-value]
    except Exception:
        return []


def fetch_quotes(symbols: list[str]) -> dict[str, dict]:
    try:
        resp = httpx.get(
            f"{TRADIER_BASE_URL}/v1/markets/quotes",
            headers=_headers(),
            params={"symbols": ",".join(symbols)},
            timeout=10,
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
                result[sym] = {"last": float(last), "prevclose": float(prev)}
        return result
    except Exception:
        return {}


def fetch_earnings_date(symbol: str) -> Optional[date]:
    try:
        resp = httpx.get(
            f"{TRADIER_BASE_URL}/beta/markets/fundamentals/calendars",
            headers=_headers(),
            params={"symbols": symbol},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data or not isinstance(data, list):
            return None
        today = date.today()
        for entry in data:
            for result in entry.get("results", []):
                report_date_str = result.get("tables", {}).get("earnings", {}).get("report_date")
                if report_date_str:
                    try:
                        d = date.fromisoformat(report_date_str)
                        if d >= today:
                            return d
                    except ValueError:
                        pass
        return None
    except Exception:
        return None


def fetch_dividend_date(symbol: str) -> Optional[date]:
    try:
        resp = httpx.get(
            f"{TRADIER_BASE_URL}/beta/markets/fundamentals/calendars",
            headers=_headers(),
            params={"symbols": symbol},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data or not isinstance(data, list):
            return None
        today = date.today()
        for entry in data:
            for result in entry.get("results", []):
                ex_date_str = result.get("tables", {}).get("dividend", {}).get("ex_dividend_date")
                if ex_date_str:
                    try:
                        d = date.fromisoformat(ex_date_str)
                        if d >= today:
                            return d
                    except ValueError:
                        pass
        return None
    except Exception:
        return None


def fetch_company_name(symbol: str) -> Optional[str]:
    try:
        resp = httpx.get(
            f"{TRADIER_BASE_URL}/beta/markets/fundamentals/company",
            headers=_headers(),
            params={"symbols": symbol},
            timeout=10,
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


def fetch_news(symbols: list[str], limit: int = 20) -> list[dict]:
    try:
        resp = httpx.get(
            f"{TRADIER_BASE_URL}/v1/markets/news",
            headers=_headers(),
            params={"symbols": ",".join(symbols), "limit": limit},
            timeout=10,
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


# ── Async functions for the scan hot-path ─────────────────────────────────────


async def fetch_candles_async(
    client: httpx.AsyncClient, symbol: str, bars: int = 120
) -> list[dict]:
    """Async variant — uses the provided AsyncClient for connection reuse."""
    try:
        end = date.today()
        start = end - timedelta(days=300)
        resp = await client.get(
            f"{TRADIER_BASE_URL}/v1/markets/history",
            headers=_headers(),
            params={
                "symbol": symbol,
                "interval": "daily",
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
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


async def fetch_price_async(
    client: httpx.AsyncClient, symbol: str
) -> Optional[float]:
    """Async variant."""
    try:
        resp = await client.get(
            f"{TRADIER_BASE_URL}/v1/markets/quotes",
            headers=_headers(),
            params={"symbols": symbol},
        )
        resp.raise_for_status()
        quote = resp.json().get("quotes", {}).get("quote", {})
        if isinstance(quote, list):
            quote = quote[0]
        last = quote.get("last") or quote.get("close")
        return round(float(last), 2) if last else None
    except Exception:
        return None


async def fetch_option_chain_async(
    client: httpx.AsyncClient,
    symbol: str,
    expiry: Optional[str] = None,
    option_type: Literal["C", "P"] = "C",
) -> list[dict]:
    """Async variant."""
    try:
        exp_resp = await client.get(
            f"{TRADIER_BASE_URL}/v1/markets/options/expirations",
            headers=_headers(),
            params={"symbol": symbol, "includeAllRoots": "true"},
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

        _today = date.today()
        if expiry and expiry in dates:
            target_exp = expiry
        else:
            target_exp = next(
                (d for d in dates if (date.fromisoformat(d) - _today).days >= 14),
                None,
            )
            if target_exp is None:
                return []

        chain_resp = await client.get(
            f"{TRADIER_BASE_URL}/v1/markets/options/chains",
            headers=_headers(),
            params={
                "symbol": symbol,
                "expiration": target_exp,
                "greeks": "true",
            },
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
        seen: set[str] = set()
        return [c for c in result if not (c["id"] in seen or seen.add(c["id"]))]  # type: ignore[func-returns-value]
    except Exception:
        return []


async def fetch_company_name_async(
    client: httpx.AsyncClient, symbol: str
) -> Optional[str]:
    """Async variant."""
    try:
        resp = await client.get(
            f"{TRADIER_BASE_URL}/beta/markets/fundamentals/company",
            headers=_headers(),
            params={"symbols": symbol},
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


async def fetch_fundamentals_calendar(
    client: httpx.AsyncClient, symbol: str
) -> dict | None:
    """Fetch the full fundamentals calendar response once per symbol.

    Returns the raw JSON dict (the list element for this symbol) so the caller
    can extract both earnings and dividend dates without a second HTTP round-trip.
    """
    try:
        resp = await client.get(
            f"{TRADIER_BASE_URL}/beta/markets/fundamentals/calendars",
            headers=_headers(),
            params={"symbols": symbol},
        )
        resp.raise_for_status()
        data = resp.json()
        if not data or not isinstance(data, list):
            return None
        for entry in data:
            for result in entry.get("results", []):
                return result
        return None
    except Exception:
        return None


def _extract_earnings_date(fund_data: dict | None) -> Optional[date]:
    """Extract next earnings date from pre-fetched fundamentals data (sync, no I/O)."""
    if not fund_data:
        return None
    report_date_str = fund_data.get("tables", {}).get("earnings", {}).get("report_date")
    if not report_date_str:
        return None
    try:
        d = date.fromisoformat(report_date_str)
        if d >= date.today():
            return d
    except ValueError:
        pass
    return None


def _extract_dividend_date(fund_data: dict | None) -> Optional[date]:
    """Extract next ex-dividend date from pre-fetched fundamentals data (sync, no I/O)."""
    if not fund_data:
        return None
    ex_date_str = fund_data.get("tables", {}).get("dividend", {}).get("ex_dividend_date")
    if not ex_date_str:
        return None
    try:
        d = date.fromisoformat(ex_date_str)
        if d >= date.today():
            return d
    except ValueError:
        pass
    return None
