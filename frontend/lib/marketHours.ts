/*
 * US equity market hours helper (Eastern Time).
 *
 * Session boundaries (ET):
 *   PRE-MARKET   04:00 – 09:30
 *   REGULAR OPEN 09:30 – 16:00
 *   AFTER-HOURS  16:00 – 20:00
 *   CLOSED       otherwise (overnight + weekends)
 *
 * Does not account for market holidays — those are rare and not worth the
 * complexity of a full holiday calendar here.
 */

export type MarketStatus = 'PRE' | 'OPEN' | 'AFTER' | 'CLOSED';

export interface MarketState {
  status: MarketStatus;
  /** Minutes until the next status transition (used for PRE / OPEN / AFTER countdowns). */
  minutesUntilChange: number;
  /** Human-readable label for when the regular session next opens (used by CLOSED). */
  nextOpenLabel: string;
}

const PRE_START   = 4 * 60;       // 240  (4:00 AM)
const OPEN_START  = 9 * 60 + 30;  // 570  (9:30 AM)
const AFTER_START = 16 * 60;      // 960  (4:00 PM)
const CLOSED_EVE  = 20 * 60;      // 1200 (8:00 PM)
const DAY_MINS    = 24 * 60;      // 1440

/** Returns ET hour/minute/dayOfWeek without requiring timezone library. */
function etComponents(now: Date): { day: number; minuteOfDay: number } {
  // toLocaleString with timeZone returns the clock reading in ET;
  // wrapping it in new Date() gives a local-tz Date whose h/m match ET.
  const et = new Date(now.toLocaleString('en-US', { timeZone: 'America/New_York' }));
  return {
    day: et.getDay(),
    minuteOfDay: et.getHours() * 60 + et.getMinutes(),
  };
}

/**
 * Converts an ET time-of-day to the equivalent CET wall-clock label.
 * Uses the live ET↔CET offset so it stays correct across DST shifts
 * (e.g. 9:30 ET → "15:30").
 */
function etTimeToCetLabel(etHour: number, etMin: number, now: Date): string {
  const etNow = new Date(now.toLocaleString('en-US', { timeZone: 'America/New_York' }));
  const cetNow = new Date(now.toLocaleString('en-US', { timeZone: 'Europe/Berlin' }));
  const offsetMin = Math.round((cetNow.getTime() - etNow.getTime()) / 60000);
  let total = etHour * 60 + etMin + offsetMin;
  total = ((total % DAY_MINS) + DAY_MINS) % DAY_MINS;
  const h = Math.floor(total / 60);
  const m = total % 60;
  return `${h}:${String(m).padStart(2, '0')} CET`;
}

export function getMarketState(now: Date): MarketState {
  const { day, minuteOfDay } = etComponents(now);
  const isWeekday = day >= 1 && day <= 5;
  // Regular session opens 9:30 ET — shown to the user in CET.
  const openLabel = etTimeToCetLabel(9, 30, now);
  const monOpenLabel = `Mon ${openLabel}`;

  // --- Weekends ---
  if (!isWeekday) {
    const daysToMon = day === 6 ? 2 : 1; // Sat → 2, Sun → 1
    return {
      status: 'CLOSED',
      minutesUntilChange: daysToMon * DAY_MINS - minuteOfDay + OPEN_START,
      nextOpenLabel: monOpenLabel,
    };
  }

  // --- Weekday overnight (midnight → PRE) ---
  if (minuteOfDay < PRE_START) {
    return {
      status: 'CLOSED',
      minutesUntilChange: OPEN_START - minuteOfDay,
      nextOpenLabel: openLabel,
    };
  }

  // --- Pre-market ---
  if (minuteOfDay < OPEN_START) {
    return {
      status: 'PRE',
      minutesUntilChange: OPEN_START - minuteOfDay,
      nextOpenLabel: openLabel,
    };
  }

  // --- Regular session ---
  if (minuteOfDay < AFTER_START) {
    return {
      status: 'OPEN',
      minutesUntilChange: AFTER_START - minuteOfDay,
      nextOpenLabel: openLabel,
    };
  }

  // --- After-hours ---
  if (minuteOfDay < CLOSED_EVE) {
    return {
      status: 'AFTER',
      minutesUntilChange: CLOSED_EVE - minuteOfDay,
      nextOpenLabel: day === 5 ? monOpenLabel : openLabel,
    };
  }

  // --- Late evening (after 8 PM) ---
  const nextOpenLabel = day === 5 ? monOpenLabel : openLabel;
  return {
    status: 'CLOSED',
    minutesUntilChange: DAY_MINS - minuteOfDay + OPEN_START,
    nextOpenLabel,
  };
}

/** Formats a minute count as "2h 15m", "45m", or "2h". */
export function formatMinutes(mins: number): string {
  if (mins <= 0) return '0m';
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}
