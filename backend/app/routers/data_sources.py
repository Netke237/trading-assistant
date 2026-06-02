"""GET /api/data-sources — probe each data source and return availability."""
from __future__ import annotations

import logging
import os
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


class DataSourceStatus(BaseModel):
    id: str
    label: str
    status: Literal["ok", "unavailable", "error", "unconfigured"]
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


@router.get("/api/data-sources", response_model=list[DataSourceStatus])
def get_data_sources() -> list[DataSourceStatus]:
    """Probe each data source and return its availability status.

    This route handler is synchronous (``def``, not ``async def``) so FastAPI
    runs it in a thread-pool executor.  ``_probe_ibkr`` may block up to 8 s
    when the IBKR auth cache is cold — that is safe here but would stall the
    event loop if this were accidentally converted to an async handler.
    """
    sources = [
        ("tradier",  "Tradier",  ["candles", "option chains", "greeks", "news", "earnings"], _probe_tradier),
        ("ibkr",     "IBKR",     ["IV rank", "IV percentile", "intraday bars"],               _probe_ibkr),
        ("yfinance", "yfinance", ["IV fallback", "earnings fallback"],                        _probe_yfinance),
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
