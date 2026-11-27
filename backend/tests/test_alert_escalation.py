"""PORTFOLIO-ALERT-ACTION T2 — escalation: episode cadence + daily summary.

Plan: docs/superpowers/plans/2026-11-27-portfolio-alert-action-plan.md,
"Definitions" and "### 2. Escalation (backend notifications)".

Episode-notified types (POSITION_ALERT_TYPES, rec_id != 'regime') send one
first-fire message per episode and at most one reminder per 24 h, from a
per-key record in alert_dedup.json (rules 1-6). REGIME_CHANGE and the
auto-trader's AUTO_TRADE_* types keep the reminderIntervalHours window path.
The monitor sends one daily summary per Berlin day from 09:00.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.services.notifications.alert_notifier as an
from app.database import Base
from app.models.portfolio import PortfolioPositionModel
from app.models.position_alert import PositionAlertHistoryModel
from app.schemas import AlertItem
from app.services.alert_episodes import (
    EpisodeStart,
    EpisodeView,
    effective_gap,
    is_start_truncated,
)

UTC = timezone.utc
H = timedelta(hours=1)
D = timedelta(days=1)
M = timedelta(minutes=1)

# 07:00 UTC on 2 Nov 2026 = 08:00 Berlin (CET, UTC+1).
T0 = datetime(2026, 11, 2, 7, 0, tzinfo=UTC)

ALL_TYPES = ['TP_HIT', 'STOP_REACHED', 'STRUCTURAL_STOP_BREACHED', 'PREMIUM_STOP',
             'TIME_STOP', 'EVENT_RISK', 'REGIME_CHANGE']
CFG = {'masterEnabled': True, 'enabledTypes': list(ALL_TYPES),
       'reminderIntervalHours': 4, 'positionAlertRetentionDays': 30}


def _triggered(plain: str) -> str:
    return next(line for line in plain.splitlines() if line.startswith('Triggered:'))


@pytest.fixture
def cfg(monkeypatch):
    holder = json.loads(json.dumps(CFG))
    monkeypatch.setattr(an, '_load_delivery_config', lambda: holder)
    return holder


@pytest.fixture
def clock(monkeypatch):
    state = {'now': T0}
    monkeypatch.setattr(an, '_now', lambda: state['now'].timestamp())
    return state


class _Sent(list):
    state: dict


@pytest.fixture
def sent(monkeypatch):
    out = _Sent()
    state = {'ok': True}

    async def _fake(subject, plain, html):
        if not state['ok']:
            return False
        out.append((subject, plain, html))
        return True

    monkeypatch.setattr(an, 'notify_enabled_channels', _fake)
    out.state = state
    return out


async def _fire(alert_type='STOP_REACHED', rec_id='rec-1', symbol='BMY',
                episode_start=None, **kw):
    return await an.notify_alert(symbol, alert_type, 'Stop breached', rec_id,
                                 None, episode_start=episode_start, **kw)


# ── Episode-notified types: rules 1-6 ─────────────────────────────────────────

async def test_first_fire_sends_once_dated_at_the_history_start(cfg, clock, sent):
    start = T0 - 2 * H
    assert await _fire(episode_start=EpisodeStart(start, False)) is True
    assert len(sent) == 1
    subject, plain, _ = sent[0]
    assert '(reminder)' not in subject
    # 05:00 UTC = 06:00 CET
    assert _triggered(plain) == 'Triggered: 02.11.2026, 06:00:00 CET'
    assert 'Active for' not in plain


async def test_same_day_repeats_are_suppressed(cfg, clock, sent):
    assert await _fire() is True
    for offset in (M, H, 12 * H, 23 * H):
        clock['now'] = T0 + offset
        assert await _fire() is False
    assert len(sent) == 1


async def test_reminder_at_24h_not_at_23h59(cfg, clock, sent):
    es = EpisodeStart(T0, False)
    assert await _fire(episode_start=es) is True
    clock['now'] = T0 + 23 * H + 59 * M
    assert await _fire(episode_start=es) is False
    clock['now'] = T0 + 24 * H
    assert await _fire(episode_start=es) is True
    subject, plain, html = sent[-1]
    assert '(reminder)' in subject
    assert _triggered(plain) == 'Triggered: 02.11.2026, 08:00:00 CET'
    assert 'Active for 1 day (since 02.11.2026)' in plain
    assert 'Active for 1 day (since 02.11.2026)' in html
    assert 'Still active as of' in plain
    # the next reminder is 24 h after this send, not after the first
    clock['now'] = T0 + 47 * H
    assert await _fire(episode_start=es) is False
    clock['now'] = T0 + 48 * H
    assert await _fire(episode_start=es) is True
    assert len(sent) == 3


async def test_gap_over_72h_starts_a_new_episode_with_a_first_fire(cfg, clock, sent):
    assert await _fire(episode_start=EpisodeStart(T0, False)) is True
    clock['now'] = T0 + 72 * H + M
    assert await _fire() is True
    subject, plain, _ = sent[-1]
    assert '(reminder)' not in subject
    # no history start given -> the new episode starts now (08:01 CET 05.11)
    assert _triggered(plain) == 'Triggered: 05.11.2026, 08:01:00 CET'
    rec = an._episodes['rec-1|STOP_REACHED']
    assert rec['start'] == clock['now'].timestamp()
    assert rec['truncated'] is False


async def test_exactly_72h_stays_in_the_same_episode(cfg, clock, sent):
    assert await _fire(episode_start=EpisodeStart(T0, False)) is True
    clock['now'] = T0 + 72 * H
    assert await _fire() is True
    assert '(reminder)' in sent[-1][0]


async def test_gap_uses_twice_a_long_reminder_interval(cfg, clock, sent):
    cfg['reminderIntervalHours'] = 48  # effective gap 96 h
    assert await _fire() is True
    clock['now'] = T0 + 95 * H
    assert await _fire() is True
    assert '(reminder)' in sent[-1][0]
    clock['now'] = T0 + 95 * H + 97 * H
    assert await _fire() is True
    assert '(reminder)' not in sent[-1][0]


async def test_history_restart_after_last_seen_starts_a_new_episode(cfg, clock, sent):
    assert await _fire(episode_start=EpisodeStart(T0, False)) is True
    clock['now'] = T0 + 2 * H
    restart = T0 + H + 30 * M
    assert await _fire(episode_start=EpisodeStart(restart, False)) is True
    assert '(reminder)' not in sent[-1][0]
    assert _triggered(sent[-1][1]) == 'Triggered: 02.11.2026, 09:30:00 CET'


async def test_the_decision_uses_the_previous_last_seen(cfg, clock, sent):
    """H.start lies after the PREVIOUS last_seen but before now: a new episode.
    Comparing against an already-advanced last_seen (= now) would miss it."""
    assert await _fire(episode_start=EpisodeStart(T0, False)) is True
    clock['now'] = T0 + H
    assert await _fire(episode_start=EpisodeStart(T0, False)) is False
    clock['now'] = T0 + 3 * H
    assert await _fire(episode_start=EpisodeStart(T0 + 2 * H, False)) is True
    assert '(reminder)' not in sent[-1][0]
    rec = an._episodes['rec-1|STOP_REACHED']
    assert rec['start'] == (T0 + 2 * H).timestamp()
    assert rec['last_seen'] == (T0 + 3 * H).timestamp()


async def test_a_truncated_history_start_never_starts_a_new_episode(cfg, clock, sent):
    assert await _fire(episode_start=EpisodeStart(T0 - 25 * D, False)) is True
    clock['now'] = T0 + H
    later_truncated = EpisodeStart(T0 + 30 * M, True)  # > prev_seen, but truncated
    assert await _fire(episode_start=later_truncated) is False
    rec = an._episodes['rec-1|STOP_REACHED']
    assert rec['start'] == (T0 - 25 * D).timestamp()
    assert rec['truncated'] is False


async def test_pruned_start_episode_stays_the_same_episode(cfg, clock, sent):
    first = T0 - 25 * D
    assert await _fire(episode_start=EpisodeStart(first, False)) is True
    for day in range(1, 7):
        clock['now'] = T0 + day * D
        # pruning moved the earliest surviving row forward: history now shows a
        # LATER, truncated start -- the record keeps the earlier one
        pruned = EpisodeStart(T0 - 25 * D + day * D, True)
        assert await _fire(episode_start=pruned) is True
        assert '(reminder)' in sent[-1][0]
        assert '(since 08.10.2026)' in sent[-1][1]
        assert 'before' not in sent[-1][1]
    rec = an._episodes['rec-1|STOP_REACHED']
    assert rec['start'] == first.timestamp() and rec['truncated'] is False


async def test_an_earlier_history_start_moves_the_record_start_earlier(cfg, clock, sent):
    assert await _fire() is True  # no history -> start = now
    clock['now'] = T0 + H
    assert await _fire(episode_start=EpisodeStart(T0 - 3 * D, True)) is False
    rec = an._episodes['rec-1|STOP_REACHED']
    assert rec['start'] == (T0 - 3 * D).timestamp()
    assert rec['truncated'] is True
    # a later non-truncated history start inside the episode never moves it forward
    clock['now'] = T0 + 2 * H
    assert await _fire(episode_start=EpisodeStart(T0 - 2 * D, False)) is False
    assert an._episodes['rec-1|STOP_REACHED']['start'] == (T0 - 3 * D).timestamp()


async def test_bmy_start_kept_in_every_reminder_under_30_day_retention(cfg, clock, sent):
    """BMY: fires every 4 h from 18.10.2026. Retention 30 days prunes the start
    from 17.11 on; every reminder keeps 18.10 and is never shown as 'before'."""
    bmy_start = datetime(2026, 10, 18, 6, 0, tzinfo=UTC)
    gap = effective_gap(cfg)
    now = datetime(2026, 10, 18, 6, 5, tzinfo=UTC)
    reminders = []
    while now <= datetime(2026, 11, 27, 7, 0, tzinfo=UTC):
        clock['now'] = now
        surviving = max(bmy_start, now - timedelta(days=30))
        truncated = is_start_truncated(surviving, now, gap, 30)
        await _fire(episode_start=EpisodeStart(surviving, truncated))
        now += 4 * H
    first, *reminders = sent
    assert '(reminder)' not in first[0]
    assert _triggered(first[1]) == 'Triggered: 18.10.2026, 08:00:00 CET'
    assert len(reminders) >= 39
    for subject, plain, _ in reminders:
        assert '(reminder)' in subject
        assert _triggered(plain) == 'Triggered: 18.10.2026, 08:00:00 CET'
        assert '(since 18.10.2026)' in plain
        assert 'before' not in plain
        assert '+ days' not in plain
    assert 'Active for 40 days (since 18.10.2026)' in reminders[-1][1]


async def test_fresh_deploy_truncated_start_renders_since_before(cfg, clock, sent):
    clock['now'] = datetime(2026, 11, 27, 7, 0, tzinfo=UTC)
    es = EpisodeStart(datetime(2026, 10, 28, 7, 0, tzinfo=UTC), True)
    assert await _fire(episode_start=es) is True
    subject, plain, html = sent[-1]
    assert '(reminder)' not in subject
    assert _triggered(plain) == 'Triggered: before 28.10.2026'
    assert 'Triggered: before 28.10.2026' in html
    clock['now'] = datetime(2026, 11, 28, 7, 0, tzinfo=UTC)
    assert await _fire(episode_start=es) is True
    subject, plain, html = sent[-1]
    assert '(reminder)' in subject
    assert _triggered(plain) == 'Triggered: before 28.10.2026'
    assert 'Active for 31+ days (since before 28.10.2026)' in plain
    assert 'Active for 31+ days (since before 28.10.2026)' in html


async def test_legacy_fired_and_first_seen_are_ignored(cfg, clock, sent):
    key = 'rec-1|STOP_REACHED'
    an._fired[key] = clock['now'].timestamp()
    an._first_seen[key] = '2026-01-01T07:00:00+00:00'
    assert await _fire(episode_start=EpisodeStart(T0 - H, False)) is True
    subject, plain, _ = sent[-1]
    assert '(reminder)' not in subject
    assert '01.01.2026' not in plain
    assert _triggered(plain) == 'Triggered: 02.11.2026, 07:00:00 CET'
    # the legacy entries are not rewritten by the new path
    assert an._first_seen[key] == '2026-01-01T07:00:00+00:00'


async def test_legacy_first_seen_is_never_used_as_a_start(cfg, clock, sent):
    key = 'rec-1|STOP_REACHED'
    an._first_seen[key] = '2026-09-01T07:00:00+00:00'
    assert await _fire() is True  # no history: start = now, not the legacy date
    assert _triggered(sent[-1][1]) == 'Triggered: 02.11.2026, 08:00:00 CET'
    assert an._episodes[key]['start'] == T0.timestamp()
    clock['now'] = T0 + D
    assert await _fire() is True
    assert 'Active for 1 day (since 02.11.2026)' in sent[-1][1]
    assert '01.09.2026' not in sent[-1][1]


async def test_muted_across_a_clear_then_unmuted_reports_the_new_episode(cfg, clock, sent):
    assert await _fire(episode_start=EpisodeStart(T0, False)) is True
    cfg['enabledTypes'] = ['TP_HIT']  # muted
    clock['now'] = T0 + H
    assert await _fire(episode_start=EpisodeStart(T0, False)) is False
    # condition clears for > 72 h, then returns while still muted
    new_start = T0 + 5 * D - 10 * M
    clock['now'] = T0 + 5 * D
    assert await _fire(episode_start=EpisodeStart(new_start, False)) is False
    rec = an._episodes['rec-1|STOP_REACHED']
    assert rec == {'start': new_start.timestamp(), 'truncated': False,
                   'last_seen': (T0 + 5 * D).timestamp(), 'last_sent': None}
    clock['now'] = T0 + 5 * D + 6 * H
    assert await _fire(episode_start=EpisodeStart(new_start, False)) is False
    cfg['enabledTypes'] = list(ALL_TYPES)  # un-muted
    clock['now'] = T0 + 6 * D
    assert await _fire(episode_start=EpisodeStart(new_start, False)) is True
    subject, plain, _ = sent[-1]
    assert '(reminder)' not in subject
    assert _triggered(plain) == 'Triggered: 07.11.2026, 07:50:00 CET'
    assert len(sent) == 2


async def test_muted_by_position_override_and_master_off_still_update_state(cfg, clock, sent):
    assert await _fire(type_enabled=False) is False
    rec = an._episodes['rec-1|STOP_REACHED']
    assert rec['start'] == T0.timestamp() and rec['last_sent'] is None
    cfg['masterEnabled'] = False
    clock['now'] = T0 + 60 * H
    assert await _fire() is False
    assert an._episodes['rec-1|STOP_REACHED']['last_seen'] == (T0 + 60 * H).timestamp()
    cfg['masterEnabled'] = True
    # 100 h after the first call, 40 h after the muted one: still the same
    # episode because the muted call kept last_seen fresh -> first fire (never
    # sent yet), dated at the original start
    clock['now'] = T0 + 100 * H
    assert await _fire() is True
    assert '(reminder)' not in sent[-1][0]
    assert _triggered(sent[-1][1]) == 'Triggered: 02.11.2026, 08:00:00 CET'


async def test_failed_first_fire_rolls_back_and_retries_as_first_fire(cfg, clock, sent):
    sent.state['ok'] = False
    assert await _fire(episode_start=EpisodeStart(T0, False)) is False
    rec = an._episodes['rec-1|STOP_REACHED']
    assert rec['last_sent'] is None
    on_disk = json.loads(an._DEDUP_PATH.read_text(encoding='utf-8'))
    assert on_disk['episodes']['rec-1|STOP_REACHED']['last_sent'] is None
    sent.state['ok'] = True
    clock['now'] = T0 + M
    assert await _fire(episode_start=EpisodeStart(T0, False)) is True
    assert '(reminder)' not in sent[-1][0]


async def test_failed_reminder_rolls_back_and_retries_as_reminder(cfg, clock, sent):
    assert await _fire(episode_start=EpisodeStart(T0, False)) is True
    clock['now'] = T0 + D
    sent.state['ok'] = False
    assert await _fire(episode_start=EpisodeStart(T0, False)) is False
    rec = an._episodes['rec-1|STOP_REACHED']
    assert rec['last_sent'] == T0.timestamp()
    assert rec['start'] == T0.timestamp()
    on_disk = json.loads(an._DEDUP_PATH.read_text(encoding='utf-8'))
    assert on_disk['episodes']['rec-1|STOP_REACHED']['last_sent'] == T0.timestamp()
    sent.state['ok'] = True
    clock['now'] = T0 + D + M
    assert await _fire(episode_start=EpisodeStart(T0, False)) is True
    assert '(reminder)' in sent[-1][0]
    assert len(sent) == 2


async def test_raising_channel_is_a_failed_send(cfg, clock, monkeypatch):
    async def _boom(subject, plain, html):
        raise RuntimeError('smtp down')

    monkeypatch.setattr(an, 'notify_enabled_channels', _boom)
    assert await _fire() is False
    assert an._episodes['rec-1|STOP_REACHED']['last_sent'] is None


async def test_restart_reload_keeps_the_episode(cfg, clock, sent):
    assert await _fire(episode_start=EpisodeStart(T0, False)) is True
    an._episodes.clear()
    an._fired.clear()
    an._first_seen.clear()
    an._load_dedup()
    assert an._episodes['rec-1|STOP_REACHED']['last_sent'] == T0.timestamp()
    clock['now'] = T0 + H
    assert await _fire(episode_start=EpisodeStart(T0, False)) is False
    clock['now'] = T0 + D
    assert await _fire(episode_start=EpisodeStart(T0, False)) is True
    assert '(reminder)' in sent[-1][0]


def test_episode_state_loads_tolerantly(tmp_path):
    good = {'start': 1.0e9, 'truncated': True, 'last_seen': 1.1e9, 'last_sent': None}
    good2 = {'start': 1.0e9, 'truncated': False, 'last_seen': 1.1e9, 'last_sent': 1.05e9}
    an._DEDUP_PATH.write_text(json.dumps({
        'fired': {'regime|REGIME_CHANGE': 5.0},
        'first_seen': {},
        'episodes': {
            'a|STOP_REACHED': good,
            'b|TP_HIT': good2,
            'c|TP_HIT': 'garbage',
            'd|TP_HIT': {'start': 'x', 'truncated': False, 'last_seen': 1.0, 'last_sent': None},
            'e|TP_HIT': {'start': 1.0, 'truncated': 'yes', 'last_seen': 1.0, 'last_sent': None},
            'f|TP_HIT': {'start': 1.0, 'truncated': False, 'last_seen': 1.0},
            'g|TP_HIT': {'start': float('nan'), 'truncated': False, 'last_seen': 1.0,
                         'last_sent': None},
            'h|TP_HIT': {'start': True, 'truncated': False, 'last_seen': 1.0, 'last_sent': None},
        },
        'summary_day': '2026-11-02',
    }), encoding='utf-8')
    an._load_dedup()
    assert an._episodes == {'a|STOP_REACHED': good, 'b|TP_HIT': good2}
    assert an._fired == {'regime|REGIME_CHANGE': 5.0}
    assert an._summary_state.get('day') == '2026-11-02'


def test_garbled_episodes_block_keeps_the_rest(tmp_path):
    an._DEDUP_PATH.write_text(json.dumps({
        'fired': {'regime|REGIME_CHANGE': 5.0}, 'first_seen': {},
        'episodes': ['not', 'a', 'map'], 'summary_day': 12,
    }), encoding='utf-8')
    an._load_dedup()
    assert an._episodes == {}
    assert an._fired == {'regime|REGIME_CHANGE': 5.0}
    assert an._summary_state.get('day') is None


async def test_no_disk_write_per_tick(cfg, clock, sent, monkeypatch):
    assert await _fire() is True
    saves = []
    monkeypatch.setattr(an, '_save_dedup', lambda: saves.append(1) or True)
    clock['now'] = T0 + M
    assert await _fire() is False
    clock['now'] = T0 + 30 * M
    assert await _fire() is False
    assert saves == []
    clock['now'] = T0 + 30 * M + H  # last_seen advanced by >= 1 h
    assert await _fire() is False
    assert saves == [1]
    clock['now'] = T0 + 2 * H
    assert await _fire(episode_start=EpisodeStart(T0 - H, False)) is False  # start changed
    assert saves == [1, 1]


async def test_forget_alerts_clears_episodes(cfg, clock, sent):
    assert await _fire() is True
    assert await _fire(alert_type='PREMIUM_STOP', stop_side='short-stock') is True
    assert await _fire(rec_id='rec-2') is True
    assert an.forget_alerts({'rec-1'}) is True
    assert set(an._episodes) == {'rec-2|STOP_REACHED'}
    on_disk = json.loads(an._DEDUP_PATH.read_text(encoding='utf-8'))
    assert set(on_disk['episodes']) == {'rec-2|STOP_REACHED'}


async def test_short_premium_stop_has_its_own_episode_key(cfg, clock, sent):
    assert await _fire(alert_type='PREMIUM_STOP', stop_side='short-stock') is True
    assert 'rec-1|PREMIUM_STOP:short' in an._episodes
    assert 'Stock stop hit (short)' in sent[-1][0]


async def test_episode_messages_are_telegram_safe(cfg, clock, sent):
    es = EpisodeStart(T0 - 40 * D, True)
    assert await an.notify_alert('A<B&C', 'STOP_REACHED', 'Stop < 90 & falling', 'rec-1',
                                 None, episode_start=es) is True
    clock['now'] = T0 + D
    assert await an.notify_alert('A<B&C', 'STOP_REACHED', 'Stop < 90 & falling', 'rec-1',
                                 None, episode_start=es) is True
    for _s, _p, html in sent:
        assert '<B' not in html and '&lt;' in html and '&amp;' in html


def test_episode_notified_types():
    for t in ('TP_HIT', 'STOP_REACHED', 'STRUCTURAL_STOP_BREACHED', 'PREMIUM_STOP',
              'TIME_STOP', 'EVENT_RISK'):
        assert an.is_episode_notified(t, 'rec-1') is True
        assert an.is_episode_notified(t, 'regime') is False
    assert an.is_episode_notified('REGIME_CHANGE', 'regime') is False
    assert an.is_episode_notified('AUTO_TRADE_REFUSED', 'auto-trade:x') is False


# ── Window path unchanged for REGIME_CHANGE and auto-trader types ─────────────

@pytest.mark.parametrize('alert_type, rec_id', [
    ('REGIME_CHANGE', 'regime'),
    ('AUTO_TRADE_REFUSED', 'auto-trade:sizing'),
])
async def test_window_path_unchanged(cfg, clock, sent, monkeypatch, alert_type, rec_id):
    """The window path reads time.time(), keys _fired/_first_seen, never the
    episode map, and reminds every reminderIntervalHours."""
    wall = {'t': 1_000_000.0}
    monkeypatch.setattr(an.time, 'time', lambda: wall['t'])
    es = EpisodeStart(T0 - 40 * D, True)  # ignored on this path
    kw = dict(type_enabled=True, episode_start=es)
    assert await an.notify_alert('MARKET', alert_type, 'r', rec_id, None, **kw) is True
    key = f'{rec_id}|{alert_type}'
    assert an._fired[key] == 1_000_000.0 and key in an._first_seen
    assert an._episodes == {}
    wall['t'] += 3 * 3600
    assert await an.notify_alert('MARKET', alert_type, 'r', rec_id, None, **kw) is False
    wall['t'] += 3600
    assert await an.notify_alert('MARKET', alert_type, 'r', rec_id, None, **kw) is True
    subject, plain, _ = sent[-1]
    assert '(reminder)' in subject
    assert 'Active for' not in plain
    assert 'before' not in _triggered(plain)
    assert an._episodes == {}


# ── Daily summary (notifier) ─────────────────────────────────────────────────

def _item(rec_id, symbol, alert_type, start=None, truncated=False, stop_side=None):
    return an.SummaryItem(rec_id=rec_id, symbol=symbol, alert_type=alert_type,
                          start=start, truncated=truncated, stop_side=stop_side)


def test_summary_due_only_from_0900_berlin_once_per_day():
    # 07:59 UTC = 08:59 CET
    assert an.summary_due(datetime(2026, 11, 2, 7, 59, tzinfo=UTC)) is False
    assert an.summary_due(datetime(2026, 11, 2, 8, 0, tzinfo=UTC)) is True
    an._summary_state['day'] = '2026-11-02'
    assert an.summary_due(datetime(2026, 11, 2, 22, 0, tzinfo=UTC)) is False
    # 23:30 UTC on 2 Nov is 00:30 on 3 Nov in Berlin, before 09:00
    assert an.summary_due(datetime(2026, 11, 2, 23, 30, tzinfo=UTC)) is False
    assert an.summary_due(datetime(2026, 11, 3, 8, 0, tzinfo=UTC)) is True
    # summer time: 09:00 CEST = 07:00 UTC
    assert an.summary_due(datetime(2026, 7, 1, 7, 0, tzinfo=UTC)) is True
    assert an.summary_due(datetime(2026, 7, 1, 6, 59, tzinfo=UTC)) is False


async def test_summary_counts_distinct_positions_per_category(sent):
    now = datetime(2026, 11, 27, 8, 30, tzinfo=UTC)
    items = [
        _item('a', 'BMY', 'STOP_REACHED', datetime(2026, 11, 18, 7, 0, tzinfo=UTC)),
        _item('a', 'BMY', 'STRUCTURAL_STOP_BREACHED', datetime(2026, 11, 18, 7, 0, tzinfo=UTC)),
        _item('b', 'NFLX', 'PREMIUM_STOP', datetime(2026, 10, 28, 7, 0, tzinfo=UTC), True),
        _item('c', 'COP', 'STOP_REACHED', datetime(2026, 11, 26, 7, 0, tzinfo=UTC)),
        _item('d', 'FTNT', 'TP_HIT', datetime(2026, 11, 27, 8, 0, tzinfo=UTC)),
        _item('e', 'HPE', 'TIME_STOP', datetime(2026, 11, 25, 7, 0, tzinfo=UTC)),
    ]
    assert await an.notify_daily_summary(items, now) is True
    [(subject, plain, html)] = sent
    assert subject == ('Bamendjou Portfolio — daily summary: 3 positions past stop, '
                       '1 at target, 1 time stop')
    assert 'BMY — Stop hit, active 9 days (since 18.11.2026)' in plain
    assert 'BMY — Structural level hit, active 9 days (since 18.11.2026)' in plain
    assert 'NFLX — Premium stop hit, active 30+ days (since before 28.10.2026)' in plain
    assert 'COP — Stop hit, active 1 day (since 26.11.2026)' in plain
    assert 'FTNT — Target reached, active under 1 h (since 27.11.2026)' in plain
    assert 'HPE — Time stop hit, active 2 days (since 25.11.2026)' in plain
    assert 'NFLX — Premium stop hit, active 30+ days (since before 28.10.2026)' in html
    assert an._summary_state['day'] == '2026-11-27'


async def test_summary_singular_and_plural_forms(sent):
    now = datetime(2026, 11, 27, 8, 30, tzinfo=UTC)
    items = [
        _item('a', 'BMY', 'STOP_REACHED', now - D),
        _item('b', 'X', 'TP_HIT', now - D), _item('c', 'Y', 'TP_HIT', now - D),
        _item('d', 'Z', 'TIME_STOP', now - D), _item('e', 'W', 'TIME_STOP', now - D),
    ]
    assert await an.notify_daily_summary(items, now) is True
    assert sent[0][0] == ('Bamendjou Portfolio — daily summary: 1 position past stop, '
                          '2 at target, 2 time stops')


async def test_summary_omits_zero_categories_and_escapes_html(sent):
    now = datetime(2026, 11, 27, 8, 30, tzinfo=UTC)
    assert await an.notify_daily_summary(
        [_item('a', 'A<B', 'TP_HIT', now - 2 * H)], now) is True
    subject, plain, html = sent[0]
    assert subject == 'Bamendjou Portfolio — daily summary: 1 at target'
    assert 'A<B — Target reached, active 2 h (since 27.11.2026)' in plain
    assert 'A&lt;B' in html and 'A<B' not in html


async def test_summary_item_without_episode_shows_no_duration(sent):
    now = datetime(2026, 11, 27, 8, 30, tzinfo=UTC)
    assert await an.notify_daily_summary([_item('a', 'BMY', 'STOP_REACHED')], now) is True
    lines = sent[0][1].splitlines()
    assert 'BMY — Stop hit' in lines


async def test_summary_zero_items_sends_nothing_and_closes_the_day(sent):
    now = datetime(2026, 11, 27, 8, 30, tzinfo=UTC)
    assert await an.notify_daily_summary([], now) is True
    assert sent == []
    assert an._summary_state['day'] == '2026-11-27'
    on_disk = json.loads(an._DEDUP_PATH.read_text(encoding='utf-8'))
    assert on_disk['summary_day'] == '2026-11-27'


async def test_summary_failed_send_leaves_the_day_open(sent):
    sent.state['ok'] = False
    now = datetime(2026, 11, 27, 8, 30, tzinfo=UTC)
    assert await an.notify_daily_summary([_item('a', 'BMY', 'STOP_REACHED', now - D)], now) is False
    assert an._summary_state.get('day') is None
    assert an.summary_due(now) is True


async def test_summary_unquoted_line(sent):
    now = datetime(2026, 11, 27, 11, 30, tzinfo=UTC)
    assert await an.notify_daily_summary(
        [_item('a', 'BMY', 'STOP_REACHED', now - D)], now, unquoted=['NFLX', 'COP']) is True
    subject, plain, html = sent[0]
    assert subject == 'Bamendjou Portfolio — daily summary: 1 position past stop'
    assert '2 positions without a quote: NFLX, COP' in plain
    assert '2 positions without a quote: NFLX, COP' in html
    sent.clear()
    an._summary_state.clear()
    assert await an.notify_daily_summary([], now, unquoted=['NFLX']) is True
    subject, plain, _ = sent[0]
    assert '1 position without a quote: NFLX' in plain
    assert subject == 'Bamendjou Portfolio — daily summary: no action alerts'


# ── Monitor: episode lookup + daily summary ──────────────────────────────────

def _pos(rec_id, symbol, contract=None, overrides=None):
    p = MagicMock()
    p.rec_id = rec_id
    p.symbol = symbol
    p.contract = contract or f'{symbol}|STOCK'
    p.alert_overrides = overrides or {}
    return p


def _alert(rec_id, symbol, alert_type):
    return AlertItem(id=f'{rec_id}-{alert_type}', kind='Action', symbol=symbol,
                     reason=f'{alert_type} fired', timestamp=T0.isoformat(),
                     recId=rec_id, alertType=alert_type)


def _fake_db(positions):
    fake_db = AsyncMock()
    fake_db.__aenter__ = AsyncMock(return_value=fake_db)
    fake_db.__aexit__ = AsyncMock(return_value=False)
    result = MagicMock()
    result.scalars.return_value.all.return_value = positions
    fake_db.execute = AsyncMock(return_value=result)
    return fake_db


async def _tick(monkeypatch, now, *, positions, alerts, quotes=None, option_quotes=None,
                episodes=None, delivery=None, generate_raises=False, episodes_raise=False):
    from app.services import portfolio_alert_monitor as mon

    mon._known_rec_ids.clear()
    mon._last_regime = None
    settings = {'alert_delivery': dict(CFG, **(delivery or {}))}
    if quotes is None:
        quotes = {p.symbol: {'last': 100.0} for p in positions}
    option_quotes = option_quotes or {}

    async def _contract_quote(client, contract):
        return {'price': option_quotes[contract]} if contract in option_quotes else None

    async def _to_thread(fn, *args):
        return quotes if args else 'PASS'

    gen = AsyncMock(side_effect=RuntimeError('boom')) if generate_raises \
        else AsyncMock(return_value=list(alerts))
    cur = AsyncMock(side_effect=RuntimeError('db down')) if episodes_raise \
        else AsyncMock(return_value=episodes or {})
    notify = AsyncMock(return_value=True)
    with (
        patch.object(mon, '_load_settings', return_value=settings),
        patch.object(mon, '_utcnow', return_value=now),
        patch.object(mon, 'generate_alerts', new=gen),
        patch.object(mon, 'current_episodes', new=cur),
        patch.object(mon, 'notify_alert', new=notify),
        patch.object(mon.alert_service, 'broadcast', new=AsyncMock()),
        patch.object(mon, 'AsyncSessionLocal', return_value=_fake_db(positions)),
        patch.object(mon.asyncio, 'to_thread', new=_to_thread),
        patch('app.data.market.fetch_contract_quote_async', new=_contract_quote),
    ):
        await mon._run_once()
    return notify, cur


def _view(rec_id, symbol, alert_type, start, truncated=False):
    return EpisodeView(rec_id=rec_id, alert_type=alert_type, symbol=symbol,
                       start=start, last=start, count=1, truncated=truncated)


AT_0905 = datetime(2026, 11, 2, 8, 5, tzinfo=UTC)  # 09:05 Berlin
AT_0859 = datetime(2026, 11, 2, 7, 59, tzinfo=UTC)
AT_1159 = datetime(2026, 11, 2, 10, 59, tzinfo=UTC)
AT_1200 = datetime(2026, 11, 2, 11, 0, tzinfo=UTC)


async def test_monitor_passes_each_alerts_episode_start(monkeypatch, sent):
    positions = [_pos('a', 'BMY'), _pos('b', 'NFLX')]
    alerts = [_alert('a', 'BMY', 'STOP_REACHED'), _alert('b', 'NFLX', 'TP_HIT')]
    start = datetime(2026, 10, 18, 6, 0, tzinfo=UTC)
    episodes = {('a', 'STOP_REACHED'): _view('a', 'BMY', 'STOP_REACHED', start, True)}
    notify, cur = await _tick(monkeypatch, AT_0859, positions=positions, alerts=alerts,
                              episodes=episodes)
    cur.assert_awaited_once()
    assert set(cur.call_args.args[1]) == {'a', 'b'}
    assert cur.call_args.args[2] == AT_0859
    by_key = {(c.args[3], c.args[1]): c.kwargs['episode_start'] for c in notify.call_args_list}
    assert by_key[('a', 'STOP_REACHED')] == EpisodeStart(start, True)
    assert by_key[('b', 'TP_HIT')] is None


async def test_monitor_episode_lookup_failure_passes_none(monkeypatch, sent):
    notify, _ = await _tick(monkeypatch, AT_0859, positions=[_pos('a', 'BMY')],
                            alerts=[_alert('a', 'BMY', 'STOP_REACHED')], episodes_raise=True)
    assert notify.call_args.kwargs['episode_start'] is None


async def test_summary_once_per_berlin_day(monkeypatch, sent):
    kw = dict(positions=[_pos('a', 'BMY')], alerts=[_alert('a', 'BMY', 'STOP_REACHED')],
              episodes={('a', 'STOP_REACHED'): _view('a', 'BMY', 'STOP_REACHED', T0 - 3 * D)})
    await _tick(monkeypatch, AT_0905, **kw)
    assert len(sent) == 1
    assert sent[0][0] == 'Bamendjou Portfolio — daily summary: 1 position past stop'
    assert 'BMY — Stop hit, active 3 days (since 30.10.2026)' in sent[0][1]
    await _tick(monkeypatch, AT_0905 + 5 * M, **kw)
    await _tick(monkeypatch, AT_0905 + 14 * H, **kw)
    assert len(sent) == 1
    await _tick(monkeypatch, AT_0905 + D, **kw)
    assert len(sent) == 2


async def test_summary_not_before_0900(monkeypatch, sent):
    await _tick(monkeypatch, AT_0859, positions=[_pos('a', 'BMY')],
                alerts=[_alert('a', 'BMY', 'STOP_REACHED')])
    assert sent == []
    assert an._summary_state.get('day') is None


async def test_summary_not_on_generation_failure_then_retried(monkeypatch, sent):
    kw = dict(positions=[_pos('a', 'BMY')], alerts=[_alert('a', 'BMY', 'STOP_REACHED')])
    await _tick(monkeypatch, AT_0905, generate_raises=True, **kw)
    assert sent == [] and an._summary_state.get('day') is None
    # not even after the 12:00 deadline: a failed generation has no alerts to report
    await _tick(monkeypatch, AT_1200, generate_raises=True, **kw)
    assert sent == [] and an._summary_state.get('day') is None
    await _tick(monkeypatch, AT_1200 + M, **kw)
    assert len(sent) == 1


async def test_summary_waits_for_a_missing_stock_quote_until_noon(monkeypatch, sent):
    positions = [_pos('a', 'BMY'), _pos('b', 'NFLX')]
    alerts = [_alert('a', 'BMY', 'STOP_REACHED'), _alert('b', 'NFLX', 'STOP_REACHED')]
    quotes = {'BMY': {'last': 50.0}}  # NFLX unquoted
    await _tick(monkeypatch, AT_0905, positions=positions, alerts=alerts, quotes=quotes)
    await _tick(monkeypatch, AT_1159, positions=positions, alerts=alerts, quotes=quotes)
    assert sent == [] and an._summary_state.get('day') is None
    await _tick(monkeypatch, AT_1200, positions=positions, alerts=alerts, quotes=quotes)
    [(subject, plain, _)] = sent
    assert subject == 'Bamendjou Portfolio — daily summary: 1 position past stop'
    assert '1 position without a quote: NFLX' in plain
    assert 'NFLX — Stop hit' not in plain
    assert an._summary_state['day'] == '2026-11-02'


async def test_summary_waits_for_a_missing_option_quote_until_noon(monkeypatch, sent):
    contract = 'COP|100|2026-12-18|C'
    positions = [_pos('a', 'BMY'), _pos('c', 'COP', contract=contract)]
    alerts = [_alert('a', 'BMY', 'STOP_REACHED')]
    await _tick(monkeypatch, AT_0905, positions=positions, alerts=alerts)
    assert sent == []
    await _tick(monkeypatch, AT_0905 + M, positions=positions, alerts=alerts,
                option_quotes={contract: 3.2})
    assert len(sent) == 1
    assert 'without a quote' not in sent[0][1]


async def test_summary_after_noon_lists_the_unquoted_option(monkeypatch, sent):
    contract = 'COP|100|2026-12-18|C'
    positions = [_pos('a', 'BMY'), _pos('c', 'COP', contract=contract)]
    await _tick(monkeypatch, AT_1200, positions=positions, alerts=[])
    [(subject, plain, _)] = sent
    assert '1 position without a quote: COP 100C 2026-12-18' in plain
    assert subject == 'Bamendjou Portfolio — daily summary: no action alerts'


async def test_summary_zero_item_day(monkeypatch, sent):
    await _tick(monkeypatch, AT_0905, positions=[_pos('a', 'BMY')],
                alerts=[_alert('a', 'BMY', 'EVENT_RISK')])
    assert sent == []
    assert an._summary_state['day'] == '2026-11-02'
    await _tick(monkeypatch, AT_0905 + H, positions=[_pos('a', 'BMY')],
                alerts=[_alert('a', 'BMY', 'STOP_REACHED')])
    assert sent == []  # one decision per day


async def test_summary_no_positions_closes_the_day(monkeypatch, sent):
    await _tick(monkeypatch, AT_0905, positions=[], alerts=[])
    assert sent == [] and an._summary_state['day'] == '2026-11-02'


async def test_summary_excludes_disabled_types(monkeypatch, sent):
    positions = [_pos('a', 'BMY'), _pos('b', 'HPE', overrides={'TIME_STOP': True}),
                 _pos('c', 'FTNT')]
    alerts = [_alert('a', 'BMY', 'TIME_STOP'), _alert('b', 'HPE', 'TIME_STOP'),
              _alert('c', 'FTNT', 'TP_HIT')]
    enabled = [t for t in ALL_TYPES if t != 'TIME_STOP']
    await _tick(monkeypatch, AT_0905, positions=positions, alerts=alerts,
                delivery={'enabledTypes': enabled})
    [(subject, plain, _)] = sent
    assert subject == 'Bamendjou Portfolio — daily summary: 1 at target, 1 time stop'
    assert 'HPE — Time stop hit' in plain
    assert 'BMY' not in plain


async def test_summary_failed_send_is_retried_next_tick(monkeypatch, sent):
    kw = dict(positions=[_pos('a', 'BMY')], alerts=[_alert('a', 'BMY', 'STOP_REACHED')])
    sent.state['ok'] = False
    await _tick(monkeypatch, AT_0905, **kw)
    assert an._summary_state.get('day') is None
    sent.state['ok'] = True
    await _tick(monkeypatch, AT_0905 + M, **kw)
    assert len(sent) == 1
    assert an._summary_state['day'] == '2026-11-02'


async def test_summary_not_sent_when_master_disabled(monkeypatch, sent):
    await _tick(monkeypatch, AT_0905, positions=[_pos('a', 'BMY')],
                alerts=[_alert('a', 'BMY', 'STOP_REACHED')],
                delivery={'masterEnabled': False})
    assert sent == [] and an._summary_state.get('day') is None


# ── Router: POST /api/alerts/notify passes the history episode start ────────

_engine = create_async_engine('sqlite+aiosqlite:///:memory:', echo=False)
_Session = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False,
                              autoflush=False, autocommit=False)


@pytest_asyncio.fixture
async def db():
    from app.models import audit_event, portfolio, position_alert, watchlist  # noqa: F401
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with _Session() as s:
        yield s
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(db):
    from app.database import get_db
    from app.main import app

    async def _override():
        async with _Session() as s:
            yield s

    app.dependency_overrides[get_db] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
        yield ac
    app.dependency_overrides.clear()


class _Clock:
    """A settable 'now' for every datetime.now() the simulated path reads."""
    now = T0


class _FakeDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        n = _Clock.now
        return n if tz is None else n.astimezone(tz)


@pytest.fixture
def sim_clock(monkeypatch):
    import app.models.position_alert as pa_model
    import app.routers.alerts as alerts_router
    import app.services.alert_generator as gen
    import app.services.position_alert_log as pal
    _Clock.now = T0
    for mod in (pa_model, alerts_router, gen, pal):
        monkeypatch.setattr(mod, 'datetime', _FakeDatetime)
    monkeypatch.setattr(an, '_now', lambda: _Clock.now.timestamp())
    monkeypatch.setattr(pal, '_load_delivery_config', lambda: dict(CFG))
    import app.services.alert_episodes as ae
    monkeypatch.setattr(ae, 'load_delivery_config', lambda: dict(CFG))
    monkeypatch.setattr(an, '_load_delivery_config', lambda: dict(CFG))
    return _Clock


async def test_router_passes_episode_start_from_history(client, db, sim_clock):
    db.add(PortfolioPositionModel(
        rec_id='REC-1', symbol='BMY', contract='BMY|STOCK', direction='Bullish',
        entry_price=60.0, qty=10, entry_date='2026-10-01', stop=55.0, targets=[]))
    db.add(PositionAlertHistoryModel(
        rec_id='REC-1', symbol='BMY', alert_type='STOP_REACHED', source='backend',
        triggered_at=T0 - 2 * D))
    await db.commit()
    with patch('app.routers.alerts.notify_alert', new=AsyncMock(return_value=True)) as m:
        resp = await client.post('/api/alerts/notify', json={
            'symbol': 'BMY', 'alertType': 'STOP_REACHED', 'reason': 'x', 'recId': 'REC-1'})
    assert resp.status_code == 200
    assert m.call_args.kwargs['episode_start'] == EpisodeStart(T0 - 2 * D, False)


async def test_router_episode_lookup_failure_passes_none(client, db, sim_clock):
    db.add(PortfolioPositionModel(
        rec_id='REC-1', symbol='BMY', contract='BMY|STOCK', direction='Bullish',
        entry_price=60.0, qty=10, entry_date='2026-10-01', stop=55.0, targets=[]))
    await db.commit()
    with (
        patch('app.routers.alerts.notify_alert', new=AsyncMock(return_value=True)) as m,
        patch('app.services.alert_episodes.current_episodes',
              new=AsyncMock(side_effect=RuntimeError('db down'))),
    ):
        resp = await client.post('/api/alerts/notify', json={
            'symbol': 'BMY', 'alertType': 'STOP_REACHED', 'reason': 'x', 'recId': 'REC-1'})
    assert resp.status_code == 200
    assert m.call_args.kwargs['episode_start'] is None


# ── Logging unchanged: a simulated 3-day run (monitor + browser POSTs) ──────

async def _simulate_three_days(client, db, monkeypatch, sim_clock):
    """Monitor tick + browser POST every 15 min for 72 h on one breached stock
    position (BMY below its stop). Returns (backend rows, frontend rows)."""
    from app.services import portfolio_alert_monitor as mon
    import app.data.market as market
    import app.services.notifications.sent_log as sent_log
    import httpx as mon_httpx

    db.add(PortfolioPositionModel(
        rec_id='REC-BMY', symbol='BMY', contract='BMY|STOCK', direction='Bullish',
        entry_price=60.0, qty=10, entry_date=T0.date().isoformat(), stop=55.0, targets=[]))
    await db.commit()

    async def _no_contract_quote(client, contract):
        return None

    class _NoClient:
        # Building a real httpx.AsyncClient (SSL context) costs ~0.4 s per
        # tick on Windows; the contract quote is stubbed anyway.
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(mon, 'AsyncSessionLocal', _Session)
    monkeypatch.setattr(mon, '_load_settings', lambda: {'alert_delivery': dict(CFG)})
    monkeypatch.setattr(mon, 'compute_overall_regime', lambda: 'PASS')
    monkeypatch.setattr(mon, '_utcnow', lambda: _Clock.now)
    monkeypatch.setattr(market, 'fetch_quotes', lambda syms: {s: {'last': 50.0} for s in syms})
    monkeypatch.setattr(market, 'fetch_contract_quote_async', _no_contract_quote)
    monkeypatch.setattr(mon_httpx, 'AsyncClient', _NoClient)
    monkeypatch.setattr(sent_log, 'prune_sent_log', lambda days: None)
    monkeypatch.setattr(mon.alert_service, 'broadcast', AsyncMock())
    mon._known_rec_ids.clear()
    mon._last_regime = None

    for i in range(72 * 4):
        sim_clock.now = T0 + i * 15 * M
        await mon._run_once()
        resp = await client.post('/api/alerts/notify', json={
            'symbol': 'BMY', 'alertType': 'STOP_REACHED', 'reason': 'Stop breached',
            'recId': 'REC-BMY', 'price': 50.0, 'referenceValue': 55.0})
        assert resp.status_code == 200

    async with _Session() as s:
        counts = dict((await s.execute(
            select(PositionAlertHistoryModel.source, func.count())
            .where(PositionAlertHistoryModel.rec_id == 'REC-BMY',
                   PositionAlertHistoryModel.alert_type == 'STOP_REACHED')
            .group_by(PositionAlertHistoryModel.source))).all())
    return counts.get('backend', 0), counts.get('frontend', 0)


async def test_three_day_run_logs_unchanged_and_escalates_per_episode(
        client, db, monkeypatch, sim_clock, sent):
    backend_rows, frontend_rows = await _simulate_three_days(client, db, monkeypatch, sim_clock)
    # log_position_alert's window is untouched: a row when the previous one of
    # the same source is MORE than 4 h old -> with 15-min ticks every 4 h 15 min,
    # ticks 0 h .. 71 h 45 m -> 17 rows per source.
    assert (backend_rows, frontend_rows) == (17, 17)
    alerts = [s for s in sent if 'Portfolio Alert' in s[0]]
    summaries = [s for s in sent if 'daily summary' in s[0]]
    # one first fire + one reminder per 24 h, shared by monitor and browser
    assert len(alerts) == 3
    assert '(reminder)' not in alerts[0][0]
    assert all('(reminder)' in s[0] for s in alerts[1:])
    assert all(_triggered(s[1]) == 'Triggered: 02.11.2026, 08:00:00 CET' for s in alerts)
    assert 'Active for 1 day (since 02.11.2026)' in alerts[1][1]
    assert 'Active for 2 days (since 02.11.2026)' in alerts[2][1]
    # 09:00 Berlin on 2, 3 and 4 Nov
    assert len(summaries) == 3
    assert 'BMY — Stop hit, active 1 h (since 02.11.2026)' in summaries[0][1]


async def test_three_day_run_log_rows_match_with_notifier_stubbed(
        client, db, monkeypatch, sim_clock):
    """Same run with the notifier stubbed out entirely (the pre-T2 dispatch can
    not influence logging either): identical row counts."""
    from app.services import portfolio_alert_monitor as mon
    monkeypatch.setattr(mon, 'notify_alert', AsyncMock(return_value=False))
    monkeypatch.setattr(mon, 'notify_daily_summary', AsyncMock(return_value=False))
    monkeypatch.setattr('app.routers.alerts.notify_alert', AsyncMock(return_value=False))
    assert await _simulate_three_days(client, db, monkeypatch, sim_clock) == (17, 17)
