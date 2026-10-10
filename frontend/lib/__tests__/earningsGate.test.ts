import {
  daysSinceScan, earningsGateFor, EARNINGS_VETO_MESSAGE, EARNINGS_UNKNOWN_ARM_MESSAGE,
  scanVetoDays, stockEarningsGate,
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

/* STOCKS-HORIZON-P0B B7 — the veto window covers the hold: Step 7 and its rail
 * judge earnings against `event_window.veto_days`, or, on a result persisted
 * before B5, against max(reject_days, the scan's hold) -- the hold from
 * ScanContext through sanitizeHoldDays, never the preset table. */
describe('P0B B7 — scanVetoDays and the veto window', () => {
  const POSITION = { reject_days: 30, caution_days: 60 };
  const CUSTOM_60_185 = { horizonPreset: 'Custom', holdMin: 60, holdMax: 185 };

  it('earningsGateFor with veto_days 60 and an aged distance of 40 vetoes', () => {
    // Scanned Monday at 43d; Thursday it has aged to 40d. reject 30 alone would pass it.
    const card = { earningsDays: 43, earningsVeto: false, earningsUnknown: false, isEtf: false };
    const window = scanVetoDays({ ...POSITION, veto_days: 60 }, null);
    expect(window).toBe(60);
    const g = earningsGateFor(card, MONDAY_SCAN, window, THURSDAY);
    expect(g).toMatchObject({ daysNow: 40, veto: true });
    expect(earningsGateFor(card, MONDAY_SCAN, POSITION.reject_days, THURSDAY).veto).toBe(false);
  });

  it('uses veto_days when present, whatever the context says', () => {
    expect(scanVetoDays({ ...POSITION, veto_days: 60 }, CUSTOM_60_185)).toBe(60);
  });

  it('falls back to max(reject_days, the scan hold) when veto_days is absent: Custom 60-185 -> 185', () => {
    expect(scanVetoDays(POSITION, CUSTOM_60_185)).toBe(185);
    expect(scanVetoDays({ ...POSITION, veto_days: null }, CUSTOM_60_185)).toBe(185);
  });

  it('keeps reject_days when it is the wider of the two (Swing 5-15 against reject 21)', () => {
    expect(scanVetoDays({ reject_days: 21, caution_days: 45 }, { holdMin: 5, holdMax: 15 })).toBe(21);
  });

  it('sanitizes the hold the same way the scan request does (rounded, never below holdMin)', () => {
    expect(scanVetoDays(POSITION, { holdMin: 60, holdMax: 44.6 })).toBe(60);
    expect(scanVetoDays(POSITION, { holdMin: 0, holdMax: 59.6 })).toBe(60);
  });

  it("keeps today's reject_days when there is no hold, and nothing when there is no window", () => {
    expect(scanVetoDays(POSITION, null)).toBe(30);
    expect(scanVetoDays(POSITION, undefined)).toBe(30);
    expect(scanVetoDays(undefined, CUSTOM_60_185)).toBeUndefined();
  });
});

describe('P0B B7 — stockEarningsGate (the stocks adapter)', () => {
  it('vetoes a card the stock scan flagged', () => {
    expect(stockEarningsGate({ earnings_days: 40, earnings_veto: true }, MONDAY_SCAN, 60, MONDAY_LATER).veto).toBe(true);
  });

  it('ages earnings_days by the scan age and judges it against the scan veto window', () => {
    // 63d at the scan, outside the 60d window; three days later 60d is still out, 61 at scan -> 58 is in.
    expect(stockEarningsGate({ earnings_days: 63, earnings_veto: false }, MONDAY_SCAN, 60, THURSDAY).veto).toBe(false);
    expect(stockEarningsGate({ earnings_days: 61, earnings_veto: false }, MONDAY_SCAN, 60, THURSDAY).veto).toBe(true);
  });

  it('unknown earnings is never a block on stocks', () => {
    for (const c of [
      { earnings_days: null, earnings_veto: false },
      {},
      // aged below zero: the print may have passed, the next date is unknown
      { earnings_days: 2, earnings_veto: true },
    ]) {
      const g = stockEarningsGate(c, MONDAY_SCAN, 60, THURSDAY);
      expect(g.veto).toBe(false);
      expect(g.armBlockedReason).toBeNull();
    }
    expect(stockEarningsGate(null, MONDAY_SCAN, 60, THURSDAY).veto).toBe(false);
  });

  it('a pre-deploy result without veto_days still honours the card flag', () => {
    expect(stockEarningsGate({ earnings_days: 40, earnings_veto: true }, MONDAY_SCAN, undefined, MONDAY_LATER).veto).toBe(true);
    expect(stockEarningsGate({ earnings_days: 40, earnings_veto: false }, MONDAY_SCAN, undefined, MONDAY_LATER).veto).toBe(false);
  });
});
