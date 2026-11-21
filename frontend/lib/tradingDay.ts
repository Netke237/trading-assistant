// frontend/lib/tradingDay.ts
// Weekday-only "last trading day" in America/New_York. No holiday calendar:
// on an exchange holiday the reference day is that weekday (see the
// PORTFOLIO-SYNC-STATE plan, stale-curve rule 4).

const ET = 'America/New_York';

interface EtParts { iso: string; weekday: number; minutes: number }

const dateFmt = new Intl.DateTimeFormat('en-CA', {
  timeZone: ET, year: 'numeric', month: '2-digit', day: '2-digit',
});
const timeFmt = new Intl.DateTimeFormat('en-US', {
  timeZone: ET, hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});

/** ET calendar date of `now` as `YYYY-MM-DD` (host time zone irrelevant). */
export function etDateIso(now: Date): string {
  const p = Object.fromEntries(dateFmt.formatToParts(now).map((x) => [x.type, x.value]));
  return `${p.year}-${p.month}-${p.day}`;
}

function etParts(now: Date): EtParts {
  const iso = etDateIso(now);
  const [y, m, d] = iso.split('-').map(Number) as [number, number, number];
  const weekday = new Date(Date.UTC(y, m - 1, d)).getUTCDay(); // 0 Sun .. 6 Sat
  const t = Object.fromEntries(timeFmt.formatToParts(now).map((x) => [x.type, x.value]));
  const minutes = Number(t.hour) * 60 + Number(t.minute);
  return { iso, weekday, minutes };
}

function shiftIso(iso: string, days: number): string {
  const [y, m, d] = iso.split('-').map(Number) as [number, number, number];
  const dt = new Date(Date.UTC(y, m - 1, d + days));
  return dt.toISOString().slice(0, 10);
}

/** Newest ET weekday whose regular session has opened (09:30 ET) at `now`. */
export function lastTradingDayEt(now: Date): string {
  const { iso, weekday, minutes } = etParts(now);
  let day = iso;
  let wd = weekday;
  if (wd === 0 || wd === 6) {
    // weekend -> Friday
    day = shiftIso(day, wd === 0 ? -2 : -1);
    return day;
  }
  if (minutes < 9 * 60 + 30) {
    // before the open: previous weekday (Monday -> Friday)
    day = shiftIso(day, wd === 1 ? -3 : -1);
  }
  return day;
}
