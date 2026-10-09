/*
 * NO THRESHOLDS, NO VERDICT (decision DOCC-3-THRESHOLD-STORES-REFUSE-2026-09-29).
 * A failed or pending threshold fetch shows no IV or event verdict anywhere on
 * Step 5 -- never one graded against a hardcoded fallback -- and names why.
 * Every state here is also held to the page contract's owner walk and pins
 * (testSupport/pageContract.tsx), the same ones the ready-path tests use.
 */
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import Step5Page from '../page';
import { useScanStore } from '@/lib/scanStore';
import { useIvThresholdsStore } from '@/lib/ivThresholdsStore';
import { useEventThresholdsStore } from '@/lib/eventThresholdsStore';
import { api } from '@/lib/api';
import { EVENT_SHIPPED, IV_SHIPPED } from '@/lib/testFixtures/thresholds';
import { STATUS_LABEL } from '@/lib/status';
import {
  expectPageCopy, gateCopy, partsOf, page, PART_ORDER, gateOf, sideVerdict,
} from '../testSupport/pageContract';
import type { TradeCardData } from '@/types/domain';

jest.mock('@/lib/api', () => ({ api: { getIvThresholds: jest.fn(), getEventThresholds: jest.fn() } }));
const getIv = api.getIvThresholds as jest.Mock;
const getEv = api.getEventThresholds as jest.Mock;

const IV_ERR = 'GET /api/config/iv-thresholds → 500 Internal Server Error';
const EV_ERR = 'GET /api/config/event-thresholds → 500 Internal Server Error';

function makeCandidate(symbol: string, ivRank: number | null, nextEventDays: number | null, iv?: number): TradeCardData {
  return {
    symbol, company: `${symbol} Co`, price: 100, direction: 'Bullish', status: 'PASS',
    stockScore: 70, stockConfidence: 'PASS', stockBreakdown: {} as any,
    nextEventDays, nextEventLabel: nextEventDays === null ? null : 'Earnings',
    contract: `${symbol}|100|2026-12-01|C`, contractScore: 70, contractConfidence: 'PASS',
    contractBreakdown: {} as any,
    contractDetails: {
      strike: 100, expiry: '2026-12-01', right: 'C', mid: 1, delta: 0.45, theta: -0.05, dte: 90,
      ...(ivRank === null ? {} : { ivRank, ivPercentile: ivRank }),
      ...(iv === undefined ? {} : { iv }),
    } as any,
    entry: {} as any, exit: {} as any,
  } as TradeCardData;
}

/** On shipped Swing values: PASS (rank 10, no event), CAUTION (rank 40), REJECT (event in 3d). */
const MIXED = [
  makeCandidate('PASSY', 10, null),
  makeCandidate('CAUTY', 40, null),
  makeCandidate('REJY', 10, 3),
];

function scan(candidates: TradeCardData[], horizon = 'Swing (5-15d)') {
  useScanStore.setState({
    scanResult: { candidates, rejected: [], scan_id: 'x', timestamp: '' } as any,
    context: { direction: 'Bullish', horizon } as any,
  } as any);
}

/** Render, and let the mount fetches settle. */
async function mount() {
  await act(async () => {
    render(<Step5Page />);
    await Promise.resolve();
    await Promise.resolve();
  });
}

/** A promise that never settles: the fetch stays in flight. */
const pending = () => new Promise(() => {});

const gates = () => [...document.querySelectorAll<HTMLElement>('[data-cell="gate"]')];
const verdictBadges = () => [...page().querySelectorAll('span')]
  .map((s) => s.textContent)
  .filter((t) => t === STATUS_LABEL.PASS || t === STATUS_LABEL.CAUTION || t === STATUS_LABEL.REJECT);

/** The header's structure, as gateSummary.test.tsx's expectGateCopy checks it,
 *  minus the head-count checks that exist only when there are verdicts. */
function expectHeaderStructure() {
  expectPageCopy();
  const header = gateCopy();
  const names = [...header.querySelectorAll<HTMLElement>('[data-part]')]
    .map((el) => el.getAttribute('data-part') as string);
  expect(names).toEqual(PART_ORDER.filter((n) => names.includes(n)));
  for (const line of header.querySelectorAll<HTMLElement>('[data-line]')) {
    const own = [...line.querySelectorAll<HTMLElement>('[data-part]')];
    expect(line.textContent).toBe(own.map((el) => el.textContent).join(' '));
  }
}

beforeEach(() => {
  getIv.mockReset();
  getEv.mockReset();
  useIvThresholdsStore.setState({ thresholds: null, status: 'idle', error: null, overrides: {} });
  useEventThresholdsStore.setState({ thresholds: null, status: 'idle', error: null });
});
afterEach(() => {
  cleanup();
  useScanStore.setState({ scanResult: undefined, context: undefined } as any);
});

describe('Step 5 with no thresholds in hand', () => {
  it('S1: both fetches fail -- every gate NO_DATA, no verdict, no counts, the error named', async () => {
    getIv.mockRejectedValue(new Error(IV_ERR));
    getEv.mockRejectedValue(new Error(EV_ERR));
    scan(MIXED);
    await mount();

    expect(gates().length).toBe(3);
    for (const g of gates()) {
      expect([g.getAttribute('data-gate'), g.getAttribute('data-side-volatility'), g.getAttribute('data-side-event')])
        .toEqual(['NO_DATA', 'NO_DATA', 'NO_DATA']);
    }
    expect(verdictBadges()).toEqual([]);
    expect(document.querySelector('[data-line="summary"]')).toBeNull();
    const un = partsOf()['thresholds-unavailable'];
    expect(un.getAttribute('data-avail')).toBe('failed');
    expect(un.textContent).toContain(IV_ERR);
    expect(partsOf()['iv-thresholds']).toBeUndefined();
    expect(partsOf()['event-window']).toBeUndefined();
    expect(page().getAttribute('data-ev-reject')).toBe('');
    expect(page().getAttribute('data-ev-caution')).toBe('');
    expect(page().getAttribute('data-iv-gated')).toBe('unknown');
    // No number from the shipped config leaks anywhere on the page.
    expect(page().textContent).not.toMatch(/\b(21|45|34|55)\b/);
    expectHeaderStructure();
  });

  it('S2: only the IV fetch fails -- the whole page is failed, with no event verdicts either', async () => {
    getIv.mockRejectedValue(new Error(IV_ERR));
    getEv.mockResolvedValue(EVENT_SHIPPED);
    scan(MIXED);
    await mount();
    expect(page().getAttribute('data-avail')).toBe('failed');
    expect(gates().map((g) => g.getAttribute('data-side-event'))).toEqual(['NO_DATA', 'NO_DATA', 'NO_DATA']);
    expect(gateOf('REJY')).toBe('NO_DATA');
    expect(verdictBadges()).toEqual([]);
    expectHeaderStructure();
  });

  it('S2b: only the event fetch fails -- likewise wholly failed, and its error is the one named', async () => {
    getIv.mockResolvedValue(IV_SHIPPED);
    getEv.mockRejectedValue(new Error(EV_ERR));
    scan(MIXED);
    await mount();
    expect(page().getAttribute('data-avail')).toBe('failed');
    expect(gateOf('CAUTY')).toBe('NO_DATA');
    expect(partsOf()['thresholds-unavailable'].getAttribute('data-error')).toBe(EV_ERR);
    expectHeaderStructure();
  });

  it('S3: Retry after a failure shows the same verdicts as the ready path', async () => {
    getIv.mockRejectedValue(new Error(IV_ERR));
    getEv.mockRejectedValue(new Error(EV_ERR));
    scan(MIXED);
    await mount();
    getIv.mockResolvedValue(IV_SHIPPED);
    getEv.mockResolvedValue(EVENT_SHIPPED);
    await act(async () => { fireEvent.click(partsOf()['thresholds-retry']); });
    const afterRetry = ['PASSY', 'CAUTY', 'REJY'].map(gateOf);
    expect(page().getAttribute('data-avail')).toBe('ready');
    expectPageCopy();

    // The ready path, from a clean mount with the same answers.
    cleanup();
    useIvThresholdsStore.setState({ thresholds: null, status: 'idle', error: null });
    useEventThresholdsStore.setState({ thresholds: null, status: 'idle', error: null });
    await mount();
    expect(['PASSY', 'CAUTY', 'REJY'].map(gateOf)).toEqual(afterRetry);
    expect(afterRetry).toEqual(['PASS', 'CAUTION', 'REJECT']);
  });

  it('S4: while the fetch is pending every gate is PENDING and the loading sentence shows', async () => {
    getIv.mockImplementation(pending);
    getEv.mockImplementation(pending);
    scan(MIXED);
    await mount();
    expect(gates().map((g) => g.getAttribute('data-gate'))).toEqual(['PENDING', 'PENDING', 'PENDING']);
    expect(verdictBadges()).toEqual([]);
    expect(partsOf()['thresholds-unavailable'].getAttribute('data-avail')).toBe('loading');
    expect(partsOf()['thresholds-retry']).toBeUndefined();
    expectHeaderStructure();
  });

  it('S5: each mount fetches both stores once, and a remount fetches again', async () => {
    getIv.mockResolvedValue(IV_SHIPPED);
    getEv.mockResolvedValue(EVENT_SHIPPED);
    scan(MIXED);
    await mount();
    expect([getIv.mock.calls.length, getEv.mock.calls.length]).toEqual([1, 1]);
    cleanup();
    await mount();
    expect([getIv.mock.calls.length, getEv.mock.calls.length]).toEqual([2, 2]);
  });

  it('S6: an Intraday scan that fails to load never says the IV gate is disabled', async () => {
    getIv.mockRejectedValue(new Error(IV_ERR));
    getEv.mockRejectedValue(new Error(EV_ERR));
    scan(MIXED, 'Intraday (0-2d)');
    await mount();
    expect(page().textContent).not.toContain('IV gate disabled');
    expect(page().getAttribute('data-iv-gated')).toBe('unknown');
    expectHeaderStructure();
  });

  it('S7: an active Swing override is labelled, and a row between the ceilings is graded by it', async () => {
    getIv.mockResolvedValue(IV_SHIPPED);
    getEv.mockResolvedValue(EVENT_SHIPPED);
    useIvThresholdsStore.setState({ overrides: { Swing: { abs_pass_max: 50 } } });
    // Absolute IV 40: above the YAML's 34 (CAUTION there), inside the override's 50.
    scan([makeCandidate('MIDY', null, null, 40)]);
    await mount();
    const o = partsOf()['iv-override'];
    expect([o.getAttribute('data-override'), o.getAttribute('data-yaml')]).toEqual(['50', '34']);
    expect(sideVerdict('MIDY', 'volatility')).toBe('PASS');
    expect(gateOf('MIDY')).toBe('PASS');
    expectHeaderStructure();
  });

  it('S7b: with the override cleared the same row is CAUTION and no label shows', async () => {
    getIv.mockResolvedValue(IV_SHIPPED);
    getEv.mockResolvedValue(EVENT_SHIPPED);
    scan([makeCandidate('MIDY', null, null, 40)]);
    await mount();
    expect(partsOf()['iv-override']).toBeUndefined();
    expect(sideVerdict('MIDY', 'volatility')).toBe('CAUTION');
  });

  it('S8: the empty page (no scan) in the failed state is held to the same contract', async () => {
    getIv.mockRejectedValue(new Error(IV_ERR));
    getEv.mockRejectedValue(new Error(EV_ERR));
    await mount();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeNull();
    expectHeaderStructure();
  });
});
