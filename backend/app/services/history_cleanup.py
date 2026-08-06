"""Database history pruning and bulk-clear utilities.

prune_old_history — called periodically from the alert monitor to enforce
                    the configured retention window.
clear_all_history — called on demand from DELETE /api/portfolio/history.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.closed_position import ClosedPositionModel, EquitySnapshotModel
from app.models.portfolio import PortfolioPositionModel
from app.models.audit_event import AuditEventModel

logger = logging.getLogger(__name__)


async def prune_old_history(db: AsyncSession, retention_years: int) -> None:
    """Delete closed trades and equity snapshots older than *retention_years* years.

    String-comparison on snapshot_date works because the format is ISO 'YYYY-MM-DD',
    which sorts lexicographically in the same order as calendar time.

    Also deletes any audit_events rows (the buy-decision trade-card snapshot,
    see log_approval) for a rec_id, but ONLY once that rec_id has no remaining
    closed_positions row (rec_id isn't unique there — partial closes leave
    multiple rows) AND no open portfolio_positions row either. This ties the
    "why did I buy this" record to the same lifetime as the trade history
    itself, rather than a separate/shorter clock — a still-open or
    still-within-window position never loses its snapshot.
    """
    if retention_years <= 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_years * 365)
    cutoff_str = cutoff.strftime('%Y-%m-%d')
    try:
        stale_rec_ids = (await db.execute(
            select(ClosedPositionModel.rec_id)
            .where(ClosedPositionModel.closed_at < cutoff)
            .distinct()
        )).scalars().all()

        await db.execute(
            delete(ClosedPositionModel).where(ClosedPositionModel.closed_at < cutoff)
        )
        await db.execute(
            delete(EquitySnapshotModel).where(EquitySnapshotModel.snapshot_date < cutoff_str)
        )

        if stale_rec_ids:
            still_referenced: set[str] = set()
            still_referenced.update((await db.execute(
                select(ClosedPositionModel.rec_id).where(ClosedPositionModel.rec_id.in_(stale_rec_ids)).distinct()
            )).scalars().all())
            still_referenced.update((await db.execute(
                select(PortfolioPositionModel.rec_id).where(PortfolioPositionModel.rec_id.in_(stale_rec_ids))
            )).scalars().all())
            fully_gone = [r for r in stale_rec_ids if r not in still_referenced]
            if fully_gone:
                await db.execute(delete(AuditEventModel).where(AuditEventModel.rec_id.in_(fully_gone)))

        await db.commit()
        logger.debug('History pruned — cutoff %s (%d-year window)', cutoff_str, retention_years)
    except Exception:
        logger.error('Failed to prune old history', exc_info=True)
        await db.rollback()


async def clear_all_history(db: AsyncSession) -> None:
    """Delete every closed trade and equity snapshot row (full reset)."""
    try:
        await db.execute(delete(ClosedPositionModel))
        await db.execute(delete(EquitySnapshotModel))
        await db.commit()
        logger.info('All trade history and equity snapshots cleared')
    except Exception:
        logger.error('Failed to clear history', exc_info=True)
        await db.rollback()
