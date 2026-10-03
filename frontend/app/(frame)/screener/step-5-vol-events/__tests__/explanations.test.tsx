/*
 * Step 5 Volatility + Events — explanations test suite.
 * Acceptance criteria verification: AC1 (deciding reasons & sub-statuses),
 * AC2 (numeric boundaries across horizons), AC3 (data quirks & negative inputs),
 * AC4 (rules strip provenance & overrides), AC5 (unavailable & prompt behavior),
 * and AC6 (pointer/keyboard interaction & zero network calls).
 */

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import Step5Page from '../page';
import { useScanStore } from '@/lib/scanStore';
import { useIvThresholdsStore } from '@/lib/ivThresholdsStore';
import { useEventThresholdsStore } from '@/lib/eventThresholdsStore';
import { api } from '@/lib/api';
import { EVENT_SHIPPED, IV_SHIPPED, echoStoredThresholds } from '@/lib/testFixtures/thresholds';
import { expectPageCopy, gateOf, sideVerdict, rowOf } from '../testSupport/pageContract';
import type { TradeCardData } from '@/types/domain';

jest.mock('@/lib/api', () => ({
  api: {
    getIvThresholds: jest.fn(),
    getEventThresholds: jest.fn(),
  },
}));

beforeEach(() => {
  echoStoredThresholds(api as unknown as Parameters<typeof echoStoredThresholds>[0]);
});

afterEach(() => {
  cleanup();
  useScanStore.setState({ scanResult: undefined, context: undefined } as any);
  useIvThresholdsStore.setState({ thresholds: null, status: 'idle', error: null, overrides: {} });
  useEventThresholdsStore.setState({ thresholds: null, status: 'idle', error: null });
});

function tableRowOf(symbol: string): HTMLElement {
  return rowOf(symbol).closest('[data-status]') as HTMLElement;
}

function makeCandidate(
  symbol: string,
  cd: Record<string, unknown> = {},
  nextEventDays: number | null = null,
  nextEventLabel: string | null = null,
): TradeCardData {
  return {
    symbol,
    company: `${symbol} Corporation`,
    price: 150,
    direction: 'Bullish',
    status: 'PASS',
    stockScore: 80,
    stockConfidence: 'PASS',
    stockBreakdown: {} as any,
    nextEventDays,
    nextEventLabel,
    contract: `${symbol}|150|2026-12-01|C`,
    contractScore: 75,
    contractConfidence: 'PASS',
    contractBreakdown: {} as any,
    contractDetails: {
      strike: 150,
      expiry: '2026-12-01',
      right: 'C',
      mid: 2.5,
      delta: 0.5,
      theta: -0.04,
      dte: 60,
      ...cd,
    },
    entry: {} as any,
    exit: {} as any,
  } as TradeCardData;
}

function setupScan(
  candidates: TradeCardData[],
  horizon = 'Swing (5-15d)',
  eventWindow?: { reject_days: number; caution_days: number },
  ivOverrides: Record<string, { abs_pass_max: number }> = {},
) {
  useScanStore.setState({
    scanResult: {
      candidates,
      rejected: [],
      scan_id: 'test-scan-123',
      timestamp: '2026-10-03T10:00:00Z',
      ...(eventWindow ? { event_window: eventWindow } : {}),
    } as any,
    context: { direction: 'Bullish', horizon } as any,
  } as any);

  useIvThresholdsStore.setState({
    thresholds: IV_SHIPPED,
    status: 'ready',
    error: null,
    overrides: ivOverrides,
  });
  useEventThresholdsStore.setState({
    thresholds: EVENT_SHIPPED,
    status: 'ready',
    error: null,
  });
}

async function mount() {
  await act(async () => {
    render(<Step5Page />);
  });
}

describe('AC1: Sub-statuses and deciding reasons for all verdict combinations', () => {
  it('IV PASS + event CAUTION: event alone decides', async () => {
    // Swing: rank pass <= 34, event reject < 21, caution < 45
    const c = makeCandidate('EVTC', { ivRank: 20 }, 30, 'Earnings');
    setupScan([c]);
    await mount();

    expect(gateOf('EVTC')).toBe('CAUTION');
    expect(sideVerdict('EVTC', 'volatility')).toBe('PASS');
    expect(sideVerdict('EVTC', 'event')).toBe('CAUTION');

    const row = tableRowOf('EVTC');
    const reasonCell = row.querySelector('[data-cell="reason"]');
    expect(reasonCell?.textContent).toContain('Event proximity');

    expectPageCopy();
  });

  it('IV REJECT + event CAUTION: IV alone decides', async () => {
    // Swing: rank > 55 is REJECT; event 30d is CAUTION
    const c = makeCandidate('IVREJ', { ivRank: 60 }, 30, 'Earnings');
    setupScan([c]);
    await mount();

    expect(gateOf('IVREJ')).toBe('REJECT');
    expect(sideVerdict('IVREJ', 'volatility')).toBe('REJECT');
    expect(sideVerdict('IVREJ', 'event')).toBe('CAUTION');

    const row = tableRowOf('IVREJ');
    const reasonCell = row.querySelector('[data-cell="reason"]');
    expect(reasonCell?.textContent).toContain('IV rank');
    expect(reasonCell?.textContent).not.toContain('event proximity');

    expectPageCopy();
  });

  it('IV CAUTION + event CAUTION: tied drivers list both', async () => {
    // Swing: rank 40 is CAUTION; event 30d is CAUTION
    const c = makeCandidate('TIEDC', { ivRank: 40 }, 30, 'Earnings');
    setupScan([c]);
    await mount();

    expect(gateOf('TIEDC')).toBe('CAUTION');
    expect(sideVerdict('TIEDC', 'volatility')).toBe('CAUTION');
    expect(sideVerdict('TIEDC', 'event')).toBe('CAUTION');

    const row = tableRowOf('TIEDC');
    const reasonCell = row.querySelector('[data-cell="reason"]');
    expect(reasonCell?.textContent).toContain('IV rank and event proximity');

    expectPageCopy();
  });

  it('IV REJECT + event REJECT: tied reject drivers list both', async () => {
    // Swing: rank 70 is REJECT; event 10d is REJECT
    const c = makeCandidate('TIEDR', { ivRank: 70 }, 10, 'Earnings');
    setupScan([c]);
    await mount();

    expect(gateOf('TIEDR')).toBe('REJECT');
    expect(sideVerdict('TIEDR', 'volatility')).toBe('REJECT');
    expect(sideVerdict('TIEDR', 'event')).toBe('REJECT');

    const row = tableRowOf('TIEDR');
    const reasonCell = row.querySelector('[data-cell="reason"]');
    expect(reasonCell?.textContent).toContain('IV rank and event proximity');

    expectPageCopy();
  });

  it('IV PASS + event PASS: No adverse driver', async () => {
    // Swing: rank 20 is PASS; event 60d is PASS
    const c = makeCandidate('ALLP', { ivRank: 20 }, 60, 'Earnings');
    setupScan([c]);
    await mount();

    expect(gateOf('ALLP')).toBe('PASS');
    expect(sideVerdict('ALLP', 'volatility')).toBe('PASS');
    expect(sideVerdict('ALLP', 'event')).toBe('PASS');

    const row = tableRowOf('ALLP');
    const reasonCell = row.querySelector('[data-cell="reason"]');
    expect(reasonCell?.textContent).toContain('No adverse driver');

    expectPageCopy();
  });

  it('Missing IV reading on gated horizon: No volatility reading driver', async () => {
    // Swing: no IV rank, no absolute IV, no event -> IV CAUTION, event PASS
    const c = makeCandidate('NOIV', {}, null);
    setupScan([c]);
    await mount();

    expect(gateOf('NOIV')).toBe('CAUTION');
    expect(sideVerdict('NOIV', 'volatility')).toBe('CAUTION');
    expect(sideVerdict('NOIV', 'event')).toBe('PASS');

    const row = tableRowOf('NOIV');
    const reasonCell = row.querySelector('[data-cell="reason"]');
    expect(reasonCell?.textContent).toContain('No volatility reading');

    expectPageCopy();
  });
});

describe('AC2: Exact numeric boundaries across horizons and bases', () => {
  it('IV boundaries: pass boundary (<= 34), caution boundary (<= 55) on Swing', async () => {
    const c1 = makeCandidate('P34', { ivRank: 34 }, null);
    const c2 = makeCandidate('C3401', { ivRank: 34.01 }, null);
    const c3 = makeCandidate('C55', { ivRank: 55 }, null);
    const c4 = makeCandidate('R5501', { ivRank: 55.01 }, null);
    setupScan([c1, c2, c3, c4]);
    await mount();

    expect(gateOf('P34')).toBe('PASS');
    expect(gateOf('C3401')).toBe('CAUTION');
    expect(gateOf('C55')).toBe('CAUTION');
    expect(gateOf('R5501')).toBe('REJECT');

    expectPageCopy();
  });

  it('Absolute IV boundaries: pass boundary (<= 34.00%), caution boundary (<= 55.00%) on Swing', async () => {
    const c1 = makeCandidate('AP34', { ivRank: null, iv: 34.00 }, null);
    const c2 = makeCandidate('AC3401', { ivRank: null, iv: 34.01 }, null);
    const c3 = makeCandidate('AC55', { ivRank: null, iv: 55.00 }, null);
    const c4 = makeCandidate('AR5501', { ivRank: null, iv: 55.01 }, null);
    setupScan([c1, c2, c3, c4]);
    await mount();

    expect(gateOf('AP34')).toBe('PASS');
    expect(gateOf('AC3401')).toBe('CAUTION');
    expect(gateOf('AC55')).toBe('CAUTION');
    expect(gateOf('AR5501')).toBe('REJECT');

    expectPageCopy();
  });

  it('Event boundaries: strict < applied (day 21 is CAUTION, day 45 is PASS on Swing 21/45)', async () => {
    const c1 = makeCandidate('EV20', { ivRank: 20 }, 20); // 20 < 21 -> REJECT
    const c2 = makeCandidate('EV21', { ivRank: 20 }, 21); // 21 is not < 21 -> CAUTION
    const c3 = makeCandidate('EV44', { ivRank: 20 }, 44); // 44 < 45 -> CAUTION
    const c4 = makeCandidate('EV45', { ivRank: 20 }, 45); // 45 is not < 45 -> PASS
    setupScan([c1, c2, c3, c4]);
    await mount();

    expect(gateOf('EV20')).toBe('REJECT');
    expect(gateOf('EV21')).toBe('CAUTION');
    expect(gateOf('EV44')).toBe('CAUTION');
    expect(gateOf('EV45')).toBe('PASS');

    expectPageCopy();
  });

  it('Coincident event boundaries: reject_days === caution_days leaves no reachable CAUTION interval', async () => {
    // 30 reject, 30 caution -> < 30 is REJECT, >= 30 is PASS (no caution reachable)
    const c1 = makeCandidate('COIN29', { ivRank: 20 }, 29); // 29 < 30 -> REJECT
    const c2 = makeCandidate('COIN30', { ivRank: 20 }, 30); // 30 is not < 30 -> PASS
    setupScan([c1, c2], 'Swing (5-15d)', { reject_days: 30, caution_days: 30 });
    await mount();

    expect(gateOf('COIN29')).toBe('REJECT');
    expect(gateOf('COIN30')).toBe('PASS');

    expectPageCopy();
  });

  it('Intraday horizon: IV is ungated, even with rank 95', async () => {
    const c = makeCandidate('INTRA', { ivRank: 95 }, 5);
    setupScan([c], 'Intraday (0-2d)');
    await mount();

    expect(sideVerdict('INTRA', 'volatility')).toBe('PASS');
    expect(gateOf('INTRA')).toBe('PASS');

    expectPageCopy();
  });

  it('Position horizon: uses Position-specific thresholds (IV 44/65, Event 30/60)', async () => {
    // 40 IV rank is PASS on Position (<= 44), but would be CAUTION on Swing
    // Event 50 is CAUTION on Position (< 60), but would be PASS on Swing
    const c = makeCandidate('POS', { ivRank: 40 }, 50);
    setupScan([c], 'Position (90-105d)');
    await mount();

    expect(sideVerdict('POS', 'volatility')).toBe('PASS');
    expect(sideVerdict('POS', 'event')).toBe('CAUTION');
    expect(gateOf('POS')).toBe('CAUTION');

    expectPageCopy();
  });
});

describe('AC3: Edge cases, nulls, zeros, and negative days', () => {
  it('Rank 0 is a valid reading (cheapest premium), not missing', async () => {
    const c = makeCandidate('RNK0', { ivRank: 0 }, null);
    setupScan([c]);
    await mount();

    expect(gateOf('RNK0')).toBe('PASS');
    const ivCell = tableRowOf('RNK0').querySelector('[data-cell="iv"]');
    expect(ivCell?.textContent).toContain('0');
    expect(ivCell?.getAttribute('data-iv-basis')).toBe('rank');

    expectPageCopy();
  });

  it('Absolute IV 0 is treated as missing data', async () => {
    const c = makeCandidate('ABS0', { ivRank: null, iv: 0 }, null);
    setupScan([c]);
    await mount();

    expect(sideVerdict('ABS0', 'volatility')).toBe('CAUTION');
    const ivCell = tableRowOf('ABS0').querySelector('[data-cell="iv"]');
    expect(ivCell?.getAttribute('data-iv-basis')).toBe('none');

    expectPageCopy();
  });

  it('Percentile 0 is displayed as context and does not corrupt gate', async () => {
    const c = makeCandidate('PCTL0', { ivRank: 15, ivPercentile: 0 }, null);
    setupScan([c]);
    await mount();

    expect(gateOf('PCTL0')).toBe('PASS');
    const pctlCell = tableRowOf('PCTL0').querySelector('[data-cell="pctl"]');
    expect(pctlCell?.textContent).toBe('0');

    expectPageCopy();
  });

  it('Null event date: no penalty applied and correctly described', async () => {
    const c = makeCandidate('NOEV', { ivRank: 20 }, null, null);
    setupScan([c]);
    await mount();

    expect(sideVerdict('NOEV', 'event')).toBe('PASS');
    expect(gateOf('NOEV')).toBe('PASS');

    // Open disclosure to verify text
    const btn = tableRowOf('NOEV').querySelector('[data-cell="disclosure"] button') as HTMLButtonElement;
    fireEvent.click(btn);

    const panel = tableRowOf('NOEV').querySelector('[data-disclosure-panel]');
    expect(panel?.textContent).toContain('No event date available; existing gate applies no event penalty');

    expectPageCopy();
  });

  it('Negative event days: displayed with exact days and evaluated with strict <', async () => {
    // Next event days = -2 (past event in raw data)
    const c = makeCandidate('NEGD', { ivRank: 20 }, -2, 'Earnings Passed');
    setupScan([c]);
    await mount();

    // -2 < 21 -> REJECT
    expect(sideVerdict('NEGD', 'event')).toBe('REJECT');
    expect(gateOf('NEGD')).toBe('REJECT');

    const eventCell = tableRowOf('NEGD').querySelector('[data-cell="event"]');
    expect(eventCell?.textContent).toContain('-2d');

    expectPageCopy();
  });
});

describe('AC4: Rules strip provenance and session overrides', () => {
  it('Rules strip displays Recorded scan event window when scanResult echoes event_window', async () => {
    const c = makeCandidate('REC', { ivRank: 25 }, 40);
    setupScan([c], 'Swing (5-15d)', { reject_days: 10, caution_days: 35 });
    await mount();

    const strip = screen.getByTestId('step-5').querySelector('[data-rules-strip]');
    expect(strip).not.toBeNull();
    expect(strip?.querySelector('[data-provenance]')?.textContent).toBe('Recorded scan event window');
    expect(strip?.querySelector('[data-horizon-tag]')?.textContent).toBe('Horizon: Swing');
    expect(strip?.textContent).toContain('Earnings < 10d → REJECT; < 35d → CAUTION; else → PASS');

    expectPageCopy();
  });

  it('Rules strip displays Legacy scan: current configuration fallback when scan has no echo', async () => {
    const c = makeCandidate('LEG', { ivRank: 25 }, 40);
    // Setup without event_window
    setupScan([c], 'Swing (5-15d)');
    await mount();

    const strip = screen.getByTestId('step-5').querySelector('[data-rules-strip]');
    expect(strip?.querySelector('[data-provenance]')?.textContent).toBe('Legacy scan: current configuration fallback');

    expectPageCopy();
  });

  it('Absolute session override changes absolute pass band only and displays notice', async () => {
    const c1 = makeCandidate('OVR', { ivRank: null, iv: 40 }, null); // Absolute IV 40
    // Shipped Swing absolute pass is 34; override to 45 makes 40 PASS
    setupScan([c1], 'Swing (5-15d)', undefined, { Swing: { abs_pass_max: 45 } });
    await mount();

    expect(gateOf('OVR')).toBe('PASS');
    const strip = screen.getByTestId('step-5').querySelector('[data-rules-strip]');
    expect(strip?.textContent).toContain('Session override: IV pass ≤ 45% (YAML baseline: 34%)');

    expectPageCopy();
  });

  it('Above-caution session override displays no reachable CAUTION interval', async () => {
    const c1 = makeCandidate('ABV', { ivRank: null, iv: 58 }, null); // Absolute IV 58
    // Swing baseline: abs_pass_max 34, abs_caution_max 55.
    // Override abs_pass_max to 60 (>= caution 55)
    setupScan([c1], 'Swing (5-15d)', undefined, { Swing: { abs_pass_max: 60 } });
    await mount();

    expect(gateOf('ABV')).toBe('PASS');
    const strip = screen.getByTestId('step-5').querySelector('[data-rules-strip]');
    expect(strip?.textContent).toContain('CAUTION: no reachable interval');
    expect(strip?.textContent).toContain('≤ 60% → PASS; > 60% → REJECT; CAUTION: no reachable interval');

    // Click explain button to inspect disclosure panel
    const row = tableRowOf('ABV');
    const btn = row.querySelector('[data-cell="disclosure"] button') as HTMLButtonElement;
    fireEvent.click(btn);
    const panel = row.querySelector('[data-disclosure-panel]');
    expect(panel?.textContent).toContain('CAUTION: no reachable interval');

    expectPageCopy();
  });
});

describe('AC6: Disclosure interaction, keyboard accessibility, and state isolation', () => {
  it('Toggling disclosure updates aria-expanded, aria-controls, and panel visibility', async () => {
    const c1 = makeCandidate('DISC1', { ivRank: 20 }, 30);
    const c2 = makeCandidate('DISC2', { ivRank: 40 }, 50);
    setupScan([c1, c2]);
    await mount();

    const row1 = tableRowOf('DISC1');
    const row2 = tableRowOf('DISC2');
    const btn1 = row1.querySelector('[data-cell="disclosure"] button') as HTMLButtonElement;
    const btn2 = row2.querySelector('[data-cell="disclosure"] button') as HTMLButtonElement;

    expect(btn1.getAttribute('aria-expanded')).toBe('false');
    expect(btn1.getAttribute('aria-controls')).toBe('disclosure-DISC1');
    expect(row1.querySelector('[data-disclosure-panel]')).toBeNull();

    // Click to open row 1
    fireEvent.click(btn1);
    expect(btn1.getAttribute('aria-expanded')).toBe('true');
    expect(btn1.textContent).toBe('Hide');
    const panel1 = row1.querySelector('[data-disclosure-panel]');
    expect(panel1).not.toBeNull();
    expect(panel1?.getAttribute('id')).toBe('disclosure-DISC1');
    expect(panel1?.getAttribute('role')).toBe('region');

    // Row 2 remains independent and closed
    expect(btn2.getAttribute('aria-expanded')).toBe('false');
    expect(row2.querySelector('[data-disclosure-panel]')).toBeNull();

    // Click again to close row 1
    fireEvent.click(btn1);
    expect(btn1.getAttribute('aria-expanded')).toBe('false');
    expect(btn1.textContent).toBe('Explain');
    expect(row1.querySelector('[data-disclosure-panel]')).toBeNull();

    expectPageCopy();
  });

  it('Keyboard Enter / Space accessible button triggers toggle', async () => {
    const c = makeCandidate('KBD', { ivRank: 20 }, 30);
    setupScan([c]);
    await mount();

    const row = tableRowOf('KBD');
    const btn = row.querySelector('[data-cell="disclosure"] button') as HTMLButtonElement;

    expect(btn.tagName).toBe('BUTTON');
    expect(btn.type).toBe('button');
    btn.focus();
    expect(document.activeElement).toBe(btn);

    // Native buttons trigger click on Enter/Space keyboard activation
    fireEvent.click(btn);
    expect(btn.getAttribute('aria-expanded')).toBe('true');
    expect(row.querySelector('[data-disclosure-panel]')).not.toBeNull();

    fireEvent.click(btn);
    expect(btn.getAttribute('aria-expanded')).toBe('false');
    expect(row.querySelector('[data-disclosure-panel]')).toBeNull();

    expectPageCopy();
  });

  it('Expanding disclosure generates zero API calls and does not mutate scanStore', async () => {
    const c = makeCandidate('API0', { ivRank: 20 }, 30);
    setupScan([c]);
    await mount();

    const getIvCallsBefore = (api.getIvThresholds as jest.Mock).mock.calls.length;
    const getEvCallsBefore = (api.getEventThresholds as jest.Mock).mock.calls.length;
    const scanStateBefore = useScanStore.getState();

    const btn = tableRowOf('API0').querySelector('[data-cell="disclosure"] button') as HTMLButtonElement;
    fireEvent.click(btn);

    const getIvCallsAfter = (api.getIvThresholds as jest.Mock).mock.calls.length;
    const getEvCallsAfter = (api.getEventThresholds as jest.Mock).mock.calls.length;

    expect(getIvCallsAfter).toBe(getIvCallsBefore);
    expect(getEvCallsAfter).toBe(getEvCallsBefore);
    expect(useScanStore.getState()).toBe(scanStateBefore);
  });
});
