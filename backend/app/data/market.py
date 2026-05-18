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


def fetch_candles(symbol: str, bars: int = 120) -> list[dict]:
    """
    Returns up to `bars` daily OHLCV bars for `symbol`, newest last.
    Each dict: {time: str (YYYY-MM-DD), open, high, low, close: float, volume: int}
    Returns [] on any error.
    """
    try:
        end = date.today()
        start = end - timedelta(days=200)  # ~200 calendar days covers 120+ trading days
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
    """
    Returns the latest price for `symbol`, or None on failure.
    """
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
    """
    Returns option contracts for `symbol`.
    option_type: "C" for calls (Bullish), "P" for puts (Bearish).
    Returns real greeks (delta, theta) from Tradier.
    Returns [] on any error.
    """
    try:
        # Step 1: get available expirations
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

        target_exp = expiry if expiry in dates else dates[0]

        # Step 2: fetch chain with greeks
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
                # ivRank: current IV as proxy — true 52-week IV rank needs historical options data
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


def fetch_quotes(symbols: list[str]) -> dict[str, dict]:
    """
    Batch-fetch latest quotes for a list of symbols.
    Returns dict keyed by symbol: {"last": float, "prevclose": float}
    Returns {} on any error.
    """
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
    """
    Returns the next earnings report date for `symbol`, or None if unavailable.
    Uses Tradier's beta fundamentals calendar endpoint — may return None if
    the account lacks fundamentals access.
    """
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
    """
    Returns the next ex-dividend date for `symbol`, or None if unavailable.
    Uses Tradier's beta fundamentals calendar endpoint.
    """
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
    """
    Returns the company name for `symbol`, or None if unavailable.
    Uses Tradier's beta fundamentals company endpoint.
    """
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
            uid = item.get("uuid", f"{sym}_{i}")
            if uid in seen:
                continue
            seen.add(uid)
            ts = item.get("providerPublishTime", 0)
            timestamp = (
                datetime.fromtimestamp(ts, tz=tz.utc).isoformat()
                if ts else ""
            )
            related = item.get("relatedTickers") or []
            article_sym = next((r for r in related if r in sym_set), sym)
            articles.append({
                "id":        uid,
                "symbol":    article_sym,
                "headline":  item.get("title", ""),
                "source":    item.get("publisher", ""),
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
