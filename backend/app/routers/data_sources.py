"""GET /api/data-sources — probe each data source and return availability."""
from __future__ import annotations

import logging
import os
from typing import Literal

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

_PROBE_TIMEOUT = 4.0   # seconds — fast enough for UI, long enough for cold gateways


class DataSourceStatus(BaseModel):
    id: str
    label: str
    status: Literal["ok", "unavailable", "error", "unconfigured"]
    provides: list[str]
    detail: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _probe_ibkr_gateway(port: int) -> tuple[str, str | None]:
    """Probe an IBKR Client Portal Gateway at the given localhost port."""
    url = f"https://localhost:{port}/v1/api/iserver/auth/status"
    try:
        resp = httpx.get(url, verify=False, timeout=_PROBE_TIMEOUT)
        resp.raise_for_status()
        if resp.json().get("authenticated"):
            return "ok", None
        return "unavailable", f"Gateway running but not authenticated — log in at https://localhost:{port}"
    except httpx.ConnectError:
        bat = "start-gateway-paper.bat" if port == 7499 else "start-gateway.bat"
        return "unavailable", f"Gateway not running — launch {bat}"
    except Exception as exc:
        return "unavailable", str(exc)


# ── Probes ────────────────────────────────────────────────────────────────────

def _probe_tradier() -> tuple[str, str | None]:
    """Live Tradier — checks TRADIER_API_TOKEN env var."""
    token = os.environ.get("TRADIER_API_TOKEN", "").strip()
    if not token:
        return "unconfigured", "TRADIER_API_TOKEN not set in .env"
    return "ok", None


def _probe_tradier_paper() -> tuple[str, str | None]:
    """Tradier sandbox — checks stored credentials and pings the sandbox API."""
    from app.services.credential_store import credential_store
    creds = credential_store.get("tradier_paper")
    if not creds or not creds.get("token") or not creds.get("account_id"):
        return "unconfigured", "Add sandbox token in Settings → Brokers"
    try:
        resp = httpx.get(
            "https://sandbox.tradier.com/v1/user/profile",
            headers={"Authorization": f"Bearer {creds['token']}", "Accept": "application/json"},
            timeout=_PROBE_TIMEOUT,
        )
        if resp.status_code == 200:
            name = resp.json().get("profile", {}).get("name", "")
            return "ok", name or None
        return "unavailable", f"Tradier sandbox returned HTTP {resp.status_code}"
    except Exception as exc:
        return "unavailable", str(exc)


def _probe_ibkr() -> tuple[str, str | None]:
    """IBKR live gateway on port 5000."""
    return _probe_ibkr_gateway(5000)


def _probe_ibkr_paper() -> tuple[str, str | None]:
    """IBKR paper gateway on port 7499."""
    return _probe_ibkr_gateway(7499)


def _probe_tiingo() -> tuple[str, str | None]:
    """Tiingo — checks TIINGO_API_TOKEN and pings the API."""
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
            return "ok", None
        return "unavailable", f"Tiingo returned HTTP {resp.status_code}"
    except Exception as exc:
        return "unavailable", str(exc)


def _probe_yfinance() -> tuple[str, str | None]:
    """yFinance — checks that the package is installed."""
    try:
        import yfinance  # noqa: F401
        return "ok", None
    except ImportError:
        return "unavailable", "yfinance not installed"


# ── Route ─────────────────────────────────────────────────────────────────────

@router.get("/api/data-sources", response_model=list[DataSourceStatus])
def get_data_sources() -> list[DataSourceStatus]:
    """Probe each data source and return its availability status.

    Synchronous handler — FastAPI runs it in a thread-pool executor so the
    blocking HTTP probes don't stall the event loop.
    """
    sources = [
        ("tradier",       "Tradier (live)",   ["candles", "option chains", "greeks", "news", "earnings"], _probe_tradier),
        ("tradier_paper", "Tradier (sandbox)", ["paper option orders", "paper stock orders"],              _probe_tradier_paper),
        ("ibkr",          "IBKR (live)",       ["IV rank", "IV percentile", "intraday bars"],              _probe_ibkr),
        ("ibkr_paper",    "IBKR (paper)",      ["paper option orders", "paper stock orders"],              _probe_ibkr_paper),
        ("tiingo",        "Tiingo",            ["daily OHLCV", "5y history", "backtesting"],               _probe_tiingo),
        ("yfinance",      "yfinance",          ["IV fallback", "earnings fallback"],                       _probe_yfinance),
    ]
    results: list[DataSourceStatus] = []
    for src_id, label, provides, probe in sources:
        try:
            status, detail = probe()
        except Exception as exc:
            logger.warning("Data source probe failed for %s: %s", src_id, exc)
            status, detail = "error", str(exc)
        results.append(DataSourceStatus(
            id=src_id,
            label=label,
            status=status,
            provides=provides,
            detail=detail,
        ))
    return results
