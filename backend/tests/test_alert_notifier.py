"""Tests for alert_notifier.notify_alert — the shared dedup + reminder chokepoint.

Covers: master/type gating, dedup within the window, and the reminder behaviour
(original trigger timestamp preserved, '(reminder)' tag + 'Still active' line,
and reset on position close via forget_alerts).
"""
from __future__ import annotations

import re

import pytest

import app.services.notifications.alert_notifier as an

# Telegram's HTML parse_mode only recognizes this tag allowlist -- anything else
# (including <br> or any block tag) makes the Bot API reject the whole message
# with a 400 that dispatch.py's error handling silently swallows into a log line.
_TELEGRAM_ALLOWED_TAGS = {
    'b', 'strong', 'i', 'em', 'u', 'ins', 's', 'strike', 'del',
    'span', 'a', 'code', 'pre', 'blockquote', 'tg-spoiler', 'tg-emoji',
}


def _assert_telegram_safe_html(html: str) -> None:
    for tag in re.findall(r'<\s*/?\s*([a-zA-Z0-9-]+)', html):
        assert tag.lower() in _TELEGRAM_ALLOWED_TAGS, (
            f'<{tag}> is not in Telegram\'s HTML parse_mode allowlist -- '
            f'sending this will make the Bot API reject the whole message'
        )

_TS = '2026-05-31T07:00:00+00:00'  # original trigger (UTC)


def _time_line(plain: str) -> str:
    return next(line for line in plain.splitlines() if line.startswith('Triggered:'))


@pytest.fixture
def captured(monkeypatch):
    """Reset notifier state, capture dispatched notifications, never hit channels."""
    an._fired.clear()
    an._first_seen.clear()
    # window 0 → second send for the same key is treated as a due reminder
    monkeypatch.setattr(an, '_MIN_DEDUP_SECONDS', 0)
    monkeypatch.setattr(
        an, '_load_delivery_config',
        lambda: {'masterEnabled': True, 'enabledTypes': ['STOP_REACHED'],
                 'reminderIntervalHours': 0},
    )
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(an, 'notify_enabled_channels',
                        lambda subject, plain, html: sent.append((subject, plain, html)))
    return sent


def test_master_disabled_suppresses(captured, monkeypatch):
    monkeypatch.setattr(an, '_load_delivery_config', lambda: {'masterEnabled': False})
    assert an.notify_alert('GOOGL', 'STOP_REACHED', 'x', 'rec-1', _TS) is False
    assert captured == []


def test_disabled_type_suppressed(captured, monkeypatch):
    monkeypatch.setattr(an, '_load_delivery_config',
                        lambda: {'masterEnabled': True, 'enabledTypes': ['TP_HIT']})
    assert an.notify_alert('GOOGL', 'STOP_REACHED', 'x', 'rec-1', _TS) is False
    assert captured == []


def test_dedup_within_window_suppresses_second(captured, monkeypatch):
    # Large window: the second identical call falls inside it and is deduped.
    monkeypatch.setattr(an, '_MIN_DEDUP_SECONDS', 3600)
    monkeypatch.setattr(
        an, '_load_delivery_config',
        lambda: {'masterEnabled': True, 'enabledTypes': ['STOP_REACHED'],
                 'reminderIntervalHours': 4},
    )
    assert an.notify_alert('GOOGL', 'STOP_REACHED', 'x', 'rec-1', _TS) is True
    assert an.notify_alert('GOOGL', 'STOP_REACHED', 'x', 'rec-1', _TS) is False
    assert len(captured) == 1


def test_first_send_is_not_tagged_reminder(captured):
    assert an.notify_alert('GOOGL', 'STOP_REACHED', 'Stop breached', 'rec-1', _TS) is True
    subject, plain, _html = captured[0]
    assert '(reminder)' not in subject
    assert 'Still active as of' not in plain


def test_reminder_preserves_original_timestamp(captured):
    # First trigger, then a later reminder with a DIFFERENT timestamp passed in.
    assert an.notify_alert('GOOGL', 'STOP_REACHED', 'Stop breached', 'rec-1', _TS) is True
    assert an.notify_alert('GOOGL', 'STOP_REACHED', 'Stop breached', 'rec-1',
                           '2026-05-31T11:30:00+00:00') is True

    first_plain = captured[0][1]
    rem_subject, rem_plain, rem_html = captured[1]

    # Date/Time on the reminder match the ORIGINAL trigger, not the later one.
    assert _time_line(first_plain) == _time_line(rem_plain)
    # Reminder is clearly distinguishable.
    assert '(reminder)' in rem_subject
    assert 'Still active as of' in rem_plain
    assert 'Still active as of' in rem_html


def test_forget_alerts_resets_first_seen(captured):
    assert an.notify_alert('GOOGL', 'STOP_REACHED', 'x', 'rec-1', _TS) is True
    an.forget_alerts({'rec-1'})
    assert not any(k.startswith('rec-1|') for k in an._first_seen)

    # A genuine re-entry after close is a fresh first send, NOT a reminder.
    assert an.notify_alert('GOOGL', 'STOP_REACHED', 'x', 'rec-1',
                           '2026-05-31T15:00:00+00:00') is True
    assert '(reminder)' not in captured[-1][0]


def test_first_send_with_none_timestamp_falls_back_and_reminder_reuses_it(captured):
    # No timestamp on first send → falls back to 'now' and is stored.
    assert an.notify_alert('GOOGL', 'STOP_REACHED', 'x', 'rec-1', None) is True
    first_time = _time_line(captured[0][1])
    # Reminder reuses that stored fallback time.
    assert an.notify_alert('GOOGL', 'STOP_REACHED', 'x', 'rec-1', None) is True
    assert _time_line(captured[1][1]) == first_time
    assert '(reminder)' in captured[1][0]


def test_event_risk_dispatches_when_enabled(monkeypatch):
    import app.services.notifications.alert_notifier as an
    sent = []
    monkeypatch.setattr(an, '_load_delivery_config',
        lambda: {'masterEnabled': True,
                 'enabledTypes': ['EVENT_RISK'],
                 'reminderIntervalHours': 4})
    monkeypatch.setattr(an, 'notify_enabled_channels',
        lambda subject, plain, html: sent.append(subject))
    an._fired.clear(); an._first_seen.clear()
    ok = an.notify_alert('AAPL', 'EVENT_RISK', 'Earnings in 2 days', 'REC-X')
    assert ok is True
    assert len(sent) == 1


def test_event_risk_in_default_enabled_types(monkeypatch):
    """When settings.yaml has no enabledTypes key, the notifier falls back to
    _DEFAULT_ENABLED_TYPES — which must include EVENT_RISK so earnings/dividend
    alerts are not silently dropped by the headless monitor."""
    import app.services.notifications.alert_notifier as an
    sent = []
    # Config WITHOUT 'enabledTypes' → notify_alert uses _DEFAULT_ENABLED_TYPES.
    monkeypatch.setattr(an, '_load_delivery_config',
        lambda: {'masterEnabled': True, 'reminderIntervalHours': 4})
    monkeypatch.setattr(an, 'notify_enabled_channels',
        lambda subject, plain, html: sent.append(subject))
    an._fired.clear(); an._first_seen.clear()
    ok = an.notify_alert('AAPL', 'EVENT_RISK', 'Earnings in 2 days', 'REC-DEF')
    assert ok is True
    assert len(sent) == 1


def test_telegram_mirrors_email_and_shows_cet(captured):
    assert an.notify_alert('CLX', 'STOP_REACHED', 'Stop breached — CLX below $89.79',
                           'rec-1', _TS) is True
    subject, plain, html = captured[0]

    # Time is labelled CET in both channels.
    assert 'CET' in _time_line(plain)
    assert 'CET' in html

    # Telegram body carries the same plain-language content as the email body:
    # symbol + human-readable type label, the reason, and a Triggered: line.
    for text in ('CLX', 'Stop hit', 'Triggered:'):
        assert text in plain
        assert text in html
    # Telegram's bold first line restores a short "Portfolio:" category tag so
    # portfolio alerts stay visually distinguishable from chart-alert and
    # strategy-watch alerts landing in the same Telegram chat, while keeping
    # the plain-language "symbol — type" headline from the July 30 redesign
    # (it does not revert to the old verbose "Bamendjou Portfolio Alert —
    # SYMBOL [ALERT_TYPE]" subject line).
    assert html.startswith('<b>Portfolio: CLX — Stop hit</b>')
    # Symbol and trigger text appear in the Telegram message.
    assert 'CLX' in html


def test_reminder_telegram_headline_keeps_portfolio_prefix(captured):
    an.notify_alert('CLX', 'STOP_REACHED', 'Stop breached — CLX below $89.79', 'rec-1', _TS)
    an.notify_alert('CLX', 'STOP_REACHED', 'Stop breached — CLX below $89.79', 'rec-1', _TS)
    _subject, _plain, html = captured[1]
    assert html.startswith('<b>Portfolio: CLX — Stop hit</b>')
    assert 'Still active as of' in html


def test_telegram_html_body_is_telegram_safe(captured):
    # Regression test for a real shipped bug: the html body once used <br> for
    # line breaks (both here and on a reminder line), which Telegram's HTML
    # parse_mode rejects outright -- the alert would silently fail to send over
    # Telegram while the email looked fine.
    assert an.notify_alert('CLX', 'STOP_REACHED', 'Stop breached — CLX below $89.79',
                           'rec-1', _TS) is True
    assert an.notify_alert('CLX', 'STOP_REACHED', 'Stop breached — CLX below $89.79',
                           'rec-1', _TS) is True  # second call -> reminder line included
    for _subject, _plain, html in captured:
        _assert_telegram_safe_html(html)
    assert 'Stop breached — CLX below $89.79' in html


def test_reason_with_angle_bracket_is_escaped_not_parsed_as_a_tag(captured):
    # `reason` is built internally today, but nothing enforces that -- and the
    # html body interpolates it raw. A stray '<' would otherwise get parsed as
    # an (invalid) tag start and make Telegram reject the whole message, same
    # failure mode as the <br> bug via different input.
    assert an.notify_alert('CLX', 'STOP_REACHED', 'Stop < 90 & falling', 'rec-1', _TS) is True
    _subject, _plain, html = captured[0]
    assert '&lt;' in html
    assert '&amp;' in html
    _assert_telegram_safe_html(html)


def test_dedup_state_persists_across_reload(monkeypatch, tmp_path):
    import app.services.notifications.alert_notifier as an

    # Point persistence at a temp file and reset state.
    dedup_file = tmp_path / 'alert_dedup.json'
    monkeypatch.setattr(an, '_DEDUP_PATH', dedup_file)
    an._fired.clear(); an._first_seen.clear()
    monkeypatch.setattr(an, '_load_delivery_config',
        lambda: {'masterEnabled': True,
                 'enabledTypes': ['STOP_REACHED'],
                 'reminderIntervalHours': 4})
    monkeypatch.setattr(an, 'notify_enabled_channels', lambda s, p, h: None)

    # First send writes the dedup file.
    assert an.notify_alert('AAPL', 'STOP_REACHED', 'Stop breached', 'REC-1') is True
    assert dedup_file.exists()

    # Simulate a restart: wipe in-memory dicts, then reload from disk.
    an._fired.clear(); an._first_seen.clear()
    an._load_dedup()

    # Same condition must now be SUPPRESSED (deduped), not re-sent.
    assert an.notify_alert('AAPL', 'STOP_REACHED', 'Stop breached', 'REC-1') is False
