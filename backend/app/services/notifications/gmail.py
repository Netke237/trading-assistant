# backend/app/services/notifications/gmail.py
from __future__ import annotations

import asyncio
import logging
import os
import re
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

_HEADER_NEWLINES_RE = re.compile(r'[\r\n]+')


def _sanitize_header_value(value: str) -> str:
    """Collapse CR/LF runs to a single space so a free-text value (e.g. an
    alert rule name pasted with a line break) can't produce a multi-line SMTP
    header.

    email.message.Message doesn't reject an embedded newline at assignment
    time -- it raises HeaderParseError/HeaderWriteError later, during
    serialization (msg.as_string() / the Generator smtplib.send_message()
    calls internally) -- and dispatch.py's _safe_notify() catches Exception
    broadly around the whole send, so that raise never surfaces anywhere. Net
    effect without this: any interpolated field containing a stray '\\r' or
    '\\n' silently drops the entire notification, every channel, with only a
    log line to show for it. A plain .replace('\\r', ' ').replace('\\n', ' ')
    would turn a CRLF pair into two spaces instead of one -- collapsing the
    whole run in one regex pass avoids that.
    """
    return _HEADER_NEWLINES_RE.sub(' ', value)


async def send_gmail(
    to: str,
    subject: str,
    body: str,
    smtp_host: str = 'smtp.gmail.com',
    smtp_port: int = 465,
    smtp_user: str = '',
    smtp_password: str = '',
) -> bool:
    """Send plain-text email via SMTP. Runs smtplib in a thread to avoid blocking."""
    user = smtp_user or os.getenv('BAMENDJOU_GMAIL_USER', '')
    password = smtp_password or os.getenv('BAMENDJOU_GMAIL_PASSWORD', '')
    if not user or not password:
        logger.warning('Gmail not configured; skipping send')
        return False

    def _send() -> None:
        msg = MIMEText(body, 'plain')
        msg['Subject'] = _sanitize_header_value(subject)
        msg['From'] = _sanitize_header_value(user)
        msg['To'] = _sanitize_header_value(to)
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(user, password)
            server.send_message(msg)

    logger.info('Sending email to %s via %s:%s', to, smtp_host, smtp_port)
    await asyncio.to_thread(_send)
    logger.info('Email delivered to %s', to)
    return True
