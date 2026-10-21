"""Shared helpers for tests that drive the strategy-watch evaluator's delivery
(WATCH-RESEND-PER-CHANNEL). The evaluator sends through dispatch.notify_channels
(per channel, with the run's already-read config) instead of
notify_enabled_channels' single bool.

Import `configured_channels_no_real_sends` into a test module to activate it there
(autouse): it makes every channel a test config ENABLES also ready (credential env
vars set to dummies) and fails the test at teardown if a real Gmail/Telegram send
was attempted -- checked at teardown because dispatch._safe_notify swallows raises.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

_CRED_ENV = ("BAMENDJOU_GMAIL_USER", "BAMENDJOU_GMAIL_PASSWORD", "BAMENDJOU_GMAIL_TO",
             "BAMENDJOU_TELEGRAM_BOT_TOKEN", "BAMENDJOU_TELEGRAM_CHAT_ID")


def per_channel(notify):
    """Adapt a bool fake notify(subject, plain, html) to notify_channels'
    signature: awaited ONCE per call, its result given to every requested
    channel (call counts and await_args subjects are unchanged)."""
    async def _notify_channels(cfg, subject, plain, html, channels):
        delivered = bool(await notify(subject, plain, html))
        return {c: delivered for c in channels}
    return _notify_channels


@pytest.fixture(autouse=True)
def configured_channels_no_real_sends(monkeypatch):
    for name in _CRED_ENV:
        monkeypatch.setenv(name, "test-dummy")
    gmail, telegram = AsyncMock(return_value=False), AsyncMock(return_value=False)
    with patch("app.services.notifications.dispatch.send_gmail", gmail), \
            patch("app.services.notifications.dispatch.send_telegram", telegram):
        yield
    assert not gmail.called and not telegram.called, "a real notification send was attempted"
