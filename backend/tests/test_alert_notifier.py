"""Tests for alert_notifier.notify_alert — the shared dedup + reminder chokepoint.

Covers: master/type gating, dedup within the window, and the reminder behaviour
(original trigger timestamp preserved, '(reminder)' tag + 'Still active' line,
and reset on position close via forget_alerts).
"""
from __future__ import annotations

import pytest

import app.services.notifications.alert_notifier as an

_TS = '2026-05-31T07:00:00+00:00'  # original trigger (UTC)


def _time_line(plain: str) -> str:
    return next(line for line in plain.splitlines() if line.startswith('Time:'))


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
