"""GET /api/data-sources — probe each data source with a real authenticated
call and return reliable availability. Results cached briefly; the Governor's
live circuit state can override a probe to 'degraded'."""
from __future__ import annotations

import logging
import os
import time
from typing import Literal

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from app.services.credential_store import credential_store
from app.data.governor import get_governor

logger = logging.getLogger(__name__)
router = APIRouter()

_PROBE_TIMEOUT = 4.0
_CACHE_TTL = 45.0  # seconds — keep panel polling from burning rate budget
_PROBE_CACHE: dict[str, tuple[str, str | None, float]] = {}  # id -> (status, detail, expires)

ProbeStatus = Literal["connected", "degraded", "down", "unconfigured"]


class DataSourceStatus(BaseModel):
    id: str
    label: str
    status: ProbeStatus
    provides: list[str]
    detail: str | None = None


# ── Probe helpers ───────────────────────────────────────────────────────────

def _probe_tradier() -> tuple[str, str | None]:
    from app.data.market import get_tradier_creds
    token, base = get_tradier_creds()
    if not token:
        return "unconfigured", "No Tradier token — add one in Settings → Brokers or set TRADIER_API_TOKEN in .env"
    try:
        resp = httpx.get(
            f"{base}/v1/markets/clock",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=_PROBE_TIMEOUT,
        )
        if resp.status_code == 200:
            return "connected", None
        return "down", f"Tradier returned HTTP {resp.status_code}"
    except Exception as exc:
        return "down", str(exc)


def _probe_tradier_paper() -> tuple[str, str | None]:
    from app.services.credential_store import credential_store
    creds = credential_store.get("tradier_paper") or {}
    token = creds.get("token") or os.environ.get("TRADIER_PAPER_TOKEN", "").strip()
    account_id = creds.get("account_id") or os.environ.get("TRADIER_PAPER_ACCOUNT_ID", "").strip()
    if not token or not account_id:
        return "unconfigured", "Add Tradier paper token + account ID in Settings → Brokers"
    try:
        resp = httpx.get(
            "https://sandbox.tradier.com/v1/markets/clock",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=_PROBE_TIMEOUT,
        )
        if resp.status_code == 200:
            return "connected", None
        return "down", f"Tradier sandbox returned HTTP {resp.status_code}"
    except Exception as exc:
        return "down", str(exc)


def _probe_alpaca(slot: str) -> tuple[str, str | None]:
    creds = credential_store.get(slot)
    if not creds or not creds.get("key_id") or not creds.get("secret_key"):
        return "unconfigured", "Add Alpaca keys in Settings → Brokers"
    base = creds.get("base_url", "https://paper-api.alpaca.markets")
    try:
        resp = httpx.get(
            f"{base}/v2/account",
            headers={
                "APCA-API-KEY-ID": creds["key_id"],
                "APCA-API-SECRET-KEY": creds["secret_key"],
            },
            timeout=_PROBE_TIMEOUT,
        )
        if resp.status_code == 200:
            return "connected", None
        return "down", f"Alpaca returned HTTP {resp.status_code}"
    except Exception as exc:
        return "down", str(exc)


def _probe_tiingo() -> tuple[str, str | None]:
    token = os.environ.get("TIINGO_API_TOKEN", "").strip()
    if not token:
        return "unconfigured", "TIINGO_API_TOKEN not set in .env"
    try:
        resp = httpx.get(
            "https://api.tiingo.com/api/test/",
            headers={"Authorization": f"Token {token}", "Content-Type": "application/json"},
            timeout=_PROBE_TIMEOUT,
        )
        if resp.status_code == 200:
            return "connected", None
        return "down", f"Tiingo returned HTTP {resp.status_code}"
    except Exception as exc:
        return "down", str(exc)


def _probe_ibkr_gateway(port: int) -> tuple[str, str | None]:
    url = f"https://localhost:{port}/v1/api/iserver/auth/status"
    try:
        resp = httpx.get(url, verify=False, timeout=_PROBE_TIMEOUT)
        resp.raise_for_status()
        if resp.json().get("authenticated"):
            return "connected", None
        return "down", f"Gateway up but not authenticated — log in at https://localhost:{port}"
    except httpx.ConnectError:
        bat = "start-gateway-paper.bat" if port == 7499 else "start-gateway.bat"
        return "down", f"Gateway not running — launch {bat}"
    except Exception as exc:
        return "down", str(exc)


def _probe_yfinance() -> tuple[str, str | None]:
    try:
        import yfinance as yf  # noqa: F401
        return "connected", None
    except ImportError:
        return "down", "yfinance not installed"


def _status_for_probe(governor_name: str | None, probe_status: str) -> str:
    """Let the Governor's live circuit state override a healthy probe to
    'degraded' — so the dot reflects real operational health during scans."""
    if governor_name is None:
        return probe_status
    gov_health = get_governor().health(governor_name)
    if gov_health == "degraded" and probe_status == "connected":
        return "degraded"
    return probe_status


# ── Route ───────────────────────────────────────────────────────────────────

@router.get("/api/data-sources", response_model=list[DataSourceStatus])
def get_data_sources() -> list[DataSourceStatus]:
    # (id, label, provides, probe_callable, governor_name)
    def _alpaca_primary():
        live = credential_store.get("alpaca_live") or {}
        return _probe_alpaca("alpaca_live") if live.get("key_id") else _probe_alpaca("alpaca_paper")

    sources = [
        ("alpaca",         "Alpaca (data)",    ["daily OHLCV", "5y history"],           _alpaca_primary,                       "alpaca"),
        ("alpaca_paper",   "Alpaca (paper)",   ["paper stock orders"],                   lambda: _probe_alpaca("alpaca_paper"),  None),
        ("ibkr",           "IBKR (live)",      ["IV rank", "intraday bars"],             lambda: _probe_ibkr_gateway(5000),     "ibkr"),
        ("ibkr_paper",     "IBKR (paper)",     ["paper orders"],                         lambda: _probe_ibkr_gateway(7499),     None),
        ("tradier",        "Tradier (live)",   ["quotes", "option chains", "calendar"],  _probe_tradier,                        "tradier"),
        ("tradier_paper",  "Tradier (paper)",  ["paper stock/option orders"],            _probe_tradier_paper,                  None),
        ("tiingo",         "Tiingo",           ["daily OHLCV fallback"],                 _probe_tiingo,                         "tiingo"),
        ("yfinance",       "yfinance",         ["last-resort fallback"],                 _probe_yfinance,                       "yfinance"),
    ]
    now = time.monotonic()
    results: list[DataSourceStatus] = []
    for src_id, label, provides, probe, gov_name in sources:
        cached = _PROBE_CACHE.get(src_id)
        if cached and cached[2] > now:
            status, detail = cached[0], cached[1]
        else:
            try:
                probe_status, detail = probe()
            except Exception as exc:
                logger.warning("probe failed for %s: %s", src_id, exc)
                probe_status, detail = "down", str(exc)
            status = _status_for_probe(gov_name, probe_status)
            _PROBE_CACHE[src_id] = (status, detail, now + _CACHE_TTL)
        results.append(DataSourceStatus(
            id=src_id, label=label, status=status, provides=provides, detail=detail,
        ))
    return results
