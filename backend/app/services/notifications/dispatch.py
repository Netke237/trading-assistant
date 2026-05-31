"""Shared notification dispatch — reused by chart-alert and portfolio-alert systems."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import yaml

from app.services.notifications.gmail import send_gmail
from app.services.notifications.telegram import send_telegram

logger = logging.getLogger(__name__)

_SETTINGS_PATH = Path(__file__).parent.parent.parent.parent / 'config' / 'settings.yaml'

# Strong references prevent GC from collecting fire-and-forget notification tasks.
_background_tasks: set = set()


async def _safe_notify(channel: str, **kwargs) -> None:
    try:
        if channel == 'gmail':
            await send_gmail(**kwargs)
            logger.info('Alert email sent to %s', kwargs.get('to', '?'))
        elif channel == 'telegram':
            await send_telegram(**kwargs)
            logger.info('Alert Telegram sent to chat %s', kwargs.get('chat_id', '?'))
    except Exception:
        logger.error('Alert notification failed (channel=%s)', channel, exc_info=True)


def dispatch(channel: str, **kwargs) -> None:
    """Schedule a notification as a background task, keeping a strong reference."""
    task = asyncio.create_task(_safe_notify(channel, **kwargs))
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
    """Dispatch to each channel that is enabled in settings.yaml."""
    cfg = load_notification_config()
    gmail = cfg.get('gmail', {})
    tg = cfg.get('telegram', {})

    if gmail.get('enabled'):
        dispatch('gmail',
            to=gmail.get('to', ''),
            subject=subject,
            body=plain_body,
            smtp_user=gmail.get('smtp_user', ''),
            smtp_password=gmail.get('smtp_password', ''),
        )

    if tg.get('enabled'):
        dispatch('telegram',
            bot_token=tg.get('bot_token', ''),
            chat_id=tg.get('chat_id', ''),
            text=html_body,
        )
