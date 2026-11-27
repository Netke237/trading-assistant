/**
 * Alert episodes — frontend mirror (PORTFOLIO-ALERT-ACTION, #672).
 *
 * Definitions: docs/superpowers/plans/2026-11-27-portfolio-alert-action-plan.md.
 * The constants are code constants, not settings. Keep them, and
 * `formatActiveDuration`, in step with backend/app/services/alert_episodes.py
 * (`EPISODE_GAP_HOURS`, `REMINDER_PERIOD_HOURS`, `DAILY_SUMMARY_HOUR_BERLIN`,
 * `format_active_duration`); the two test tables mirror each other.
 */

export const EPISODE_GAP_HOURS = 72;
export const REMINDER_PERIOD_HOURS = 24;
export const DAILY_SUMMARY_HOUR_BERLIN = 9;

const HOUR_MS = 3_600_000;
const DAY_MS = 24 * HOUR_MS;

/** The alert key: `(recId, alertType)`. */
export function episodeKey(recId: string, alertType: string): string {
  return `${recId}\u0000${alertType}`;
}

function toMs(v: Date | string): number {
  return v instanceof Date ? v.getTime() : Date.parse(v);
}

/** Duration text, same rules as the backend's `format_active_duration`:
 *  `< 1 h` → "under 1 h"; `< 24 h` → "N h" (floor); else "N days" (floor of
 *  whole 24 h periods, "1 day" singular); truncated → "N+ days". A start after
 *  `now` counts as 0. Null when either time does not parse — never a number
 *  made up from NaN. */
export function formatActiveDuration(start: Date | string, now: Date, truncated: boolean): string | null {
  const s = toMs(start);
  const n = now.getTime();
  if (!Number.isFinite(s) || !Number.isFinite(n)) return null;
  const delta = Math.max(0, n - s);
  if (truncated) return `${Math.floor(delta / DAY_MS)}+ days`;
  if (delta < HOUR_MS) return 'under 1 h';
  if (delta < DAY_MS) return `${Math.floor(delta / HOUR_MS)} h`;
  const days = Math.floor(delta / DAY_MS);
  return days === 1 ? '1 day' : `${days} days`;
}

/** "since 18 Nov" (browser local date of the episode start), or
 *  "since before 28 Oct" when the start is truncated — then the date is only
 *  the earliest KNOWN fire, never the condition's start. Null when unparseable. */
export function formatSince(start: Date | string, truncated: boolean): string | null {
  const s = toMs(start);
  if (!Number.isFinite(s)) return null;
  const date = new Date(s).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
  return truncated ? `since before ${date}` : `since ${date}`;
}
