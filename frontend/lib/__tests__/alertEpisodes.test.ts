import {
  EPISODE_GAP_HOURS, REMINDER_PERIOD_HOURS, DAILY_SUMMARY_HOUR_BERLIN,
  formatActiveDuration, formatSince, episodeKey,
} from '@/lib/alertEpisodes';

// PORTFOLIO-ALERT-ACTION T4 (#672). Mirrors backend/tests/test_alert_episodes.py
// DURATION_CASES case for case: the two formatters must say the same thing.

const MIN = 60_000;
const H = 60 * MIN;
const D = 24 * H;

const DURATION_CASES: [number, boolean, string][] = [
  [0, false, 'under 1 h'],
  [59 * MIN + 59_000, false, 'under 1 h'],
  [H, false, '1 h'],
  [23 * H + 59 * MIN, false, '23 h'],
  [24 * H, false, '1 day'],
  [47 * H + 59 * MIN, false, '1 day'],
  [48 * H, false, '2 days'],
  [30 * D + 5 * H, false, '30 days'],
  [30 * D + 5 * H, true, '30+ days'],
  [D, true, '1+ days'],
];

const NOW = new Date('2026-11-27T12:00:00Z');

describe('alertEpisodes constants (keep in step with backend alert_episodes.py)', () => {
  it('mirror the backend values', () => {
    expect(EPISODE_GAP_HOURS).toBe(72);
    expect(REMINDER_PERIOD_HOURS).toBe(24);
    expect(DAILY_SUMMARY_HOUR_BERLIN).toBe(9);
  });
});

describe('formatActiveDuration', () => {
  it.each(DURATION_CASES)('delta %p ms, truncated %p → %p', (delta, truncated, text) => {
    expect(formatActiveDuration(new Date(NOW.getTime() - delta), NOW, truncated)).toBe(text);
  });

  it('accepts the API ISO string (UTC offset)', () => {
    expect(formatActiveDuration('2026-11-27T09:00:00+00:00', NOW, false)).toBe('3 h');
  });

  it('a future start reads "under 1 h"', () => {
    expect(formatActiveDuration(new Date(NOW.getTime() + 2 * H), NOW, false)).toBe('under 1 h');
  });

  it('an unparseable start returns null, never a number', () => {
    expect(formatActiveDuration('not a date', NOW, false)).toBeNull();
  });
});

describe('formatSince', () => {
  it('exact date only for a non-truncated start', () => {
    expect(formatSince('2026-11-18T12:00:00+00:00', false)).toBe('since 18 Nov');
  });
  it('truncated start reads "since before"', () => {
    expect(formatSince('2026-10-28T12:00:00+00:00', true)).toBe('since before 28 Oct');
  });
  it('unparseable → null', () => {
    expect(formatSince('nope', false)).toBeNull();
  });
});

describe('episodeKey', () => {
  it('is (recId, alertType)', () => {
    expect(episodeKey('REC-1', 'STOP_REACHED')).toBe(episodeKey('REC-1', 'STOP_REACHED'));
    expect(episodeKey('REC-1', 'STOP_REACHED')).not.toBe(episodeKey('REC-1', 'TP_HIT'));
  });
});
