import { staleCurveNotice, formatPointDate, type StaleCurveInput } from '../staleCurve';

// 2026-11-17 (Tuesday) 12:00 ET
const NOW = new Date('2026-11-17T17:00:00Z');
const curve = [
  { date: '2026-10-22', value: 1400 },
  { date: '2026-10-23', value: 1530 },
];
const base: StaleCurveInput = {
  kind: 'open',
  lastSnapshotDate: '2026-10-23',
  curve,
  positionsCount: 3,
  openPnlToday: -37,
  unquotedSymbols: ['BMY'],
  skippedContracts: ['BMY|67|2027-03-19|C'],
  now: NOW,
  ready: true,
};
const make = (o: Partial<StaleCurveInput> = {}) => staleCurveNotice({ ...base, ...o });

describe('staleCurveNotice null conditions (each alone)', () => {
  it('shows for the base fixture', () => { expect(make()).not.toBeNull(); });
  it('null when not ready', () => { expect(make({ ready: false })).toBeNull(); });
  it('null with no open positions', () => { expect(make({ positionsCount: 0 })).toBeNull(); });
  it('null with an empty curve', () => { expect(make({ curve: [] })).toBeNull(); });
  it('null with no lastSnapshotDate', () => { expect(make({ lastSnapshotDate: null })).toBeNull(); });
  it('null when the last snapshot is the reference day', () => {
    expect(make({ lastSnapshotDate: '2026-11-17', curve: [{ date: '2026-11-17', value: 5 }] })).toBeNull();
  });
  it('shown when one weekday older than the reference day', () => {
    expect(make({ lastSnapshotDate: '2026-11-16', curve: [{ date: '2026-11-16', value: 5 }] })).not.toBeNull();
  });
  it('null when the snapshot is dated after the reference day (CET-local date)', () => {
    expect(make({ lastSnapshotDate: '2026-11-18', curve: [{ date: '2026-11-18', value: 5 }] })).toBeNull();
  });
  it('null when lastSnapshotDate is not in the curve and the newest point differs', () => {
    expect(make({ lastSnapshotDate: '2026-10-24' })).toBeNull();
  });
});

describe('staleCurveNotice text', () => {
  it('prints the exact sample sentence', () => {
    expect(make()!.text).toBe(
      'Last point: 23 Oct, +$1,530. Open P&L today is −$37. No daily snapshot is written while a position has no quote (BMY now), so the line has stopped.',
    );
  });
  it('equity variant has no Open P&L sentence and no live value', () => {
    const n = make({ kind: 'equity' })!;
    expect(n.text).toBe(
      'Last point: 23 Oct, +$1,530. No daily snapshot is written while a position has no quote (BMY now), so the line has stopped.',
    );
    expect(n.liveValue).toBeNull();
  });
  it('open notice carries liveValue = openPnlToday and dates', () => {
    const n = make()!;
    expect(n.liveValue).toBe(-37);
    expect(n.lastPointDate).toBe('2026-10-23');
    expect(n.referenceDay).toBe('2026-11-17');
  });
  it('falls back when no symbols are known', () => {
    expect(make({ unquotedSymbols: [], skippedContracts: [] })!.text).toBe(
      'Last point: 23 Oct, +$1,530. Open P&L today is −$37. No daily snapshot has been written since then. One is written when this page loads with every position quoted.',
    );
  });
  it('skipped contracts take precedence over unquoted symbols, deduplicated', () => {
    const n = make({
      skippedContracts: ['BMY|67|2027-03-19|C', 'BMY|70|2027-03-19|C', 'AAPL|1|2027-01-01|P'],
      unquotedSymbols: ['ZZZ'],
    })!;
    expect(n.text).toContain('(BMY, AAPL now)');
    expect(n.text).not.toContain('ZZZ');
  });
  it('uses unquoted symbols when skipped contracts are empty', () => {
    expect(make({ skippedContracts: [], unquotedSymbols: ['BMY', 'KO'] })!.text).toContain('(BMY, KO now)');
  });
  it('adds the year only when it differs from now ET year', () => {
    const n = make({ lastSnapshotDate: '2025-12-31', curve: [{ date: '2025-12-31', value: -12.4 }] })!;
    expect(n.text.startsWith('Last point: 31 Dec 2025, −$12.')).toBe(true);
  });
  it('uses the raw newest point after sorting, not input order', () => {
    const n = make({ curve: [curve[1]!, curve[0]!] })!;
    expect(n.text).toContain('Last point: 23 Oct, +$1,530.');
  });
  it('uses lastSnapshotDate point when the newest point differs but it is present', () => {
    const n = make({
      lastSnapshotDate: '2026-10-23',
      curve: [...curve, { date: '2026-10-24', value: 9 }],
    })!;
    expect(n.text).toContain('Last point: 23 Oct, +$1,530.');
    expect(n.lastPointDate).toBe('2026-10-23');
  });
  it('formats a gain with plus and a zero without', () => {
    expect(make({ curve: [{ date: '2026-10-23', value: 0 }] })!.text).toContain('Last point: 23 Oct, $0.');
  });
});

describe('weekend reference', () => {
  it('Saturday now: a Friday snapshot is current', () => {
    const sat = new Date('2026-11-21T17:00:00Z');
    expect(make({ now: sat, lastSnapshotDate: '2026-11-20', curve: [{ date: '2026-11-20', value: 1 }] })).toBeNull();
  });
  it('the 23 Oct curve is stale on Sat 21 Nov', () => {
    const n = make({ now: new Date('2026-11-21T17:00:00Z') })!;
    expect(n.referenceDay).toBe('2026-11-20');
  });
});

describe('formatPointDate', () => {
  it('manual D MMM', () => {
    expect(formatPointDate('2026-10-03', '2026-11-17')).toBe('3 Oct');
    expect(formatPointDate('2025-01-09', '2026-11-17')).toBe('9 Jan 2025');
  });
});
