"""Alert episodes over position_alert_history (PORTFOLIO-ALERT-ACTION, #672).

Read-only. Nothing here writes, flushes or commits.

Definitions (docs/superpowers/plans/2026-11-27-portfolio-alert-action-plan.md):

- **Alert key** = ``(rec_id, alert_type)``. Rows of every source count.
- **Episode** = a maximal run of a key's fires, sorted by ``triggered_at``, in
  which consecutive fires are at most the effective gap apart.
- **Effective gap** = ``max(EPISODE_GAP_HOURS, 2 x reminderIntervalHours)``.
- **Current episode** = the key's latest episode if ``now - last <= gap``.
- **Start truncated** = ``start - gap <= now - positionAlertRetentionDays``:
  an earlier fire could have been pruned without breaking the run, so the
  start is only the earliest *known* fire and must never be shown as an exact
  date or count.
- Naive datetimes (SQLite returns them for ``DateTime(timezone=True)``) are UTC.

The constants are code constants, not settings: ``POST
/api/settings/alert-delivery`` rewrites the ``alert_delivery`` block with a
fixed key set, so a new yaml key would be dropped on the next save. They are
mirrored in ``frontend/lib/alertEpisodes.ts`` -- keep the two in step.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.position_alert import PositionAlertHistoryModel

logger = logging.getLogger(__name__)

# Keep in step with frontend/lib/alertEpisodes.ts.
EPISODE_GAP_HOURS = 72
REMINDER_PERIOD_HOURS = 24
DAILY_SUMMARY_HOUR_BERLIN = 9

_DEFAULT_REMINDER_HOURS = 4
_DEFAULT_RETENTION_DAYS = 30

_SETTINGS_PATH = Path(__file__).parent.parent.parent / 'config' / 'settings.yaml'


def load_delivery_config() -> dict:
    """The ``alert_delivery`` block of settings.yaml, read the same way
    position_alert_log / alert_notifier read it. ``{}`` when unreadable."""
    try:
        if _SETTINGS_PATH.exists():
            with open(_SETTINGS_PATH) as f:
                cfg = yaml.safe_load(f) or {}
                delivery = cfg.get('alert_delivery', {})
                return delivery if isinstance(delivery, dict) else {}
    except Exception:
        logger.debug('Could not load alert_delivery config', exc_info=True)
    return {}


@dataclass(frozen=True)
class Episode:
    start: datetime
    last: datetime
    count: int


@dataclass(frozen=True)
class EpisodeView:
    rec_id: str
    alert_type: str
    symbol: str
    start: datetime
    last: datetime
    count: int
    truncated: bool


@dataclass(frozen=True)
class EpisodeStart:
    start: datetime
    truncated: bool


def as_utc(dt: datetime) -> datetime:
    """Naive → UTC (labelled); aware → converted to UTC."""
    if dt.tzinfo is None or dt.utcoffset() is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def split_episodes(timestamps: Iterable[datetime], gap: timedelta) -> list[Episode]:
    """Split one key's fire times into episodes (oldest first). Pure.

    Consecutive fires exactly ``gap`` apart stay in the same episode; only a
    gap strictly greater than ``gap`` starts a new one.
    """
    ts = sorted(as_utc(t) for t in timestamps if t is not None)
    episodes: list[Episode] = []
    if not ts:
        return episodes
    start = last = ts[0]
    count = 1
    for t in ts[1:]:
        if t - last > gap:
            episodes.append(Episode(start=start, last=last, count=count))
            start, count = t, 0
        last = t
        count += 1
    episodes.append(Episode(start=start, last=last, count=count))
    return episodes


def _reminder_hours(delivery_cfg: Optional[dict]) -> float:
    raw = (delivery_cfg or {}).get('reminderIntervalHours', _DEFAULT_REMINDER_HOURS)
    try:
        hours = float(raw)
    except (TypeError, ValueError):
        return float(_DEFAULT_REMINDER_HOURS)
    if hours != hours or hours in (float('inf'), float('-inf')):
        return float(_DEFAULT_REMINDER_HOURS)
    return hours


def effective_gap(delivery_cfg: Optional[dict]) -> timedelta:
    """``max(72 h, 2 x reminderIntervalHours)``."""
    return max(timedelta(hours=EPISODE_GAP_HOURS), timedelta(hours=2 * _reminder_hours(delivery_cfg)))


def retention_days(delivery_cfg: Optional[dict]) -> int:
    """``positionAlertRetentionDays`` as the pruner reads it (int, default 30)."""
    raw = (delivery_cfg or {}).get('positionAlertRetentionDays', _DEFAULT_RETENTION_DAYS)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_RETENTION_DAYS


def is_start_truncated(start: datetime, now: datetime, gap: timedelta, retention: int) -> bool:
    """``start - gap <= now - retention``. A retention <= 0 disables pruning
    (prune_position_alert_history returns early), so nothing is truncated."""
    if retention <= 0:
        return False
    return as_utc(start) - gap <= as_utc(now) - timedelta(days=retention)


def format_active_duration(start: datetime, now: datetime, truncated: bool) -> str:
    """Duration text, same rules as frontend/lib/alertEpisodes.ts:
    ``< 1 h`` → "under 1 h"; ``< 24 h`` → "N h" (floor); else "N days"
    (floor of whole 24 h periods, "1 day" singular); truncated → "N+ days".
    """
    delta = as_utc(now) - as_utc(start)
    if delta < timedelta(0):
        delta = timedelta(0)
    if truncated:
        return f'{delta // timedelta(days=1)}+ days'
    if delta < timedelta(hours=1):
        return 'under 1 h'
    if delta < timedelta(hours=24):
        return f'{delta // timedelta(hours=1)} h'
    days = delta // timedelta(days=1)
    return '1 day' if days == 1 else f'{days} days'


async def _rows_by_key(
    db: AsyncSession,
    rec_ids: Iterable[str],
    alert_types: Optional[Iterable[str]] = None,
) -> dict[tuple[str, str], list[tuple[datetime, str]]]:
    ids = list(dict.fromkeys(rec_ids))
    if not ids:
        return {}
    stmt = select(
        PositionAlertHistoryModel.rec_id,
        PositionAlertHistoryModel.alert_type,
        PositionAlertHistoryModel.symbol,
        PositionAlertHistoryModel.triggered_at,
    ).where(PositionAlertHistoryModel.rec_id.in_(ids))
    if alert_types is not None:
        types = list(alert_types)
        if not types:
            return {}
        stmt = stmt.where(PositionAlertHistoryModel.alert_type.in_(types))
    stmt = stmt.order_by(
        PositionAlertHistoryModel.rec_id,
        PositionAlertHistoryModel.alert_type,
        PositionAlertHistoryModel.triggered_at,
    )
    out: dict[tuple[str, str], list[tuple[datetime, str]]] = defaultdict(list)
    for rec_id, alert_type, symbol, triggered_at in (await db.execute(stmt)).all():
        if triggered_at is None:
            continue
        out[(rec_id, alert_type)].append((as_utc(triggered_at), symbol))
    return out


def _views_for_key(
    key: tuple[str, str],
    fires: list[tuple[datetime, str]],
    now: datetime,
    gap: timedelta,
    retention: int,
) -> list[EpisodeView]:
    # Symbol of the latest fire; rows of one rec_id carry one symbol in practice.
    symbol = max(fires, key=lambda f: f[0])[1]
    return [
        EpisodeView(
            rec_id=key[0], alert_type=key[1], symbol=symbol,
            start=ep.start, last=ep.last, count=ep.count,
            truncated=is_start_truncated(ep.start, now, gap, retention),
        )
        for ep in split_episodes([f[0] for f in fires], gap)
    ]


async def all_episodes(
    db: AsyncSession,
    rec_id: str,
    now: datetime,
    *,
    delivery_cfg: Optional[dict] = None,
) -> list[EpisodeView]:
    """Every episode of every alert type for one rec_id, newest start first."""
    cfg = load_delivery_config() if delivery_cfg is None else delivery_cfg
    gap, retention = effective_gap(cfg), retention_days(cfg)
    views: list[EpisodeView] = []
    for key, fires in (await _rows_by_key(db, [rec_id])).items():
        views.extend(_views_for_key(key, fires, now, gap, retention))
    views.sort(key=lambda v: (v.start, v.alert_type), reverse=True)
    return views


async def current_episodes(
    db: AsyncSession,
    rec_ids: Iterable[str],
    now: datetime,
    alert_types: Optional[Iterable[str]] = None,
    *,
    delivery_cfg: Optional[dict] = None,
) -> dict[tuple[str, str], EpisodeView]:
    """Current episodes keyed by ``(rec_id, alert_type)``; one query.

    ``delivery_cfg`` lets a caller that also reports the gap/retention use the
    exact values the computation used; loaded from settings.yaml when omitted.
    """
    cfg = load_delivery_config() if delivery_cfg is None else delivery_cfg
    gap, retention = effective_gap(cfg), retention_days(cfg)
    now = as_utc(now)
    out: dict[tuple[str, str], EpisodeView] = {}
    for key, fires in (await _rows_by_key(db, rec_ids, alert_types)).items():
        views = _views_for_key(key, fires, now, gap, retention)
        latest = views[-1]
        if now - latest.last <= gap:
            out[key] = latest
    return out


async def episode_start(
    db: AsyncSession,
    rec_id: str,
    alert_type: str,
    now: datetime,
    *,
    delivery_cfg: Optional[dict] = None,
) -> Optional[EpisodeStart]:
    """The current episode's ``(start, truncated)`` for one key, or None."""
    view = (await current_episodes(
        db, [rec_id], now, [alert_type], delivery_cfg=delivery_cfg,
    )).get((rec_id, alert_type))
    if view is None:
        return None
    return EpisodeStart(start=view.start, truncated=view.truncated)
