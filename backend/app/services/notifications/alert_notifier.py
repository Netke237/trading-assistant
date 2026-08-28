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

import html as html_lib
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app.services.notifications.dispatch import notify_enabled_channels

logger = logging.getLogger(__name__)

# All alert timestamps are shown in Central European time, pinned to the
# Europe/Berlin zone so the displayed clock does not depend on the server's
# local timezone. Falls back to the server local zone if tz data is missing.
try:
    from zoneinfo import ZoneInfo
    _CET = ZoneInfo('Europe/Berlin')
except Exception:
    _CET = None
_TZ_LABEL = 'CET'

_SETTINGS_PATH = Path(__file__).parent.parent.parent.parent / 'config' / 'settings.yaml'

_DEFAULT_ENABLED_TYPES = [
    'TP_HIT', 'STOP_REACHED', 'STRUCTURAL_STOP_BREACHED', 'PREMIUM_STOP', 'TIME_STOP', 'EVENT_RISK', 'REGIME_CHANGE',
]
# While a condition stays true we re-send (remind) at most once per this window.
_DEFAULT_REMINDER_HOURS = 4
# Never remind faster than this, regardless of config. Must stay STRICTLY GREATER
# than the monitor's 15-min tick interval: if it were equal, an entry written at
# tick N would sit exactly on the purge boundary at tick N+1 and scheduling jitter
# could resurrect a still-true condition into a duplicate email.
_MIN_DEDUP_SECONDS = 20 * 60

# key "recId|alertType" -> wall-clock timestamp of last send
_fired: dict[str, float] = {}
# key "recId|alertType" -> ISO timestamp of the FIRST time this condition fired.
# Survives the dedup-window purge so every reminder keeps the original trigger
# time (a reminder must not look like a brand-new alert). Cleared only when the
# position closes (forget_alerts).
_first_seen: dict[str, str] = {}
_fired_lock = threading.Lock()

# Persisted across restarts so a backend restart does NOT re-email every
# currently-breached position. Stored as wall-clock seconds (time.time()),
# NOT monotonic — monotonic resets each process and is meaningless on disk.
_DEDUP_PATH = Path(__file__).parent.parent.parent.parent / 'alert_dedup.json'


def _save_dedup() -> None:
    """Persist dedup state. Caller must hold _fired_lock."""
    try:
        with open(_DEDUP_PATH, 'w', encoding='utf-8') as f:
            json.dump({'fired': _fired, 'first_seen': _first_seen}, f)
    except Exception:
        logger.debug('Could not persist dedup state', exc_info=True)


def _load_dedup() -> None:
    """Load dedup state from disk into the in-memory dicts (idempotent)."""
    try:
        if _DEDUP_PATH.exists():
            with open(_DEDUP_PATH, encoding='utf-8') as f:
                data = json.load(f) or {}
            _fired.update({k: float(v) for k, v in data.get('fired', {}).items()})
            _first_seen.update(data.get('first_seen', {}))
    except Exception:
        logger.debug('Could not load dedup state', exc_info=True)


_load_dedup()


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
    local = dt.astimezone(_CET) if _CET else dt.astimezone()
    return local.strftime('%d.%m.%Y'), local.strftime('%H:%M:%S')


_ALERT_TYPE_LABELS = {
    'TP_HIT': 'Target reached',
    'STOP_REACHED': 'Stop hit',
    'STRUCTURAL_STOP_BREACHED': 'Structural stop hit',
    'PREMIUM_STOP': 'Premium stop hit',
    'TIME_STOP': 'Time stop hit',
    'EVENT_RISK': 'Event risk warning',
    'REGIME_CHANGE': 'Market regime changed',
}


def _build_notification(symbol: str, alert_type: str, reason: str,
                        timestamp: str | None,
                        is_reminder: bool = False) -> tuple[str, str, str]:
    # Date/Time always reflect the ORIGINAL trigger, even on reminders.
    date_str, time_str = _format_dt(timestamp)
    type_label = _ALERT_TYPE_LABELS.get(alert_type, alert_type)
    tag = ' (reminder)' if is_reminder else ''
    subject = f'Bamendjou Portfolio Alert — {symbol}: {type_label}{tag}'
    # On a reminder, note that the condition is still active as of now, without
    # disturbing the original Triggered: line above.
    still_plain = ''
    still_html = ''
    if is_reminder:
        _, now_time = _format_dt(None)  # current CET time
        still_plain = f'Still active as of {now_time} {_TZ_LABEL}\n'
        still_html = f'Still active as of {now_time} {_TZ_LABEL}\n'
    plain = (
        f'{symbol} — {type_label}\n'
        f'{reason}\n\n'
        f'Triggered: {date_str}, {time_str} {_TZ_LABEL}\n'
        f'{still_plain}'
    )
    # Telegram mirrors the email body exactly (same content, same order), with a
    # bold first line equal to the plain-language headline, prefixed with a
    # short "Portfolio:" category tag. Chart-alert and strategy-watch
    # notifications can land in the same Telegram chat as these, and neither
    # the plain-language headline nor the body distinguishes source once the
    # 2026-07-30 redesign (d9733d5) dropped the old "Bamendjou Portfolio
    # Alert" prefix -- this restores just enough context to tell them apart
    # at a glance without reverting to that verbose subject-as-headline
    # format. Telegram's HTML parse_mode only recognizes a small tag
    # allowlist (b/i/u/s/a/code/pre/blockquote) -- NOT <br> or any block tag.
    # An unsupported tag makes the Bot API reject the whole message with a
    # 400, which dispatch.py's error handling swallows into a log line with
    # no user-visible signal. Line breaks must be plain '\n', exactly like
    # the plain-text body -- Telegram renders literal newlines as line breaks
    # natively in HTML mode.
    # `reason` is built internally from f-string templates (see
    # alert_generator.py / portfolio_alert_monitor.py) so it's not truly
    # free-form user input today, but `symbol` and `alert_type` are caller-
    # supplied strings with no enforced format -- escaping all three is cheap
    # insurance against the same silent-Telegram-failure mode the <br> bug
    # caused, just via unexpected '<'/'&' characters instead of a hardcoded tag.
    html = (
        f'<b>Portfolio: {html_lib.escape(symbol)} — {html_lib.escape(type_label)}</b>\n'
        f'{html_lib.escape(reason)}\n\n'
        f'Triggered: {date_str}, {time_str} {_TZ_LABEL}\n'
        f'{still_html}'
    )
    return subject, plain, html


async def notify_alert(symbol: str, alert_type: str, reason: str, rec_id: str,
                 timestamp: str | None = None,
                 type_enabled: bool | None = None) -> bool:
    """Dispatch one portfolio alert to email/Telegram, deduped across all callers.

    Returns True if the alert was actually delivered by at least one channel,
    False if suppressed (master off, type disabled, already sent within the
    dedup window) or if delivery genuinely failed. The dedup window is only
    armed on a CONFIRMED send — a bad SMTP password or a dead Telegram bot
    token used to mark the alert "sent" the instant it was scheduled
    (fire-and-forget, outcome unobserved), which then silently suppressed
    every retry for the whole dedup window even though nothing was ever
    delivered. Now a failed attempt leaves the key unmarked so the very next
    check retries instead of going quiet.

    ``type_enabled`` carries a position's explicit per-type override (Feature D)
    and, when not None, REPLACES the global ``enabledTypes`` check for this one
    call — that is what lets a single position turn an alert type on while it
    stays off account-wide. Leave it None (the default, and every caller that
    has no position in hand) to use the global list as before. ``masterEnabled``
    is deliberately NOT bypassed: it is the user's account-wide kill switch and
    a per-position toggle must not defeat it.
    """
    delivery = _load_delivery_config()
    if not delivery.get('masterEnabled', True):
        return False

    if type_enabled is not None:
        if not type_enabled:
            return False
    else:
        enabled_types = delivery.get('enabledTypes', _DEFAULT_ENABLED_TYPES)
        if alert_type not in enabled_types:
            return False

    key = f'{rec_id}|{alert_type}'
    now = time.time()
    window = _dedup_seconds(delivery)

    with _fired_lock:
        # purge expired entries (>= so a zero-second window expires immediately)
        expired = [k for k, ts in _fired.items() if now - ts >= window]
        for k in expired:
            _fired.pop(k, None)

        if key in _fired:
            return False  # already sent within the window

        # Optimistic hold: claimed now, before the actual (async) send, so a
        # concurrent call for the same key (browser POST racing the headless
        # monitor's tick) still can't double-send during the network round
        # trip. Rolled back below if delivery doesn't actually succeed.
        _fired[key] = now
        # First-ever send for this condition records the trigger time; later
        # sends are reminders and reuse it. _first_seen outlives the dedup purge.
        original_ts = _first_seen.get(key)
        is_reminder = original_ts is not None
        if not is_reminder:
            original_ts = timestamp or datetime.now(timezone.utc).isoformat()
            _first_seen[key] = original_ts
        _save_dedup()
    subject, plain, html = _build_notification(
        symbol, alert_type, reason, original_ts, is_reminder=is_reminder)
    try:
        sent = await notify_enabled_channels(subject, plain, html)
    except Exception:
        logger.error('Failed to dispatch notification for %s', key, exc_info=True)
        sent = False

    if not sent:
        with _fired_lock:
            # Release the hold so the next check retries this condition
            # instead of staying silent for the rest of the dedup window —
            # but only if nothing newer has since claimed the key.
            if _fired.get(key) == now:
                _fired.pop(key, None)
            if not is_reminder:
                _first_seen.pop(key, None)
            _save_dedup()
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
        # Drop original-trigger records too, so a genuine re-entry later starts
        # a fresh trigger timestamp instead of inheriting the closed one.
        stale_first = {k for k in _first_seen if k.split('|', 1)[0] in rec_ids}
        for k in stale_first:
            _first_seen.pop(k, None)
        _save_dedup()
    if to_remove:
        logger.info('Cleared %d dedup entries for closed positions', len(to_remove))
