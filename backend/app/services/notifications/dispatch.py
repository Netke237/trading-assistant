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


_CHANNELS = ('gmail', 'telegram')   # send order


def _channel_block(cfg: dict, name: str) -> dict:
    # A channel block that is null or not a mapping (`gmail:` with nothing under
    # it) counts as DISABLED, and the other channel is still tried. `.get(k, {})`
    # only covered a MISSING key: a null block raised AttributeError and Telegram
    # was never attempted.
    block = cfg.get(name) if isinstance(cfg, dict) else None
    return block if isinstance(block, dict) else {}


def ready_channels(cfg: dict) -> list[str]:
    """The enabled channels whose credentials are present, in send order.

    WATCH-RESEND-PER-CHANNEL: the same checks send_gmail/send_telegram make
    before they return False without sending (settings.yaml first, env vars as
    fallback). An enabled channel that fails them cannot deliver anything, so
    the strategy-watch evaluator does not wait for it.
    """
    ready = []
    gmail = _channel_block(cfg, 'gmail')
    if gmail.get('enabled') \
            and (gmail.get('smtp_user') or os.getenv('BAMENDJOU_GMAIL_USER', '')) \
            and (gmail.get('smtp_password') or os.getenv('BAMENDJOU_GMAIL_PASSWORD', '')) \
            and (gmail.get('to') or os.getenv('BAMENDJOU_GMAIL_TO', '')):
        ready.append('gmail')
    tg = _channel_block(cfg, 'telegram')
    if tg.get('enabled') \
            and (tg.get('bot_token') or os.getenv('BAMENDJOU_TELEGRAM_BOT_TOKEN', '')) \
            and (tg.get('chat_id') or os.getenv('BAMENDJOU_TELEGRAM_CHAT_ID', '')):
        ready.append('telegram')
    return ready


async def _send_channels(cfg: dict, subject: str, plain_body: str, html_body: str,
                         channels=None) -> dict[str, bool]:
    """Send to each channel enabled in cfg (restricted to `channels` when given);
    {channel: delivered} for every channel ATTEMPTED."""
    gmail = _channel_block(cfg, 'gmail')
    tg = _channel_block(cfg, 'telegram')
    wanted = _CHANNELS if channels is None else tuple(channels)

    result: dict[str, bool] = {}

    if 'gmail' in wanted and gmail.get('enabled'):
        result['gmail'] = await dispatch('gmail',
            _subject=subject,
            to=gmail.get('to', '') or os.getenv('BAMENDJOU_GMAIL_TO', ''),
            subject=subject,
            body=plain_body,
            smtp_user=gmail.get('smtp_user', '') or os.getenv('BAMENDJOU_GMAIL_USER', ''),
            smtp_password=gmail.get('smtp_password', ''),  # yaml first, gmail.py falls back to env var if empty
        )

    if 'telegram' in wanted and tg.get('enabled'):
        result['telegram'] = await dispatch('telegram',
            _subject=subject,
            bot_token=tg.get('bot_token', ''),  # yaml first, telegram.py falls back to env var if empty
            chat_id=tg.get('chat_id', '') or os.getenv('BAMENDJOU_TELEGRAM_CHAT_ID', ''),
            text=html_body,
        )

    return result


async def notify_channels(cfg: dict, subject: str, plain_body: str, html_body: str,
                          channels) -> dict[str, bool]:
    """Per-channel delivery with an ALREADY-READ config (WATCH-RESEND-PER-CHANNEL).

    Attempts each listed channel that is enabled in cfg, Gmail then Telegram;
    returns {channel: delivered} for each one attempted. A channel listed but
    not enabled is not attempted and is absent from the result.
    """
    return await _send_channels(cfg, subject, plain_body, html_body, channels)


async def notify_enabled_channels(subject: str, plain_body: str, html_body: str) -> bool:
    """Dispatch to each channel that is enabled in settings.yaml.

    Credentials are read from settings.yaml first (UI-managed, gitignored file),
    with env vars (BAMENDJOU_GMAIL_PASSWORD, BAMENDJOU_TELEGRAM_BOT_TOKEN) as fallback.

    Returns True if at least one enabled channel actually delivered — callers
    (notify_alert) use this to decide whether the alert was really sent, not
    just scheduled.
    """
    cfg = load_notification_config()
    return any((await _send_channels(cfg, subject, plain_body, html_body)).values())
