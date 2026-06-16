"""DB-first cache for SEC EDGAR fundamentals data.

Public API:
- get_fundamentals(symbol, staleness_days)  : DB-first lookup; fetches from EDGAR on miss/stale.
- prefetch_universe(symbols, staleness_days): Rate-limited background job; call from a thread.
- get_prefetch_status()                     : Returns current prefetch job state dict.

Rows are upserted on composite PK (symbol, fiscal_period_end) via session.merge(), so
re-running prefetch is always safe and idempotent.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.fundamentals import FundamentalsModel

logger = logging.getLogger(__name__)

# ── Prefetch progress state (module-level singleton) ─────────────────────────

_prefetch_status: dict[str, Any] = {
    "total":       0,
    "done":        0,
    "failed":      0,
    "in_progress": False,
}

# ── Helper: DB row → FundamentalsSnapshot ────────────────────────────────────

def _row_to_snapshot(row: FundamentalsModel):
    """Convert a FundamentalsModel DB row back to a FundamentalsSnapshot.

    Derived metrics that require prior-year values (growth rates) are set to None
    because prior-year raw values are not stored in the DB.  Margins, ratios, and
    FCF are recomputed from the stored raw fields.
    """
    from app.data.edgar import FundamentalsSnapshot, _safe_div

    def _d(val) -> Decimal | None:
        """Cast a Numeric/Decimal column value to Decimal, or None."""
        if val is None:
            return None
        return Decimal(str(val))

    rev        = _d(row.revenue)
    gross      = _d(row.gross_profit)
    op_income  = _d(row.operating_income)
    ocf        = _d(row.op_cash_flow)
    capex      = _d(row.capex)
    total_debt = _d(row.total_debt)
    eq         = _d(row.stockholders_eq)
    ca         = _d(row.current_assets)
    cl         = _d(row.current_liab)

    fcf = (ocf - capex) if (ocf is not None and capex is not None) else ocf

    return FundamentalsSnapshot(
        symbol            = row.symbol,
        fiscal_period_end = row.fiscal_period_end,
        filed_date        = row.filed_date,
        cik               = row.cik or "",
        revenue           = rev,
        net_income        = _d(row.net_income),
        eps_diluted       = _d(row.eps_diluted),
        gross_profit      = gross,
        operating_income  = op_income,
        op_cash_flow      = ocf,
        capex             = capex,
        total_debt        = total_debt,
        stockholders_eq   = eq,
        current_assets    = ca,
        current_liab      = cl,
        shares_diluted    = _d(row.shares_diluted),
        # Derived — recomputed from raw fields
        gross_margin      = _safe_div(gross, rev),
        operating_margin  = _safe_div(op_income, rev),
        fcf               = fcf,
        debt_to_equity    = _safe_div(total_debt, eq),
        current_ratio     = _safe_div(ca, cl),
        # Growth rates stored in DB and read back here
        revenue_growth_yoy  = float(row.revenue_growth_yoy) if row.revenue_growth_yoy is not None else None,
        eps_growth_yoy      = float(row.eps_growth_yoy)     if row.eps_growth_yoy     is not None else None,
        share_growth_yoy    = float(row.share_growth_yoy)   if row.share_growth_yoy   is not None else None,
        # Prior-year raw — not stored in DB
        prev_revenue        = None,
        prev_eps_diluted    = None,
        prev_shares_diluted = None,
    )


# ── Helper: FundamentalsSnapshot → FundamentalsModel (for upsert) ─────────────

def _snapshot_to_model(snap) -> FundamentalsModel:
    """Build a FundamentalsModel instance from a FundamentalsSnapshot for upsert."""
    return FundamentalsModel(
        symbol            = snap.symbol,
        fiscal_period_end = snap.fiscal_period_end,
        filed_date        = snap.filed_date,
        cik               = snap.cik,
        revenue           = snap.revenue,
        net_income        = snap.net_income,
        eps_diluted       = snap.eps_diluted,
        gross_profit      = snap.gross_profit,
        operating_income  = snap.operating_income,
        op_cash_flow      = snap.op_cash_flow,
        capex             = snap.capex,
        total_debt        = snap.total_debt,
        stockholders_eq   = snap.stockholders_eq,
        current_assets    = snap.current_assets,
        current_liab      = snap.current_liab,
        shares_diluted      = snap.shares_diluted,
        revenue_growth_yoy  = snap.revenue_growth_yoy,
        eps_growth_yoy      = snap.eps_growth_yoy,
        share_growth_yoy    = snap.share_growth_yoy,
        source              = "sec_edgar",
        fetched_at          = datetime.now(timezone.utc),
    )


# ── Public API ─────────────────────────────────────────────────────────────────

async def get_fundamentals(symbol: str, staleness_days: int = 90):
    """Return a FundamentalsSnapshot for `symbol`, using the DB as a cache.

    Algorithm:
    1. Query DB for the most recent row (by fiscal_period_end DESC).
    2. If row exists and fetched_at is within staleness_days → return from DB.
    3. Otherwise fetch fresh data via edgar.get_snapshot(); upsert and return it.
    4. Return None on any error or if EDGAR has no data for this symbol.
    """
    from app.data.edgar import get_snapshot

    try:
        async with AsyncSessionLocal() as db:
            # 1. Most recent row in DB
            result = await db.execute(
                select(FundamentalsModel)
                .where(FundamentalsModel.symbol == symbol)
                .order_by(FundamentalsModel.fiscal_period_end.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()

            # 2. Check freshness
            if row is not None:
                cutoff = datetime.now(timezone.utc) - timedelta(days=staleness_days)
                fetched_at = row.fetched_at
                # Ensure tz-aware for comparison
                if fetched_at is not None:
                    if fetched_at.tzinfo is None:
                        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
                    if fetched_at >= cutoff:
                        logger.debug(
                            "fundamentals_store: cache hit for %s (fetched %s)",
                            symbol, fetched_at.date(),
                        )
                        return _row_to_snapshot(row)

            # 3. Fetch fresh from EDGAR (blocking I/O → run in thread)
            logger.debug("fundamentals_store: fetching EDGAR snapshot for %s", symbol)
            snap = await asyncio.to_thread(get_snapshot, symbol)
            if snap is None:
                logger.debug("fundamentals_store: no EDGAR data for %s", symbol)
                return None

            # Upsert via merge (handles composite PK naturally)
            model = _snapshot_to_model(snap)
            await db.merge(model)
            await db.commit()
            logger.debug(
                "fundamentals_store: upserted fundamentals for %s (period %s)",
                symbol, snap.fiscal_period_end,
            )
            return snap

    except Exception as exc:
        logger.error(
            "fundamentals_store: error fetching %s — %s", symbol, exc, exc_info=True
        )
        return None


def prefetch_universe(symbols: list[str], staleness_days: int = 90) -> None:
    """Prefetch fundamentals for all symbols (blocking; call from a background thread).

    Runs all fetches in a single event loop with a semaphore to cap concurrent
    EDGAR requests at 4, with 150 ms between each release — keeping the rate safely
    under EDGAR's 10 req/s limit while being ~4x faster than a serial loop.

    Updates _prefetch_status in-place so callers can poll get_prefetch_status().
    """
    global _prefetch_status

    _prefetch_status.update({
        "total":       len(symbols),
        "done":        0,
        "failed":      0,
        "in_progress": True,
    })

    async def _run_all() -> None:
        sem = asyncio.Semaphore(4)

        async def _fetch_one(symbol: str) -> None:
            async with sem:
                try:
                    snap = await get_fundamentals(symbol, staleness_days)
                    if snap is not None:
                        _prefetch_status["done"] += 1
                    else:
                        _prefetch_status["failed"] += 1
                except Exception as exc:
                    logger.warning("fundamentals_store prefetch: %s failed — %s", symbol, exc)
                    _prefetch_status["failed"] += 1
                await asyncio.sleep(0.15)  # rate-limit EDGAR within each semaphore slot

        await asyncio.gather(*[_fetch_one(s) for s in symbols])

    try:
        asyncio.run(_run_all())
    except Exception as exc:
        logger.error("fundamentals_store prefetch: run failed — %s", exc)

    _prefetch_status["in_progress"] = False
    logger.info(
        "fundamentals_store prefetch complete: %d done, %d failed",
        _prefetch_status["done"],
        _prefetch_status["failed"],
    )


def get_prefetch_status() -> dict:
    """Return a copy of the current prefetch status dict."""
    return dict(_prefetch_status)
