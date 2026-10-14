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
 *
 * `ivGated` is the horizon's fact (does this horizon gate on volatility) and
 * `hasIv` is the row's (did anything answer for this row). Round 3 found the
 * tooltip choosing a sentence about the FORMER using the LATTER, so both are
 * now carried on the result and neither has a default.
 */
import { gateDrivers, gateDriverPhrase, eventVolGateTooltip } from '@/lib/statusTooltips';

describe('gateDrivers', () => {
  it('attributes nothing to a PASS row', () => {
    // The defect: every clean row was handed a cause.
    const d = gateDrivers({ ivStatus: 'PASS', proxStatus: 'PASS', gate: 'PASS', hasIv: true, ivGated: true });
    expect(d).toEqual({ iv: false, event: false, ivMissing: false, hasIv: true, ivGated: true });
    expect(gateDriverPhrase(d, 'IV rank')).toMatch(/clear on both/);
  });

  it('separates a MISSING reading from a reading that failed', () => {
    const missing = gateDrivers({ ivStatus: 'CAUTION', proxStatus: 'PASS', gate: 'CAUTION', hasIv: false, ivGated: true });
    expect(missing).toEqual({ iv: true, event: false, ivMissing: true, hasIv: false, ivGated: true });
    expect(gateDriverPhrase(missing, 'IV')).toBe(
      'no measured check. Missing volatility reading is not a measured driver',
    );

    const failed = gateDrivers({ ivStatus: 'CAUTION', proxStatus: 'PASS', gate: 'CAUTION', hasIv: true, ivGated: true });
    expect(failed).toEqual({ iv: true, event: false, ivMissing: false, hasIv: true, ivGated: true });
    expect(gateDriverPhrase(failed, 'IV rank')).toBe('measured checks: IV rank');
  });

  it('reports BOTH when both sides are at the gate, without losing the missing-reading fact', () => {
    // The old enum collapsed this to a bare 'both' and dropped `ivMissing`.
    const d = gateDrivers({ ivStatus: 'CAUTION', proxStatus: 'CAUTION', gate: 'CAUTION', hasIv: false, ivGated: true });
    expect(d).toEqual({ iv: true, event: true, ivMissing: true, hasIv: false, ivGated: true });
    expect(gateDriverPhrase(d, 'IV')).toBe(
      'measured checks: event proximity. Missing volatility reading is not a measured driver',
    );
    expect(gateDriverPhrase(d, 'IV')).not.toBe('no volatility reading and event proximity');
  });

  it('attributes to the event alone when only the event is at the gate', () => {
    const d = gateDrivers({ ivStatus: 'PASS', proxStatus: 'REJECT', gate: 'REJECT', hasIv: true, ivGated: true });
    expect(d).toEqual({ iv: false, event: true, ivMissing: false, hasIv: true, ivGated: true });
    expect(gateDriverPhrase(d, 'IV rank')).toBe('measured checks: event proximity');
  });

  it('an event-REJECT with no IV reading names only event proximity and discloses the gap', () => {
    const d = gateDrivers({ ivStatus: 'CAUTION', proxStatus: 'REJECT', gate: 'REJECT', hasIv: false, ivGated: true });
    expect(d).toEqual({ iv: false, event: true, ivMissing: false, hasIv: false, ivGated: true });
    expect(gateDriverPhrase(d, 'IV')).toBe(
      'measured checks: event proximity. Missing volatility reading is not a measured driver',
    );
    expect(gateDriverPhrase(d, 'IV')).not.toContain('no volatility reading and');
  });

  it('does NOT blame the event when it is merely bad, but not AT the gate', () => {
    // The `event` flag was the one this file did not pin: round 2 loosened it to
    // `proxStatus !== 'PASS'` and every test still passed. That wrong version is
    // user-visible -- this row would read "Driven by: IV rank and event
    // proximity" and be counted in the banner's event bucket, when the event is
    // a CAUTION and the REJECT came from the IV side alone.
    const d = gateDrivers({ ivStatus: 'REJECT', proxStatus: 'CAUTION', gate: 'REJECT', hasIv: true, ivGated: true });
    expect(d).toEqual({ iv: true, event: false, ivMissing: false, hasIv: true, ivGated: true });
    expect(gateDriverPhrase(d, 'IV rank')).toBe('measured checks: IV rank');
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

  it('ROUND 3: an UNGATED horizon never claims the volatility side was cleared, reading or no reading', () => {
    // The finding. Round 2 chose between these two sentences on `hasIv` -- the
    // ROW's data -- when both are claims about the HORIZON. On Intraday
    // ivStatusFor returns PASS for whatever figure it is handed, so a row at IV
    // rank 95 (the top of that name's own 52-week range, its most expensive
    // premium) took the hasIv branch and was told its volatility was "clear",
    // one line under a banner reading "IV gate disabled for this horizon".
    const withReading = gateDrivers({ ivStatus: 'PASS', proxStatus: 'PASS', gate: 'PASS', hasIv: true, ivGated: false });
    expect(gateDriverPhrase(withReading, 'IV rank')).not.toMatch(/clear on both/);
    expect(gateDriverPhrase(withReading, 'IV rank')).toMatch(/does not gate on volatility/);

    // And the mirror: where the horizon DOES gate, a judged-and-passed reading
    // is exactly what "clear on both" means, so it must survive.
    const gated = gateDrivers({ ivStatus: 'PASS', proxStatus: 'PASS', gate: 'PASS', hasIv: true, ivGated: true });
    expect(gateDriverPhrase(gated, 'IV rank')).toMatch(/clear on both/);
  });

  it('ROUND 3: gated, passing, and unreadable is stated rather than defaulted', () => {
    // Not reachable from step 5 today -- its page downgrades an unreadable row
    // to CAUTION on any gating horizon -- but the last two rounds were both
    // spent on states this type could not express, so it has words of its own.
    const d = gateDrivers({ ivStatus: 'PASS', proxStatus: 'PASS', gate: 'PASS', hasIv: false, ivGated: true });
    const phrase = gateDriverPhrase(d, 'IV');
    expect(phrase).toMatch(/no reading to judge/);
    expect(phrase).not.toMatch(/clear on both/);
    expect(phrase).not.toMatch(/does not gate on volatility/);
  });
});

describe('eventVolGateTooltip speaks the same vocabulary as the banner', () => {
  it('a row with no reading is not blamed on "IV"', () => {
    const drivers = gateDrivers({ ivStatus: 'CAUTION', proxStatus: 'PASS', gate: 'CAUTION', hasIv: false, ivGated: true });
    const t = eventVolGateTooltip({
      ivRank: null, ivBasis: 'none', ivStatus: 'CAUTION',
      nextEventDays: null, proxStatus: 'PASS', evReject: 21, evCaution: 45, gate: 'CAUTION', drivers,
    });
    expect(t).toBe(
      'Gate shows the worse of IV and event proximity. IV: no data; no known upcoming event. '
      + 'Driven by: no measured check. Missing volatility reading is not a measured driver.',
    );
    expect(t).not.toContain('Driven by: no volatility reading.');
    expect(t).not.toMatch(/Driven by: IV\./);
  });

  it('a PASS row is not told it is driven by anything', () => {
    const drivers = gateDrivers({ ivStatus: 'PASS', proxStatus: 'PASS', gate: 'PASS', hasIv: true, ivGated: true });
    const t = eventVolGateTooltip({
      ivRank: 10, ivBasis: 'rank', ivStatus: 'PASS',
      nextEventDays: null, proxStatus: 'PASS', evReject: 21, evCaution: 45, gate: 'PASS', drivers,
    });
    expect(t).not.toMatch(/Driven by: both/);
    expect(t).toMatch(/clear on both/);
  });

  it('ROUND 3: the tooltip takes the horizon fact from the drivers, not from the figure it prints', () => {
    // This is the wiring the round-3 mutation walked through: the tooltip used
    // to re-derive "is there a reading" as `ivRank != null` and pass it down as
    // the discriminant, so a real figure on an ungated horizon produced "(PASS)
    // ... clear on both". The figure is still printed; it no longer decides
    // anything.
    const drivers = gateDrivers({ ivStatus: 'PASS', proxStatus: 'PASS', gate: 'PASS', hasIv: true, ivGated: false });
    const t = eventVolGateTooltip({
      ivRank: 95, ivBasis: 'rank', ivStatus: 'PASS',
      nextEventDays: null, proxStatus: 'PASS', evReject: 1, evCaution: 3, gate: 'PASS', drivers,
    });
    expect(t).toMatch(/IV rank 95 \(PASS\)/);            // the figure is still shown
    expect(t).toMatch(/does not gate on volatility/);    // but nothing claims it was judged
    expect(t).not.toMatch(/clear on both/);
  });
});
