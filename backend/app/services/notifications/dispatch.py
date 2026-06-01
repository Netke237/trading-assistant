"""Shared notification dispatch — reused by chart-alert and portfolio-alert systems."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import yaml

from app.services.notifications.gmail import send_gmail
from app.services.notifications.telegram import send_telegram
from app.services.notifications.sent_log import log_sent

logger = logging.getLogger(__name__)

_SETTINGS_PATH = Path(__file__).parent.parent.parent.parent / 'config' / 'settings.yaml'

# Strong references prevent GC from collecting fire-and-forget notification tasks.
_background_tasks: set = set()


async def _safe_notify(channel: str, _subject: str = '', **kwargs) -> None:
    try:
        if channel == 'gmail':
            sent = await send_gmail(**kwargs)
            recipient = kwargs.get('to', '')
        elif channel == 'telegram':
            sent = await send_telegram(**kwargs)
            recipient = kwargs.get('chat_id', '')
        else:
            return
        if sent:
            log_sent(channel, recipient, _subject)
            logger.info('Alert %s sent to %s', channel, recipient or '?')
    except Exception:
        logger.error('Alert notification failed (channel=%s)', channel, exc_info=True)


def dispatch(channel: str, *, _subject: str = '', **kwargs) -> None:
    """Schedule a notification as a background task, keeping a strong reference."""
    task = asyncio.create_task(_safe_notify(channel, _subject=_subject, **kwargs))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


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


def notify_enabled_channels(subject: str, plain_body: str, html_body: str) -> None:
    """Dispatch to each channel that is enabled in settings.yaml.

    Credentials (smtp_password, bot_token) are intentionally NOT read from
    settings.yaml — they live in env vars (BAMENDJOU_GMAIL_PASSWORD,
    BAMENDJOU_TELEGRAM_BOT_TOKEN) and gmail.py / telegram.py pick them up
    automatically when the argument is empty string.
    """
    cfg = load_notification_config()
    gmail = cfg.get('gmail', {})
    tg = cfg.get('telegram', {})

    if gmail.get('enabled'):
        dispatch('gmail',
            _subject=subject,
            to=gmail.get('to', '') or os.getenv('BAMENDJOU_GMAIL_TO', ''),
            subject=subject,
            body=plain_body,
            smtp_user=gmail.get('smtp_user', '') or os.getenv('BAMENDJOU_GMAIL_USER', ''),
            smtp_password='',  # empty → gmail.py falls back to BAMENDJOU_GMAIL_PASSWORD
        )

    if tg.get('enabled'):
        dispatch('telegram',
            _subject=subject,
            bot_token='',      # empty → telegram.py falls back to BAMENDJOU_TELEGRAM_BOT_TOKEN
            chat_id=tg.get('chat_id', '') or os.getenv('BAMENDJOU_TELEGRAM_CHAT_ID', ''),
            text=html_body,
        )
