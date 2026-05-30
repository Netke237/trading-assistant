# backend/app/services/notifications/gmail.py
from __future__ import annotations

import asyncio
import logging
import os
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


async def send_gmail(
    to: str,
    subject: str,
    body: str,
    smtp_host: str = 'smtp.gmail.com',
    smtp_port: int = 465,
    smtp_user: str = '',
    smtp_password: str = '',
) -> None:
    """Send plain-text email via SMTP. Runs smtplib in a thread to avoid blocking."""
    user = smtp_user or os.getenv('BAMENDJOU_GMAIL_USER', '')
    password = smtp_password or os.getenv('BAMENDJOU_GMAIL_PASSWORD', '')
    if not user or not password:
        logger.warning('Gmail not configured; skipping send')
        return

    def _send() -> None:
        msg = MIMEText(body, 'plain')
        msg['Subject'] = subject
        msg['From'] = user
        msg['To'] = to
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(user, password)
            server.send_message(msg)

    logger.info('Sending email to %s via %s:%s', to, smtp_host, smtp_port)
    await asyncio.to_thread(_send)
    logger.info('Email delivered to %s', to)
