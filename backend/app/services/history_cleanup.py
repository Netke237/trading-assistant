"""Database history pruning and bulk-clear utilities.

prune_old_history — called periodically from the alert monitor to enforce
                    the configured retention window.
clear_all_history — called on demand from DELETE /api/portfolio/history.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.closed_position import ClosedPositionModel, EquitySnapshotModel

logger = logging.getLogger(__name__)


async def prune_old_history(db: AsyncSession, retention_years: int) -> None:
    """Delete closed trades and equity snapshots older than *retention_years* years.

    String-comparison on snapshot_date works because the format is ISO 'YYYY-MM-DD',
    which sorts lexicographically in the same order as calendar time.
    """
    if retention_years <= 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_years * 365)
    cutoff_str = cutoff.strftime('%Y-%m-%d')
    try:
        await db.execute(
            delete(ClosedPositionModel).where(ClosedPositionModel.closed_at < cutoff)
        )
        await db.execute(
            delete(EquitySnapshotModel).where(EquitySnapshotModel.snapshot_date < cutoff_str)
        )
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
