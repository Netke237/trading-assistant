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

export function getMarketState(now: Date): MarketState {
  const { day, minuteOfDay } = etComponents(now);
  const isWeekday = day >= 1 && day <= 5;

  // --- Weekends ---
  if (!isWeekday) {
    const daysToMon = day === 6 ? 2 : 1; // Sat → 2, Sun → 1
    return {
      status: 'CLOSED',
      minutesUntilChange: daysToMon * DAY_MINS - minuteOfDay + OPEN_START,
      nextOpenLabel: 'Mon 9:30',
    };
  }

  // --- Weekday overnight (midnight → PRE) ---
  if (minuteOfDay < PRE_START) {
    return {
      status: 'CLOSED',
      minutesUntilChange: OPEN_START - minuteOfDay,
      nextOpenLabel: '9:30',
    };
  }

  // --- Pre-market ---
  if (minuteOfDay < OPEN_START) {
    return {
      status: 'PRE',
      minutesUntilChange: OPEN_START - minuteOfDay,
      nextOpenLabel: '9:30',
    };
  }

  // --- Regular session ---
  if (minuteOfDay < AFTER_START) {
    return {
      status: 'OPEN',
      minutesUntilChange: AFTER_START - minuteOfDay,
      nextOpenLabel: '9:30',
    };
  }

  // --- After-hours ---
  if (minuteOfDay < CLOSED_EVE) {
    return {
      status: 'AFTER',
      minutesUntilChange: CLOSED_EVE - minuteOfDay,
      nextOpenLabel: day === 5 ? 'Mon 9:30' : '9:30',
    };
  }

  // --- Late evening (after 8 PM) ---
  const nextOpenLabel = day === 5 ? 'Mon 9:30' : '9:30';
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
