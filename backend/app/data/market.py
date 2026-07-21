from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

_EASTERN = ZoneInfo("America/New_York")
from typing import Literal, Optional

import httpx
import pandas as pd

from app.scoring.dte_window import DTE_WINDOW_TOLERANCE_DAYS

TRADIER_BASE_URL = os.getenv("TRADIER_BASE_URL", "https://api.tradier.com")
TRADIER_TOKEN = os.getenv("TRADIER_API_TOKEN", "")

logger = logging.getLogger(__name__)


def get_tradier_creds() -> tuple[str, str]:
    """Return (token, base_url) for the best available Tradier credential.

    Priority: credential store live → credential store paper → env-var fallback.
    Credentials saved via the Settings UI always take precedence over .env values.
    """
    try:
        from app.services.credential_store import credential_store
        live = credential_store.get("tradier_live") or {}
        if live.get("token", "").strip():
            return live["token"].strip(), "https://api.tradier.com"
        paper = credential_store.get("tradier_paper") or {}
        if paper.get("token", "").strip():
            return paper["token"].strip(), "https://sandbox.tradier.com"
    except Exception:
        pass
    return TRADIER_TOKEN, TRADIER_BASE_URL


def _tradier_base() -> str:
    return get_tradier_creds()[1]


# ── In-process caches ─────────────────────────────────────────────────────────
# Candles: daily bars don't change within a trading session — date-keyed cache.
_candles_cache: dict[str, tuple[list[dict], str]] = {}

# Company names: immutable; permanent cache for the process lifetime.
_company_cache: dict[str, str] = {}

# yfinance calendar: reset daily (overnight earnings updates).
_yf_cal_cache: dict[str, tuple[Optional[date], Optional[date]]] = {}
_yf_cal_cache_date: str = ""

# Yahoo Finance ticker equivalents for index symbols not served by Tradier quotes.
_YF_SYMBOL_MAP: dict[str, str] = {
    "SPX": "^GSPC",
    "NDX": "^NDX",
    "VIX": "^VIX",
    "RUT": "^RUT",
    "DJI": "^DJI",
}


def _headers() -> dict:
    token, _ = get_tradier_creds()
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


# ── Original synchronous functions (kept for backwards compat) ────────────────


def _fetch_daily_yf(symbol: str) -> list[dict]:
    """Daily OHLCV bars from yfinance (5-year window). Maps index tickers via _YF_SYMBOL_MAP.
    Suppresses yfinance stderr noise. Returns [] on any error.
    """
    try:
        import yfinance as yf
        yf_symbol = _YF_SYMBOL_MAP.get(symbol, symbol)
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            df = yf.download(yf_symbol, period="5y", interval="1d", progress=False)
        if df is None or df.empty:
            return []
        if isinstance(df.columns, pd.MultiIndex):
            df = df.droplevel(1, axis=1)
        return [
            {
                "time":   ts.strftime("%Y-%m-%d"),
                "open":   round(float(row["Open"]),   2),
                "high":   round(float(row["High"]),   2),
                "low":    round(float(row["Low"]),    2),
                "close":  round(float(row["Close"]),  2),
                "volume": 0 if pd.isna(row["Volume"]) else int(row["Volume"]),
            }
            for ts, row in df.iterrows()
        ]
    except Exception:
        return []


def fetch_candles(symbol: str, bars: int = 252) -> list[dict]:
    """
    Returns up to `bars` daily OHLCV bars for `symbol`, newest last.
    Each dict: {time: str (YYYY-MM-DD), open, high, low, close: float, volume: int}
    Tries Tradier first; falls back to yfinance (handles index tickers via _YF_SYMBOL_MAP).
    Results are cached per calendar day; cache is shared with fetch_candles_async.
    """
    cached = _candles_cache.get(symbol)
    if cached is not None:
        data, cached_date = cached
        if cached_date == date.today().isoformat() and len(data) >= bars:
            return data[-bars:]

    rows: list[dict] = []
    try:
        end = date.today()
        calendar_days = max(400, int(bars * 1.75))
        start = end - timedelta(days=calendar_days)
        resp = httpx.get(
            f"{_tradier_base()}/v1/markets/history",
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
        if history:
            day_list = history.get("day", [])
            if isinstance(day_list, dict):
                day_list = [day_list]
            rows = [
                {
                    "time":   d["date"],
                    "open":   round(float(d["open"]),   2),
                    "high":   round(float(d["high"]),   2),
                    "low":    round(float(d["low"]),    2),
                    "close":  round(float(d["close"]),  2),
                    "volume": int(d["volume"]),
                }
                for d in day_list
            ]
    except Exception:
        pass

    if not rows:
        rows = _fetch_daily_yf(symbol)
        if rows:
            logger.info("fetch_candles: yfinance fallback for %s (%d bars)", symbol, len(rows))

    if rows:
        _candles_cache[symbol] = (rows, date.today().isoformat())
    return rows[-bars:]


# Tradier timesales only supports these intraday intervals.
_TRADIER_INTRADAY_INTERVALS = {"1min", "5min", "15min"}

# Maps our internal interval names to yfinance interval codes.
_YF_INTERVAL_MAP: dict[str, str] = {
    "1min":  "1m",
    "5min":  "5m",
    "15min": "15m",
    "30min": "30m",
    "1h":    "1h",
    "4h":    "4h",    # fetched as 1h, resampled in _fetch_intraday_yf
    "daily": "1d",
    "weekly": "1wk",
}

# Maximum calendar days yfinance can return per interval.
_YF_MAX_DAYS: dict[str, int] = {
    "1m":  7,
    "5m":  55, "15m": 55, "30m": 55, "90m": 55,
    "1h":  730, "60m": 730,
    "4h":  730,   # fetched as 1h then resampled
    "1d":  3650,  # yfinance daily goes back ~10 years
    "1wk": 3650,
}

# The chart-facing / frontend interval spelling ('1D', '1W') doesn't match this
# module's own keys ('daily', 'weekly') — normalize before any lookup so both
# spellings resolve identically (yfinance interval code, day cap, IBKR eligibility).
_INTERVAL_ALIASES: dict[str, str] = {"1D": "daily", "1W": "weekly"}


def normalize_interval(interval: str) -> str:
    """Canonicalize chart-facing interval spellings to this module's internal
    convention, so lookup tables (_YF_INTERVAL_MAP, _YF_MAX_DAYS, IBKR eligibility)
    match regardless of which spelling the caller used."""
    return _INTERVAL_ALIASES.get(interval, interval)


def _resample_bars(bars: list[dict], target_minutes: int) -> list[dict]:
    """Aggregate OHLCV bars to a coarser interval via pandas resample."""
    if not bars:
        return []
    df = pd.DataFrame(bars)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("time")
    rule = f"{target_minutes}min"
    resampled = (
        df.resample(rule, origin="epoch")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna(subset=["open", "close"])
    )
    return [
        {
            "time":   int(ts.timestamp()),
            "open":   round(float(row["open"]),   4),
            "high":   round(float(row["high"]),   4),
            "low":    round(float(row["low"]),    4),
            "close":  round(float(row["close"]),  4),
            "volume": int(row["volume"]),
        }
        for ts, row in resampled.iterrows()
    ]


def _days_to_yf_period(days: int) -> str:
    """Convert a day count to a yfinance period string.

    Using `period=` avoids explicit start/end date arithmetic and works
    correctly regardless of the system clock being ahead of real-world time.
    """
    if days <= 7:   return "7d"
    if days <= 30:  return "1mo"
    if days <= 60:  return "60d"
    if days <= 90:  return "3mo"
    if days <= 180: return "6mo"
    if days <= 365: return "1y"
    if days <= 730: return "2y"
    return "5y"


def _fetch_intraday_yf(symbol: str, interval: str = "15m", days: int = 55) -> list[dict]:
    """
    Fetch intraday bars from yfinance.
    - 15m / 5m / 30m: up to 55 calendar days
    - 1h / 60m: up to 730 calendar days (2 years)
    - 4h: fetched as 1h then resampled to 240-min bars (730 cal. days)
    - 1m: up to 7 calendar days

    Uses period= parameter (not explicit start/end) to avoid failures when
    the system clock is ahead of yfinance servers.
    """
    if interval == "4h":
        rows_1h = _fetch_intraday_yf(symbol, interval="1h", days=min(days, 730))
        return _resample_bars(rows_1h, target_minutes=240)

    max_days = _YF_MAX_DAYS.get(interval, 55)
    capped_days = min(days, max_days)
    period = _days_to_yf_period(capped_days)
    try:
        import yfinance as yf
        _stderr_buf = io.StringIO()
        with contextlib.redirect_stderr(_stderr_buf):
            df = yf.download(
                symbol,
                period=period,
                interval=interval,
                progress=False,
            )
        _yf_stderr = _stderr_buf.getvalue().strip()
        if _yf_stderr:
            logger.debug("yfinance stderr for %s [%s]: %s", symbol, interval, _yf_stderr[:200])
        if df is None or df.empty:
            return []
        # yfinance ≥1.1 returns MultiIndex columns (Price, Ticker) for single-ticker downloads
        if isinstance(df.columns, pd.MultiIndex):
            df = df.droplevel(1, axis=1)
        return [
            {
                "time":   int(ts.timestamp()),
                "open":   round(float(row["Open"]),   4),
                "high":   round(float(row["High"]),   4),
                "low":    round(float(row["Low"]),    4),
                "close":  round(float(row["Close"]),  4),
                "volume": int(row["Volume"]),
            }
            for ts, row in df.iterrows()
        ]
    except Exception:
        return []


def fetch_intraday_candles(
    symbol: str,
    interval: str = "15min",
    days: int = 55,
) -> list[dict]:
    """
    Returns intraday OHLCV bars merged from Tradier + yfinance.

    Expected history per interval:
      15min → ~60 calendar days  (Tradier ≤55d + yfinance ≤55d, overlap removed)
      1h    → ~730 calendar days (yfinance only; Tradier doesn't support 1h timesales)
      4h    → ~730 calendar days (yfinance 1h resampled to 4h; Tradier unsupported)
      1min  → ~7 calendar days   (yfinance cap)

    Tradier bars take precedence on timestamp conflicts (more accurate for recent data).
    Returns [] only when both sources fail.
    """
    interval = normalize_interval(interval)
    logger.info("Fetching intraday %s %s days=%s", symbol, interval, days)

    # ── Tradier (only for supported intervals) ───────────────────────────────
    tradier_rows: list[dict] = []
    if get_tradier_creds()[0] and interval in _TRADIER_INTRADAY_INTERVALS:
        try:
            end = date.today()
            start = end - timedelta(days=min(days, 55))
            resp = httpx.get(
                f"{_tradier_base()}/v1/markets/timesales",
                headers=_headers(),
                params={
                    "symbol":         symbol,
                    "interval":       interval,
                    "start":          start.isoformat(),
                    "end":            end.isoformat(),
                    "session_filter": "all",
                },
                timeout=30,
            )
            resp.raise_for_status()
            series = resp.json().get("series")
            if series:
                data = series.get("data", [])
                if isinstance(data, dict):
                    data = [data]
                for d in data:
                    raw_time = d.get("time", "")
                    try:
                        dt = datetime.fromisoformat(raw_time)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=_EASTERN)
                        unix_ts = int(dt.timestamp())
                    except (ValueError, TypeError):
                        unix_ts = 0
                    tradier_rows.append({
                        "time":   unix_ts,
                        "open":   round(float(d.get("open",   0)), 4),
                        "high":   round(float(d.get("high",   0)), 4),
                        "low":    round(float(d.get("low",    0)), 4),
                        "close":  round(float(d.get("close",  0)), 4),
                        "volume": int(d.get("volume", 0)),
                    })
            if tradier_rows:
                logger.info("Tradier returned %d bars for %s", len(tradier_rows), symbol)
            else:
                logger.warning("Tradier returned 0 bars for %s", symbol)
        except Exception as exc:
            logger.warning("Tradier intraday fetch failed for %s: %s", symbol, exc)

    # ── IBKR (for 1h/4h/daily/weekly and any interval beyond yfinance's window) ──
    ibkr_rows: list[dict] = []
    _ibkr_intervals = {"1h", "4h", "daily", "weekly"}
    if interval in _ibkr_intervals:
        try:
            from .ibkr import fetch_intraday_ibkr
            ibkr_rows = fetch_intraday_ibkr(symbol, interval, days)
            if ibkr_rows:
                logger.info("IBKR returned %d bars for %s [interval=%s]", len(ibkr_rows), symbol, interval)
            else:
                logger.debug("IBKR returned 0 bars for %s [interval=%s]", symbol, interval)
        except Exception as exc:
            logger.debug("IBKR fetch skipped for %s: %s", symbol, exc)

    # ── yfinance (always; extended range for 1h/4h/daily/weekly) ─────────────
    yf_interval = _YF_INTERVAL_MAP.get(interval, interval.replace("min", "m"))
    yf_max = _YF_MAX_DAYS.get(yf_interval, 55)
    yf_rows = _fetch_intraday_yf(symbol, interval=yf_interval, days=min(days, yf_max))
    if yf_rows:
        logger.info("yfinance returned %d bars for %s", len(yf_rows), symbol)
    else:
        logger.warning("yfinance returned 0 bars for %s [interval=%s]", symbol, yf_interval)

    # ── Merge: yfinance baseline → IBKR → Tradier (highest priority) ─────────
    if not tradier_rows and not ibkr_rows and not yf_rows:
        logger.warning("No intraday data from any source for %s", symbol)
        return []

    merged: dict[int, dict] = {}
    if yf_rows:
        merged.update({b["time"]: b for b in yf_rows})
    if ibkr_rows:
        merged.update({b["time"]: b for b in ibkr_rows})   # IBKR overwrites yf
    if tradier_rows:
        merged.update({b["time"]: b for b in tradier_rows})  # Tradier overwrites all

    result = sorted(merged.values(), key=lambda b: b["time"])
    logger.info(
        "Merged %d Tradier + %d IBKR + %d yf → %d total bars for %s",
        len(tradier_rows), len(ibkr_rows), len(yf_rows), len(result), symbol,
    )
    return result


def fetch_price(symbol: str) -> Optional[float]:
    try:
        resp = httpx.get(
            f"{_tradier_base()}/v1/markets/quotes",
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
        pass

    # yfinance fallback — serve from daily cache if warm, otherwise use fast_info.
    cached = _candles_cache.get(symbol)
    if cached is not None:
        data, cached_date = cached
        if cached_date == date.today().isoformat() and data:
            return data[-1]["close"]
    try:
        import yfinance as yf
        yf_symbol = _YF_SYMBOL_MAP.get(symbol, symbol)
        fi = yf.Ticker(yf_symbol).fast_info
        price = fi.last_price or fi.previous_close
        return round(float(price), 2) if price else None
    except Exception:
        return None


def _nearest_expiration_in_window(
    dates: list[str], bounds: tuple[int, int], today: date,
    *, tolerance_days: int = DTE_WINDOW_TOLERANCE_DAYS,
) -> Optional[str]:
    """Return the expiration date closest to the centre of [min_dte, max_dte].

    Monthly option cycles are spaced ~30-35 days apart; a fixed-width window
    derived from a holding period can straddle a real expiration by a handful
    of days (e.g. a 180-210d window missing a listed 179d and 214d expiry on
    either side) even though either would serve the intended hold just as
    well. If nothing falls strictly inside the window, retry against
    [lo - tolerance_days, hi + tolerance_days] before giving up.

    Returns None if no available expiration falls inside the window or its
    tolerance margin.
    """
    lo, hi = bounds
    centre = (lo + hi) / 2

    def _dte(d: str) -> int:
        return (date.fromisoformat(d) - today).days

    in_window = [d for d in dates if lo <= _dte(d) <= hi]
    if in_window:
        return min(in_window, key=lambda d: abs(_dte(d) - centre))

    near = [d for d in dates if (lo - tolerance_days) <= _dte(d) <= (hi + tolerance_days)]
    if not near:
        return None
    return min(near, key=lambda d: abs(_dte(d) - centre))


def fetch_option_chain(
    symbol: str,
    expiry: Optional[str] = None,
    option_type: Literal["C", "P"] = "C",
    dte_bounds: Optional[tuple[int, int]] = None,
) -> list[dict]:
    try:
        exp_resp = httpx.get(
            f"{_tradier_base()}/v1/markets/options/expirations",
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
        elif dte_bounds is not None:
            target_exp = _nearest_expiration_in_window(dates, dte_bounds, _today)
            if target_exp is None:
                return []
        else:
            target_exp = next(
                (d for d in dates if (date.fromisoformat(d) - _today).days >= 21),
                None,
            )
            if target_exp is None:
                return []

        chain_resp = httpx.get(
            f"{_tradier_base()}/v1/markets/options/chains",
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
            last = float(c.get("last") or 0)
            # Outside market hours Tradier returns bid=0, ask=0 — fall back to last price.
            if ask > 0:
                mid = round((bid + ask) / 2, 2)
                spread = round(ask - bid, 2)
            elif last > 0:
                mid = round(last, 2)
                spread = 0.0
            else:
                continue
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
        # Enrich with IBKR IV Rank/Percentile if available
        _ibkr_iv = None
        try:
            from .ibkr import fetch_iv_metrics_ibkr
            _ibkr_iv = fetch_iv_metrics_ibkr(symbol)
            if _ibkr_iv:
                for c in result:
                    c["ivRank"] = round(_ibkr_iv["ivRank"], 1)
                    c["ivPercentile"] = round(_ibkr_iv["ivPercentile"], 1)
        except Exception:
            pass  # keep existing fallback values

        # IBKR unavailable — try tastytrade's real IV Rank/Percentile before
        # falling back to the raw-IV-as-proxy values set above.
        if not _ibkr_iv:
            try:
                from .tastytrade_iv import fetch_iv_metrics_tastytrade
                _tasty_iv = fetch_iv_metrics_tastytrade([symbol])
                if _tasty_iv and symbol in _tasty_iv:
                    for c in result:
                        c["ivRank"] = round(_tasty_iv[symbol]["ivRank"], 1)
                        c["ivPercentile"] = round(_tasty_iv[symbol]["ivPercentile"], 1)
            except Exception:
                pass  # keep existing fallback values

        zero_iv = sum(1 for c in result if c["ivRank"] == 0)
        if zero_iv > len(result) * 0.5 and result:
            yf_iv = _yf_iv_for_chain(symbol, target_exp, option_type == "C")
            for c in result:
                if c["ivRank"] == 0:
                    yf_val = yf_iv.get(float(c["strike"]))
                    if yf_val:
                        c["ivRank"] = int(round(yf_val * 100))
                        c["implied_volatility"] = round(yf_val, 4)

        seen: set[str] = set()
        return [c for c in result if not (c["id"] in seen or seen.add(c["id"]))]  # type: ignore[func-returns-value]
    except Exception:
        return []


def fetch_quotes(symbols: list[str]) -> dict[str, dict]:
    try:
        resp = httpx.get(
            f"{_tradier_base()}/v1/markets/quotes",
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
            f"{_tradier_base()}/beta/markets/fundamentals/calendars",
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
            f"{_tradier_base()}/beta/markets/fundamentals/calendars",
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
            f"{_tradier_base()}/beta/markets/fundamentals/company",
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
    if get_tradier_creds()[0]:
        try:
            resp = httpx.get(
                f"{_tradier_base()}/v1/markets/news",
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


def _yf_iv_for_chain(symbol: str, expiry: str, is_call: bool) -> dict[float, float]:
    """Return strike → IV map from yfinance for a given expiry. Empty dict on any failure."""
    try:
        import yfinance as yf
        chain = yf.Ticker(symbol).option_chain(expiry)
        df = chain.calls if is_call else chain.puts
        return {float(row["strike"]): float(row["impliedVolatility"]) for _, row in df.iterrows()}
    except Exception:
        return {}


def _calendar_dates_yf(symbol: str) -> tuple[Optional[date], Optional[date]]:
    """Fetch earnings + dividend dates in ONE yfinance calendar call (avoids two round-trips)."""
    try:
        import yfinance as yf
        from datetime import datetime as _dt
        today = date.today()
        cal = yf.Ticker(symbol).calendar
        if not cal:
            return None, None

        # Earnings
        earn: Optional[date] = None
        dates = cal.get("Earnings Date")
        if dates:
            raw = list(dates)[0] if hasattr(dates, "__iter__") else dates
            d: date = raw if isinstance(raw, date) and not isinstance(raw, _dt) else raw.date()
            earn = d if d >= today else None

        # Dividend
        div: Optional[date] = None
        raw_div = cal.get("Ex-Dividend Date") or cal.get("Dividend Date")
        if raw_div is not None:
            d2: date = raw_div if isinstance(raw_div, date) and not isinstance(raw_div, _dt) else raw_div.date()
            div = d2 if d2 >= today else None

        return earn, div
    except Exception:
        return None, None


# Keep single-date shims so existing callers outside the scan hot-path still work
def _earnings_date_yf(symbol: str) -> Optional[date]:
    return _calendar_dates_yf(symbol)[0]


def _dividend_date_yf(symbol: str) -> Optional[date]:
    return _calendar_dates_yf(symbol)[1]


# Limits concurrent Yahoo Finance calendar fetches — prevents rate-limiting during batch scans
_YF_CALENDAR_SEM: asyncio.Semaphore | None = None


def _get_yf_sem() -> asyncio.Semaphore:
    global _YF_CALENDAR_SEM
    if _YF_CALENDAR_SEM is None:
        _YF_CALENDAR_SEM = asyncio.Semaphore(5)
    return _YF_CALENDAR_SEM


async def fetch_calendar_dates_async(symbol: str) -> tuple[Optional[date], Optional[date]]:
    """Rate-limited async wrapper — fetches earnings + dividend in one yfinance call.
    Results are cached per calendar day; dates don't change within a trading session."""
    global _yf_cal_cache_date, _yf_cal_cache
    today = date.today().isoformat()
    if today != _yf_cal_cache_date:
        _yf_cal_cache_date = today
        _yf_cal_cache = {}

    if symbol in _yf_cal_cache:
        return _yf_cal_cache[symbol]

    async with _get_yf_sem():
        # Double-check after acquiring semaphore — another coroutine may have populated it.
        if symbol in _yf_cal_cache:
            return _yf_cal_cache[symbol]
        result = await asyncio.to_thread(_calendar_dates_yf, symbol)

    _yf_cal_cache[symbol] = result
    return result


# ── Async functions for the scan hot-path ─────────────────────────────────────


async def fetch_candles_async(
    client: httpx.AsyncClient, symbol: str, bars: int = 252
) -> list[dict]:
    """Async variant — uses the provided AsyncClient for connection reuse.
    Results are cached for the current calendar day (daily bars don't change intraday).
    Falls back to yfinance when Tradier is unavailable."""
    cached = _candles_cache.get(symbol)
    if cached is not None:
        data, cached_date = cached
        if cached_date == date.today().isoformat():
            return data

    rows: list[dict] = []
    try:
        end = date.today()
        calendar_days = max(400, int(bars * 1.75))
        start = end - timedelta(days=calendar_days)
        resp = await client.get(
            f"{_tradier_base()}/v1/markets/history",
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
        if history:
            day_list = history.get("day", [])
            if isinstance(day_list, dict):
                day_list = [day_list]
            for d in day_list[-bars:]:
                rows.append({
                    "time": d["date"],
                    "open": round(float(d["open"]), 2),
                    "high": round(float(d["high"]), 2),
                    "low": round(float(d["low"]), 2),
                    "close": round(float(d["close"]), 2),
                    "volume": int(d["volume"]),
                })
    except Exception:
        pass

    if not rows:
        rows = await asyncio.to_thread(_fetch_daily_yf, symbol)
        if rows:
            logger.info("fetch_candles_async: yfinance fallback for %s (%d bars)", symbol, len(rows))

    if rows:
        _candles_cache[symbol] = (rows, date.today().isoformat())
    return rows


# Lazy semaphore for candle pre-warm — wider than scan concurrency since candles are the
# heaviest single call and pre-warming happens before the scan, not during it.
_PREWARM_SEM: asyncio.Semaphore | None = None


def _get_prewarm_sem() -> asyncio.Semaphore:
    global _PREWARM_SEM
    if _PREWARM_SEM is None:
        _PREWARM_SEM = asyncio.Semaphore(15)
    return _PREWARM_SEM


async def prewarm_candles_async(symbols: list[str]) -> int:
    """Pre-populate the candle cache for all symbols before the scan runs.

    Returns the count of symbols for which candles were successfully fetched.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        sem = _get_prewarm_sem()

        async def _one(symbol: str) -> bool:
            async with sem:
                rows = await fetch_candles_async(client, symbol)
                return bool(rows)

        results = await asyncio.gather(*(_one(s) for s in symbols), return_exceptions=True)
    return sum(1 for r in results if r is True)


async def fetch_price_async(
    client: httpx.AsyncClient, symbol: str
) -> Optional[float]:
    """Async variant. Falls back to yfinance when Tradier is unavailable."""
    try:
        resp = await client.get(
            f"{_tradier_base()}/v1/markets/quotes",
            headers=_headers(),
            params={"symbols": symbol},
        )
        resp.raise_for_status()
        quote = resp.json().get("quotes", {}).get("quote", {})
        if isinstance(quote, list):
            quote = quote[0]
        last = quote.get("last") or quote.get("close")
        if last:
            return round(float(last), 2)
    except Exception:
        pass

    # yfinance fallback — serve from daily cache if warm, otherwise use fast_info.
    cached = _candles_cache.get(symbol)
    if cached is not None:
        data, cached_date = cached
        if cached_date == date.today().isoformat() and data:
            return data[-1]["close"]
    try:
        import yfinance as yf
        yf_symbol = _YF_SYMBOL_MAP.get(symbol, symbol)
        fi = await asyncio.to_thread(lambda: yf.Ticker(yf_symbol).fast_info)
        price = fi.last_price or fi.previous_close
        return round(float(price), 2) if price else None
    except Exception:
        return None


async def fetch_option_chain_async(
    client: httpx.AsyncClient,
    symbol: str,
    expiry: Optional[str] = None,
    option_type: Literal["C", "P"] = "C",
    dte_bounds: Optional[tuple[int, int]] = None,
) -> list[dict]:
    """Async variant."""
    try:
        exp_resp = await client.get(
            f"{_tradier_base()}/v1/markets/options/expirations",
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
        elif dte_bounds is not None:
            target_exp = _nearest_expiration_in_window(dates, dte_bounds, _today)
            if target_exp is None:
                return []
        else:
            target_exp = next(
                (d for d in dates if (date.fromisoformat(d) - _today).days >= 21),
                None,
            )
            if target_exp is None:
                return []

        chain_resp = await client.get(
            f"{_tradier_base()}/v1/markets/options/chains",
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
            last = float(c.get("last") or 0)
            # Outside market hours Tradier returns bid=0, ask=0 — fall back to last price.
            if ask > 0:
                mid = round((bid + ask) / 2, 2)
                spread = round(ask - bid, 2)
            elif last > 0:
                mid = round(last, 2)
                spread = 0.0
            else:
                continue
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
        # Enrich with IBKR IV Rank/Percentile if available (async-safe via to_thread)
        _ibkr_iv = None
        try:
            from .ibkr import fetch_iv_metrics_ibkr
            _ibkr_iv = await asyncio.to_thread(fetch_iv_metrics_ibkr, symbol)
            if _ibkr_iv:
                for c in result:
                    c["ivRank"] = round(_ibkr_iv["ivRank"], 1)
                    c["ivPercentile"] = round(_ibkr_iv["ivPercentile"], 1)
        except Exception:
            pass

        # IBKR unavailable — try tastytrade's real IV Rank/Percentile before
        # falling back to the raw-IV-as-proxy values set above. Wrapped in
        # asyncio.to_thread purely to avoid blocking this coroutine's event
        # loop while fetch_iv_metrics_tastytrade's run_coro() call blocks its
        # calling thread waiting on the shared bridge loop (Task 6).
        if not _ibkr_iv:
            try:
                from .tastytrade_iv import fetch_iv_metrics_tastytrade
                _tasty_iv = await asyncio.to_thread(fetch_iv_metrics_tastytrade, [symbol])
                if _tasty_iv and symbol in _tasty_iv:
                    for c in result:
                        c["ivRank"] = round(_tasty_iv[symbol]["ivRank"], 1)
                        c["ivPercentile"] = round(_tasty_iv[symbol]["ivPercentile"], 1)
            except Exception:
                pass  # keep existing fallback values

        zero_iv = sum(1 for c in result if c["ivRank"] == 0)
        if zero_iv > len(result) * 0.5 and result:
            async with _get_yf_sem():
                yf_iv = await asyncio.to_thread(_yf_iv_for_chain, symbol, target_exp, option_type == "C")
            for c in result:
                if c["ivRank"] == 0:
                    yf_val = yf_iv.get(float(c["strike"]))
                    if yf_val:
                        c["ivRank"] = int(round(yf_val * 100))
                        c["implied_volatility"] = round(yf_val, 4)

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
    except Exception as exc:
        logger.debug("market cap fetch failed for %s: %s", symbol, exc)
    _market_cap_cache[symbol] = result
    return result


async def fetch_contract_quote_async(
    client: httpx.AsyncClient,
    contract_id: str,
) -> dict | None:
    """Fetch live mid price + greeks for a single contract or stock position.

    Option format: SYMBOL|STRIKE|EXPIRY|C/P  (e.g. AAPL|185|2025-05-16|C)
    Stock format:  SYMBOL|STOCK               (e.g. BA|STOCK)
    Returns a dict with: price, delta, theta, ivRank — or None on failure.
    """
    try:
        parts = contract_id.split("|")
        # Stock position — fetch underlying price, no greeks.
        if len(parts) == 2 and parts[1].upper() == "STOCK":
            symbol = parts[0]
            price = await fetch_price_async(client, symbol)
            if price is None:
                return None
            return {"price": price, "delta": None, "theta": None, "ivRank": None}

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
    """Async variant. Company names are permanent — cached for the process lifetime.

    Lookup order:
    1. In-process cache (already resolved this session).
    2. KNOWN_NAMES hardcoded table (covers ~150 common S&P 500 / NAS 100 tickers).
    3. Tradier beta/fundamentals/company API call (requires higher API tier).
    """
    cached_name = _company_cache.get(symbol)
    if cached_name is not None:
        return cached_name

    from app.data.company_names import KNOWN_NAMES
    known = KNOWN_NAMES.get(symbol)
    if known:
        _company_cache[symbol] = known
        return known

    try:
        resp = await client.get(
            f"{_tradier_base()}/beta/markets/fundamentals/company",
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
                    _company_cache[symbol] = name
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
            f"{_tradier_base()}/beta/markets/fundamentals/calendars",
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
