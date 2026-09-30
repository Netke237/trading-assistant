"""Shared notification dispatch — reused by chart-alert and portfolio-alert systems."""
from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

from app.services.notifications.gmail import send_gmail
from app.services.notifications.telegram import send_telegram
from app.services.notifications.sent_log import log_sent

logger = logging.getLogger(__name__)

_SETTINGS_PATH = Path(__file__).parent.parent.parent.parent / 'config' / 'settings.yaml'


async def _safe_notify(channel: str, _subject: str = '', **kwargs) -> bool:
    try:
        if channel == 'gmail':
            sent = await send_gmail(**kwargs)
            recipient = kwargs.get('to', '')
        elif channel == 'telegram':
            sent = await send_telegram(**kwargs)
            recipient = kwargs.get('chat_id', '')
        else:
            return False
        if sent:
            log_sent(channel, recipient, _subject)
            logger.info('Alert %s sent to %s', channel, recipient or '?')
        return bool(sent)
    except Exception:
        logger.error('Alert notification failed (channel=%s)', channel, exc_info=True)
        return False


async def dispatch(channel: str, *, _subject: str = '', **kwargs) -> bool:
    """Send one notification and report whether it was actually delivered.

    Awaited directly (not fire-and-forget) so a caller — notify_alert, in
    particular — can tell a real send failure (bad creds, network down) apart
    from success, instead of marking the alert "sent" the instant it was
    scheduled regardless of outcome.
    """
    return await _safe_notify(channel, _subject=_subject, **kwargs)


def read_notification_config() -> tuple[dict, bool]:
    """The notifications block from settings.yaml, and whether the file could be read.

    P6 (decision P4B-FOLLOWUPS-2026-09-26, item 7). `readable` is False when the
    file EXISTS but opening or parsing it failed, or its top level is not a
    mapping -- a corrupt file, which is logged at ERROR. A MISSING file is
    readable and empty: no channels configured, the fresh-install state.

    The block itself is always a dict: a `notifications:` that is null or not a
    mapping reads as {} (nothing enabled), the same rule a null channel block
    follows in notify_enabled_channels.
    """
    try:
        if not _SETTINGS_PATH.exists():
            return {}, True
        with open(_SETTINGS_PATH) as f:
            doc = yaml.safe_load(f)
    except Exception:
        logger.error('Could not read %s; notification config unavailable', _SETTINGS_PATH, exc_info=True)
        return {}, False
    if doc is None:
        return {}, True
    if not isinstance(doc, dict):
        logger.error('%s is not a mapping (got %s); notification config unavailable',
                     _SETTINGS_PATH, type(doc).__name__)
        return {}, False
    block = doc.get('notifications')
    return (block if isinstance(block, dict) else {}), True


def load_notification_config() -> dict:
    """Read the notifications block from settings.yaml ({} when unavailable).

    Unchanged contract for its callers (chart_alerts.py x3, notify_enabled_channels):
    a corrupt file still reads as {}, now logged at ERROR by the reader. A caller
    that must tell "nothing enabled" from "could not read" uses
    read_notification_config instead.
    """
    return read_notification_config()[0]


async def notify_enabled_channels(subject: str, plain_body: str, html_body: str) -> bool:
    """Dispatch to each channel that is enabled in settings.yaml.

    Credentials are read from settings.yaml first (UI-managed, gitignored file),
    with env vars (BAMENDJOU_GMAIL_PASSWORD, BAMENDJOU_TELEGRAM_BOT_TOKEN) as fallback.

    Returns True if at least one enabled channel actually delivered — callers
    (notify_alert) use this to decide whether the alert was really sent, not
    just scheduled.
    """
    cfg = load_notification_config()
    # A channel block that is null or not a mapping (`gmail:` with nothing under
    # it) counts as DISABLED, and the other channel is still tried. `.get(k, {})`
    # only covered a MISSING key: a null block raised AttributeError out of this
    # function and Telegram was never attempted.
    gmail = cfg.get('gmail')
    gmail = gmail if isinstance(gmail, dict) else {}
    tg = cfg.get('telegram')
    tg = tg if isinstance(tg, dict) else {}

    delivered = False

    if gmail.get('enabled'):
        delivered = await dispatch('gmail',
            _subject=subject,
            to=gmail.get('to', '') or os.getenv('BAMENDJOU_GMAIL_TO', ''),
            subject=subject,
            body=plain_body,
            smtp_user=gmail.get('smtp_user', '') or os.getenv('BAMENDJOU_GMAIL_USER', ''),
            smtp_password=gmail.get('smtp_password', ''),  # yaml first, gmail.py falls back to env var if empty
        ) or delivered

    if tg.get('enabled'):
        delivered = await dispatch('telegram',
            _subject=subject,
            bot_token=tg.get('bot_token', ''),  # yaml first, telegram.py falls back to env var if empty
            chat_id=tg.get('chat_id', '') or os.getenv('BAMENDJOU_TELEGRAM_CHAT_ID', ''),
            text=html_body,
        ) or delivered

    return delivered
