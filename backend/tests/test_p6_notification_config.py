# backend/tests/test_p6_notification_config.py
"""P6 unit B (B1/B2) -- decision P4B-FOLLOWUPS-2026-09-26, item 7.

  - a null / non-dict gmail or telegram block counts as DISABLED, and the other
    channel is still tried (it used to raise AttributeError out of
    notify_enabled_channels, so Telegram was never attempted);
  - a corrupt settings.yaml is logged at ERROR and reported unreadable;
  - the watch evaluator treats an unreadable file as channels-enabled, so an
    undelivered event is kept and resent instead of committed silently.

Every test points dispatch._SETTINGS_PATH at its own tmp file (the autouse
conftest fixture already keeps the real settings.yaml out of reach).
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

import app.services.notifications.dispatch as dispatch
from app.services.strategy_watch_evaluator import _any_channel_enabled


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "settings.yaml"
    monkeypatch.setattr(dispatch, "_SETTINGS_PATH", path)
    return path


# ── read_notification_config ─────────────────────────────────────────────────

def test_a_missing_file_is_readable_and_empty(settings_file):
    assert dispatch.read_notification_config() == ({}, True)


def test_a_corrupt_file_is_unreadable_and_logged_at_error(settings_file, caplog):
    settings_file.write_text("notifications: {gmail: [unclosed\n")
    with caplog.at_level(logging.ERROR, logger=dispatch.__name__):
        assert dispatch.read_notification_config() == ({}, False)
    assert any(r.levelno == logging.ERROR for r in caplog.records)
    # The legacy reader keeps its {} contract for chart_alerts.py's callers.
    assert dispatch.load_notification_config() == {}


def test_a_non_mapping_top_level_is_unreadable(settings_file):
    settings_file.write_text("- just\n- a list\n")
    assert dispatch.read_notification_config() == ({}, False)


@pytest.mark.parametrize("text", ["", "notifications:\n", "notifications: 7\n", "other: 1\n"])
def test_an_empty_or_non_dict_notifications_block_reads_as_nothing_enabled(settings_file, text):
    settings_file.write_text(text)
    assert dispatch.read_notification_config() == ({}, True)


def test_a_real_block_reads_back(settings_file):
    settings_file.write_text("notifications:\n  telegram:\n    enabled: true\n")
    assert dispatch.read_notification_config() == ({"telegram": {"enabled": True}}, True)


# ── notify_enabled_channels ──────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("gmail_block", ["  gmail:\n", "  gmail: off\n", "  gmail: [1, 2]\n"])
async def test_a_null_or_non_dict_gmail_block_is_disabled_and_telegram_is_still_tried(
    settings_file, gmail_block,
):
    settings_file.write_text(
        "notifications:\n" + gmail_block
        + "  telegram:\n    enabled: true\n    bot_token: t\n    chat_id: c\n"
    )
    gmail = AsyncMock(return_value=True)
    telegram = AsyncMock(return_value=True)
    with patch.object(dispatch, "send_gmail", gmail), \
         patch.object(dispatch, "send_telegram", telegram), \
         patch.object(dispatch, "log_sent"):
        delivered = await dispatch.notify_enabled_channels("s", "plain", "<b>html</b>")
    assert delivered is True
    gmail.assert_not_awaited()
    telegram.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("tg_block", ["  telegram:\n", "  telegram: off\n"])
async def test_a_null_or_non_dict_telegram_block_is_disabled_and_gmail_is_still_tried(
    settings_file, tg_block,
):
    settings_file.write_text(
        "notifications:\n  gmail:\n    enabled: true\n    to: a@b.c\n" + tg_block
    )
    gmail = AsyncMock(return_value=True)
    telegram = AsyncMock(return_value=True)
    with patch.object(dispatch, "send_gmail", gmail), \
         patch.object(dispatch, "send_telegram", telegram), \
         patch.object(dispatch, "log_sent"):
        assert await dispatch.notify_enabled_channels("s", "plain", "html") is True
    gmail.assert_awaited_once()
    telegram.assert_not_awaited()


# ── the watch evaluator ──────────────────────────────────────────────────────

def test_an_unreadable_file_counts_as_channels_enabled(settings_file):
    settings_file.write_text("notifications: {gmail: [unclosed\n")
    assert _any_channel_enabled() is True


def test_a_missing_file_counts_as_no_channel(settings_file):
    assert _any_channel_enabled() is False


def test_a_readable_file_with_everything_disabled_counts_as_no_channel(settings_file):
    settings_file.write_text("notifications:\n  gmail:\n    enabled: false\n  telegram:\n")
    assert _any_channel_enabled() is False
