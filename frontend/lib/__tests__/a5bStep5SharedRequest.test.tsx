/**
 * A5b — a stock scan started from Step 5 builds its request with the shared
 * builder (decision A5B-A5C-LOCKED-2026-09-24 part (1); account_size decision
 * A5B-ACCOUNT-SIZE-2026-09-24). Plan:
 * docs/superpowers/plans/2026-09-24-a5b-step5-shared-request-plan.md
 *
 * Before A5b, Step 5's runScan hand-built the POST /api/stock-scan body and
 * dropped the confidence gate, the ATR pair, the Step-3 overrides, the headwind
 * and fundamentals thresholds and require_choppy_regime.
 */
import '@testing-library/jest-dom';
import { render, fireEvent, waitFor, screen } from '@testing-library/react';
import { runStockScan } from '@/lib/stockScan';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { useSettingsStore, DEFAULT_CONFIDENCE_GATE } from '@/lib/settingsStore';
import { useRiskStore } from '@/lib/riskStore';
import { api } from '@/lib/api';
import Step5 from '../../app/(frame)/screener/step-5-strategy/page';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => '/screener/step-5-strategy',
}));

jest.mock('@/lib/api', () => ({
  api: {
    postStockScan: jest.fn(),
    getLastStockScanStatus: jest.fn(),
    startHistoryPrefetch: jest.fn(),
    getHistoryPrefetchStatus: jest.fn(),
  },
  getLastDataRefresh: jest.fn(() => Promise.resolve({ last_refresh: null })),
  API_BASE_URL: 'http://localhost:8000',
}));

const m = (f: unknown) => f as jest.Mock;
const RESULT = (id: string) => ({ scan_id: id, timestamp: '2026-09-24T10:00:00+00:00', rejected: [], candidates: [] });

const ATR_OVERRIDES = { confidence_atr_mult_target: 3.5, confidence_atr_mult_stop: 1.25 };
const STEP3 = {
  weight_trend: 0.4,
  fast_ema: 12,
  regime_headwind_caution_pct: -3,
  regime_headwind_reject_pct: -9,
  fundamentals_caution_above: 55,
  fundamentals_reject_above: 75,
  ...ATR_OVERRIDES,
  pullback_require_reversal: true,
};
const GATE_ON = { ...DEFAULT_CONFIDENCE_GATE, enabled: true, cautionBelow: 60, rejectBelow: 40 };
const PORTFOLIO_VALUE = 123_456;

const initial = {
  scan: useScanStore.getInitialState(),
  params: useScanParamsStore.getInitialState(),
  settings: useSettingsStore.getInitialState(),
  risk: useRiskStore.getInitialState(),
};

/** Seeds every store — call BEFORE render (the page's useState initializer
 *  captures scanParams, and skipHydration means the hydration sync never fires). */
function seed(opts: { scanOverrides?: Record<string, number | boolean | string>; gate?: unknown } = {}) {
  useScanStore.setState({
    context: { universe: 'NDX100', direction: 'Bearish', horizon: 'Position (1–6m)' },
    scanOverrides: { ...(opts.scanOverrides ?? STEP3) },
  } as never);
  // `in`, not `??`: T6 seeds an explicit null gate.
  useSettingsStore.setState({ confidenceGate: ('gate' in opts ? opts.gate : GATE_ON) as never });
  useScanParamsStore.setState({ requireChoppyRegime: true });
  useRiskStore.setState({ limits: { ...useRiskStore.getState().limits, portfolioValue: PORTFOLIO_VALUE } });
}

beforeEach(() => {
  jest.restoreAllMocks();
  for (const f of Object.values(api)) m(f).mockReset();
  m(api.getLastStockScanStatus).mockResolvedValue({ status: 'idle', updated_at: null, strategy: null });
  m(api.postStockScan).mockResolvedValue(RESULT('S5'));
  useScanStore.setState(initial.scan, true);
  useScanParamsStore.setState(initial.params, true);
  useSettingsStore.setState(initial.settings, true);
  useRiskStore.setState(initial.risk, true);
  localStorage.clear();
});

function card(re: RegExp): HTMLButtonElement {
  return screen.getAllByText(re).map((el) => el.closest('button')).find(Boolean) as HTMLButtonElement;
}

/** Click a strategy card and return the body it posted. Waits for the run's
 *  finally (loadingStrategy clears after getLastStockScanStatus) so the next
 *  click in the same test is not swallowed by a disabled button. */
async function runCard(re: RegExp): Promise<Record<string, unknown>> {
  const btn = card(re);
  const before = m(api.postStockScan).mock.calls.length;
  fireEvent.click(btn);
  await waitFor(() => expect(m(api.postStockScan).mock.calls.length).toBe(before + 1));
  await waitFor(() => expect(card(re)).not.toBeDisabled());
  return m(api.postStockScan).mock.calls[before][0];
}

const MA = /^MA Crossover \d+\/\d+$/;
const MR_BB = /Mean Reversion BB/;
const MR_MULTI = /Mean Reversion Multi-Signal/;
const MULTI_KEYS = ['mean_reversion_variants', 'mean_reversion_min_confirmations', 'vwap_lookback', 'vwap_deviation_pct'];

describe('T1 — the pin: a Step-5 body equals a Step-3/4 body apart from account_size', () => {
  it('ma_crossover', async () => {
    seed();
    render(<Step5 />);
    const step5 = await runCard(MA);
    m(api.postStockScan).mockClear();
    await runStockScan('ma_crossover');
    // Let runStockScan's fire-and-forget meta refresh land inside this test.
    await waitFor(() => expect(api.getLastStockScanStatus).toHaveBeenCalledTimes(2));
    const step4 = m(api.postStockScan).mock.calls[0][0];
    expect({ ...step5, account_size: 0 }).toStrictEqual({ ...step4, account_size: 0 });
    expect(step5.account_size).toBe(PORTFOLIO_VALUE);
    expect(step4.account_size).toBe(50_000);
  });
});

describe('T2 — every seeded value reaches the Step-5 body (hard-coded, not via the helper)', () => {
  const EXPECTED = {
    universe: ['NDX100'],
    direction: 'Bearish',
    horizon: 'Position',
    confidence_caution_below: 60,
    confidence_reject_below: 40,
    confidence_atr_mult_target: 3.5,
    confidence_atr_mult_stop: 1.25,
    regime_headwind_caution_pct: -3,
    regime_headwind_reject_pct: -9,
    fundamentals_caution_above: 55,
    fundamentals_reject_above: 75,
    pullback_require_reversal: true,
    require_choppy_regime: true,
    account_size: PORTFOLIO_VALUE,
    risk_pct: 0.01,
  };

  it.each([
    ['ma_crossover', MA],
    ['mean_reversion_bb', MR_BB],
  ])('%s', async (strategy, re) => {
    seed();
    render(<Step5 />);
    const body = await runCard(re);
    expect(body).toMatchObject({ ...EXPECTED, strategy });
    // Exactly the scorer keys — the headwind/fundamentals/ATR/reversal keys are filtered out.
    expect(body.overrides).toStrictEqual({ weight_trend: 0.4, fast_ema: 12 });
  });
});

describe('T3 — no full ATR override: the horizon pair; gate off: no thresholds', () => {
  it('sends the position pair 2.5/1.5 and undefined confidence thresholds', async () => {
    const { confidence_atr_mult_target: _t, confidence_atr_mult_stop: _s, ...noAtr } = STEP3;
    seed({ scanOverrides: noAtr, gate: { ...DEFAULT_CONFIDENCE_GATE, enabled: false } });
    render(<Step5 />);
    const body = await runCard(MA);
    expect(body.confidence_atr_mult_target).toBe(2.5);
    expect(body.confidence_atr_mult_stop).toBe(1.5);
    expect(body).toHaveProperty('confidence_caution_below', undefined);
    expect(body).toHaveProperty('confidence_reject_below', undefined);
  });
});

describe("T4 — Step 5's local panel edits still win", () => {
  it('an edited MA-crossover fast period rides in as a per-run override', async () => {
    seed();
    render(<Step5 />);
    const edited = useScanParamsStore.getState().maCrossoverFast + 7;
    fireEvent.change(screen.getByLabelText(/MA crossover fast/i), { target: { value: String(edited) } });
    const step5 = await runCard(MA);
    expect(step5.ma_crossover_fast).toBe(edited);
    // The edit is local — the saved store is untouched.
    expect(useScanParamsStore.getState().maCrossoverFast).not.toBe(edited);
    m(api.postStockScan).mockClear();
    await runStockScan('ma_crossover', { maCrossoverFast: edited });
    await waitFor(() => expect(api.getLastStockScanStatus).toHaveBeenCalledTimes(2));
    const step4 = m(api.postStockScan).mock.calls[0][0];
    expect({ ...step5, account_size: 0 }).toStrictEqual({ ...step4, account_size: 0 });
  });
});

// T5 is a panel-wiring and shadowing guard (mutations 4 and 8), NOT a
// regression test for the A5b defect: the pre-A5b literal also sent these four
// fields from useScanParamsStore, so T5 passes on the old code too.
describe('T5 — mean_reversion_multi carries the panel values; other strategies carry none', () => {
  it('multi body has all four variant fields from the rendered panel', async () => {
    seed();
    render(<Step5 />);
    // Toggle RSI off then on: the order changes, and with 2 variants the min (2) is not clamped.
    const rsi = screen.getByLabelText('RSI extremes + trend filter');
    fireEvent.click(rsi);
    fireEvent.click(screen.getByLabelText('RSI extremes + trend filter'));
    const minSelect = screen.getByText('Fire when at least').parentElement!.querySelector('select')!;
    fireEvent.change(minSelect, { target: { value: '3' } });   // not 1: mutation 8 injects 1
    fireEvent.change(screen.getByLabelText(/VWAP lookback/), { target: { value: '33' } });
    fireEvent.change(screen.getByLabelText(/VWAP deviation/), { target: { value: '3.5' } });

    const multi = await runCard(MR_MULTI);
    expect(multi.mean_reversion_variants).toStrictEqual(['mean_reversion_bb', 'mean_reversion_vwap_daily', 'mean_reversion_rsi']);
    expect(multi.mean_reversion_min_confirmations).toBe(3);
    expect(multi.vwap_lookback).toBe(33);
    expect(multi.vwap_deviation_pct).toBeCloseTo(0.035);

    const bb = await runCard(MR_BB);
    for (const k of MULTI_KEYS) expect(bb).not.toHaveProperty(k);
  });
});

describe('T6 — a builder throw on Step 5 lands in the page error, like a post failure', () => {
  it('shows the error, posts nothing and re-enables the cards', async () => {
    seed({ gate: null });
    render(<Step5 />);
    const btn = card(MA);
    fireEvent.click(btn);
    await waitFor(() => expect(screen.getByText(/TypeError/)).toBeInTheDocument());
    expect(api.postStockScan).not.toHaveBeenCalled();
    await waitFor(() => expect(card(MA)).not.toBeDisabled());
    expect(card(MR_BB)).not.toBeDisabled();
    expect(screen.queryByText('Running backtest scan…')).not.toBeInTheDocument();
  });
});

describe('T7 — runStockScan: a builder throw is still inside the try, before reachedRequest', () => {
  it('returns null, FAILED, and does not blame the backend for a pre-request throw', async () => {
    seed();   // both ATR overrides: the builder's first gate read is `.enabled`
    const real = useSettingsStore.getState();
    const gate = { ...real.confidenceGate };
    Object.defineProperty(gate, 'enabled', {
      get() { throw new TypeError('Failed to fetch'); },
    });
    jest.spyOn(useSettingsStore, 'getState').mockReturnValue({ ...real, confidenceGate: gate });

    const result = await runStockScan('ma_crossover');
    expect(result).toBeNull();
    const s = useScanStore.getState();
    expect(s.scanState).toBe('FAILED');
    expect(s.stockScanError).toBeTruthy();
    expect(s.stockScanError).not.toMatch(/could not reach the backend/);
    expect(api.postStockScan).not.toHaveBeenCalled();
    await waitFor(() => expect(api.getLastStockScanStatus).toHaveBeenCalledTimes(1));
  });
});
