"""Persistence for portfolio alert fires (position_alert_history).

Deliberately independent of notify_alert()'s dispatch gating and dedup —
log_position_alert() runs regardless of masterEnabled/enabledTypes, so an
alert type you've muted for notifications still leaves an audit trail
answering "why did this fire". Its own dedup window (reminderIntervalHours)
exists purely to avoid one row per tick for a condition that stays true —
not to suppress rows based on user notification preferences.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import yaml
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.position_alert import PositionAlertHistoryModel

logger = logging.getLogger(__name__)

_SETTINGS_PATH = Path(__file__).parent.parent.parent / 'config' / 'settings.yaml'
_DEFAULT_REMINDER_HOURS = 4
_DEFAULT_RETENTION_DAYS = 30


def _load_delivery_config() -> dict:
    try:
        if _SETTINGS_PATH.exists():
            with open(_SETTINGS_PATH) as f:
                cfg = yaml.safe_load(f) or {}
                return cfg.get('alert_delivery', {})
    except Exception:
        logger.debug('Could not load alert_delivery config', exc_info=True)
    return {}


async def log_position_alert(
    db: AsyncSession,
    *,
    rec_id: str,
    symbol: str,
    alert_type: str,
    source: str,
    price: Optional[float] = None,
    reference_value: Optional[float] = None,
    reference_kind: Optional[str] = None,
    direction: Optional[str] = None,
    contract: Optional[str] = None,
    note: Optional[str] = None,
) -> None:
    """Write one row, deduped per (rec_id, alert_type, source[, note]) within
    the reminder window — one row per new occurrence/reminder, not per tick.
    `note` participates in the dedup key so distinct events that happen to
    share the same rec_id/alert_type/source (e.g. two different REGIME_CHANGE
    transitions, both keyed rec_id="regime") aren't suppressed as duplicates
    of each other.

    Callers pass a `db` session they own the transaction lifecycle of — this
    function NEVER commits or rolls back that session directly (a rollback
    would expire every object already loaded on it, which can crash sibling
    work still in progress on the same session, e.g. other positions in the
    same generate_alerts() loop). Instead it does its own work inside a
    SAVEPOINT (begin_nested): on success the insert is flushed and the
    savepoint released (still pending in the caller's outer transaction,
    persisted whenever the caller eventually commits); on failure only the
    savepoint rolls back, leaving the caller's session/transaction untouched.
    The caller is responsible for its own eventual commit, same as it always
    was before this call was added to its code path.
    """
    try:
        delivery = _load_delivery_config()
        hours = delivery.get('reminderIntervalHours', _DEFAULT_REMINDER_HOURS)
        try:
            window = timedelta(hours=float(hours))
        except (TypeError, ValueError):
            window = timedelta(hours=_DEFAULT_REMINDER_HOURS)

        cutoff = datetime.now(timezone.utc) - window

        async with db.begin_nested():
            conditions = [
                PositionAlertHistoryModel.rec_id == rec_id,
                PositionAlertHistoryModel.alert_type == alert_type,
                PositionAlertHistoryModel.source == source,
                PositionAlertHistoryModel.triggered_at >= cutoff,
            ]
            if note is not None:
                conditions.append(PositionAlertHistoryModel.note == note)
            existing = await db.execute(
                select(PositionAlertHistoryModel.id).where(*conditions).limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                return

            row = PositionAlertHistoryModel(
                rec_id=rec_id,
                symbol=symbol,
                alert_type=alert_type,
                source=source,
                price=price,
                reference_value=reference_value,
                reference_kind=reference_kind,
                direction=direction,
                contract=contract,
                note=note,
            )
            db.add(row)
    except Exception:
        logger.error('Failed to log position alert %s|%s|%s', rec_id, alert_type, source, exc_info=True)


async def prune_position_alert_history(db: AsyncSession, retention_days: int) -> None:
    """Delete alert-history rows older than *retention_days* days."""
    if retention_days <= 0:
        return
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        await db.execute(
            delete(PositionAlertHistoryModel).where(PositionAlertHistoryModel.triggered_at < cutoff)
        )
        await db.commit()
        logger.debug('position_alert_history pruned — cutoff %s (%d-day window)', cutoff, retention_days)
    except Exception:
        logger.error('Failed to prune position_alert_history', exc_info=True)
        await db.rollback()
