from __future__ import annotations

import asyncio
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


def fetch_candles(symbol: str, bars: int = 252) -> list[dict]:
    """
    Returns up to `bars` daily OHLCV bars for `symbol`, newest last.
    Each dict: {time: str (YYYY-MM-DD), open, high, low, close: float, volume: int}
    Returns [] on any error.
    """
    try:
        end = date.today()
        start = end - timedelta(days=365)
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
                (d for d in dates if (date.fromisoformat(d) - _today).days >= 21),
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


def _fetch_news_yf(symbols: list[str], limit: int = 20) -> list[dict]:
    """Fetch news for *symbols* using yfinance (free, no API key needed)."""
    try:
        import yfinance as yf
        from datetime import datetime, timezone as tz
    except Exception:
        return []

    seen: set[str] = set()
    articles: list[dict] = []
    sym_set = set(symbols)

    for sym in symbols:
        try:
            items = yf.Ticker(sym).news or []
        except Exception:
            items = []
        for i, item in enumerate(items):
            # yfinance >=0.2.52 wraps everything under a "content" key
            content = item.get("content") or item
            uid = item.get("id") or content.get("id") or f"{sym}_{i}"
            if uid in seen:
                continue
            seen.add(uid)
            pub = content.get("pubDate") or ""
            timestamp = pub if pub else ""
            provider = content.get("provider") or {}
            source = provider.get("displayName") or content.get("publisher", "")
            related = content.get("relatedTickers") or item.get("relatedTickers") or []
            article_sym = next((r for r in related if r in sym_set), sym)
            headline = content.get("title") or item.get("title", "")
            if not headline:
                continue
            articles.append({
                "id":        uid,
                "symbol":    article_sym,
                "headline":  headline,
                "source":    source,
                "timestamp": timestamp,
                "sentiment": "neutral",
            })

    articles.sort(key=lambda x: x["timestamp"], reverse=True)
    return articles[:limit]


def fetch_news(symbols: list[str], limit: int = 20) -> list[dict]:
    """
    Returns recent news headlines for the given symbols.
    Tries Tradier first (when TRADIER_API_TOKEN is set), then falls back to yfinance.
    Each item: {id, symbol, headline, source, timestamp, sentiment}
    """
    if TRADIER_TOKEN:
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
            if result:
                return result
        except Exception:
            pass
    return _fetch_news_yf(symbols, limit)


def fetch_earnings_events(symbols: list[str], days_ahead: int = 60) -> list[dict]:
    """
    Returns upcoming earnings dates for *symbols* within *days_ahead* days.
    Each item: {date: 'YYYY-MM-DD', symbol: str, label: 'Earnings', status: 'PENDING'}
    Uses yfinance — free, no API key needed.
    """
    try:
        import yfinance as yf
        from datetime import date as date_type, datetime
    except Exception:
        return []

    events: list[dict] = []
    today = date_type.today()

    for sym in symbols:
        try:
            cal = yf.Ticker(sym).calendar
            if not cal:
                continue
            dates = cal.get("Earnings Date")
            if not dates:
                continue
            raw = list(dates)[0] if hasattr(dates, "__iter__") else dates
            if hasattr(raw, "date"):
                d = raw.date()
            else:
                d = datetime.fromisoformat(str(raw)).date()
            delta = (d - today).days
            if delta < -1 or delta > days_ahead:
                continue
            events.append({
                "date":   d.isoformat(),
                "symbol": sym,
                "label":  "Earnings",
                "status": "PENDING",
            })
        except Exception:
            continue

    events.sort(key=lambda x: x["date"])
    return events


def fetch_dividend_events(symbols: list[str], days_ahead: int = 60) -> list[dict]:
    """
    Returns upcoming ex-dividend dates for *symbols* within *days_ahead* days.
    Each item: {date: 'YYYY-MM-DD', symbol: str, label: 'Dividend', status: 'PENDING'}
    Uses yfinance — free, no API key needed.
    """
    from datetime import date as date_type, timedelta
    today = date_type.today()
    cutoff = today + timedelta(days=days_ahead)
    events: list[dict] = []
    for sym in symbols:
        try:
            div_date = _dividend_date_yf(sym)
            if div_date is not None and today <= div_date <= cutoff:
                events.append({
                    "date":   div_date.isoformat(),
                    "symbol": sym,
                    "label":  "Dividend",
                    "status": "PENDING",
                })
        except Exception:
            continue
    events.sort(key=lambda x: x["date"])
    return events


def _compute_iv_bs(
    mid: float,
    S: float,
    K: float,
    dte: int,
    is_call: bool,
    r: float = 0.05,
) -> Optional[float]:
    """Implied volatility via Black-Scholes inversion (scipy brentq). Returns decimal or None."""
    try:
        from scipy.optimize import brentq
        from scipy.stats import norm as _norm
        import math as _math
    except ImportError:
        return None
    T = dte / 365.0
    if T <= 0 or mid <= 0 or S <= 0 or K <= 0:
        return None
    intrinsic = max(0.0, S - K) if is_call else max(0.0, K - S)
    if mid <= intrinsic * 1.001:
        return None

    def _bs(sigma: float) -> float:
        d1 = (_math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * _math.sqrt(T))
        d2 = d1 - sigma * _math.sqrt(T)
        if is_call:
            return S * _norm.cdf(d1) - K * _math.exp(-r * T) * _norm.cdf(d2) - mid
        return K * _math.exp(-r * T) * _norm.cdf(-d2) - S * _norm.cdf(-d1) - mid

    try:
        sigma = brentq(_bs, 1e-6, 20.0, xtol=1e-6, full_output=False)
        return round(float(sigma), 4)
    except (ValueError, RuntimeError):
        return None


def _earnings_date_yf(symbol: str) -> Optional[date]:
    """Next earnings date via yfinance (fallback when Tradier fundamentals unavailable)."""
    try:
        import yfinance as yf
        from datetime import datetime as _dt
        cal = yf.Ticker(symbol).calendar
        if not cal:
            return None
        dates = cal.get("Earnings Date")
        if not dates:
            return None
        raw = list(dates)[0] if hasattr(dates, "__iter__") else dates
        # yfinance 1.x returns datetime.date; older versions return datetime.datetime
        d: date = raw if isinstance(raw, date) and not isinstance(raw, _dt) else raw.date()
        return d if d >= date.today() else None
    except Exception:
        return None


def _dividend_date_yf(symbol: str) -> Optional[date]:
    """Next ex-dividend date via yfinance (fallback when Tradier fundamentals unavailable)."""
    try:
        import yfinance as yf
        from datetime import datetime as _dt
        cal = yf.Ticker(symbol).calendar
        if not cal:
            return None
        raw = cal.get("Ex-Dividend Date") or cal.get("Dividend Date")
        if raw is None:
            return None
        d: date = raw if isinstance(raw, date) and not isinstance(raw, _dt) else raw.date()
        return d if d >= date.today() else None
    except Exception:
        return None


# ── Async functions for the scan hot-path ─────────────────────────────────────


async def fetch_candles_async(
    client: httpx.AsyncClient, symbol: str, bars: int = 252
) -> list[dict]:
    """Async variant — uses the provided AsyncClient for connection reuse."""
    try:
        end = date.today()
        start = end - timedelta(days=365)
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
                (d for d in dates if (date.fromisoformat(d) - _today).days >= 21),
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


_market_cap_cache: dict[str, float | None] = {}


async def fetch_market_cap_async(symbol: str) -> float | None:
    """Return market cap in USD for *symbol*, or None if unavailable.

    Uses yfinance (which already appears in the project as a dividend fallback).
    Results are cached for the lifetime of the process so repeated scans don't
    re-fetch the same data.
    """
    if symbol in _market_cap_cache:
        return _market_cap_cache[symbol]
    result: float | None = None
    try:
        import yfinance as yf  # local import — optional dependency
        info = await asyncio.to_thread(lambda: yf.Ticker(symbol).info)
        cap = info.get("marketCap")
        if cap:
            result = float(cap)
    except Exception:
        pass
    _market_cap_cache[symbol] = result
    return result


async def fetch_contract_quote_async(
    client: httpx.AsyncClient,
    contract_id: str,
) -> dict | None:
    """Fetch live mid price + greeks for a single contract.

    contract_id format: SYMBOL|STRIKE|EXPIRY|C/P  (e.g. AAPL|185|2025-05-16|C)
    Returns a chain-entry dict with: price, delta, theta, ivRank, dte — or None.
    """
    try:
        parts = contract_id.split("|")
        if len(parts) != 4:
            return None
        symbol, strike_str, expiry, right = parts
        if right not in ("C", "P"):
            return None
        target_strike = int(float(strike_str))
        chain = await fetch_option_chain_async(
            client, symbol, expiry=expiry, option_type=right  # type: ignore[arg-type]
        )
        return next((c for c in chain if c["strike"] == target_strike), None)
    except Exception:
        return None


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
