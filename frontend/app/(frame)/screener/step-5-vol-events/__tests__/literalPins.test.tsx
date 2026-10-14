/*
 * Step 5 — the page's sentences pinned against LITERAL strings.
 *
 * WHY (SCREENER-PINNING-PASS). gateSummary.test.tsx's PART_PINS / CELL_PINS
 * prove every sentence on this page equals ITS OWN BUILDER run over data read
 * back off the element the page rendered. That is circular for any defect
 * inside a builder, and round 7 measured it twice: swapping the two bands
 * inside ivThresholdSentence (the page then says "IV rank <= 55 -> PASS" beside
 * a CAUTION badge for IV 45) and swapping reject/caution inside
 * eventVolGateTooltip both shipped the full suite green.
 *
 * Everything below is a hand-written literal and a whole-string `toBe`. The
 * rendered scan injects IV thresholds in which ALL FOUR numbers differ from
 * each other and from the event window (rank 30/50, absolute 40/60, event
 * 21/45): the shipped values (IV_SHIPPED) and every other fixture set rank == absolute, so
 * a page looking up the RANK band for an ABSOLUTE row was invisible (plan round
 * 1 F1). Each row's two sides disagree, so a swap of sides shows too.
 */
import { cleanup, render, screen } from '@testing-library/react';
import Step5Page from '../page';
import { ivThresholdSentence } from '../gateSummary';
import { useScanStore } from '@/lib/scanStore';
import { useIvThresholdsStore } from '@/lib/ivThresholdsStore';
import { useEventThresholdsStore } from '@/lib/eventThresholdsStore';
import type { TradeCardData } from '@/types/domain';
import { api } from '@/lib/api';
import { EVENT_SHIPPED, IV_SHIPPED, echoStoredThresholds } from '@/lib/testFixtures/thresholds';

// DOCC-3: the page fetches both stores on mount; each fetch answers with the
// record the test set, so it re-sets the test's values rather than clearing them.
jest.mock('@/lib/api', () => ({ api: { getIvThresholds: jest.fn(), getEventThresholds: jest.fn() } }));
beforeEach(() => echoStoredThresholds(api as unknown as Parameters<typeof echoStoredThresholds>[0]));

describe('ivThresholdSentence — round 7 F1', () => {
  it('a rank band', () => {
    expect(ivThresholdSentence([{ basis: 'rank', passMax: 34, cautionMax: 55 }]))
      .toBe('IV rank ≤ 34 → PASS; ≤ 55 → CAUTION; above → REJECT.');
  });
  it('an absolute band, other numbers -- none is baked in', () => {
    expect(ivThresholdSentence([{ basis: 'absolute', passMax: 44, cautionMax: 65 }]))
      .toBe('IV ≤ 44 → PASS; ≤ 65 → CAUTION; above → REJECT.');
  });
  it('two bands, in the order given', () => {
    expect(ivThresholdSentence([
      { basis: 'absolute', passMax: 40, cautionMax: 60 },
      { basis: 'rank', passMax: 30, cautionMax: 50 },
    ])).toBe(
      'IV ≤ 40 → PASS; ≤ 60 → CAUTION; above → REJECT. '
      + 'IV rank ≤ 30 → PASS; ≤ 50 → CAUTION; above → REJECT.',
    );
  });
  it('no caution ceiling rejects directly after PASS without inventing CAUTION', () => {
    expect(ivThresholdSentence([{ basis: 'rank', passMax: 30, cautionMax: null }]))
      .toBe('IV rank ≤ 30 → PASS; above → REJECT.');
  });
  it('no band, no sentence', () => {
    expect(ivThresholdSentence([])).toBe('');
  });
});

function candidate(symbol: string, cd: Record<string, unknown>, nextEventDays: number | null): TradeCardData {
  return {
    symbol, company: `${symbol} Co`, price: 100, direction: 'Bullish', status: 'PASS',
    stockScore: 70, stockConfidence: 'PASS', stockBreakdown: {} as any,
    nextEventDays, nextEventLabel: null,
    contract: `${symbol}|100|2026-12-01|C`, contractScore: 70, contractConfidence: 'PASS',
    contractBreakdown: {} as any,
    contractDetails: { strike: 100, expiry: '2026-12-01', right: 'C', mid: 1, delta: 0.45, theta: -0.05, dte: 90, ...cd },
    entry: {} as any, exit: {} as any,
  } as TradeCardData;
}

describe('the rendered Swing page, word for word', () => {
  beforeEach(() => {
    useScanStore.setState({
      scanResult: {
        candidates: [
          // rank 37: 30 < 37 <= 50 -> IV CAUTION; event 60d >= 45 -> PASS; gate CAUTION
          candidate('RNK', { ivRank: 37, ivPercentile: 37 }, 60),
          // absolute 58: 40 < 58 <= 60 -> IV CAUTION; event 10d < 21 -> REJECT; gate REJECT
          // (on the RANK band 58 would be REJECT -- the lookup is discriminated)
          candidate('ABS', { ivRank: null, iv: 58, ivPercentile: null }, 10),
          // nothing answered: IV CAUTION on a gated horizon; no event -> PASS; gate CAUTION
          candidate('NOV', { ivRank: null, ivPercentile: null }, null),
        ],
        rejected: [], scan_id: 'x', timestamp: '',
      } as any,
      context: { direction: 'Bullish', horizon: 'Swing (5-15d)' } as any,
    } as any);
    useIvThresholdsStore.setState({
      thresholds: { ...IV_SHIPPED, Swing: { rank_pass_max: 30, rank_caution_max: 50, abs_pass_max: 40, abs_caution_max: 60 } },
      status: 'ready', error: null, overrides: {},
    });
    useEventThresholdsStore.setState({ thresholds: EVENT_SHIPPED, status: 'ready', error: null });   // Swing 21/45
    render(<Step5Page />);
  });

  afterEach(() => {
    cleanup();   // unmount first, or the store resets below re-render a live page
    useScanStore.setState({ scanResult: undefined, context: undefined } as any);
    useIvThresholdsStore.setState({ thresholds: null, status: 'idle', error: null, overrides: {} });
    useEventThresholdsStore.setState({ thresholds: null, status: 'idle', error: null });
  });

  const line = (name: string) =>
    screen.getByTestId('step-5-header').querySelector(`[data-line="${name}"]`)?.textContent;
  const tooltip = (symbol: string) =>
    document.querySelector(`[data-row="${symbol}"] [role="tooltip"]`)?.textContent;

  it('the thresholds line', () => {
    expect(line('thresholds')).toBe(
      'IV rank ≤ 30 → PASS; ≤ 50 → CAUTION; above → REJECT. '
      + 'IV ≤ 40 → PASS; ≤ 60 → CAUTION; above → REJECT. '
      + 'Earnings < 21d → REJECT; < 45d → CAUTION; else → PASS. '
      + 'Gate = worst of IV and event proximity.',
    );
  });

  it('the summary line', () => {
    expect(line('summary')).toBe(
      '3 shown — 0 PASS, 2 CAUTION, 1 REJECT. '
      + "Driven by measured checks: 1 on IV rank above its threshold; 1 on an event inside this horizon's window. "
      + '1 of them has no volatility reading at all — graded CAUTION on the volatility side alone, '
      + 'never PASS there. The gate verdict above is the worse of that and the event window, '
      + 'so it can be lower still.',
    );
  });

  it('every row tooltip', () => {
    expect(tooltip('RNK')).toBe(
      'Gate shows the worse of IV rank and event proximity. IV rank 37 (CAUTION); '
      + "next event in 60d vs. this horizon's reject <21d / caution <45d window (PASS). "
      + 'Driven by: measured checks: IV rank.',
    );
    expect(tooltip('ABS')).toBe(
      'Gate shows the worse of IV and event proximity. '
      + 'IV 58.0% — an absolute level, no rank source available (CAUTION); '
      + "next event in 10d vs. this horizon's reject <21d / caution <45d window (REJECT). "
      + 'Driven by: measured checks: event proximity.',
    );
    expect(tooltip('NOV')).toBe(
      'Gate shows the worse of IV and event proximity. IV: no data; no known upcoming event. '
      + 'Driven by: no measured check. Missing volatility reading is not a measured driver.',
    );
  });

  it('every row verdict, both sides', () => {
    const sides = (s: string) => {
      const el = document.querySelector(`[data-row="${s}"]`);
      return [el?.getAttribute('data-side-volatility'), el?.getAttribute('data-side-event'), el?.getAttribute('data-gate')];
    };
    expect(sides('RNK')).toEqual(['CAUTION', 'PASS', 'CAUTION']);
    expect(sides('ABS')).toEqual(['CAUTION', 'REJECT', 'REJECT']);
    expect(sides('NOV')).toEqual(['CAUTION', 'PASS', 'CAUTION']);
  });
});
