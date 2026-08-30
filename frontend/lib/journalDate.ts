/*
 * Trading Journal — local-calendar-day <-> UTC ISO conversion.
 *
 * The journal's `entry_date` field and its `date_from`/`date_to` filters are
 * all calendar days picked via <input type="date"> ("YYYY-MM-DD"), but stored
 * server-side as `DateTime(timezone=True)`, UTC-normalized. Sending a bare
 * "YYYY-MM-DD" string would let the backend's datetime parser read it as UTC
 * midnight rather than the user's LOCAL midnight — an off-by-one-day bug for
 * any timezone west of UTC. Every write path (the entry_date field itself,
 * and the date_from/date_to filter boundaries) must instead construct local
 * midnight (`new Date(year, month, day, 0, 0, 0)`) — or local end-of-day for
 * date_to — and send `.toISOString()`.
 *
 * This is the first date-range filter of this shape in the app — there was
 * no existing pattern to copy, so this mechanic is implemented fresh here and
 * shared by both the filter bar and the entry form (Frontend changes plan,
 * Context section).
 */

function parseDateInputValue(value: string): { year: number; month: number; day: number } | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim());
  if (!m) return null;
  return { year: Number(m[1]), month: Number(m[2]) - 1, day: Number(m[3]) };
}

/** "YYYY-MM-DD" (local calendar day) -> ISO string at LOCAL midnight. Used for
 *  `entry_date` on write, and as the `date_from` filter boundary. */
export function localDateInputToStartOfDayIso(value: string): string | undefined {
  const d = parseDateInputValue(value);
  if (!d) return undefined;
  return new Date(d.year, d.month, d.day, 0, 0, 0, 0).toISOString();
}

/** "YYYY-MM-DD" (local calendar day) -> ISO string at LOCAL end-of-day. Used
 *  for the `date_to` filter boundary, so the whole picked day is included. */
export function localDateInputToEndOfDayIso(value: string): string | undefined {
  const d = parseDateInputValue(value);
  if (!d) return undefined;
  return new Date(d.year, d.month, d.day, 23, 59, 59, 999).toISOString();
}

/** ISO datetime -> "YYYY-MM-DD" for pre-filling an <input type="date">, using
 *  LOCAL date parts (mirrors the local-midnight encoding above) — reading the
 *  UTC date parts back out would reproduce the same off-by-one-day bug this
 *  module exists to avoid, for anyone west of UTC. */
export function isoToLocalDateInputValue(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const y = String(d.getFullYear()).padStart(4, '0');
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}
