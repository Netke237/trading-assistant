export const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const;

/**
 * Returns a human-readable cadence description for schedule rows.
 *
 * When showDaysOfWeek is false (e.g. nightly ingestion, EDGAR fundamentals, S&P 500 update),
 * the job runs daily.
 * When showDaysOfWeek is true (e.g. Strategy Tuning), the hint describes the active
 * weekdays (e.g. "Runs at the configured time on Mon, Wed, Sat" or "Runs at the configured time on Sat").
 */
export function formatScheduleCadence(
  showDaysOfWeek: boolean,
  daysOfWeek: number[] | null | undefined,
): string {
  if (!showDaysOfWeek) {
    return 'Runs at the configured time every day';
  }
  const days = Array.isArray(daysOfWeek) ? daysOfWeek : [];
  const unique = Array.from(new Set(days))
    .filter((d) => Number.isInteger(d) && d >= 0 && d < DAY_LABELS.length)
    .sort((a, b) => a - b);
  if (unique.length === 0) {
    return 'No active days selected';
  }
  if (unique.length === DAY_LABELS.length) {
    return 'Runs at the configured time every day';
  }
  const dayNames = unique.map((d) => DAY_LABELS[d]).join(', ');
  return `Runs at the configured time on ${dayNames}`;
}
