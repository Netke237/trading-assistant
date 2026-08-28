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


def load_notification_config() -> dict:
    """Read the notifications block from settings.yaml."""
    try:
        if _SETTINGS_PATH.exists():
            with open(_SETTINGS_PATH) as f:
                cfg = yaml.safe_load(f) or {}
                return cfg.get('notifications', {})
    except Exception:
        logger.debug('Could not load notification config', exc_info=True)
    return {}


async def notify_enabled_channels(subject: str, plain_body: str, html_body: str) -> bool:
    """Dispatch to each channel that is enabled in settings.yaml.

    Credentials are read from settings.yaml first (UI-managed, gitignored file),
    with env vars (BAMENDJOU_GMAIL_PASSWORD, BAMENDJOU_TELEGRAM_BOT_TOKEN) as fallback.

    Returns True if at least one enabled channel actually delivered — callers
    (notify_alert) use this to decide whether the alert was really sent, not
    just scheduled.
    """
    cfg = load_notification_config()
    gmail = cfg.get('gmail', {})
    tg = cfg.get('telegram', {})

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
