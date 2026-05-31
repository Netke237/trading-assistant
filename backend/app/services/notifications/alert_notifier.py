"""Single source of truth for portfolio-alert notification dispatch.

Both the browser (via POST /api/alerts/notify) and the headless background
monitor (portfolio_alert_monitor) funnel through `notify_alert` here, so the
two paths share ONE dedup set. This guarantees:

  * what the user sees in-app gets emailed/Telegrammed (browser path), and
  * a browser-closed user still gets emails (monitor fallback path),

without the same trigger being sent twice — whichever path fires first wins,
the other is deduped.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app.services.notifications.dispatch import notify_enabled_channels

logger = logging.getLogger(__name__)

_SETTINGS_PATH = Path(__file__).parent.parent.parent.parent / 'config' / 'settings.yaml'

_DEFAULT_ENABLED_TYPES = [
    'TP_HIT', 'STOP_REACHED', 'PREMIUM_STOP', 'TIME_STOP', 'REGIME_CHANGE',
]
# While a condition stays true we re-send (remind) at most once per this window.
_DEFAULT_REMINDER_HOURS = 4
# Never remind faster than this, regardless of config. Must stay STRICTLY GREATER
# than the monitor's 15-min tick interval: if it were equal, an entry written at
# tick N would sit exactly on the purge boundary at tick N+1 and scheduling jitter
# could resurrect a still-true condition into a duplicate email.
_MIN_DEDUP_SECONDS = 20 * 60

# key "recId|alertType" -> monotonic timestamp of last send
_fired: dict[str, float] = {}
_fired_lock = threading.Lock()


def _load_delivery_config() -> dict:
    try:
        if _SETTINGS_PATH.exists():
            with open(_SETTINGS_PATH) as f:
                cfg = yaml.safe_load(f) or {}
                return cfg.get('alert_delivery', {})
    except Exception:
        logger.debug('Could not load alert_delivery config', exc_info=True)
    return {}


def _dedup_seconds(delivery: dict) -> float:
    hours = delivery.get('reminderIntervalHours', _DEFAULT_REMINDER_HOURS)
    try:
        secs = float(hours) * 3600.0
    except (TypeError, ValueError):
        secs = _DEFAULT_REMINDER_HOURS * 3600.0
    return max(secs, _MIN_DEDUP_SECONDS)


def _format_dt(timestamp: str | None) -> tuple[str, str]:
    """Parse an ISO timestamp (UTC) into local (date, time) strings.

    Returns ('dd.mm.yyyy', 'HH:MM:SS'). Falls back to the current time when the
    timestamp is missing or unparseable.
    """
    dt: datetime | None = None
    if timestamp:
        try:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        except ValueError:
            dt = None
    if dt is None:
        dt = datetime.now(timezone.utc)
    local = dt.astimezone()  # convert to the server's local timezone
    return local.strftime('%d.%m.%Y'), local.strftime('%H:%M:%S')


def _build_notification(symbol: str, alert_type: str, reason: str,
                        timestamp: str | None) -> tuple[str, str, str]:
    date_str, time_str = _format_dt(timestamp)
    subject = f'Bamendjou Alert — {symbol} [{alert_type}]'
    plain = (
        f'Symbol:  {symbol}\n'
        f'Type:    {alert_type}\n'
        f'Trigger: {reason}\n'
        f'Date:    {date_str}\n'
        f'Time:    {time_str}\n'
    )
    html = (
        f'<b>Bamendjou Alert</b> — {symbol}\n\n'
        f'<b>Type:</b> {alert_type}\n'
        f'<b>Trigger:</b> {reason}\n'
        f'<b>Date:</b> {date_str}\n'
        f'<b>Time:</b> {time_str}\n'
    )
    return subject, plain, html


def notify_alert(symbol: str, alert_type: str, reason: str, rec_id: str,
                 timestamp: str | None = None) -> bool:
    """Dispatch one portfolio alert to email/Telegram, deduped across all callers.

    Returns True if the alert was dispatched, False if suppressed (master off,
    type disabled, or already sent within the dedup window).
    """
    delivery = _load_delivery_config()
    if not delivery.get('masterEnabled', True):
        return False

    enabled_types = delivery.get('enabledTypes', _DEFAULT_ENABLED_TYPES)
    if alert_type not in enabled_types:
        return False

    key = f'{rec_id}|{alert_type}'
    now = time.monotonic()
    window = _dedup_seconds(delivery)

    with _fired_lock:
        # purge expired entries
        expired = [k for k, ts in _fired.items() if now - ts > window]
        for k in expired:
            _fired.pop(k, None)

        if key in _fired:
            return False  # already sent within the window

        _fired[key] = now
    subject, plain, html = _build_notification(symbol, alert_type, reason, timestamp)
    try:
        notify_enabled_channels(subject, plain, html)
    except Exception:
        logger.error('Failed to dispatch notification for %s', key, exc_info=True)
        return False
    logger.info('Dispatched alert notification: %s', key)
    return True


def forget_alerts(rec_ids: set[str]) -> None:
    """Drop dedup entries for the given recIds so a re-entry can alert again.

    Called by the monitor when positions disappear from the portfolio.
    """
    if not rec_ids:
        return
    with _fired_lock:
        to_remove = {k for k in _fired if k.split('|', 1)[0] in rec_ids}
        for k in to_remove:
            _fired.pop(k, None)
    if to_remove:
        logger.info('Cleared %d dedup entries for closed positions', len(to_remove))
