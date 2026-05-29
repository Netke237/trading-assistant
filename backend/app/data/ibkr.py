"""IBKR Client Portal Web API adapter — READ-ONLY market data.

Allowed paths: /iserver/auth/*, /tickle, /iserver/secdef/*, /iserver/marketdata/*
NEVER call order/trade/account endpoints.

The IBKR gateway runs at https://localhost:5000/v1/api and uses a self-signed
certificate — all requests use verify=False.
"""
from __future__ import annotations

import logging
import threading
import time
import warnings

import httpx
import urllib3

warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

_BASE = "https://localhost:5000/v1/api"
_TIMEOUT = 8

# ── Module-level caches ───────────────────────────────────────────────────────

# Auth status cache: {"result": bool, "expires": float}
_auth_cache: dict | None = None
_AUTH_TTL = 60.0  # seconds

# conid cache: symbol → int (permanent for process lifetime)
# -1 is the failure sentinel (CONID_MISS_SENTINEL): symbol resolved but no conid found
_conid_cache: dict[str, int] = {}
CONID_MISS_SENTINEL = -1

# Locks for thread-safe read-check-write on caches
_auth_lock = threading.Lock()
_conid_lock = threading.Lock()


# ── Authentication / keep-alive ──────────────────────────────────────────────


def ibkr_available() -> bool:
    """Return True if the IBKR gateway is running and authenticated.

    Result is cached for 60 seconds. On success, also fires a POST /tickle
    keep-alive (fire-and-forget, errors ignored).
    """
    global _auth_cache

    now = time.monotonic()
    with _auth_lock:
        if _auth_cache is not None and now < _auth_cache["expires"]:
            return _auth_cache["result"]

    try:
        resp = httpx.get(
            f"{_BASE}/iserver/auth/status",
            verify=False,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        authenticated = bool(resp.json().get("authenticated", False))
    except Exception as exc:
        logger.debug("IBKR auth check failed: %s", exc)
        with _auth_lock:
            _auth_cache = {"result": False, "expires": now + _AUTH_TTL}
        return False

    with _auth_lock:
        _auth_cache = {"result": authenticated, "expires": now + _AUTH_TTL}

    if authenticated:
        # Fire-and-forget keep-alive
        try:
            httpx.post(f"{_BASE}/tickle", verify=False, timeout=_TIMEOUT)
        except Exception:
            pass

    return authenticated


# ── Contract ID resolution ────────────────────────────────────────────────────


def _conid(symbol: str) -> int | None:
    """Resolve symbol to IBKR contract ID. Results cached permanently in-process.

    Failures are cached as CONID_MISS_SENTINEL (-1) to prevent repeated gateway
    hammering when a symbol cannot be resolved.
    """
    with _conid_lock:
        cached = _conid_cache.get(symbol)
    if cached is not None:  # covers both real conids and the sentinel
        return None if cached == CONID_MISS_SENTINEL else cached

    try:
        resp = httpx.post(
            f"{_BASE}/iserver/secdef/search",
            json={"symbol": symbol, "secType": "STK"},
            verify=False,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json()
        if not results or not isinstance(results, list):
            with _conid_lock:
                _conid_cache[symbol] = CONID_MISS_SENTINEL
            return None

        # Try to find a result with STK in sections; otherwise take the first
        conid_val: int | None = None
        for entry in results:
            sections = entry.get("sections", [])
            has_stk = any(
                (s.get("secType") == "STK" if isinstance(s, dict) else False)
                for s in sections
            )
            raw_conid = entry.get("conid")
            if raw_conid is not None:
                if has_stk:
                    conid_val = int(raw_conid)
                    break
                if conid_val is None:
                    conid_val = int(raw_conid)

        if conid_val is not None:
            with _conid_lock:
                _conid_cache[symbol] = conid_val
            return conid_val

        with _conid_lock:
            _conid_cache[symbol] = CONID_MISS_SENTINEL
        return None
    except Exception as exc:
        logger.debug("IBKR conid lookup failed for %s: %s", symbol, exc)
        with _conid_lock:
            _conid_cache[symbol] = CONID_MISS_SENTINEL
        return None


# ── Interval / period mapping ────────────────────────────────────────────────


def _map_interval(interval: str, lookback: int) -> tuple[str, str]:
    """Map a Bamendjou interval + lookback to IBKR (period, bar) strings.

    Returns (period, bar).  For "4h" the bar is "1h" — caller resamples.
    """
    iv = interval.lower()

    if iv in ("1min", "1m"):
        period = "1d" if lookback <= 7 else "5d"
        return period, "1min"

    if iv in ("5min", "5m"):
        return "5d", "5min"

    if iv in ("15min", "15m"):
        return "5d", "15min"

    if iv in ("1h", "60m"):
        return "1M", "1h"

    if iv == "4h":
        # Fetch 1h bars, resample to 4h in the caller
        return "6M", "1h"

    if iv in ("daily", "1d"):
        return "2y", "1d"

    if iv in ("weekly", "1wk"):
        return "5y", "1w"

    # Fallback
    return "5d", "15min"


# ── Intraday bars ─────────────────────────────────────────────────────────────


def fetch_intraday_ibkr(symbol: str, interval: str, lookback: int) -> list[dict]:
    """Fetch intraday OHLCV bars from IBKR.

    Returns the same bar shape as market.py:
      [{"time": int (unix ts), "open": float, "high": float,
        "low": float, "close": float, "volume": int}]

    Returns [] when the gateway is unavailable or conid cannot be resolved.
    """
    if not ibkr_available():
        return []

    conid_val = _conid(symbol)
    if conid_val is None:
        return []

    period, bar = _map_interval(interval, lookback)

    try:
        resp = httpx.get(
            f"{_BASE}/iserver/marketdata/history",
            params={
                "conid": conid_val,
                "exchange": "SMART",
                "period": period,
                "bar": bar,
                "outsideRth": "false",
            },
            verify=False,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        raw_data = resp.json().get("data", [])
        if not raw_data:
            return []

        bars: list[dict] = []
        for item in raw_data:
            t = item.get("t")
            if t is None:
                continue
            o = item.get("o")
            h = item.get("h")
            l = item.get("l")
            c = item.get("c")
            if any(v is None for v in (o, h, l, c)):
                continue
            bars.append({
                "time":   int(t / 1000),
                "open":   round(float(o), 4),
                "high":   round(float(h), 4),
                "low":    round(float(l), 4),
                "close":  round(float(c), 4),
                "volume": int(item.get("v", 0)),
            })

        # Resample 1h → 4h when requested
        if interval.lower() == "4h" and bars:
            from .market import _resample_bars
            bars = _resample_bars(bars, target_minutes=240)

        return bars
    except Exception as exc:
        logger.debug("IBKR intraday fetch failed for %s: %s", symbol, exc)
        return []


# ── IV metrics ────────────────────────────────────────────────────────────────


def fetch_iv_metrics_ibkr(symbol: str) -> dict | None:
    """Fetch IV Rank (field 7308) and IV Percentile (field 7309) from IBKR.

    Returns {"ivRank": float, "ivPercentile": float} or None if unavailable.
    """
    if not ibkr_available():
        return None

    conid_val = _conid(symbol)
    if conid_val is None:
        return None

    try:
        resp = httpx.get(
            f"{_BASE}/iserver/marketdata/snapshot",
            params={"conids": conid_val, "fields": "7308,7309"},
            verify=False,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        items = resp.json()
        if not items or not isinstance(items, list):
            return None

        item = items[0]
        raw_rank = item.get("7308")
        raw_pct = item.get("7309")

        if raw_rank is None or raw_pct is None:
            return None

        # Fields can be "--" or other non-numeric strings
        try:
            iv_rank = float(raw_rank)
            iv_pct = float(raw_pct)
        except (ValueError, TypeError):
            return None

        return {"ivRank": iv_rank, "ivPercentile": iv_pct}
    except Exception as exc:
        logger.debug("IBKR IV metrics fetch failed for %s: %s", symbol, exc)
        return None
