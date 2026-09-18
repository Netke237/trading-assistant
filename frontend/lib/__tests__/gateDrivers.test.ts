/*
 * gateDrivers — the single classifier behind Step 5's banner AND its per-row
 * tooltip.
 *
 * These exist because the two used to decide this independently and disagreed
 * on screen about the same row: a candidate with no volatility reading at all
 * was counted by the banner as "no volatility reading" while its own tooltip
 * one pixel away said "Driven by: IV" — the exact conflation the banner was
 * built to end. A PASSING row was told it was "driven by both", because the
 * tooltip had no PASS branch at all.
 */
import { gateDrivers, gateDriverPhrase, eventVolGateTooltip } from '@/lib/statusTooltips';

describe('gateDrivers', () => {
  it('attributes nothing to a PASS row', () => {
    // The defect: every clean row was handed a cause.
    const d = gateDrivers({ ivStatus: 'PASS', proxStatus: 'PASS', gate: 'PASS', hasIv: true });
    expect(d).toEqual({ iv: false, event: false, ivMissing: false });
    expect(gateDriverPhrase(d, 'IV rank')).toMatch(/clear on both/);
  });

  it('separates a MISSING reading from a reading that failed', () => {
    const missing = gateDrivers({ ivStatus: 'CAUTION', proxStatus: 'PASS', gate: 'CAUTION', hasIv: false });
    expect(missing).toEqual({ iv: true, event: false, ivMissing: true });
    expect(gateDriverPhrase(missing, 'IV')).toBe('no volatility reading');

    const failed = gateDrivers({ ivStatus: 'CAUTION', proxStatus: 'PASS', gate: 'CAUTION', hasIv: true });
    expect(failed).toEqual({ iv: true, event: false, ivMissing: false });
    expect(gateDriverPhrase(failed, 'IV rank')).toBe('IV rank');
  });

  it('reports BOTH when both sides are at the gate, without losing the missing-reading fact', () => {
    // The old enum collapsed this to a bare 'both' and dropped `ivMissing`.
    const d = gateDrivers({ ivStatus: 'CAUTION', proxStatus: 'CAUTION', gate: 'CAUTION', hasIv: false });
    expect(d).toEqual({ iv: true, event: true, ivMissing: true });
    expect(gateDriverPhrase(d, 'IV')).toBe('no volatility reading and event proximity');
  });

  it('attributes to the event alone when only the event is at the gate', () => {
    const d = gateDrivers({ ivStatus: 'PASS', proxStatus: 'REJECT', gate: 'REJECT', hasIv: true });
    expect(d).toEqual({ iv: false, event: true, ivMissing: false });
    expect(gateDriverPhrase(d, 'IV rank')).toBe('event proximity');
  });

  it('does NOT blame the event when it is merely bad, but not AT the gate', () => {
    // The `event` flag was the one this file did not pin: round 2 loosened it to
    // `proxStatus !== 'PASS'` and every test still passed. That wrong version is
    // user-visible -- this row would read "Driven by: IV rank and event
    // proximity" and be counted in the banner's event bucket, when the event is
    // a CAUTION and the REJECT came from the IV side alone.
    const d = gateDrivers({ ivStatus: 'REJECT', proxStatus: 'CAUTION', gate: 'REJECT', hasIv: true });
    expect(d).toEqual({ iv: true, event: false, ivMissing: false });
    expect(gateDriverPhrase(d, 'IV rank')).toBe('IV rank');
  });

  it('a PASSING row with no reading is not told it is "clear on both"', () => {
    // Reachable on Intraday, where the horizon does not gate on IV at all, and
    // where a missing reading is the common case. "IV: no data" and "clear on
    // both" in one sentence is the same conflation running backwards.
    const d = gateDrivers({ ivStatus: 'PASS', proxStatus: 'PASS', gate: 'PASS', hasIv: false });
    const phrase = gateDriverPhrase(d, 'IV', false);
    expect(phrase).toMatch(/does not gate on volatility/);
    expect(phrase).not.toMatch(/clear on both/);
  });
});

describe('eventVolGateTooltip speaks the same vocabulary as the banner', () => {
  it('a row with no reading is not blamed on "IV"', () => {
    const drivers = gateDrivers({ ivStatus: 'CAUTION', proxStatus: 'PASS', gate: 'CAUTION', hasIv: false });
    const t = eventVolGateTooltip({
      ivRank: null, ivBasis: 'none', ivStatus: 'CAUTION',
      nextEventDays: null, proxStatus: 'PASS', evReject: 21, evCaution: 45, gate: 'CAUTION', drivers,
    });
    expect(t).toMatch(/Driven by: no volatility reading\./);
    expect(t).not.toMatch(/Driven by: IV\./);
  });

  it('a PASS row is not told it is driven by anything', () => {
    const drivers = gateDrivers({ ivStatus: 'PASS', proxStatus: 'PASS', gate: 'PASS', hasIv: true });
    const t = eventVolGateTooltip({
      ivRank: 10, ivBasis: 'rank', ivStatus: 'PASS',
      nextEventDays: null, proxStatus: 'PASS', evReject: 21, evCaution: 45, gate: 'PASS', drivers,
    });
    expect(t).not.toMatch(/Driven by: both/);
    expect(t).toMatch(/clear on both/);
  });
});
