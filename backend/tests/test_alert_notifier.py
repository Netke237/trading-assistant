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

    async def _fake_notify(subject, plain, html):
        sent.append((subject, plain, html))
        return True

    monkeypatch.setattr(an, 'notify_enabled_channels', _fake_notify)
    return sent


async def test_master_disabled_suppresses(captured, monkeypatch):
    monkeypatch.setattr(an, '_load_delivery_config', lambda: {'masterEnabled': False})
    assert await an.notify_alert('GOOGL', 'STOP_REACHED', 'x', 'rec-1', _TS) is False
    assert captured == []


async def test_disabled_type_suppressed(captured, monkeypatch):
    monkeypatch.setattr(an, '_load_delivery_config',
                        lambda: {'masterEnabled': True, 'enabledTypes': ['TP_HIT']})
    assert await an.notify_alert('GOOGL', 'STOP_REACHED', 'x', 'rec-1', _TS) is False
    assert captured == []


async def test_dedup_within_window_suppresses_second(captured, monkeypatch):
    # Large window: the second identical call falls inside it and is deduped.
    monkeypatch.setattr(an, '_MIN_DEDUP_SECONDS', 3600)
    monkeypatch.setattr(
        an, '_load_delivery_config',
        lambda: {'masterEnabled': True, 'enabledTypes': ['STOP_REACHED'],
                 'reminderIntervalHours': 4},
    )
    assert await an.notify_alert('GOOGL', 'STOP_REACHED', 'x', 'rec-1', _TS) is True
    assert await an.notify_alert('GOOGL', 'STOP_REACHED', 'x', 'rec-1', _TS) is False
    assert len(captured) == 1


async def test_failed_delivery_does_not_permanently_suppress_retries(monkeypatch):
    """Round-8 audit finding: notify_alert used to mark the dedup key 'sent'
    the instant the send was scheduled (fire-and-forget), before delivery was
    even attempted — so a genuine failure (bad SMTP password, dead Telegram
    token, network down) got silently swallowed by the dedup window with no
    retry until it expired. notify_enabled_channels now reports whether
    anything was actually delivered, and a failed attempt must leave the key
    unmarked so the very next check retries instead of going quiet."""
    import app.services.notifications.alert_notifier as an
    an._fired.clear(); an._first_seen.clear()
    monkeypatch.setattr(an, '_MIN_DEDUP_SECONDS', 3600)  # large window
    monkeypatch.setattr(
        an, '_load_delivery_config',
        lambda: {'masterEnabled': True, 'enabledTypes': ['STOP_REACHED'],
                 'reminderIntervalHours': 4},
    )

    async def _fake_notify_fails(subject, plain, html):
        return False  # simulates every channel failing to deliver

    monkeypatch.setattr(an, 'notify_enabled_channels', _fake_notify_fails)

    # A failed attempt reports False...
    assert await an.notify_alert('GOOGL', 'STOP_REACHED', 'x', 'rec-1', _TS) is False
    # ...and does NOT arm the dedup window — the very next check retries.
    assert 'rec-1|STOP_REACHED' not in an._fired
    assert await an.notify_alert('GOOGL', 'STOP_REACHED', 'x', 'rec-1', _TS) is False


async def test_successful_delivery_after_prior_failure_arms_dedup(monkeypatch):
    """Once delivery actually succeeds, the dedup window IS armed as normal —
    only a failed send should leave the key unmarked."""
    import app.services.notifications.alert_notifier as an
    an._fired.clear(); an._first_seen.clear()
    monkeypatch.setattr(an, '_MIN_DEDUP_SECONDS', 3600)
    monkeypatch.setattr(
        an, '_load_delivery_config',
        lambda: {'masterEnabled': True, 'enabledTypes': ['STOP_REACHED'],
                 'reminderIntervalHours': 4},
    )
    sent = []

    async def _fake_notify_succeeds(subject, plain, html):
        sent.append(subject)
        return True

    monkeypatch.setattr(an, 'notify_enabled_channels', _fake_notify_succeeds)

    assert await an.notify_alert('GOOGL', 'STOP_REACHED', 'x', 'rec-1', _TS) is True
    assert 'rec-1|STOP_REACHED' in an._fired
    # A second call within the window is now correctly deduped.
    assert await an.notify_alert('GOOGL', 'STOP_REACHED', 'x', 'rec-1', _TS) is False
    assert len(sent) == 1


async def test_first_send_is_not_tagged_reminder(captured):
    assert await an.notify_alert('GOOGL', 'STOP_REACHED', 'Stop breached', 'rec-1', _TS) is True
    subject, plain, _html = captured[0]
    assert '(reminder)' not in subject
    assert 'Still active as of' not in plain


async def test_reminder_preserves_original_timestamp(captured):
    # First trigger, then a later reminder with a DIFFERENT timestamp passed in.
    assert await an.notify_alert('GOOGL', 'STOP_REACHED', 'Stop breached', 'rec-1', _TS) is True
    assert await an.notify_alert('GOOGL', 'STOP_REACHED', 'Stop breached', 'rec-1',
                           '2026-05-31T11:30:00+00:00') is True

    first_plain = captured[0][1]
    rem_subject, rem_plain, rem_html = captured[1]

    # Date/Time on the reminder match the ORIGINAL trigger, not the later one.
    assert _time_line(first_plain) == _time_line(rem_plain)
    # Reminder is clearly distinguishable.
    assert '(reminder)' in rem_subject
    assert 'Still active as of' in rem_plain
    assert 'Still active as of' in rem_html


async def test_forget_alerts_resets_first_seen(captured):
    assert await an.notify_alert('GOOGL', 'STOP_REACHED', 'x', 'rec-1', _TS) is True
    an.forget_alerts({'rec-1'})
    assert not any(k.startswith('rec-1|') for k in an._first_seen)

    # A genuine re-entry after close is a fresh first send, NOT a reminder.
    assert await an.notify_alert('GOOGL', 'STOP_REACHED', 'x', 'rec-1',
                           '2026-05-31T15:00:00+00:00') is True
    assert '(reminder)' not in captured[-1][0]


async def test_first_send_with_none_timestamp_falls_back_and_reminder_reuses_it(captured):
    # No timestamp on first send → falls back to 'now' and is stored.
    assert await an.notify_alert('GOOGL', 'STOP_REACHED', 'x', 'rec-1', None) is True
    first_time = _time_line(captured[0][1])
    # Reminder reuses that stored fallback time.
    assert await an.notify_alert('GOOGL', 'STOP_REACHED', 'x', 'rec-1', None) is True
    assert _time_line(captured[1][1]) == first_time
    assert '(reminder)' in captured[1][0]


async def test_event_risk_dispatches_when_enabled(monkeypatch):
    import app.services.notifications.alert_notifier as an
    sent = []

    async def _fake_notify(subject, plain, html):
        sent.append(subject)
        return True

    monkeypatch.setattr(an, '_load_delivery_config',
        lambda: {'masterEnabled': True,
                 'enabledTypes': ['EVENT_RISK'],
                 'reminderIntervalHours': 4})
    monkeypatch.setattr(an, 'notify_enabled_channels', _fake_notify)
    an._fired.clear(); an._first_seen.clear()
    ok = await an.notify_alert('AAPL', 'EVENT_RISK', 'Earnings in 2 days', 'REC-X')
    assert ok is True
    assert len(sent) == 1


async def test_event_risk_in_default_enabled_types(monkeypatch):
    """When settings.yaml has no enabledTypes key, the notifier falls back to
    _DEFAULT_ENABLED_TYPES — which must include EVENT_RISK so earnings/dividend
    alerts are not silently dropped by the headless monitor."""
    import app.services.notifications.alert_notifier as an
    sent = []

    async def _fake_notify(subject, plain, html):
        sent.append(subject)
        return True

    # Config WITHOUT 'enabledTypes' → notify_alert uses _DEFAULT_ENABLED_TYPES.
    monkeypatch.setattr(an, '_load_delivery_config',
        lambda: {'masterEnabled': True, 'reminderIntervalHours': 4})
    monkeypatch.setattr(an, 'notify_enabled_channels', _fake_notify)
    an._fired.clear(); an._first_seen.clear()
    ok = await an.notify_alert('AAPL', 'EVENT_RISK', 'Earnings in 2 days', 'REC-DEF')
    assert ok is True
    assert len(sent) == 1


async def test_telegram_mirrors_email_and_shows_cet(captured):
    assert await an.notify_alert('CLX', 'STOP_REACHED', 'Stop breached — CLX below $89.79',
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


async def test_reminder_telegram_headline_keeps_portfolio_prefix(captured):
    await an.notify_alert('CLX', 'STOP_REACHED', 'Stop breached — CLX below $89.79', 'rec-1', _TS)
    await an.notify_alert('CLX', 'STOP_REACHED', 'Stop breached — CLX below $89.79', 'rec-1', _TS)
    _subject, _plain, html = captured[1]
    assert html.startswith('<b>Portfolio: CLX — Stop hit</b>')
    assert 'Still active as of' in html


async def test_telegram_html_body_is_telegram_safe(captured):
    # Regression test for a real shipped bug: the html body once used <br> for
    # line breaks (both here and on a reminder line), which Telegram's HTML
    # parse_mode rejects outright -- the alert would silently fail to send over
    # Telegram while the email looked fine.
    assert await an.notify_alert('CLX', 'STOP_REACHED', 'Stop breached — CLX below $89.79',
                           'rec-1', _TS) is True
    assert await an.notify_alert('CLX', 'STOP_REACHED', 'Stop breached — CLX below $89.79',
                           'rec-1', _TS) is True  # second call -> reminder line included
    for _subject, _plain, html in captured:
        _assert_telegram_safe_html(html)
    assert 'Stop breached — CLX below $89.79' in html


async def test_reason_with_angle_bracket_is_escaped_not_parsed_as_a_tag(captured):
    # `reason` is built internally today, but nothing enforces that -- and the
    # html body interpolates it raw. A stray '<' would otherwise get parsed as
    # an (invalid) tag start and make Telegram reject the whole message, same
    # failure mode as the <br> bug via different input.
    assert await an.notify_alert('CLX', 'STOP_REACHED', 'Stop < 90 & falling', 'rec-1', _TS) is True
    _subject, _plain, html = captured[0]
    assert '&lt;' in html
    assert '&amp;' in html
    _assert_telegram_safe_html(html)


async def test_type_enabled_true_bypasses_globally_disabled_type(captured, monkeypatch):
    # Global config has STOP_REACHED disabled account-wide (fixture only enables
    # it); an explicit per-position override of True must still get through —
    # this is the whole point of Feature D's per-position alert overrides.
    monkeypatch.setattr(an, '_load_delivery_config',
        lambda: {'masterEnabled': True, 'enabledTypes': ['TP_HIT'], 'reminderIntervalHours': 0})
    assert await an.notify_alert('GOOGL', 'STOP_REACHED', 'x', 'rec-1', _TS, type_enabled=True) is True
    assert len(captured) == 1


async def test_type_enabled_false_suppresses_globally_enabled_type(captured):
    # Global config enables STOP_REACHED; an explicit per-position override of
    # False must still suppress it — muting one position must not require
    # muting the type account-wide.
    assert await an.notify_alert('GOOGL', 'STOP_REACHED', 'x', 'rec-1', _TS, type_enabled=False) is False
    assert captured == []


async def test_type_enabled_none_falls_back_to_global_enabled_types(captured, monkeypatch):
    # type_enabled=None (the default, and every caller with no override on this
    # position) must defer to the global list exactly as before Feature D.
    monkeypatch.setattr(an, '_load_delivery_config',
        lambda: {'masterEnabled': True, 'enabledTypes': ['TP_HIT'], 'reminderIntervalHours': 0})
    assert await an.notify_alert('GOOGL', 'STOP_REACHED', 'x', 'rec-1', _TS, type_enabled=None) is False
    assert captured == []


async def test_type_enabled_true_never_bypasses_master_disabled(captured, monkeypatch):
    # masterEnabled is the account-wide kill switch — a per-position override
    # must never defeat it, no matter how explicit.
    monkeypatch.setattr(an, '_load_delivery_config',
        lambda: {'masterEnabled': False, 'enabledTypes': ['STOP_REACHED'], 'reminderIntervalHours': 0})
    assert await an.notify_alert('GOOGL', 'STOP_REACHED', 'x', 'rec-1', _TS, type_enabled=True) is False
    assert captured == []


async def test_dedup_state_persists_across_reload(monkeypatch, tmp_path):
    import app.services.notifications.alert_notifier as an

    # Point persistence at a temp file and reset state.
    dedup_file = tmp_path / 'alert_dedup.json'
    monkeypatch.setattr(an, '_DEDUP_PATH', dedup_file)
    an._fired.clear(); an._first_seen.clear()
    monkeypatch.setattr(an, '_load_delivery_config',
        lambda: {'masterEnabled': True,
                 'enabledTypes': ['STOP_REACHED'],
                 'reminderIntervalHours': 4})

    async def _fake_notify(s, p, h):
        return True

    monkeypatch.setattr(an, 'notify_enabled_channels', _fake_notify)

    # First send writes the dedup file.
    assert await an.notify_alert('AAPL', 'STOP_REACHED', 'Stop breached', 'REC-1') is True
    assert dedup_file.exists()

    # Simulate a restart: wipe in-memory dicts, then reload from disk.
    an._fired.clear(); an._first_seen.clear()
    an._load_dedup()

    # Same condition must now be SUPPRESSED (deduped), not re-sent.
    assert await an.notify_alert('AAPL', 'STOP_REACHED', 'Stop breached', 'REC-1') is False


# ── STOP-SEMANTICS-2026-10-02: side-aware PREMIUM_STOP ──────────────────────

@pytest.fixture
def premium_captured(captured, monkeypatch):
    monkeypatch.setattr(
        an, '_load_delivery_config',
        lambda: {'masterEnabled': True, 'enabledTypes': ['PREMIUM_STOP', 'STOP_REACHED'],
                 'reminderIntervalHours': 4},
    )
    monkeypatch.setattr(an, '_MIN_DEDUP_SECONDS', 3600)
    return captured


@pytest.mark.parametrize('side, label', [
    ('short-stock', 'Stock stop hit (short)'),
    ('long-stock', 'Stock stop hit'),
    ('option', 'Premium stop hit'),
    (None, 'Premium stop hit'),
])
def test_premium_stop_label_follows_the_side(side, label):
    subject, plain, _ = an._build_notification('AAPL', 'PREMIUM_STOP', 'r', _TS, stop_side=side)
    assert subject.endswith(f'AAPL: {label}')
    assert plain.startswith(f'AAPL — {label}')


def test_stop_side_is_ignored_for_other_types():
    subject, _, _ = an._build_notification('AAPL', 'STOP_REACHED', 'r', _TS, stop_side='short-stock')
    assert subject.endswith('AAPL: Stop hit')
    assert an._dedup_key('rec-1', 'STOP_REACHED', 'short-stock') == 'rec-1|STOP_REACHED'


async def test_short_fire_ignores_legacy_fall_side_dedup_state(premium_captured):
    # State written under the old fall-side rule: a live hold AND a first-seen
    # date. Under one shared key the rise-side fire would be suppressed, or sent
    # as a "(reminder)" dated at the wrong-side trigger.
    an._fired['rec-1|PREMIUM_STOP'] = an.time.time()
    an._first_seen['rec-1|PREMIUM_STOP'] = '2026-01-01T07:00:00+00:00'
    assert await an.notify_alert('AAPL', 'PREMIUM_STOP', 'Stock stop — AAPL at $110.00',
                                 'rec-1', _TS, stop_side='short-stock') is True
    [(subject, plain, _)] = premium_captured
    assert '(reminder)' not in subject
    assert 'Stock stop hit (short)' in subject
    assert '01.01.2026' not in plain
    assert 'rec-1|PREMIUM_STOP:short' in an._fired


async def test_legacy_and_unstamped_fires_keep_the_legacy_key(premium_captured):
    assert await an.notify_alert('AAPL', 'PREMIUM_STOP', 'r', 'rec-1', _TS) is True
    assert await an.notify_alert('AAPL', 'PREMIUM_STOP', 'r', 'rec-2', _TS,
                                 stop_side='option') is True
    assert set(an._fired) == {'rec-1|PREMIUM_STOP', 'rec-2|PREMIUM_STOP'}


async def test_short_key_survives_a_save_and_reload(premium_captured, monkeypatch, tmp_path):
    monkeypatch.setattr(an, '_DEDUP_PATH', tmp_path / 'alert_dedup.json')
    assert await an.notify_alert('AAPL', 'PREMIUM_STOP', 'r', 'rec-1', _TS,
                                 stop_side='short-stock') is True
    an._fired.clear()
    an._first_seen.clear()
    an._load_dedup()
    assert 'rec-1|PREMIUM_STOP:short' in an._fired
    # ...and so a second fire inside the window stays deduped across a restart.
    assert await an.notify_alert('AAPL', 'PREMIUM_STOP', 'r', 'rec-1', _TS,
                                 stop_side='short-stock') is False


async def test_forget_alerts_drops_both_keys_of_a_closed_short(premium_captured, monkeypatch, tmp_path):
    monkeypatch.setattr(an, '_DEDUP_PATH', tmp_path / 'alert_dedup.json')
    an._fired['rec-1|PREMIUM_STOP'] = an.time.time()
    an._first_seen['rec-1|PREMIUM_STOP'] = _TS
    await an.notify_alert('AAPL', 'PREMIUM_STOP', 'r', 'rec-1', _TS, stop_side='short-stock')
    assert an.forget_alerts({'rec-1'}) is True
    assert not [k for k in an._fired if k.startswith('rec-1|')]
    assert not [k for k in an._first_seen if k.startswith('rec-1|')]
