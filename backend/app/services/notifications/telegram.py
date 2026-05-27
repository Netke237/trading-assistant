# backend/app/services/notifications/telegram.py
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)
TELEGRAM_API = 'https://api.telegram.org'


async def send_telegram(
    bot_token: str = '',
    chat_id: str = '',
    text: str = '',
) -> None:
    """Send message via Telegram Bot API."""
    token = bot_token or os.getenv('BAMENDJOU_TELEGRAM_BOT_TOKEN', '')
    cid = chat_id or os.getenv('BAMENDJOU_TELEGRAM_CHAT_ID', '')
    if not token or not cid:
        logger.warning('Telegram not configured; skipping send')
        return

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f'{TELEGRAM_API}/bot{token}/sendMessage',
            json={'chat_id': cid, 'text': text, 'parse_mode': 'HTML'},
            timeout=10,
        )
        resp.raise_for_status()
