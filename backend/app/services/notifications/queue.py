# backend/app/services/notifications/queue.py
from __future__ import annotations

import asyncio
import logging

from app.services.notifications.gmail import send_gmail
from app.services.notifications.telegram import send_telegram

logger = logging.getLogger(__name__)
_NOTIFY_QUEUE: asyncio.Queue = asyncio.Queue(maxsize=500)


async def enqueue(channel: str, params: dict) -> None:
    """Enqueue a notification for background delivery. Never blocks."""
    try:
        _NOTIFY_QUEUE.put_nowait({'channel': channel, 'params': params})
    except asyncio.QueueFull:
        logger.warning('Notification queue full; dropping: channel=%s', channel)


async def notification_worker() -> None:
    """Background task that drains the notification queue. Started once on app startup."""
    while True:
        task = await _NOTIFY_QUEUE.get()
        try:
            if task['channel'] == 'gmail':
                await send_gmail(**task['params'])
            elif task['channel'] == 'telegram':
                await send_telegram(**task['params'])
        except Exception:
            logger.error('Notification delivery failed', exc_info=True)
