from __future__ import annotations

import asyncio
import contextlib
import contextvars
import io
import logging
import math
import os
import sys
import time
import weakref
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

_EASTERN = ZoneInfo("America/New_York")
from typing import Literal, Optional
from urllib.parse import urlsplit

import httpx
import pandas as pd

from app.data import governor as _governor
from app.data.governor import ProviderUnavailable, RateLimited
from app.data.quote_liveness import classify_quote
from app.scoring.contract_validator import max_quote_age_seconds
from app.scoring.dte_window import DTE_WINDOW_TOLERANCE_DAYS
from app.services.audit import log_event

TRADIER_BASE_URL = os.getenv("TRADIER_BASE_URL", "https://api.tradier.com")
TRADIER_TOKEN = os.getenv("TRADIER_API_TOKEN", "")

# Module-level clock (A4d): fetch_intraday_candles reads it once as its first
# line. Tests patch app.data.market._now, never time.time globally.
_now = time.time

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
        # Deliberately broad: a malformed/missing credentials file (or any
        # error reading the paper-broker token override) should never crash
        # price fetching — fall through to the env-var token below instead.
        pass
    return TRADIER_TOKEN, TRADIER_BASE_URL


def _tradier_base() -> str:
    return get_tradier_creds()[1]


def _is_sandbox_base(base: str) -> bool:
    """True when a Tradier base URL is the sandbox (the paper token's base).

    Substring, not equality, so a trailing slash on TRADIER_BASE_URL still counts.
    """
    return "sandbox.tradier.com" in (base or "")


# ── In-process caches ─────────────────────────────────────────────────────────
# Candles: daily bars don't change within a trading session — date-keyed cache.
_candles_cache: dict[str, tuple[list[dict], str]] = {}

# Company names: immutable; permanent cache for the process lifetime.
_company_cache: dict[str, str] = {}

# Fundamentals calendar (earnings/dividend dates): doesn't change intraday —
# date-keyed cache, same safety margin as _candles_cache.
_fundamentals_calendar_cache: dict[str, tuple[dict | None, str]] = {}

# Option expirations list: changes rarely (new expiries added ~weekly), not
# intraday -- date-keyed cache, same pattern as the calendar cache above.
_expirations_cache: dict[str, tuple[list[str], str]] = {}

# yfinance calendar: reset daily (overnight earnings updates).
_yf_cal_cache: dict[str, tuple[Optional[date], Optional[date]]] = {}
_yf_cal_cache_date: str = ""
# Audit round 2, R2-F4: a FAILED yfinance calendar lookup is backed off per
# symbol for a short TTL -- not cached for the day (round 1, F3: that pinned a
# stock at CAUTION all day) and not re-asked on every re-scan either (that
# re-hit a rate-limited feed with no cool-down and could prolong a ban).
# symbol -> `_yf_fail_clock()` value until which it is not re-asked. Kept apart
# from `_yf_cal_cache`, which holds REAL answers only (the fire path reads it).
_YF_CAL_FAIL_TTL_S: float = 10 * 60
_yf_cal_fail_until: dict[str, float] = {}
_yf_fail_clock = time.monotonic   # indirection so a test can move time without moving asyncio's

# Yahoo Finance ticker equivalents for index symbols not served by Tradier quotes.
_YF_SYMBOL_MAP: dict[str, str] = {
    "SPX": "^GSPC",
    "NDX": "^NDX",
    "VIX": "^VIX",
    "RUT": "^RUT",
    "DJI": "^DJI",
}


def _finite_ohlc(row: dict) -> bool:
    """True if a bar's open/high/low/close are all finite numbers.

    A source can hand back NaN via a path float() doesn't reject — e.g. the
    literal string "NaN" (float("NaN") succeeds and returns nan rather than
    raising) — so this must be checked explicitly rather than relying on a
    conversion failure to catch it. Applied to every source (Tradier, IBKR,
    yfinance) at the point their rows are merged/returned, not just the
    yfinance helpers, since any of them can hand back a bad bar for a thin
    or halted trading session.
    """
    return all(math.isfinite(row[k]) for k in ("open", "high", "low", "close"))


def _headers(token: str | None = None) -> dict:
    if token is None:
        token, _ = get_tradier_creds()
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


# ── Tradier admission (TRADIER-GOVERNOR, plan D3) ─────────────────────────────
# Every Tradier request in this module goes through `_tradier_get` (sync) or
# `_tradier_get_async` (async), which admit it on the governor's shared
# `tradier` bucket first. The governor is looked up at call time through the
# module attribute, so a test can swap `governor.get_governor`.

# Set while a deadline-bound auto-trade fire-path call runs. Such a call never
# waits for a slot: it books an overdraft (refused only during a 429 cooldown).
_TRADIER_FIRE_PATH: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_TRADIER_FIRE_PATH", default=False,
)
# > 0 when a token was already taken for the next request in this context
# (`tradier_prepay`), so that request makes no further admission.
_TRADIER_PREPAID: contextvars.ContextVar[int] = contextvars.ContextVar(
    "_TRADIER_PREPAID", default=0,
)
# Call sites already warned about for a sync Tradier call made on a running
# event loop (one WARNING per call site).
_TRADIER_ON_LOOP_WARNED: set[tuple[str, int]] = set()


@contextlib.contextmanager
def tradier_fire_path():
    """Mark the Tradier calls made inside the block as fire-path calls.

    A ContextVar: it does NOT cross `ThreadPoolExecutor.submit` (which copies
    no context) -- submit `run_on_fire_path` instead. Reset on exit, including
    on an exception."""
    token = _TRADIER_FIRE_PATH.set(True)
    try:
        yield
    finally:
        _TRADIER_FIRE_PATH.reset(token)


def run_on_fire_path(fn, *args):
    """`fn(*args)` inside `tradier_fire_path()`. Submit this to an executor so
    the marker is set inside the worker thread."""
    with tradier_fire_path():
        return fn(*args)


def tradier_prepay(admit_timeout: float | None) -> bool:
    """Take one `tradier` token now (a normal, waiting admission) for the next
    Tradier request made in the CURRENT context. True when admitted (the
    marker is set), False otherwise (the marker is left alone)."""
    if not _governor.get_governor().admit_sync("tradier", admit_timeout=admit_timeout):
        return False
    _TRADIER_PREPAID.set(1)
    return True


def _retry_after_seconds(resp) -> float | None:
    """The response's Retry-After in seconds when it is numeric, else None."""
    try:
        value = float(resp.headers.get("Retry-After"))
    except Exception:
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _on_running_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _warn_on_loop_once() -> None:
    """Log one WARNING per call site of `_tradier_get` reached on a running
    event loop, naming the site and its caller."""
    site = sys._getframe(2)  # the caller of _tradier_get
    key = (site.f_code.co_filename, site.f_lineno)
    if key in _TRADIER_ON_LOOP_WARNED:
        return
    _TRADIER_ON_LOOP_WARNED.add(key)
    caller = site.f_back
    called_from = (
        f"{os.path.basename(caller.f_code.co_filename)}:{caller.f_lineno} {caller.f_code.co_name}"
        if caller is not None else "?"
    )
    logger.warning(
        "Sync Tradier call on a running event loop: %s (%s:%d), called from %s; "
        "admitted by overdraft so the loop is never blocked waiting. Move the caller "
        "to a worker thread.",
        site.f_code.co_name, os.path.basename(site.f_code.co_filename), site.f_lineno, called_from,
    )


def _tradier_get(url, *, params=None, headers=None, timeout, admit_timeout: float | None = None):
    """`httpx.get` for Tradier, admitted on the governor's `tradier` bucket.

    Admission, in order (plan D3): a prepaid token is consumed; else a
    fire-path call books an overdraft; else a call on a running event loop
    books an overdraft too (safety net, with a WARNING); else a normal
    admission that waits up to `admit_timeout` (None = without limit, the bulk
    default). Not admitted -> `ProviderUnavailable`, which the call site
    handles like any failed request. `timeout` is the site's HTTP timeout,
    passed through unchanged; `admit_timeout` is never an HTTP timeout.

    A 429 records the shared cooldown (Retry-After when numeric) and the
    response is returned unchanged for the site's own status check. There is
    no sync retry."""
    gov = _governor.get_governor()
    prepaid = _TRADIER_PREPAID.get()
    if prepaid > 0:
        _TRADIER_PREPAID.set(prepaid - 1)
        admitted = True
    elif _TRADIER_FIRE_PATH.get():
        admitted = gov.admit_sync("tradier", admit_timeout=0.0, overdraft=True)
    elif _on_running_loop():
        _warn_on_loop_once()
        admitted = gov.admit_sync("tradier", admit_timeout=0.0, overdraft=True)
    else:
        admitted = gov.admit_sync("tradier", admit_timeout=admit_timeout)
    if not admitted:
        raise ProviderUnavailable("tradier rate limiter: no admission")

    try:
        resp = httpx.get(url, params=params, headers=headers, timeout=timeout)
    except Exception:
        gov.record_failure("tradier")
        raise
    if getattr(resp, "status_code", None) == 429:
        gov.note_rate_limited("tradier", _retry_after_seconds(resp))
    else:
        gov.record_success("tradier")
    return resp


async def _tradier_get_async(
    client,
    url,
    *,
    params=None,
    headers=None,
    timeout=httpx.USE_CLIENT_DEFAULT,
    retries: int = 2,
    method: str = "GET",
):
    """`client.get` (or `method`) for Tradier, admitted on the governor.

    Bulk calls go through `Governor.call`, which waits for a slot and retries
    a 429 after its Retry-After (`retries` times); when they run out,
    `RateLimited` propagates to the site's own `except`. A fire-path call
    (`tradier_fire_path()` set in this task) goes through
    `Governor.call_overdraft`: no waiting, exactly one attempt. Any other
    response is returned for the site to check. The client's timeout applies
    unless one is given; `timeout=None` is never forwarded (it would mean no
    timeout at all in httpx)."""
    kwargs = {"params": params, "headers": headers}
    if timeout is not httpx.USE_CLIENT_DEFAULT and timeout is not None:
        kwargs["timeout"] = timeout
    send = getattr(client, method.lower())

    async def _attempt():
        resp = await send(url, **kwargs)
        if getattr(resp, "status_code", None) == 429:
            raise RateLimited("tradier HTTP 429", retry_after=_retry_after_seconds(resp))
        return resp

    gov = _governor.get_governor()
    if _TRADIER_FIRE_PATH.get():
        return await gov.call_overdraft("tradier", _attempt)
    return await gov.call("tradier", _attempt, retries=retries)


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
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
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
        resp = _tradier_get(
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
            rows = [r for r in rows if _finite_ohlc(r)]
    except Exception as exc:
        # Kept broad deliberately (the request, response-shape parsing, and the
        # dict-comprehension below can each fail in different ways) — but this
        # falls through to the yfinance fallback just below, so a persistent
        # failure here (bad creds, Tradier response shape change) would
        # otherwise go completely unnoticed. Log instead of silently passing.
        logger.debug("Tradier daily-candles fetch failed for %s: %s", symbol, exc)

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
# '60m' is folded to '1h' here rather than in each lookup table: market.py and
# ibkr.py both already special-cased it, but chart_cache.py's widening did not,
# so '?interval=60m' silently served 55 days where '1h' served 730.
_INTERVAL_ALIASES: dict[str, str] = {"1D": "daily", "1W": "weekly", "60m": "1h"}


# W2-INTERVAL (decision FOLLOWUPS-QUEUE-2026-09-25 (1)): the chart's spelling of an
# interval is the one stored on composite rules and watches. The short forms the
# CompositeAlertDialog used to save map to it. Deliberately NOT folded into
# normalize_interval: that feeds every fetch, and '15m' callers elsewhere
# (regime.py, strategy_engine) would silently switch series.
_CHART_SPELLING: dict[str, str] = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "60m": "1h"}


def chart_interval(interval: object) -> object:
    """The chart's spelling of `interval`; anything else (incl. non-strings) unchanged."""
    return _CHART_SPELLING.get(interval, interval) if isinstance(interval, str) else interval


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
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        return [
            {
                "time":   int(ts.timestamp()),
                "open":   round(float(row["Open"]),   4),
                "high":   round(float(row["High"]),   4),
                "low":    round(float(row["Low"]),    4),
                "close":  round(float(row["Close"]),  4),
                "volume": 0 if pd.isna(row["Volume"]) else int(row["Volume"]),
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

    Tradier bars take precedence on timestamp conflicts (more accurate for recent data),
    EXCEPT on the sandbox base (A4d): its feed is 15 minutes delayed, so its newest
    bar can be partial. That bar never overwrites another source's finite bar at
    its timestamp, and when it fills an empty timestamp it is kept only while it
    is the newest bar of the result -- see _merge_tradier_rows.
    Returns [] only when both sources fail.
    """
    fetch_start = _now()  # first line, before any network call (A4d)
    # Credentials read ONCE: the guard, the URL, the header and the sandbox
    # policy all come from this one read, so they cannot disagree (A4d).
    token, base = get_tradier_creds()
    on_sandbox = _is_sandbox_base(base)
    interval = normalize_interval(interval)
    logger.info("Fetching intraday %s %s days=%s", symbol, interval, days)

    # ── Tradier (only for supported intervals) ───────────────────────────────
    tradier_rows: list[dict] = []
    if token and interval in _TRADIER_INTRADAY_INTERVALS:
        try:
            end = date.today()
            start = end - timedelta(days=min(days, 55))
            resp = _tradier_get(
                f"{base}/v1/markets/timesales",
                headers=_headers(token),
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
            tradier_rows = [r for r in tradier_rows if _finite_ohlc(r)]
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
    partial_ts: int | None = None
    yielded = False
    if tradier_rows:  # the helper is never called without Tradier rows
        partial_ts, yielded = _merge_tradier_rows(
            merged, tradier_rows, on_sandbox=on_sandbox,
            span=_INTERVAL_COMPLETION_SECONDS.get(interval), fetch_start=fetch_start,
        )

    # Catch-all: a bad bar from IBKR or yfinance (not just Tradier, already
    # filtered above) must not reach the merged result either.
    result = sorted((b for b in merged.values() if _finite_ohlc(b)), key=lambda b: b["time"])
    # Rule 3 (A4d), AFTER the catch-all so "newest" is the newest bar a
    # consumer will see: a presumed-partial sandbox bar that filled an empty
    # timestamp is dropped unless it is the newest bar. Kenneth, 2026-09-24:
    # a partial bar never sits behind a newer bar.
    dropped = partial_ts is not None and bool(result) and result[-1]["time"] != partial_ts
    if dropped:
        result = [b for b in result if b["time"] != partial_ts]
    logger.info(
        "Merged %d Tradier + %d IBKR + %d yf → %d total bars for %s "
        "(sandbox partial bar: yielded=%d dropped=%d)",
        len(tradier_rows), len(ibkr_rows), len(yf_rows), len(result), symbol,
        int(yielded), int(dropped),
    )
    return result


# A4d: slack beyond the sandbox feed lag before the newest sandbox bar is
# presumed complete. Only a sandbox more than ~30 minutes behind lets a partial
# bar past the window, and then the merge behaves as it did before A4d.
PARTIAL_BAR_SLACK_SECONDS = 900


def _merge_tradier_rows(
    merged: dict[int, dict],
    rows: list[dict],
    *,
    on_sandbox: bool,
    span: int | None,
    fetch_start: float,
) -> tuple[int | None, bool]:
    """Merge Tradier rows into `merged` (in place). Returns (partial_ts, yielded).

    Off the sandbox, or when `span` is None (an interval without a known bar
    length), every Tradier row overwrites the other sources, as before A4d.

    On the sandbox, P -- the row with the greatest `time` -- is presumed PARTIAL
    when `P.time + span + TRADIER_SANDBOX_FEED_LAG_SECONDS +
    PARTIAL_BAR_SLACK_SECONDS > fetch_start`. Every other row overwrites as
    before. A presumed-partial P:
      * never overwrites another source's FINITE bar at its timestamp
        (returns (None, True): it yielded);
      * otherwise fills the timestamp and is returned as `partial_ts`, which
        the caller drops unless it is the newest bar of the final result.
    P is identified by timestamp, so every Tradier row at P's time is held back,
    and the other source's bar is read before any Tradier row lands.
    """
    p_time = max(b["time"] for b in rows)
    partial = (
        on_sandbox and span is not None
        and p_time + span + TRADIER_SANDBOX_FEED_LAG_SECONDS + PARTIAL_BAR_SLACK_SECONDS > fetch_start
    )
    if not partial:
        merged.update({b["time"]: b for b in rows})
        return None, False
    held = merged.get(p_time)
    merged.update({b["time"]: b for b in rows if b["time"] != p_time})
    if held is not None and _finite_ohlc(held):
        return None, True
    merged[p_time] = [b for b in rows if b["time"] == p_time][-1]  # last row wins, as dict.update did
    return p_time, False



# ── Completed intraday bars for a REGIME measurement (A4b) ─────────────────────
# Decision A4B-DROP-FORMING-15MIN-BAR-2026-09-24: the Intraday-horizon regime is
# measured on COMPLETED 15-minute bars only, on every reader, in line with the
# auto-trader's Option A for daily bars (a forming bar buys a coin flip, not
# information). Strategy signal/backtest bars are NOT regime and do not use this.
INTRADAY_REGIME_BAR_SECONDS = 900
# Tradier's sandbox serves 15-minute-DELAYED market data, so a sandbox bar can be
# partial long after its own 15 minutes have elapsed on the wall clock. Since
# A4d the partial (newest) sandbox bar no longer wins the merge against a finite
# yfinance bar; it can still reach the result when no other source has its
# timestamp (pre/after-hours), and then only as the newest bar -- which is why
# this lag is still applied (whether to narrow it is open_questions[110]).
TRADIER_SANDBOX_FEED_LAG_SECONDS = 900


def intraday_feed_lag_seconds() -> int:
    """Seconds the intraday feed in use runs behind the wall clock.

    900 when the Tradier base this process fetches from is the sandbox (the
    paper token's base), else 0. Keyed on `_tradier_base()`, which reads the
    same credentials `fetch_intraday_candles` reads for its base. Substring, not
    equality (`_is_sandbox_base`), so a trailing slash still counts. When Tradier returned
    nothing and only yfinance (real time) answered, the sandbox lag still
    applies: that drops one extra COMPLETE bar -- the conservative direction.
    """
    try:
        base = _tradier_base() or ""
    except Exception:
        return TRADIER_SANDBOX_FEED_LAG_SECONDS
    return TRADIER_SANDBOX_FEED_LAG_SECONDS if _is_sandbox_base(base) else 0


def completed_intraday_bars(
    bars: list[dict],
    now: float | None = None,
    bar_seconds: int = INTRADAY_REGIME_BAR_SECONDS,
    feed_lag: int | None = None,
) -> list[dict]:
    """The bars whose interval had fully elapsed, in the feed's own clock, at `now`.

    `time` is the bar's START as a unix int (both sources of
    fetch_intraday_candles), so a bar is complete iff
    `time + bar_seconds + feed_lag <= now`. A bar whose `time` is not an int
    (or is a bool) cannot be shown complete and is DROPPED -- fail closed.
    Order is preserved. `now` defaults to time.time(); `feed_lag` to
    intraday_feed_lag_seconds().
    """
    import time as _time
    if now is None:
        now = _time.time()
    if feed_lag is None:
        feed_lag = intraday_feed_lag_seconds()
    cutoff = now - bar_seconds - feed_lag
    return [
        b for b in bars
        if isinstance(b.get("time"), int) and not isinstance(b.get("time"), bool)
        and b["time"] <= cutoff
    ]


# ── Completed bars for a USER-INTERVAL regime model (A4c) ──────────────────────
# Kenneth, 2026-09-24: "every model that decides or fires" drops the forming bar
# -- the user-built alert models (composite watches HMM_intraday, chart-drawn
# composite and regime-condition rules) on their own intervals. Intraday
# intervals only: daily/weekly are returned unchanged (logged separately).
# 4h is 4h + 1h: fetch_intraday_candles builds it by resampling yfinance 1h bars
# (which start at :30) into epoch-aligned 4h buckets keyed by bucket START, so
# the bucket's last 1h constituent can end up to 30 min past the nominal 4h.
_INTERVAL_COMPLETION_SECONDS: dict[str, int] = {
    "1min": 60, "1m": 60,
    "5min": 300, "5m": 300,
    "15min": 900, "15m": 900,
    "30min": 1800, "30m": 1800,
    "1h": 3600,
    "4h": 4 * 3600 + 3600,
}


def is_intraday_interval(interval: object) -> bool:
    """True iff `interval` is an intraday interval this module can judge bar
    completeness for (the same table completed_bars_for_interval uses). Daily,
    weekly, non-strings and unrecognised strings are False (A4f)."""
    return isinstance(interval, str) and normalize_interval(interval) in _INTERVAL_COMPLETION_SECONDS


def completed_bars_for_interval(
    bars: list[dict],
    interval: str,
    now: float | None = None,
) -> list[dict]:
    """`completed_intraday_bars` for a user-chosen `interval`.

    An interval outside `_INTERVAL_COMPLETION_SECONDS` (daily, weekly, or an
    unrecognised string) returns `bars` unchanged -- fail OPEN on purpose:
    dropping every bar would silently kill the user's alert. The sandbox feed
    lag applies only to the intervals Tradier timesales actually serves.
    """
    norm = normalize_interval(interval)
    span = _INTERVAL_COMPLETION_SECONDS.get(norm)
    if span is None:
        return bars
    lag = intraday_feed_lag_seconds() if norm in _TRADIER_INTRADAY_INTERVALS else 0
    return completed_intraday_bars(bars, now=now, bar_seconds=span, feed_lag=lag)

def fetch_price(symbol: str) -> Optional[float]:
    try:
        resp = _tradier_get(
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
    min_dte_floor: Optional[int] = None,
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

    `min_dte_floor` is the contract validator's hard-reject floor
    (dte_window.widened_min_dte: at least hold_max + 21 when a hold is supplied).
    Drop expiries below it before choosing the nearest window centre, so the
    one fetched expiry can pass the same validator floor. Custom 15-200d has
    window 221-400 and floor221; Intraday 0-2d has window23-58 and floor23.
    """
    lo, hi = bounds
    centre = (lo + hi) / 2

    def _dte(d: str) -> int:
        return (date.fromisoformat(d) - today).days

    if min_dte_floor is not None:
        dates = [d for d in dates if _dte(d) >= min_dte_floor]

    in_window = [d for d in dates if lo <= _dte(d) <= hi]
    if in_window:
        return min(in_window, key=lambda d: abs(_dte(d) - centre))

    near = [d for d in dates if (lo - tolerance_days) <= _dte(d) <= (hi + tolerance_days)]
    if not near:
        return None
    return min(near, key=lambda d: abs(_dte(d) - centre))


# The no-window pick when a caller passes no limits: the first expiry at or
# above this many days. Pinned to contract_rules.yaml's hard_reject.min_dte by
# tests/test_option_chain_expiry_selection.py.
_DEFAULT_MIN_DTE_FLOOR = 21


def _pick_expiration_without_window(
    dates: list[str], today: date, dte_limits: Optional[tuple[int, int, int, int]],
) -> Optional[str]:
    """The expiry to fetch when no hold window is set.

    `dte_limits` is (min_dte, preferred_dte_min, preferred_dte_max, max_dte) as
    the contract validator applies them (contract_validator.effective_dte_limits).
    Only expiries inside [min_dte, max_dte] can yield a contract the validator
    accepts, so nothing outside it is picked (None when nothing is listed
    there). Among those, the one with the smallest distance to the preferred
    band [preferred_dte_min, preferred_dte_max] wins, the shorter on a tie --
    so the shortest expiry inside the band when there is one. This does NOT maximise the DTE sub-score (_score_dte peaks at the
    band's centre and is 0 at its edges); it only stays out of the hard-reject
    range and as close to the band as the listing allows.

    With the shipped rules (21, 21-60, 90) that is the old "first expiry of
    21+ days" whenever that expiry is at most 90 days out; when it is further
    (only longer expiries listed) the old pick was certain to be rejected as
    dte_too_long and nothing is fetched instead.

    A fixed 21 used to be the floor whatever the rules said: a min_dte override
    of 45 fetched the first 21+ day expiry, every contract of which was then
    rejected as dte_too_short, dropping the symbol from the scan.

    dte_limits=None keeps that old pick (first expiry of 21+ days, now taken in
    date order rather than listing order) for callers that pass no rules; it
    stops there, as before. With dte_limits set every listed date is parsed, so
    one malformed entry fails the whole fetch (the caller's except returns []).
    """
    def _dte(d: str) -> int:
        return (date.fromisoformat(d) - today).days

    ordered = sorted(dates)
    if dte_limits is None:
        return next((d for d in ordered if _dte(d) >= _DEFAULT_MIN_DTE_FLOOR), None)
    # An inverted band (preferred min above max) gives odd distances, but the
    # validator then scores every DTE 0, so which in-range expiry wins is moot.
    lo, pref_lo, pref_hi, hi = dte_limits

    def _off_band(d: str) -> int:
        n = _dte(d)
        return pref_lo - n if n < pref_lo else max(0, n - pref_hi)

    in_range = [d for d in ordered if lo <= _dte(d) <= hi]
    return min(in_range, key=_off_band) if in_range else None  # min() keeps the first (shorter) on a tie


def _quote_liveness_inputs() -> tuple[float, bool, float, float]:
    """(now_s, session_open, feed_lag_s, max_age_s) for ONE chain fetch.

    Taken once per fetch, before the row loop, so every row of a chain is
    classified against the same instant and one fetch cannot straddle 16:00
    row by row (NO-LIVE-QUOTE, plan 3a). The session test is the scheduler's
    one, re-exported by market_session; imported HERE, at call time, because
    importing market_session imports this module (through
    strategy_watch_scheduler's chain), so a module-level import would be
    circular.
    """
    from app.services.market_session import MARKET_TZ, _market_session_open
    return (
        _now(),
        _market_session_open(datetime.now(MARKET_TZ)),
        float(intraday_feed_lag_seconds()),
        max_quote_age_seconds(),
    )


def _quote_keys(c: dict, bid: float, ask: float, q: tuple[float, bool, float, float]) -> dict:
    """The three liveness keys every chain row carries: quoteState, quoteLive
    and quoteAgeS (the fresher side's age in seconds, or None). Tradier's
    `bid_date`/`ask_date` are epoch MILLISECONDS. Deliberately NOT `bid`/`ask`:
    scan.py's bearish spread builder reads those keys off raw chain rows, and
    adding them would silently switch that unaudited path on (plan section 2)."""
    now_s, session_open, feed_lag_s, max_age_s = q
    state, age_s = classify_quote(
        bid, ask, c.get("bid_date"), c.get("ask_date"),
        now_s=now_s, session_open=session_open, feed_lag_s=feed_lag_s, max_age_s=max_age_s,
    )
    return {
        "quoteState": state,
        "quoteLive": state == "live",
        "quoteAgeS": round(age_s, 1) if age_s is not None else None,
    }


def fetch_option_chain(
    symbol: str,
    expiry: Optional[str] = None,
    option_type: Literal["C", "P"] = "C",
    dte_bounds: Optional[tuple[int, int]] = None,
    min_dte_floor: Optional[int] = None,
    dte_limits: Optional[tuple[int, int, int, int]] = None,
) -> list[dict]:
    try:
        exp_resp = _tradier_get(
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
            target_exp = _nearest_expiration_in_window(dates, dte_bounds, _today, min_dte_floor=min_dte_floor)
            if target_exp is None:
                # Distinguish "no listed expiry at/above the validator's floor"
                # from a missing chain: the caller can only report "no option chain".
                logger.info("chain %s: no expiry in DTE window %s at/above floor %s (listed: %d)",
                          symbol, dte_bounds, min_dte_floor, len(dates))
                return []
        else:
            target_exp = _pick_expiration_without_window(dates, _today, dte_limits)
            if target_exp is None:
                logger.info("chain %s: no expiry within DTE limits %s (listed: %d)",
                          symbol, dte_limits or f">= {_DEFAULT_MIN_DTE_FLOOR}", len(dates))
                return []

        chain_resp = _tradier_get(
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
        quote_inputs = _quote_liveness_inputs()
        result = []
        for c in contracts:
            if c.get("option_type") != tradier_type:
                continue

            bid = float(c.get("bid") or 0)
            ask = float(c.get("ask") or 0)
            # No ask (<= 0, or NaN) = no executable price for a buyer (FR-24
            # "missing ask"): the row is DROPPED (NO-LIVE-QUOTE, Kenneth's Q-C).
            # This replaced a fallback to the last trade price with a
            # fabricated zero spread, which graded as a perfect spread. Its
            # premise -- "outside market hours Tradier returns bid=0, ask=0" --
            # was never observed: 0 of 4,868 measured rows had ask == 0, in or
            # out of session (plan section 1). Off-hours rows carry the last
            # close's real two-sided quotes; quoteState below marks them.
            if not ask > 0:
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
                # ⚠ SHAPE HAZARD — this is the DEAD sync twin of
                # fetch_option_chain_async (nothing calls it; see Amendment A).
                # It USED TO write raw absolute IV into `ivRank` (converted in round 4), the pre-Phase-A
                # shape. ROUND 4 finding 7: this twin is dead code (verified --
                # the only non-test references are its own def and two
                # docstrings), and it was left on the PRE-SPLIT shape on that
                # basis. The hazard was not the dead code itself but the GREEN
                # TEST pinning `ivRank == int(round(iv*100))` and
                # `ivPercentile == 0` as correct: anyone unifying the twins by
                # copying the tested one would have restored the exact defect
                # Phase A removed, with a passing suite. Converted to match the
                # async twin so the repo holds no pre-split shape at all.
                # It still has no callers -- see the note above.
                "iv": round(iv * 100, 1) if iv > 0 else None,
                "ivRank": None,
                "ivPercentile": None,
                "spread": spread,
                "volume": volume,
                "open_interest": oi,
                "score": 0,
                **_quote_keys(c, bid, ask, quote_inputs),
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

        # IBKR unavailable — try tastytrade's real IV Rank/Percentile (adapter
        # returns 0-100 scale, normalized from tastytrade's 0-1 wire fractions)
        # before falling back to the raw-IV-as-proxy values set above.
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

        zero_iv = sum(1 for c in result if not c.get("iv"))
        if zero_iv > len(result) * 0.5 and result:
            yf_iv = _yf_iv_for_chain(symbol, target_exp, option_type == "C")
            for c in result:
                if not c.get("iv"):
                    yf_val = yf_iv.get(float(c["strike"]))
                    if yf_val:
                        c["iv"] = round(yf_val * 100, 1)
                        c["implied_volatility"] = round(yf_val, 4)

        seen: set[str] = set()
        return [c for c in result if not (c["id"] in seen or seen.add(c["id"]))]  # type: ignore[func-returns-value]
    except Exception:
        return []


def fetch_quotes(symbols: list[str]) -> dict[str, dict]:
    try:
        resp = _tradier_get(
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
            raw_last = q.get("last")
            raw_close = q.get("close")
            last = raw_last or raw_close or 0
            prev = q.get("prevclose") or last
            if sym and not raw_last and raw_close:
                log_event("quote_fallback_to_close", sym, {
                    "raw_last": raw_last,
                    "raw_close": raw_close,
                    "used_price": float(last),
                })
            if sym and last:
                result[sym] = {"last": float(last), "prevclose": float(prev)}
        return result
    except Exception:
        return {}


def fetch_earnings_date(symbol: str) -> Optional[date]:
    try:
        resp = _tradier_get(
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
        resp = _tradier_get(
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
        resp = _tradier_get(
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


def _article_url(value: object) -> str | None:
    """Return *value* only when it is an absolute http(s) link the provider supplied.

    Non-strings, blanks, relative paths, other schemes (``javascript:``,
    ``data:``, ``ftp:`` ...), host-less URLs and links containing whitespace or
    control characters yield ``None``. Never constructs a link (#265).
    """
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in candidate):
        return None
    try:
        parsed = urlsplit(candidate)
        host = parsed.hostname
    except ValueError:
        return None
    if parsed.scheme.lower() not in ("http", "https") or not host:
        return None
    return candidate


def _first_article_url(*values: object) -> str | None:
    for value in values:
        url = _article_url(value)
        if url:
            return url
    return None


def _nested_url(container: object) -> object:
    return container.get("url") if isinstance(container, dict) else None


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
            article = {
                "id":        uid,
                "symbol":    article_sym,
                "headline":  headline,
                "source":    source,
                "timestamp": timestamp,
                "sentiment": "neutral",
            }
            # Provider-supplied original link only: new shape canonicalUrl /
            # clickThroughUrl, then the legacy top-level "link". Added only
            # when valid so the pre-existing item shape is untouched.
            url = _first_article_url(
                _nested_url(content.get("canonicalUrl")),
                _nested_url(content.get("clickThroughUrl")),
                content.get("link"),
                item.get("link"),
            )
            if url:
                article["url"] = url
            articles.append(article)

    articles.sort(key=lambda x: x["timestamp"], reverse=True)
    return articles[:limit]


def fetch_news(symbols: list[str], limit: int = 20) -> list[dict]:
    """
    Returns recent news headlines for the given symbols.
    Tries Tradier first (when TRADIER_API_TOKEN is set), then falls back to yfinance.
    Each item: {id, symbol, headline, source, timestamp, sentiment} plus an
    optional ``url`` (provider-supplied absolute http(s) article link only).
    """
    if get_tradier_creds()[0]:
        try:
            resp = _tradier_get(
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
                article = {
                    "id":        str(a.get("id", i)),
                    "symbol":    symbol,
                    "headline":  a.get("title", ""),
                    "source":    a.get("source", ""),
                    "timestamp": a.get("datetime", ""),
                    "sentiment": "neutral",
                }
                url = _first_article_url(a.get("url"), a.get("link"))
                if url:
                    article["url"] = url
                result.append(article)
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


class EarningsLookupError(Exception):
    """An earnings lookup FAILED (audit round 1, F3) -- the request raised, timed
    out or answered with something unreadable.

    Distinct from a lookup that ANSWERED "no date on file", which returns None.
    The two used to be one value (`_calendar_dates_yf` swallowed every error into
    `(None, None)`), so the fire-time refusal could only ever say "none on file"
    and the scan day-cached a transient failure as if it were an answer.

    WHERE THE SOURCE ALLOWS: yfinance can itself swallow a failed request and
    hand back an empty calendar, which is then indistinguishable from a genuine
    "no calendar" and reads as None. What it raises is reported as a failure.
    """


def _calendar_dates_yf_strict(symbol: str) -> tuple[Optional[date], Optional[date]]:
    """Earnings + dividend dates in ONE yfinance calendar call, or raise
    `EarningsLookupError` when the call fails. `(None, None)` means yfinance
    answered with no calendar. A date already past reads as None (the next one
    is not known)."""
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
    except Exception as exc:
        raise EarningsLookupError(f"yfinance calendar for {symbol} failed: {exc}") from exc


def _calendar_dates_yf(symbol: str) -> tuple[Optional[date], Optional[date]]:
    """Fetch earnings + dividend dates in ONE yfinance calendar call (avoids two round-trips).

    Lenient: a failed lookup reads as `(None, None)`, exactly as before audit
    round 1. Callers that must tell a failure from "no date" use
    `_calendar_dates_yf_strict`."""
    try:
        return _calendar_dates_yf_strict(symbol)
    except EarningsLookupError:
        return None, None


# Keep single-date shims so existing callers outside the scan hot-path still work
def _earnings_date_yf(symbol: str) -> Optional[date]:
    return _calendar_dates_yf(symbol)[0]


def _dividend_date_yf(symbol: str) -> Optional[date]:
    return _calendar_dates_yf(symbol)[1]


def _loop_semaphore(
    registry: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]", limit: int,
) -> asyncio.Semaphore:
    """The semaphore for the RUNNING event loop, created on first use.

    On Python 3.11 an `asyncio.Semaphore` binds to the first event loop that
    has to WAIT on it (`asyncio.mixins._LoopBoundMixin._get_loop`, reached from
    `acquire()` only when the semaphore is locked). A process-wide singleton
    therefore raised `RuntimeError: ... is bound to a different event loop` in
    any later loop that contended on it (pytest-asyncio's loop per test, a
    script calling `asyncio.run` twice), and the contending symbol was lost.
    One semaphore per running loop keeps `limit` on every loop and never
    raises that error. Two loops running at the same time each get their own
    `limit`.

    The registry is keyed weakly by the loop object, so a new loop that reuses
    a dead loop's id never inherits its semaphore. A semaphore that has ever
    been contended holds its loop in `Semaphore._loop`, so that entry stays in
    the registry after its loop closes — a small, bounded cost in multi-loop
    processes (tests, scripts). Call only from inside a coroutine.
    """
    loop = asyncio.get_running_loop()
    sem = registry.get(loop)
    if sem is None:
        sem = asyncio.Semaphore(limit)
        registry[loop] = sem
    return sem


# Limits concurrent Yahoo Finance calendar fetches — prevents rate-limiting during batch scans
_YF_CALENDAR_SEMS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


def _get_yf_sem() -> asyncio.Semaphore:
    return _loop_semaphore(_YF_CALENDAR_SEMS, 5)


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
    if _yf_fail_clock() < _yf_cal_fail_until.get(symbol, float("-inf")):
        return None, None   # R2-F4: inside the failure backoff -- not re-asked

    async with _get_yf_sem():
        # Double-check after acquiring semaphore — another coroutine may have populated it.
        if symbol in _yf_cal_cache:
            return _yf_cal_cache[symbol]
        if _yf_fail_clock() < _yf_cal_fail_until.get(symbol, float("-inf")):
            return None, None
        try:
            result = await asyncio.to_thread(_calendar_dates_yf_strict, symbol)
        except EarningsLookupError:
            # Audit round 1, F3: a FAILED lookup is not cached for the day.
            # Since D4 was amended an unknown date caps a stock card at
            # CAUTION, so day-caching one transient failure pinned the symbol
            # at CAUTION for the rest of the day, re-scans included. Round 2,
            # R2-F4: it is backed off for `_YF_CAL_FAIL_TTL_S` instead, so a
            # re-scan inside that window does not re-hit a rate-limited feed.
            # Only real answers are day-cached -- a genuine "no date" among
            # them (the `(None, None)` return above).
            _yf_cal_fail_until[symbol] = _yf_fail_clock() + _YF_CAL_FAIL_TTL_S
            return None, None

    _yf_cal_fail_until.pop(symbol, None)
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
        resp = await _tradier_get_async(
            client,
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
            rows = [r for r in rows if _finite_ohlc(r)]
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
_PREWARM_SEMS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


def _get_prewarm_sem() -> asyncio.Semaphore:
    return _loop_semaphore(_PREWARM_SEMS, 15)


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
        resp = await _tradier_get_async(
            client,
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
    min_dte_floor: Optional[int] = None,
    dte_limits: Optional[tuple[int, int, int, int]] = None,
) -> list[dict]:
    """Async variant."""
    try:
        cached_exp = _expirations_cache.get(symbol)
        if cached_exp is not None and cached_exp[1] == date.today().isoformat():
            dates = cached_exp[0]
        else:
            exp_resp = await _tradier_get_async(
                client,
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
            _expirations_cache[symbol] = (dates, date.today().isoformat())

        _today = date.today()
        if expiry and expiry in dates:
            target_exp = expiry
        elif dte_bounds is not None:
            target_exp = _nearest_expiration_in_window(dates, dte_bounds, _today, min_dte_floor=min_dte_floor)
            if target_exp is None:
                # Distinguish "no listed expiry at/above the validator's floor"
                # from a missing chain: the caller can only report "no option chain".
                logger.info("chain %s: no expiry in DTE window %s at/above floor %s (listed: %d)",
                          symbol, dte_bounds, min_dte_floor, len(dates))
                return []
        else:
            target_exp = _pick_expiration_without_window(dates, _today, dte_limits)
            if target_exp is None:
                logger.info("chain %s: no expiry within DTE limits %s (listed: %d)",
                          symbol, dte_limits or f">= {_DEFAULT_MIN_DTE_FLOOR}", len(dates))
                return []

        chain_resp = await _tradier_get_async(
            client,
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
        quote_inputs = _quote_liveness_inputs()
        result = []
        for c in contracts:
            if c.get("option_type") != tradier_type:
                continue

            bid = float(c.get("bid") or 0)
            ask = float(c.get("ask") or 0)
            # No ask (<= 0, or NaN) = no executable price for a buyer (FR-24
            # "missing ask"): the row is DROPPED (NO-LIVE-QUOTE, Kenneth's Q-C).
            # This replaced a fallback to the last trade price with a
            # fabricated zero spread, which graded as a perfect spread. Its
            # premise -- "outside market hours Tradier returns bid=0, ask=0" --
            # was never observed: 0 of 4,868 measured rows had ask == 0, in or
            # out of session (plan section 1). Off-hours rows carry the last
            # close's real two-sided quotes; quoteState below marks them.
            if not ask > 0:
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
                # ABSOLUTE implied volatility for THIS strike, 0-100, or None.
                # Tradier is the only vendor returning a per-contract IV; IBKR
                # and tastytrade return a symbol-level RANK, a different
                # quantity (where today's IV sits in its own 52-week range).
                # Until 2026-09-06 this value was written into `ivRank`, so a
                # name at 45% IV scored as though it had IV rank 45
                # of its own range -- failing iv_rank_pass_max: 34 -- and a name
                # at 75% was HARD-REJECTED at max_iv_rank: 70 even when 75% is
                # low for it. See PHASE-A-NULL-IVRANK-2026-09-06.
                "iv": round(iv * 100, 1) if iv > 0 else None,
                # An IV RANK, or None. None means "no rank source
                # answered" -- a distinct state from any number, and what tells
                # the scorer to judge `iv` against the ABSOLUTE thresholds
                # instead. Only the IBKR and tastytrade branches below fill it.
                "ivRank": None,
                "ivPercentile": None,
                "spread": spread,
                "volume": volume,
                "open_interest": oi,
                "score": 0,
                **_quote_keys(c, bid, ask, quote_inputs),
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

        # IBKR unavailable — try tastytrade's real IV Rank/Percentile (adapter
        # returns 0-100 scale, normalized from tastytrade's 0-1 wire fractions)
        # before falling back to the raw-IV-as-proxy values set above. Wrapped in
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

        # Counts contracts with no ABSOLUTE IV, which is what the yfinance
        # backfill below supplies. Reading `ivRank` was only correct while that
        # field held raw IV; now that it holds a rank or None, a
        # Tradier-only chain would have read 0-of-N and skipped the backfill.
        zero_iv = sum(1 for c in result if not c.get("iv"))
        if zero_iv > len(result) * 0.5 and result:
            async with _get_yf_sem():
                yf_iv = await asyncio.to_thread(_yf_iv_for_chain, symbol, target_exp, option_type == "C")
            for c in result:
                if not c.get("iv"):
                    yf_val = yf_iv.get(float(c["strike"]))
                    if yf_val:
                        # yfinance supplies an ABSOLUTE IV, never a rank.
                        c["iv"] = round(yf_val * 100, 1)
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

    How an option row is matched:
      - EXPIRY exactly. The chain fetch falls back to ANOTHER expiry when the
        requested one is not listed (an expired or mistyped contract); that
        row is not this contract's quote, so it is refused here, once, for
        every caller (it used to be returned, and only get_option_quote
        checked).
      - STRIKE after integer truncation on BOTH sides (`int(float(strike))`
        here, `int(strike)` in the chain rows). A known, pre-existing limit: a
        fractional strike such as 22.5 gets the 22 row's price. Callers must
        not use this helper to authorize money on a fractional strike --
        daily_risk_hooks.opening_price quotes the exact OSI symbol instead for
        that reason.
    A contract whose ask is 0 has no row (the chain builder drops it), so it
    is None too. What None means is up to each caller: most treat it as
    "quote unavailable", and GET /api/portfolio marks the row
    `quoteUnavailable` and skips that request's equity snapshot.
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
        return next(
            (c for c in chain if c["strike"] == target_strike and c["expiry"] == expiry), None,
        )
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
        resp = await _tradier_get_async(
            client,
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
    cached = _fundamentals_calendar_cache.get(symbol)
    if cached is not None:
        data, cached_date = cached
        if cached_date == date.today().isoformat():
            return data

    try:
        resp = await _tradier_get_async(
            client,
            f"{_tradier_base()}/beta/markets/fundamentals/calendars",
            headers=_headers(),
            params={"symbols": symbol},
        )
        resp.raise_for_status()
        data = resp.json()
        result: dict | None = None
        if data and isinstance(data, list):
            for entry in data:
                for r in entry.get("results", []):
                    result = r
                    break
                if result is not None:
                    break
        # Only a genuine response (even a legitimately empty one -- Tradier
        # successfully answered "no calendar entries for this symbol") gets
        # cached. A transient failure below (timeout, 5xx, bad JSON) must NOT
        # be memoized as "no data" for the rest of the day -- matches
        # _candles_cache/_company_cache, which likewise only write on success.
        _fundamentals_calendar_cache[symbol] = (result, date.today().isoformat())
        return result
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


def _first_calendar_result(data) -> dict | None:
    """The first `results` entry of a Tradier fundamentals/calendars answer."""
    if data and isinstance(data, list):
        for entry in data:
            for r in entry.get("results", []):
                return r
    return None


# httpx timeouts are PER PHASE (connect, read, write, pool each get their own),
# not a total, so a bare `timeout=8` let one slow request run 8-16s+ (audit
# round 2, R2-F3). The hard bound on the fire path is the per-source thread
# deadline in `auto_trader`; these keep an abandoned thread from lingering far
# past it. Both sit under `auto_trader._TRADIER_LOOKUP_DEADLINE_S` (5s).
_TRADIER_CALENDAR_HTTP_TIMEOUT = httpx.Timeout(4.0, connect=2.0)


def _fundamentals_calendar_sync(symbol: str) -> dict | None:
    """Sync twin of `fetch_fundamentals_calendar` for the fire path, which runs
    on a worker thread. Reuses the scan's same-day answer when there is one
    (that cache holds only real answers). Raises `EarningsLookupError` on a
    failed request instead of reading it as "no data"; a real answer is cached
    the way the async path caches it."""
    cached = _fundamentals_calendar_cache.get(symbol)
    if cached is not None and cached[1] == date.today().isoformat():
        return cached[0]
    try:
        resp = _tradier_get(
            f"{_tradier_base()}/beta/markets/fundamentals/calendars",
            headers=_headers(),
            params={"symbols": symbol},
            timeout=_TRADIER_CALENDAR_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        result = _first_calendar_result(resp.json())
    except Exception as exc:
        raise EarningsLookupError(f"fundamentals calendar for {symbol} failed: {exc}") from exc
    _fundamentals_calendar_cache[symbol] = (result, date.today().isoformat())
    return result


# The fire path's two earnings sources, in the scan's order (`routers/scan.py`,
# the candidate loop): Tradier fundamentals first, then the yfinance calendar.
# Each one is called by `auto_trader._lookup_earnings_date` under its OWN
# deadline (audit round 2, R2-F3); neither is bounded on its own.
#
# Each returns the date (today or later) or None when the source ANSWERED with
# no future date, and raises `EarningsLookupError` when it FAILED. Each reuses
# the scan's same-day answer when there is one (both caches hold real answers
# only), which also keeps a fire right after a scan from re-hitting a feed that
# scan just hammered.

def tradier_next_earnings_date(symbol: str) -> Optional[date]:
    """Source 1: Tradier fundamentals/calendars (`_fundamentals_calendar_sync`)."""
    return _extract_earnings_date(_fundamentals_calendar_sync(symbol))


def yfinance_next_earnings_date(symbol: str) -> Optional[date]:
    """Source 2: the yfinance calendar, strict (a failure raises)."""
    if _yf_cal_cache_date == date.today().isoformat():
        cached = _yf_cal_cache.get(symbol)
        if cached is not None:
            return cached[0]
    return _calendar_dates_yf_strict(symbol)[0]
