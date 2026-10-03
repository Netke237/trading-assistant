import {
  daysSinceScan, earningsGateFor, EARNINGS_VETO_MESSAGE, EARNINGS_UNKNOWN_ARM_MESSAGE,
} from '@/lib/earningsGate';

/* Audit round 1, F4 — the auditor's example. Monday 2026-10-05: a Swing scan
 * sees earnings 23 days out against the 21-day reject window, so the backend
 * set earningsVeto false. Thursday 2026-10-08 the print is 20 days out. */
const MONDAY_SCAN = '2026-10-05T14:30:00';
const THURSDAY = new Date(2026, 9, 8, 10, 0, 0);
const MONDAY_LATER = new Date(2026, 9, 5, 22, 0, 0);
const STOCK = { earningsDays: 23, earningsVeto: false, earningsUnknown: false, isEtf: false };

describe('daysSinceScan', () => {
  it('counts whole calendar days, not 24-hour blocks', () => {
    expect(daysSinceScan(MONDAY_SCAN, THURSDAY)).toBe(3);
    expect(daysSinceScan(MONDAY_SCAN, MONDAY_LATER)).toBe(0);
    expect(daysSinceScan('2026-10-05T23:59:00', new Date(2026, 9, 6, 0, 1))).toBe(1);
  });

  it('is 0 for a missing or unreadable timestamp, and never negative', () => {
    expect(daysSinceScan(undefined, THURSDAY)).toBe(0);
    expect(daysSinceScan('not a date', THURSDAY)).toBe(0);
    expect(daysSinceScan('2026-10-09T10:00:00', THURSDAY)).toBe(0);
  });
});

describe('earningsGateFor — the Monday/Thursday example', () => {
  it('Monday: 23d against a 21d window is no veto', () => {
    const g = earningsGateFor(STOCK, MONDAY_SCAN, 21, MONDAY_LATER);
    expect(g).toMatchObject({ daysNow: 23, veto: false, unknown: false, armBlockedReason: null });
  });

  it('Thursday: the same card has aged to 20d, inside the window — vetoed', () => {
    const g = earningsGateFor(STOCK, MONDAY_SCAN, 21, THURSDAY);
    expect(g).toMatchObject({ daysNow: 20, daysAtScan: 23, ageDays: 3, veto: true });
    expect(g.armBlockedReason).toBe(EARNINGS_VETO_MESSAGE);
  });

  it('a print that may have passed since the scan reads as unknown (CAUTION for a stock), not a veto', () => {
    const g = earningsGateFor({ ...STOCK, earningsDays: 2, earningsVeto: true }, MONDAY_SCAN, 21, THURSDAY);
    expect(g).toMatchObject({ daysNow: null, veto: false, unknown: true, passedSinceScan: true });
    expect(g.armBlockedReason).toBe(EARNINGS_UNKNOWN_ARM_MESSAGE);
  });

  it('a backend veto is kept when there is no window to re-judge against', () => {
    const g = earningsGateFor({ ...STOCK, earningsDays: 5, earningsVeto: true }, MONDAY_SCAN, undefined, MONDAY_LATER);
    expect(g.veto).toBe(true);
  });
});

describe('earningsGateFor — F8: arming an unfireable card', () => {
  it('a single stock with unknown earnings cannot be armed', () => {
    const g = earningsGateFor({ earningsDays: null, earningsUnknown: true, isEtf: false }, MONDAY_SCAN, 21, MONDAY_LATER);
    expect(g).toMatchObject({ veto: false, unknown: true });
    expect(g.armBlockedReason).toBe(EARNINGS_UNKNOWN_ARM_MESSAGE);
  });

  it('a pre-deploy card without isEtf is a stock (the safe direction)', () => {
    const g = earningsGateFor({ earningsDays: null, earningsUnknown: true }, MONDAY_SCAN, 21, MONDAY_LATER);
    expect(g.armBlockedReason).toBe(EARNINGS_UNKNOWN_ARM_MESSAGE);
  });

  it('an ETF with unknown earnings may be armed', () => {
    const g = earningsGateFor({ earningsDays: null, earningsUnknown: true, isEtf: true }, MONDAY_SCAN, 21, MONDAY_LATER);
    expect(g.armBlockedReason).toBeNull();
  });
});
