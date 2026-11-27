"""Single source of truth for portfolio-alert notification dispatch.

Both the browser (via POST /api/alerts/notify) and the headless background
monitor (portfolio_alert_monitor) funnel through `notify_alert` here, so the
two paths share ONE dedup set. This guarantees:

  * what the user sees in-app gets emailed/Telegrammed (browser path), and
  * a browser-closed user still gets emails (monitor fallback path),

without the same trigger being sent twice — whichever path fires first wins,
the other is deduped.
"""
from __future__ import annotations

import html as html_lib
import json
import logging
import os
import tempfile
import threading
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence

import yaml

from app.services.alert_episodes import (
    DAILY_SUMMARY_HOUR_BERLIN,
    REMINDER_PERIOD_HOURS,
    EpisodeStart,
    as_utc,
    effective_gap,
    format_active_duration,
)
from app.services.alert_generator import POSITION_ALERT_TYPES
from app.services.notifications.dispatch import notify_enabled_channels

logger = logging.getLogger(__name__)

# All alert timestamps are shown in Central European time, pinned to the
# Europe/Berlin zone so the displayed clock does not depend on the server's
# local timezone. Falls back to the server local zone if tz data is missing.
try:
    from zoneinfo import ZoneInfo
    _CET = ZoneInfo('Europe/Berlin')
except Exception:
    _CET = None
_TZ_LABEL = 'CET'

_SETTINGS_PATH = Path(__file__).parent.parent.parent.parent / 'config' / 'settings.yaml'

_DEFAULT_ENABLED_TYPES = [
    'TP_HIT', 'STOP_REACHED', 'STRUCTURAL_STOP_BREACHED', 'PREMIUM_STOP', 'TIME_STOP', 'EVENT_RISK', 'REGIME_CHANGE',
]
# While a condition stays true we re-send (remind) at most once per this window.
_DEFAULT_REMINDER_HOURS = 4
# Never remind faster than this, regardless of config. Must stay STRICTLY GREATER
# than the monitor's 15-min tick interval: if it were equal, an entry written at
# tick N would sit exactly on the purge boundary at tick N+1 and scheduling jitter
# could resurrect a still-true condition into a duplicate email.
_MIN_DEDUP_SECONDS = 20 * 60

# key "recId|alertType" -> wall-clock timestamp of last send
_fired: dict[str, float] = {}
# key "recId|alertType" -> ISO timestamp of the FIRST time this condition fired.
# Survives the dedup-window purge so every reminder keeps the original trigger
# time (a reminder must not look like a brand-new alert). Cleared only when the
# position closes (forget_alerts).
_first_seen: dict[str, str] = {}
_fired_lock = threading.Lock()

# PORTFOLIO-ALERT-ACTION (#672) -- per-key episode records for the
# episode-notified types (POSITION_ALERT_TYPES, rec_id != 'regime'), keyed by
# `_dedup_key`: {start, truncated, last_seen, last_sent} as epoch seconds
# (last_sent None = nothing sent in this episode yet) + bool. Replaces the
# `_fired` window / `_first_seen` path for those types only; REGIME_CHANGE and
# the auto-trader's types never touch it. Guarded by `_fired_lock`.
_episodes: dict[str, dict] = {}
# Daily summary: {'day': 'YYYY-MM-DD'} (Europe/Berlin) once that day's summary
# was delivered or decided to be empty. Guarded by `_fired_lock`.
_summary_state: dict[str, str] = {}

# The file is re-saved for an unsent call only when last_seen advanced by at
# least this much (rule 6: no per-tick disk write).
_LAST_SEEN_SAVE_SECONDS = 3600.0
_SUMMARY_DEADLINE_HOUR_BERLIN = 12

# Action types (daily summary) and their summary categories.
_PAST_STOP_TYPES = ('STOP_REACHED', 'STRUCTURAL_STOP_BREACHED', 'PREMIUM_STOP')
ACTION_TYPES = frozenset({*_PAST_STOP_TYPES, 'TP_HIT', 'TIME_STOP'})
_ACTION_TYPE_ORDER = ('STOP_REACHED', 'STRUCTURAL_STOP_BREACHED', 'PREMIUM_STOP',
                      'TP_HIT', 'TIME_STOP')


def _now() -> float:
    """Wall clock (epoch seconds) for the episode path (patched in tests)."""
    return time.time()

# Persisted across restarts so a backend restart does NOT re-email every
# currently-breached position. Stored as wall-clock seconds (time.time()),
# NOT monotonic — monotonic resets each process and is meaningless on disk.
_DEDUP_PATH = Path(__file__).parent.parent.parent.parent / 'alert_dedup.json'


def _save_dedup() -> bool:
    """Persist dedup state. Caller must hold _fired_lock.

    Returns True when the file was written, False when it was not. It still
    never raises -- every existing caller relies on that -- but a caller that
    must know whether the ON-DISK state matches memory (`forget_alerts`) can.

    ATOMIC: serialise first, write a unique temp file beside the target, fsync
    it, then os.replace() it over the target. The old bare open(path, 'w')
    truncated the file BEFORE writing, so a crash or encoding error part-way
    left it empty or half-written -- and _load_dedup then lost every dedup
    hold AND first-seen record on the next restart. Now a failure at any step
    leaves the previous file exactly as it was.
    """
    tmp_name = None
    try:
        payload = json.dumps({
            'fired': _fired, 'first_seen': _first_seen,
            'episodes': _episodes, 'summary_day': _summary_state.get('day'),
        })
        fd, tmp_name = tempfile.mkstemp(
            dir=_DEDUP_PATH.parent, prefix='.alert_dedup.', suffix='.tmp')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, _DEDUP_PATH)
        tmp_name = None
        return True
    except Exception:
        logger.warning('Could not persist dedup state', exc_info=True)
        return False
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def _finite_number(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _parse_episode(value) -> Optional[dict]:
    """One persisted episode record, or None when any field is missing or
    malformed (the entry is then dropped, never half-used)."""
    if not isinstance(value, dict):
        return None
    start, truncated = value.get('start'), value.get('truncated')
    last_seen = value.get('last_seen')
    if 'last_sent' not in value:
        return None
    last_sent = value.get('last_sent')
    if not (_finite_number(start) and _finite_number(last_seen)
            and isinstance(truncated, bool)):
        return None
    if last_sent is not None and not _finite_number(last_sent):
        return None
    return {'start': float(start), 'truncated': truncated,
            'last_seen': float(last_seen),
            'last_sent': None if last_sent is None else float(last_sent)}


def _parse_day(value) -> Optional[str]:
    if not isinstance(value, str):
        return None
    try:
        datetime.strptime(value, '%Y-%m-%d')
    except ValueError:
        return None
    return value


def _load_dedup() -> None:
    """Load dedup state from disk into the in-memory dicts (idempotent).

    The episode map and the summary day load tolerantly: a missing or garbled
    entry is dropped on its own, without costing the rest of the file.
    """
    try:
        if _DEDUP_PATH.exists():
            with open(_DEDUP_PATH, encoding='utf-8') as f:
                data = json.load(f) or {}
            if not isinstance(data, dict):
                raise ValueError('alert_dedup.json is not a JSON object')
            episodes = data.get('episodes')
            if isinstance(episodes, dict):
                for k, v in episodes.items():
                    rec = _parse_episode(v)
                    if isinstance(k, str) and rec is not None:
                        _episodes[k] = rec
            day = _parse_day(data.get('summary_day'))
            if day is not None:
                _summary_state['day'] = day
            _fired.update({k: float(v) for k, v in data.get('fired', {}).items()})
            _first_seen.update(data.get('first_seen', {}))
    except Exception:
        # WARNING, not DEBUG: an unreadable store means every dedup hold and
        # first-seen record is gone, which the operator needs to see.
        logger.warning('Could not load dedup state', exc_info=True)


_load_dedup()


def _load_delivery_config() -> dict:
    try:
        if _SETTINGS_PATH.exists():
            with open(_SETTINGS_PATH) as f:
                cfg = yaml.safe_load(f) or {}
                return cfg.get('alert_delivery', {})
    except Exception:
        logger.debug('Could not load alert_delivery config', exc_info=True)
    return {}


def _dedup_seconds(delivery: dict) -> float:
    hours = delivery.get('reminderIntervalHours', _DEFAULT_REMINDER_HOURS)
    try:
        secs = float(hours) * 3600.0
    except (TypeError, ValueError):
        secs = _DEFAULT_REMINDER_HOURS * 3600.0
    return max(secs, _MIN_DEDUP_SECONDS)


def _format_dt(timestamp: str | None) -> tuple[str, str]:
    """Parse an ISO timestamp (UTC) into local (date, time) strings.

    Returns ('dd.mm.yyyy', 'HH:MM:SS'). Falls back to the current time when the
    timestamp is missing or unparseable.
    """
    dt: datetime | None = None
    if timestamp:
        try:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        except ValueError:
            dt = None
    if dt is None:
        dt = datetime.now(timezone.utc)
    local = dt.astimezone(_CET) if _CET else dt.astimezone()
    return local.strftime('%d.%m.%Y'), local.strftime('%H:%M:%S')


_ALERT_TYPE_LABELS = {
    'TP_HIT': 'Target reached',
    'STOP_REACHED': 'Stop hit',
    'STRUCTURAL_STOP_BREACHED': 'Structural level hit',
    'PREMIUM_STOP': 'Premium stop hit',
    'TIME_STOP': 'Time stop hit',
    'EVENT_RISK': 'Event risk warning',
    'REGIME_CHANGE': 'Market regime changed',
}

# STOP-SEMANTICS-2026-10-02 -- PREMIUM_STOP's label by the side it fired under
# (`AlertItem.stopSide`). None (an unstamped or legacy fire) keeps the legacy
# label above.
_PREMIUM_STOP_LABELS_BY_SIDE = {
    'short-stock': 'Stock stop hit (short)',
    'long-stock': 'Stock stop hit',
    'option': 'Premium stop hit',
}


def _dedup_key(rec_id: str, alert_type: str, stop_side: str | None) -> str:
    """The dedup / first-seen key for one alert condition.

    A short stock's PREMIUM_STOP gets its OWN key (`...:short`). Its stop fires
    on a RISE since STOP-SEMANTICS; state written under the old fall-side rule
    (a `_fired` hold, a `_first_seen` date) lives on the legacy key and so can
    neither suppress the rise-side fire nor send it as a "(reminder)" dated at
    the wrong-side trigger. This replaces a one-time reset at deploy: nothing
    has to run once, so nothing can run twice. `forget_alerts` splits on the
    FIRST `|`, so a closed short still clears both keys.
    """
    key = f'{rec_id}|{alert_type}'
    if alert_type == 'PREMIUM_STOP' and stop_side == 'short-stock':
        key += ':short'
    return key


def _type_label(alert_type: str, stop_side: str | None) -> str:
    return (
        _PREMIUM_STOP_LABELS_BY_SIDE.get(stop_side or '', _ALERT_TYPE_LABELS['PREMIUM_STOP'])
        if alert_type == 'PREMIUM_STOP'
        else _ALERT_TYPE_LABELS.get(alert_type, alert_type)
    )


def _build_notification(symbol: str, alert_type: str, reason: str,
                        timestamp: str | None,
                        is_reminder: bool = False,
                        stop_side: str | None = None,
                        *,
                        start_truncated: bool = False,
                        active_line: str | None = None) -> tuple[str, str, str]:
    """``start_truncated`` / ``active_line`` are used by the episode path only:
    a truncated start is the earliest KNOWN fire, so ``Triggered:`` reads
    "before dd.mm.yyyy" (no exact date or time); ``active_line`` is the
    reminder's "Active for ..." line. The window path passes neither."""
    # Date/Time always reflect the ORIGINAL trigger, even on reminders.
    date_str, time_str = _format_dt(timestamp)
    type_label = _type_label(alert_type, stop_side)
    tag = ' (reminder)' if is_reminder else ''
    subject = f'Bamendjou Portfolio Alert — {symbol}: {type_label}{tag}'
    triggered = (f'Triggered: before {date_str}' if start_truncated
                 else f'Triggered: {date_str}, {time_str} {_TZ_LABEL}')
    active_plain = f'{active_line}\n' if active_line else ''
    active_html = f'{html_lib.escape(active_line)}\n' if active_line else ''
    # On a reminder, note that the condition is still active as of now, without
    # disturbing the original Triggered: line above.
    still_plain = ''
    still_html = ''
    if is_reminder:
        _, now_time = _format_dt(None)  # current CET time
        still_plain = f'Still active as of {now_time} {_TZ_LABEL}\n'
        still_html = f'Still active as of {now_time} {_TZ_LABEL}\n'
    plain = (
        f'{symbol} — {type_label}\n'
        f'{reason}\n\n'
        f'{triggered}\n'
        f'{active_plain}'
        f'{still_plain}'
    )
    # Telegram mirrors the email body exactly (same content, same order), with a
    # bold first line equal to the plain-language headline, prefixed with a
    # short "Portfolio:" category tag. Chart-alert and strategy-watch
    # notifications can land in the same Telegram chat as these, and neither
    # the plain-language headline nor the body distinguishes source once the
    # 2026-07-30 redesign (d9733d5) dropped the old "Bamendjou Portfolio
    # Alert" prefix -- this restores just enough context to tell them apart
    # at a glance without reverting to that verbose subject-as-headline
    # format. Telegram's HTML parse_mode only recognizes a small tag
    # allowlist (b/i/u/s/a/code/pre/blockquote) -- NOT <br> or any block tag.
    # An unsupported tag makes the Bot API reject the whole message with a
    # 400, which dispatch.py's error handling swallows into a log line with
    # no user-visible signal. Line breaks must be plain '\n', exactly like
    # the plain-text body -- Telegram renders literal newlines as line breaks
    # natively in HTML mode.
    # `reason` is built internally from f-string templates (see
    # alert_generator.py / portfolio_alert_monitor.py) so it's not truly
    # free-form user input today, but `symbol` and `alert_type` are caller-
    # supplied strings with no enforced format -- escaping all three is cheap
    # insurance against the same silent-Telegram-failure mode the <br> bug
    # caused, just via unexpected '<'/'&' characters instead of a hardcoded tag.
    html = (
        f'<b>Portfolio: {html_lib.escape(symbol)} — {html_lib.escape(type_label)}</b>\n'
        f'{html_lib.escape(reason)}\n\n'
        f'{triggered}\n'
        f'{active_html}'
        f'{still_html}'
    )
    return subject, plain, html


def is_episode_notified(alert_type: str, rec_id: str) -> bool:
    """True for the types escalated per episode (first fire + one reminder per
    24 h): POSITION_ALERT_TYPES on a real position. REGIME_CHANGE and every
    auto-trader type keep the reminderIntervalHours window path."""
    return alert_type in POSITION_ALERT_TYPES and rec_id != 'regime'


def _send_allowed(delivery: dict, alert_type: str, type_enabled: bool | None) -> bool:
    if not delivery.get('masterEnabled', True):
        return False
    if type_enabled is not None:
        return bool(type_enabled)
    return alert_type in delivery.get('enabledTypes', _DEFAULT_ENABLED_TYPES)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def _berlin_date(dt: datetime) -> str:
    local = as_utc(dt).astimezone(_CET) if _CET else as_utc(dt).astimezone()
    return local.strftime('%d.%m.%Y')


def _since_text(start: datetime, now: datetime, truncated: bool) -> str:
    """'9 days (since 18.11.2026)' / '30+ days (since before 28.10.2026)'."""
    duration = format_active_duration(start, now, truncated)
    before = 'before ' if truncated else ''
    return f'{duration} (since {before}{_berlin_date(start)})'


async def _notify_episode(symbol: str, alert_type: str, reason: str, key: str,
                          delivery: dict, type_enabled: bool | None,
                          stop_side: str | None,
                          episode_start: EpisodeStart | None) -> bool:
    """Episode cadence for one key (plan §2, rules 1-6).

    The state update (rules 1-3) runs on EVERY call, before the master/type
    gating, against the record's PREVIOUS last_seen; the gating decides only
    whether to send (rule 4) and so whether last_sent changes.
    """
    now = _now()
    gap = effective_gap(delivery).total_seconds()
    h_start: float | None = None
    h_truncated = False
    if episode_start is not None:
        h_start = as_utc(episode_start.start).timestamp()
        h_truncated = bool(episode_start.truncated)

    with _fired_lock:
        rec = _episodes.get(key)
        prev_seen = rec['last_seen'] if rec is not None else None
        # Rule 1 -- a truncated history start never by itself starts one.
        new_episode = (
            rec is None
            or now - prev_seen > gap
            or (h_start is not None and not h_truncated and h_start > prev_seen)
        )
        dirty = False
        if new_episode:
            # Rule 2 -- no legacy seed: `_first_seen` is never read here.
            if h_start is not None:
                start, truncated = h_start, h_truncated
            else:
                start, truncated = now, False
            rec = {'start': start, 'truncated': truncated,
                   'last_seen': now, 'last_sent': None}
            _episodes[key] = rec
            dirty = True
        else:
            # Rule 3 -- the start only ever moves earlier.
            if h_start is not None and h_start < rec['start']:
                rec['start'], rec['truncated'] = h_start, h_truncated
                dirty = True
            if now - prev_seen >= _LAST_SEEN_SAVE_SECONDS:
                dirty = True
            rec['last_seen'] = now

        # Rule 4 -- the gating decides only the send.
        if not _send_allowed(delivery, alert_type, type_enabled):
            if dirty:
                _save_dedup()
            return False
        prev_sent = rec['last_sent']
        if prev_sent is None:
            is_reminder = False
        elif now - prev_sent >= REMINDER_PERIOD_HOURS * 3600.0:
            is_reminder = True
        else:
            if dirty:
                _save_dedup()
            return False
        # Rule 5 -- optimistic hold, claimed before the (async) send.
        rec['last_sent'] = now
        start, truncated = rec['start'], rec['truncated']
        _save_dedup()

    active_line = None
    if is_reminder:
        active_line = 'Active for ' + _since_text(
            datetime.fromtimestamp(start, timezone.utc),
            datetime.fromtimestamp(now, timezone.utc), truncated)
    subject, plain, html = _build_notification(
        symbol, alert_type, reason, _iso(start), is_reminder=is_reminder,
        stop_side=stop_side, start_truncated=truncated, active_line=active_line)
    try:
        sent = await notify_enabled_channels(subject, plain, html)
    except Exception:
        logger.error('Failed to dispatch notification for %s', key, exc_info=True)
        sent = False

    if not sent:
        with _fired_lock:
            # Only last_sent is restored (the episode state stays), and only if
            # nothing newer has claimed or reset the record meanwhile.
            cur = _episodes.get(key)
            if cur is not None and cur.get('last_sent') == now:
                cur['last_sent'] = prev_sent
            _save_dedup()
        return False

    logger.info('Dispatched alert notification: %s', key)
    return True


async def notify_alert(symbol: str, alert_type: str, reason: str, rec_id: str,
                 timestamp: str | None = None,
                 type_enabled: bool | None = None,
                 stop_side: str | None = None,
                 episode_start: EpisodeStart | None = None) -> bool:
    """Dispatch one portfolio alert to email/Telegram, deduped across all callers.

    Returns True if the alert was actually delivered by at least one channel,
    False if suppressed (master off, type disabled, already sent within the
    dedup window) or if delivery genuinely failed. The dedup window is only
    armed on a CONFIRMED send — a bad SMTP password or a dead Telegram bot
    token used to mark the alert "sent" the instant it was scheduled
    (fire-and-forget, outcome unobserved), which then silently suppressed
    every retry for the whole dedup window even though nothing was ever
    delivered. Now a failed attempt leaves the key unmarked so the very next
    check retries instead of going quiet.

    ``type_enabled`` carries a position's explicit per-type override (Feature D)
    and, when not None, REPLACES the global ``enabledTypes`` check for this one
    call — that is what lets a single position turn an alert type on while it
    stays off account-wide. Leave it None (the default, and every caller that
    has no position in hand) to use the global list as before. ``masterEnabled``
    is deliberately NOT bypassed: it is the user's account-wide kill switch and
    a per-position toggle must not defeat it.

    ``stop_side`` is the PREMIUM_STOP side stamp (``AlertItem.stopSide``). It
    picks the label and, for a short stock, the separate dedup key
    (``_dedup_key``). Ignored for every other type.

    ``episode_start`` (PORTFOLIO-ALERT-ACTION) is the key's current history
    episode ``(start, truncated)`` or None. For an episode-notified type
    (``is_episode_notified``) the window/``_first_seen`` path below is replaced
    by ``_notify_episode``: one first-fire message per episode, then at most
    one reminder per 24 h. It is ignored on the window path.
    """
    delivery = _load_delivery_config()
    if is_episode_notified(alert_type, rec_id):
        return await _notify_episode(
            symbol, alert_type, reason, _dedup_key(rec_id, alert_type, stop_side),
            delivery, type_enabled, stop_side, episode_start)

    if not delivery.get('masterEnabled', True):
        return False

    if type_enabled is not None:
        if not type_enabled:
            return False
    else:
        enabled_types = delivery.get('enabledTypes', _DEFAULT_ENABLED_TYPES)
        if alert_type not in enabled_types:
            return False

    key = _dedup_key(rec_id, alert_type, stop_side)
    now = time.time()
    window = _dedup_seconds(delivery)

    with _fired_lock:
        # purge expired entries (>= so a zero-second window expires immediately)
        expired = [k for k, ts in _fired.items() if now - ts >= window]
        for k in expired:
            _fired.pop(k, None)

        if key in _fired:
            return False  # already sent within the window

        # Optimistic hold: claimed now, before the actual (async) send, so a
        # concurrent call for the same key (browser POST racing the headless
        # monitor's tick) still can't double-send during the network round
        # trip. Rolled back below if delivery doesn't actually succeed.
        _fired[key] = now
        # First-ever send for this condition records the trigger time; later
        # sends are reminders and reuse it. _first_seen outlives the dedup purge.
        original_ts = _first_seen.get(key)
        is_reminder = original_ts is not None
        if not is_reminder:
            original_ts = timestamp or datetime.now(timezone.utc).isoformat()
            _first_seen[key] = original_ts
        _save_dedup()
    subject, plain, html = _build_notification(
        symbol, alert_type, reason, original_ts, is_reminder=is_reminder,
        stop_side=stop_side)
    try:
        sent = await notify_enabled_channels(subject, plain, html)
    except Exception:
        logger.error('Failed to dispatch notification for %s', key, exc_info=True)
        sent = False

    if not sent:
        with _fired_lock:
            # Release the hold so the next check retries this condition
            # instead of staying silent for the rest of the dedup window —
            # but only if nothing newer has since claimed the key.
            if _fired.get(key) == now:
                _fired.pop(key, None)
            if not is_reminder:
                _first_seen.pop(key, None)
            _save_dedup()
        return False

    logger.info('Dispatched alert notification: %s', key)
    return True


def forget_alerts(rec_ids: set[str]) -> bool:
    """Drop dedup entries for the given recIds so a re-entry can alert again.

    Called by the monitor when positions disappear from the portfolio.

    Returns False when the in-memory holds were cleared but the file could not
    be written, so the ON-DISK hold survives a restart (P3b). The portfolio
    monitor ignores the result; the auto-trader's callers report it.
    """
    if not rec_ids:
        return True
    with _fired_lock:
        to_remove = {k for k in _fired if k.split('|', 1)[0] in rec_ids}
        for k in to_remove:
            _fired.pop(k, None)
        # Drop original-trigger records too, so a genuine re-entry later starts
        # a fresh trigger timestamp instead of inheriting the closed one.
        stale_first = {k for k in _first_seen if k.split('|', 1)[0] in rec_ids}
        for k in stale_first:
            _first_seen.pop(k, None)
        # ...and the episode records (same first-`|` split, so a closed
        # short's `:short` key goes too).
        stale_episodes = {k for k in _episodes if k.split('|', 1)[0] in rec_ids}
        for k in stale_episodes:
            _episodes.pop(k, None)
        saved = _save_dedup()
    if to_remove:
        logger.info('Cleared %d dedup entries for closed positions', len(to_remove))
    return saved


# ── Daily summary (PORTFOLIO-ALERT-ACTION, #672) ────────────────────────────

@dataclass(frozen=True)
class SummaryItem:
    """One (position, action type) line of the daily summary. ``start`` is the
    key's current history episode start (None when unknown -> no duration)."""
    rec_id: str
    symbol: str
    alert_type: str
    start: Optional[datetime] = None
    truncated: bool = False
    stop_side: Optional[str] = None


def _berlin(now: datetime) -> datetime:
    return as_utc(now).astimezone(_CET) if _CET else as_utc(now).astimezone()


def berlin_day(now: datetime) -> str:
    """The Europe/Berlin calendar day of ``now`` as YYYY-MM-DD."""
    return _berlin(now).strftime('%Y-%m-%d')


def summary_due(now: datetime) -> bool:
    """Berlin local time >= 09:00 and today's summary not yet concluded."""
    if _berlin(now).hour < DAILY_SUMMARY_HOUR_BERLIN:
        return False
    with _fired_lock:
        return _summary_state.get('day') != berlin_day(now)


def summary_deadline_passed(now: datetime) -> bool:
    """From 12:00 Berlin the summary is sent even with unquoted positions."""
    return _berlin(now).hour >= _SUMMARY_DEADLINE_HOUR_BERLIN


def _plural(n: int, singular: str, plural: str) -> str:
    return f'{n} {singular if n == 1 else plural}'


def _summary_subject(items: Sequence[SummaryItem]) -> str:
    def _positions(types: Iterable[str]) -> int:
        wanted = set(types)
        return len({i.rec_id for i in items if i.alert_type in wanted})

    parts = []
    past_stop = _positions(_PAST_STOP_TYPES)
    if past_stop:
        parts.append(_plural(past_stop, 'position past stop', 'positions past stop'))
    target = _positions(('TP_HIT',))
    if target:
        parts.append(f'{target} at target')
    time_stop = _positions(('TIME_STOP',))
    if time_stop:
        parts.append(_plural(time_stop, 'time stop', 'time stops'))
    return 'Bamendjou Portfolio — daily summary: ' + (', '.join(parts) or 'no action alerts')


def _summary_line(item: SummaryItem, now: datetime) -> str:
    line = f'{item.symbol} — {_type_label(item.alert_type, item.stop_side)}'
    if item.start is not None:
        line += ', active ' + _since_text(item.start, now, item.truncated)
    return line


async def notify_daily_summary(items: Sequence[SummaryItem], now: datetime,
                               unquoted: Sequence[str] = ()) -> bool:
    """Send (or, with nothing to report, conclude) today's Berlin summary.

    ``items`` are this tick's action-type alerts the caller already filtered
    to enabled types and quoted positions; ``unquoted`` lists the positions
    without a quote (one entry per position), reported on their own line and
    excluded from the counts. Returns True when the day is concluded: zero
    items and zero unquoted (no message), or a confirmed delivery. The day is
    recorded only then -- a failed send returns False and the caller retries.
    """
    day = berlin_day(now)
    seen: set[tuple[str, str]] = set()
    unique: list[SummaryItem] = []
    for item in items:
        if item.alert_type not in ACTION_TYPES or (item.rec_id, item.alert_type) in seen:
            continue
        seen.add((item.rec_id, item.alert_type))
        unique.append(item)

    if not unique and not unquoted:
        with _fired_lock:
            _summary_state['day'] = day
            _save_dedup()
        return True

    unique.sort(key=lambda i: (i.symbol, _ACTION_TYPE_ORDER.index(i.alert_type), i.rec_id))
    lines = [_summary_line(i, now) for i in unique]
    if unquoted:
        noun = 'position' if len(unquoted) == 1 else 'positions'
        lines.append(f'{len(unquoted)} {noun} without a quote: {", ".join(unquoted)}')
    subject = _summary_subject(unique)
    plain = '\n'.join(lines) + '\n'
    html = (f'<b>Portfolio: daily summary</b>\n'
            + '\n'.join(html_lib.escape(line) for line in lines) + '\n')
    try:
        sent = await notify_enabled_channels(subject, plain, html)
    except Exception:
        logger.error('Failed to dispatch the daily summary', exc_info=True)
        sent = False
    if not sent:
        return False
    with _fired_lock:
        _summary_state['day'] = day
        _save_dedup()
    logger.info('Dispatched daily summary for %s', day)
    return True
