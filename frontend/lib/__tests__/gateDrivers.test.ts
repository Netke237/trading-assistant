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
    const d = gateDrivers({ ivStatus: 'PASS', proxStatus: 'PASS', gate: 'PASS', hasIv: true, ivGated: true });
    expect(d).toEqual({ iv: false, event: false, ivMissing: false, hasIv: expect.any(Boolean), ivGated: true });
    expect(gateDriverPhrase(d, 'IV rank')).toMatch(/clear on both/);
  });

  it('separates a MISSING reading from a reading that failed', () => {
    const missing = gateDrivers({ ivStatus: 'CAUTION', proxStatus: 'PASS', gate: 'CAUTION', hasIv: false, ivGated: true });
    expect(missing).toEqual({ iv: true, event: false, ivMissing: true, hasIv: expect.any(Boolean), ivGated: true });
    expect(gateDriverPhrase(missing, 'IV')).toBe('no volatility reading');

    const failed = gateDrivers({ ivStatus: 'CAUTION', proxStatus: 'PASS', gate: 'CAUTION', hasIv: true, ivGated: true });
    expect(failed).toEqual({ iv: true, event: false, ivMissing: false, hasIv: expect.any(Boolean), ivGated: true });
    expect(gateDriverPhrase(failed, 'IV rank')).toBe('IV rank');
  });

  it('reports BOTH when both sides are at the gate, without losing the missing-reading fact', () => {
    // The old enum collapsed this to a bare 'both' and dropped `ivMissing`.
    const d = gateDrivers({ ivStatus: 'CAUTION', proxStatus: 'CAUTION', gate: 'CAUTION', hasIv: false, ivGated: true });
    expect(d).toEqual({ iv: true, event: true, ivMissing: true, hasIv: expect.any(Boolean), ivGated: true });
    expect(gateDriverPhrase(d, 'IV')).toBe('no volatility reading and event proximity');
  });

  it('attributes to the event alone when only the event is at the gate', () => {
    const d = gateDrivers({ ivStatus: 'PASS', proxStatus: 'REJECT', gate: 'REJECT', hasIv: true, ivGated: true });
    expect(d).toEqual({ iv: false, event: true, ivMissing: false, hasIv: expect.any(Boolean), ivGated: true });
    expect(gateDriverPhrase(d, 'IV rank')).toBe('event proximity');
  });

  it('does NOT blame the event when it is merely bad, but not AT the gate', () => {
    // The `event` flag was the one this file did not pin: round 2 loosened it to
    // `proxStatus !== 'PASS'` and every test still passed. That wrong version is
    // user-visible -- this row would read "Driven by: IV rank and event
    // proximity" and be counted in the banner's event bucket, when the event is
    // a CAUTION and the REJECT came from the IV side alone.
    const d = gateDrivers({ ivStatus: 'REJECT', proxStatus: 'CAUTION', gate: 'REJECT', hasIv: true, ivGated: true });
    expect(d).toEqual({ iv: true, event: false, ivMissing: false, hasIv: expect.any(Boolean), ivGated: true });
    expect(gateDriverPhrase(d, 'IV rank')).toBe('IV rank');
  });

  it('a PASSING row with no reading is not told it is "clear on both"', () => {
    // Reachable on Intraday, where the horizon does not gate on IV at all, and
    // where a missing reading is the common case. "IV: no data" and "clear on
    // both" in one sentence is the same conflation running backwards.
    const d = gateDrivers({ ivStatus: 'PASS', proxStatus: 'PASS', gate: 'PASS', hasIv: false, ivGated: false });
    const phrase = gateDriverPhrase(d, 'IV');
    expect(phrase).toMatch(/does not gate on volatility/);
    expect(phrase).not.toMatch(/clear on both/);
  });
});

describe('eventVolGateTooltip speaks the same vocabulary as the banner', () => {
  it('a row with no reading is not blamed on "IV"', () => {
    const drivers = gateDrivers({ ivStatus: 'CAUTION', proxStatus: 'PASS', gate: 'CAUTION', hasIv: false, ivGated: true });
    const t = eventVolGateTooltip({
      ivRank: null, ivBasis: 'none', ivStatus: 'CAUTION',
      nextEventDays: null, proxStatus: 'PASS', evReject: 21, evCaution: 45, drivers,
    });
    expect(t).toMatch(/Driven by: no volatility reading\./);
    expect(t).not.toMatch(/Driven by: IV\./);
  });

  it('a PASS row is not told it is driven by anything', () => {
    const drivers = gateDrivers({ ivStatus: 'PASS', proxStatus: 'PASS', gate: 'PASS', hasIv: true, ivGated: true });
    const t = eventVolGateTooltip({
      ivRank: 10, ivBasis: 'rank', ivStatus: 'PASS',
      nextEventDays: null, proxStatus: 'PASS', evReject: 21, evCaution: 45, drivers,
    });
    expect(t).not.toMatch(/Driven by: both/);
    expect(t).toMatch(/clear on both/);
  });
});

describe('the flags round 3 found unpinned', () => {
  it('does NOT blame the IV side when it is merely bad, but not AT the gate', () => {
    // Round 2 added this test for `event` and left `iv` unguarded; round 3
    // showed the symmetric mutation (`ivStatus !== 'PASS'`) survived all 1695
    // tests. The wrong version is reachable today: ivRank 45 is CAUTION on
    // Swing, an event 3 days out is REJECT, and the row would be reported as
    // "driven by IV rank and event proximity" and counted in the banner's IV
    // bucket -- a CAUTION presented as the cause of a REJECT.
    const d = gateDrivers({ ivStatus: 'CAUTION', proxStatus: 'REJECT', gate: 'REJECT', hasIv: true, ivGated: true });
    expect(d.iv).toBe(false);
    expect(d.event).toBe(true);
    expect(gateDriverPhrase(d, 'IV rank')).toBe('event proximity');
  });

  it('never claims a row is "clear" on a horizon that does not gate on volatility', () => {
    // Reachable on Intraday one line under the header "IV gate disabled for this
    // horizon". A row sitting at 90% IV passed only because nothing was checked;
    // calling it clear asserts a check that never ran.
    const withReading = gateDrivers({ ivStatus: 'PASS', proxStatus: 'PASS', gate: 'PASS', hasIv: true, ivGated: false });
    expect(gateDriverPhrase(withReading, 'IV')).toMatch(/does not gate on volatility/);
    expect(gateDriverPhrase(withReading, 'IV')).not.toMatch(/clear on both/);

    // ...and still says "clear on both" where volatility WAS checked and passed.
    const gated = gateDrivers({ ivStatus: 'PASS', proxStatus: 'PASS', gate: 'PASS', hasIv: true, ivGated: true });
    expect(gateDriverPhrase(gated, 'IV')).toMatch(/clear on both/);
  });

  it('carries hasIv and ivGated so no consumer re-derives them', () => {
    // The tooltip used to compute hasIv from `ivRank != null` while the page used
    // `iv.basis !== 'none'`. Both are now read off this object.
    const d = gateDrivers({ ivStatus: 'PASS', proxStatus: 'PASS', gate: 'PASS', hasIv: false, ivGated: false });
    expect(d.hasIv).toBe(false);
    expect(d.ivGated).toBe(false);
  });
});
