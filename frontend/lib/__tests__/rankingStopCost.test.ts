/**
 * The ranking table's scan-time stop-vs-premium gate (Phase B3).
 *
 * Spec: docs/superpowers/plans/2026-09-02-gate-basis-spec.md §2.3, test 9.
 * Decision: B3-SCOPED-STOP-2026-09-08.
 *
 * The presenter has one job the whole gate rests on: NEVER let "not computed"
 * look like a verdict. Everything else here is formatting; that one is the
 * defect this file exists to prevent.
 */
import { rankingStopCost } from '../risk';
import { cardToRow } from '../../app/(frame)/screener/step-4-ranking/cardToRow';
import type { TradeCardData } from '@/types/domain';

describe('rankingStopCost', () => {
  it('renders a computed gate as a percentage carrying its verdict', () => {
    const r = rankingStopCost(59.4, 'PASS');
    expect(r.label).toBe('59%');
    expect(r.status).toBe('PASS');
    expect(r.tooltip).toContain('59%');
  });

  it('rounds the label to whole percent in both directions', () => {
    expect(rankingStopCost(59.4, 'PASS').label).toBe('59%');
    expect(rankingStopCost(59.5, 'PASS').label).toBe('60%');
    expect(rankingStopCost(0, 'PASS').label).toBe('0%');
    expect(rankingStopCost(100, 'CAUTION').label).toBe('100%');
  });

  it('the tooltip and the label quote the SAME rounded figure', () => {
    // The card's own badge had exactly this defect twice (rounds 5 and 8): a
    // percentage decided at full precision beside words decided at printed
    // precision, straddling the line between them.
    for (const pct of [0.4, 12.5, 49.6, 70.0, 99.5]) {
      const r = rankingStopCost(pct, 'CAUTION');
      expect(r.tooltip).toContain(r.label);
    }
  });

  describe('"not computed" is never a verdict', () => {
    // status null is what the ranking page branches on to render dim text
    // instead of a badge. If any of these returned a status, an ungraded
    // candidate would wear a PASS-coloured badge.
    it.each([
      ['both absent',      null,      null],
      ['both undefined',   undefined, undefined],
      ['pct without verdict',   59.4, null],
      ['verdict without pct',   null,  'PASS'],
      ['pct undefined, verdict present', undefined, 'CAUTION'],
      ['NaN pct',          NaN,       'PASS'],
      ['Infinite pct',     Infinity,  'PASS'],
    ] as const)('%s → no badge', (_label, pct, status) => {
      const r = rankingStopCost(pct as number | null, status as 'PASS' | 'CAUTION' | null);
      expect(r.status).toBeNull();
      expect(r.label).toBe('—');
      expect(r.tooltip).toMatch(/not computed/i);
      expect(r.tooltip).toMatch(/re-run the scan/i);
    });
  });

  it('says WHICH contract the figure describes', () => {
    // A Step 6 override changes the contract without recomputing this, so a
    // tooltip that only quoted the number would let a user read it as
    // describing the contract they picked.
    const t = rankingStopCost(59, 'PASS').tooltip;
    expect(t).toMatch(/SCAN picked/);
    expect(t).toMatch(/Step 6/);
    expect(t).toMatch(/never blocks/i);
  });
});

/* ── The wire → row hop ─────────────────────────────────────────────────── */

const CARD = {
  symbol: 'MSFT', company: 'Microsoft', price: 402.0, direction: 'Bullish',
  status: 'PASS', stockScore: 81,
  stockBreakdown: { trend: 80, pullback: 70, trigger: 75, event: 90, volatility: 60 },
} as unknown as TradeCardData;

describe('cardToRow carries the gate onto the row', () => {
  it('copies both fields verbatim', () => {
    const row = cardToRow({ ...CARD, stopCostPct: 59.4, stopCostStatus: 'CAUTION' }, 1, null, 'Swing (5–15d)');
    expect(row.stopCostPct).toBe(59.4);
    expect(row.stopCostStatus).toBe('CAUTION');
  });

  it('SPEC TEST 9: a candidate persisted before B3 renders "not computed"', () => {
    // A scan session stored before the gate shipped has candidates with
    // neither field. No store migration handles this on purpose (see
    // scanStore's migrate) -- the absent value has to degrade honestly here.
    const row = cardToRow(CARD, 1, null, 'Swing (5–15d)');
    expect(row.stopCostPct).toBeNull();
    expect(row.stopCostStatus).toBeNull();

    const shown = rankingStopCost(row.stopCostPct, row.stopCostStatus);
    expect(shown.status).toBeNull();
    expect(shown.label).toBe('—');
    expect(shown.tooltip).toMatch(/re-run the scan/i);
  });

  it('does not invent a verdict from a half-populated candidate', () => {
    const row = cardToRow({ ...CARD, stopCostPct: 59.4 } as TradeCardData, 1, null, 'Swing (5–15d)');
    expect(rankingStopCost(row.stopCostPct, row.stopCostStatus).status).toBeNull();
  });
});
