// frontend/lib/staleCurve.ts
// Pure rule for the "this P&L line has stopped" notice (PORTFOLIO-SYNC-STATE).
import { formatMoney } from './portfolioFormat';
import { etDateIso, lastTradingDayEt } from './tradingDay';

export interface CurvePoint { date: string; value: number }

export interface StaleCurveInput {
  kind: 'open' | 'equity';
  lastSnapshotDate: string | null;
  curve: CurvePoint[];
  positionsCount: number;
  openPnlToday: number;
  unquotedSymbols: string[];
  skippedContracts: string[];
  now: Date;
  ready: boolean;
}

export interface StaleCurveNotice {
  text: string;
  lastPointDate: string;
  referenceDay: string;
  liveValue: number | null;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** `D MMM`, plus the year when it differs from `currentYearIso`'s year. */
export function formatPointDate(iso: string, currentYearIso: string): string {
  const [y, m, d] = iso.split('-').map(Number) as [number, number, number];
  const base = `${d} ${MONTHS[m - 1]}`;
  return String(y) === currentYearIso.slice(0, 4) ? base : `${base} ${y}`;
}

function uniq(xs: string[]): string[] {
  return Array.from(new Set(xs));
}

export function staleCurveNotice(input: StaleCurveInput): StaleCurveNotice | null {
  const { kind, lastSnapshotDate, curve, positionsCount, openPnlToday, now } = input;
  if (!input.ready) return null;
  if (positionsCount <= 0) return null;
  if (curve.length === 0 || lastSnapshotDate === null) return null;

  const referenceDay = lastTradingDayEt(now);
  if (!(lastSnapshotDate < referenceDay)) return null;

  const sorted = [...curve].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  let lastPoint = sorted[sorted.length - 1]!;
  if (lastPoint.date !== lastSnapshotDate) {
    const match = sorted.find((p) => p.date === lastSnapshotDate);
    if (!match) return null; // never print a mismatched pair
    lastPoint = match;
  }

  const symbols = input.skippedContracts.length > 0
    ? uniq(input.skippedContracts.map((c) => c.split('|')[0]!))
    : uniq(input.unquotedSymbols);
  const cause = symbols.length > 0
    ? `No daily snapshot is written while a position has no quote (${symbols.join(', ')} now), so the line has stopped.`
    : 'No daily snapshot has been written since then. One is written when this page loads with every position quoted.';

  const point = `Last point: ${formatPointDate(lastPoint.date, etDateIso(now))}, ${formatMoney(lastPoint.value, { plus: true })}.`;
  const text = kind === 'open'
    ? `${point} Open P&L today is ${formatMoney(openPnlToday)}. ${cause}`
    : `${point} ${cause}`;

  return {
    text,
    lastPointDate: lastPoint.date,
    referenceDay,
    liveValue: kind === 'open' ? openPnlToday : null,
  };
}
