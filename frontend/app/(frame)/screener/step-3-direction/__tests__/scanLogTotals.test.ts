import { scanLogTotals } from '../scanLogTotals';
import type { ScanResult } from '@/lib/scanStore';

/**
 * Every bug in this panel has been a DISAGREEMENT between its numbers, and
 * each one shipped because nothing asserted they agree. The invariant:
 *
 *   scanned == passed + rejected + trimmed
 *
 * and the funnel (which reads `shownResult`) must come from the same result
 * the other numbers do.
 */

const completed: ScanResult = {
  scan_id: 'REC-1', timestamp: 't',
  candidates: [{ symbol: 'AAA' } as never, { symbol: 'BBB' } as never],
  rejected: Array.from({ length: 513 }, (_, i) => ({ symbol: `R${i}`, reason: 'x' })),
  pipeline: {
    scanned: 518, failed_data: 10, failed_pre_screen: 237, no_chain: 15,
    failed_score: 200, failed_contracts: 51, other_rejected: 0,
    failed_direction: 0, failed_shortlist: 3, candidates: 2,
  },
};

/**
 * WEAK ON PURPOSE-ADJACENT, so do not lean on it: `totalTrimmed` is defined as
 * `max(0, scanned - passed - rejected)`, which makes this identity hold
 * automatically whenever `scanned >= passed + rejected`. It can only fail in
 * the one direction where scanned is SHORT of the other two.
 *
 * In particular it would NOT have caught the bug this file was written for.
 * There, the header fell back to `passed + rejected` (5) while the funnel
 * rendered a stale `pipeline.scanned` (518): the three header numbers summed
 * perfectly and the contradiction was between the header and the funnel.
 *
 * `expectNothingStaleIsReachable` below is the assertion that actually guards
 * it — the funnel and the numbers both read `shownResult`, so the only way they
 * can disagree is if something stale is still reachable through it.
 */
function expectCoherent(t: ReturnType<typeof scanLogTotals>) {
  expect(t.totalScanned).toBe(t.totalPassed + t.totalRejected + t.totalTrimmed);
}

/** No stale figure is reachable — including by the funnel, which renders
 *  `shownResult.pipeline`. If this holds, the header and the funnel cannot
 *  disagree, because there is nothing for either to disagree with. */
function expectNothingStaleIsReachable(t: ReturnType<typeof scanLogTotals>) {
  expect(t.shownResult).toBeUndefined();
  expect(t.shownResult?.pipeline).toBeUndefined();
  expect(t.totalScanned).toBe(0);
  expect(t.totalPassed).toBe(0);
  expect(t.totalRejected).toBe(0);
  expect(t.totalTrimmed).toBe(0);
  expect(t.rejectedLog).toEqual([]);
}

describe('scanLogTotals', () => {
  it('reports the server count and names the cap gap, on a completed scan', () => {
    const t = scanLogTotals('COMPLETED', [], completed);

    expect(t.totalScanned).toBe(518);
    expect(t.totalPassed).toBe(2);
    expect(t.totalRejected).toBe(513);
    expect(t.totalTrimmed).toBe(3);
    expectCoherent(t);
  });

  it('falls back to the persisted rejected list after a reload', () => {
    // liveRejectedLog is empty because it is not persisted; the panel must not
    // report "Rejected 0" beside a restored scan's real "Scanned 518".
    const t = scanLogTotals('COMPLETED', [], completed);

    expect(t.totalRejected).toBe(513);
    expect(t.rejectedLog).toHaveLength(513);
  });

  it('shows nothing from a previous run while a scan is running', () => {
    // RunScanButton clears rejectedLog on start but NOT scanResult. Reading the
    // stale result for some numbers and not others gave "Scanned 5" above the
    // funnel's "Universe 518".
    const t = scanLogTotals('SCANNING', [], completed);

    expectNothingStaleIsReachable(t);
    expectCoherent(t);
  });

  it('shows nothing from a previous run after a failed scan', () => {
    // FAILED is a persisted terminal state, so this survives a reload.
    const t = scanLogTotals('FAILED', [], completed);

    expectNothingStaleIsReachable(t);
    expectCoherent(t);
  });

  it.each(['IDLE', 'SCANNING', 'FAILED', 'CANCELLED'])(
    'exposes nothing for the funnel to render in state %s', (state) => {
      // The funnel reads shownResult.pipeline. If an unsettled state could
      // still hand it one, the header and the funnel would disagree again —
      // which is exactly how this panel broke three times running.
      expectNothingStaleIsReachable(scanLogTotals(state, [], completed));
    },
  );

  it.each(['IDLE', 'SCANNING', 'FAILED', 'CANCELLED', 'COMPLETED', 'PARTIAL'])(
    'keeps the numbers coherent in state %s', (state) => {
      expectCoherent(scanLogTotals(state, [], completed));
      expectCoherent(scanLogTotals(state, completed.rejected, completed));
    },
  );

  it('prefers the live log over the persisted copy when one is present', () => {
    const live = [{ symbol: 'Z', reason: 'live' }];
    const t = scanLogTotals('COMPLETED', live, completed);

    expect(t.rejectedLog).toBe(live);
  });

  it('derives scanned from passed + rejected when there is no pipeline', () => {
    const noPipeline: ScanResult = { ...completed, pipeline: undefined };
    const t = scanLogTotals('COMPLETED', [], noPipeline);

    expect(t.totalScanned).toBe(515);
    expect(t.totalTrimmed).toBe(0);
    expectCoherent(t);
  });
});
