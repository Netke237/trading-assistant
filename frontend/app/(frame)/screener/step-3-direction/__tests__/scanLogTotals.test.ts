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

function expectCoherent(t: ReturnType<typeof scanLogTotals>) {
  expect(t.totalScanned).toBe(t.totalPassed + t.totalRejected + t.totalTrimmed);
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

    expect(t.shownResult).toBeUndefined();
    expect(t.totalScanned).toBe(0);
    expect(t.totalPassed).toBe(0);
    expect(t.totalRejected).toBe(0);
    expectCoherent(t);
  });

  it('shows nothing from a previous run after a failed scan', () => {
    // FAILED is a persisted terminal state, so this survives a reload.
    const t = scanLogTotals('FAILED', [], completed);

    expect(t.shownResult).toBeUndefined();
    expect(t.totalScanned).toBe(0);
    expectCoherent(t);
  });

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
