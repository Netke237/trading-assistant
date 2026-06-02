"""GET /api/data-sources — probe each data source and return availability."""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


class DataSourceStatus(BaseModel):
    id: str
    label: str
    status: str          # "ok" | "unavailable" | "error" | "unconfigured"
    provides: list[str]
    detail: str | None = None


# ── Probes ────────────────────────────────────────────────────────────────────


def _probe_tradier() -> tuple[str, str | None]:
    """Return (status, detail).  Checks that the API token is set."""
    token = os.environ.get("TRADIER_API_TOKEN", "").strip()
    if not token:
        return "unconfigured", "TRADIER_API_TOKEN not set"
    return "ok", None


def _probe_ibkr() -> tuple[str, str | None]:
    """Return (status, detail).  Calls ibkr_available() — result cached 60 s."""
    from app.data.ibkr import ibkr_available
    available = ibkr_available()
    if available:
        return "ok", None
    return "unavailable", "Gateway unreachable or not authenticated"


def _probe_yfinance() -> tuple[str, str | None]:
    """Return (status, detail).  Checks that yfinance can be imported."""
    try:
        import yfinance  # noqa: F401
        return "ok", None
    except ImportError:
        return "unavailable", "yfinance not installed"


# ── Route ─────────────────────────────────────────────────────────────────────

import sys as _sys

_SOURCES: list[dict] = [
    {
        "id": "tradier",
        "label": "Tradier",
        "provides": ["candles", "option chains", "greeks", "news", "earnings"],
        "probe": "_probe_tradier",
    },
    {
        "id": "ibkr",
        "label": "IBKR",
        "provides": ["IV rank", "IV percentile", "intraday bars"],
        "probe": "_probe_ibkr",
    },
    {
        "id": "yfinance",
        "label": "yfinance",
        "provides": ["IV fallback", "earnings fallback"],
        "probe": "_probe_yfinance",
    },
]


@router.get("/api/data-sources", response_model=list[DataSourceStatus])
def get_data_sources() -> list[DataSourceStatus]:
    """Probe each data source and return its availability status."""
    _mod = _sys.modules[__name__]
    results: list[DataSourceStatus] = []
    for src in _SOURCES:
        try:
            probe_fn = getattr(_mod, src["probe"])
            status, detail = probe_fn()
        except Exception as exc:
            logger.warning("Data source probe failed for %s: %s", src["id"], exc)
            status, detail = "error", str(exc)
        results.append(DataSourceStatus(
            id=src["id"],
            label=src["label"],
            status=status,
            provides=src["provides"],
            detail=detail,
        ))
    return results
