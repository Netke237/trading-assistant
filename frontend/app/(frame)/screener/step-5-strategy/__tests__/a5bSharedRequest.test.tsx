/**
 * A5b — a stock scan started from Step 5 builds its request with the same
 * builder as Steps 3/4 (decision A5B-A5C-LOCKED-2026-09-24, item 1), so it
 * carries every Step-3 setting. Plan:
 * docs/superpowers/plans/2026-09-24-a5b-step5-shared-request-plan.md
 */
import '@testing-library/jest-dom';
import { render, fireEvent, waitFor, screen, cleanup } from '@testing-library/react';
import { runStockScan } from '@/lib/stockScan';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { useSettingsStore, DEFAULT_CONFIDENCE_GATE } from '@/lib/settingsStore';
import { useRiskStore } from '@/lib/riskStore';
import { api } from '@/lib/api';
import Step5 from '../page';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => '/screener/step-5-strategy',
}));

jest.mock('@/lib/api', () => ({
  api: {
    postStockScan: jest.fn(),
    getLastStockScanStatus: jest.fn(),
  },
  getLastDataRefresh: jest.fn(() => Promise.resolve({ last_refresh: null })),
  API_BASE_URL: 'http://localhost:8000',
}));

const m = (f: unknown) => f as jest.Mock;

const STEP3 = {
  weight_trend: 0.5,
  max_delta: 0.4,                        // options-only: must be filtered out
  regime_headwind_caution_pct: -7,
  regime_headwind_reject_pct: -13,
  fundamentals_caution_above: 70,
  fundamentals_reject_above: 90,
  confidence_atr_mult_target: 3.25,
  confidence_atr_mult_stop: 1.75,
  pullback_require_reversal: true,
};

const STRATEGY_LABELS: Record<string, RegExp> = {
  pullback_ema: /^Pullback to \d+-(EMA|SMA)$/,
  breakout_base: /^Breakout from tight base$/,
  ma_crossover: /^MA Crossover \d+\/\d+$/,
  mean_reversion_rsi: /^Mean Reversion RSI \/ \d+-SMA$/,
  mean_reversion_bb: /^Mean Reversion BB$/,
  mean_reversion_vwap: /^Mean Reversion VWAP \(15m\)$/,
  mean_reversion_multi: /^Mean Reversion Multi-Signal$/,
};

function reset(portfolioValue = 50_000) {
  m(api.postStockScan).mockReset();
  m(api.postStockScan).mockResolvedValue({ scan_id: 'S', timestamp: '2026-09-24T10:00:00+00:00', rejected: [], candidates: [] });
  m(api.getLastStockScanStatus).mockReset();
  m(api.getLastStockScanStatus).mockResolvedValue({ status: 'idle', updated_at: null, strategy: null });
  useScanStore.setState({
    context: { universe: 'NDX100', direction: 'Bearish', horizon: 'Position (1–6m)' },
    scanOverrides: { ...STEP3 },
    stockScanResult: null,
    stockScanRequest: null,
    activeStrategy: null,
    scanState: 'IDLE',
    stockScanError: null,
  } as never);
  useScanParamsStore.setState({
    pullbackTolerancePct: 0.04,
    pullbackEmaPeriod: 21,
    rsiOversold: 27,
    requireChoppyRegime: true,
    btMinTrades: 12,
    btMinWinRate: 0.55,
    stockShortlistMax: 17,
    meanReversionVariants: ['mean_reversion_rsi', 'mean_reversion_bb'],
    meanReversionMinConfirm: 2,
    vwapLookback: 15,
    vwapDeviationPct: 0.025,
  });
  useSettingsStore.setState({
    confidenceGate: { ...DEFAULT_CONFIDENCE_GATE, enabled: true, cautionBelow: 58, rejectBelow: 41 },
  });
  useRiskStore.setState((s) => ({ limits: { ...s.limits, portfolioValue } }));
}

function strategyButton(key: string): HTMLButtonElement {
  const el = screen.getAllByText(STRATEGY_LABELS[key])
    .map((e) => e.closest('button')).find((b) => b !== null);
  if (!el) throw new Error(`no button for ${key}`);
  return el as HTMLButtonElement;
}

async function step5Body(key: string, edit?: () => void) {
  render(<Step5 />);
  edit?.();
  fireEvent.click(strategyButton(key));
  await waitFor(() => expect(m(api.postStockScan)).toHaveBeenCalledTimes(1));
  const body = m(api.postStockScan).mock.calls[0][0];
  await waitFor(() => expect(useScanStore.getState().stockScanRequest).toEqual(body));
  cleanup();
  return body;
}

async function step34Body(key: string, overrides = {}) {
  m(api.postStockScan).mockClear();
  await runStockScan(key, overrides);
  return m(api.postStockScan).mock.calls[0][0];
}

beforeEach(() => reset());
afterEach(cleanup);

describe('T1 — a Step-5 body equals the Step-3/4 body, every strategy', () => {
  it.each(Object.keys(STRATEGY_LABELS))('%s', async (key) => {
    const s5 = await step5Body(key);
    const s34 = await step34Body(key);
    expect(s5).toEqual(s34);
    expect(s5.strategy).toBe(key);
  });
});

describe('T2 — literal pins (so T1 cannot pass with both paths wrong)', () => {
  it('carries every Step-3 setting', async () => {
    const b = await step5Body('mean_reversion_rsi');
    expect(b.universe).toEqual(['NDX100']);
    expect(b.direction).toBe('Bearish');
    expect(b.horizon).toBe('Position');
    expect(b.overrides).toEqual({ weight_trend: 0.5 });
    expect(b.confidence_caution_below).toBe(58);
    expect(b.confidence_reject_below).toBe(41);
    expect(b.confidence_atr_mult_target).toBe(3.25);
    expect(b.confidence_atr_mult_stop).toBe(1.75);
    expect(b.regime_headwind_caution_pct).toBe(-7);
    expect(b.regime_headwind_reject_pct).toBe(-13);
    expect(b.fundamentals_caution_above).toBe(70);
    expect(b.fundamentals_reject_above).toBe(90);
    expect(b.pullback_require_reversal).toBe(true);
    expect(b.require_choppy_regime).toBe(true);
    expect(b.rsi_oversold).toBe(27);
    expect(b.bt_min_trades).toBe(12);
    expect(b.shortlist_max_candidates).toBe(17);
    expect(b.risk_pct).toBe(0.01);
    expect(b.mean_reversion_variants).toBeUndefined();
  });

  it('mean_reversion_multi carries its four fields from the store', async () => {
    const b = await step5Body('mean_reversion_multi');
    expect(b.mean_reversion_variants).toEqual(['mean_reversion_rsi', 'mean_reversion_bb']);
    expect(b.mean_reversion_min_confirmations).toBe(2);
    expect(b.vwap_lookback).toBe(15);
    expect(b.vwap_deviation_pct).toBe(0.025);
  });
});

describe('T3 — confidence gate disabled', () => {
  it('sends no confidence thresholds', async () => {
    useSettingsStore.setState({ confidenceGate: { ...DEFAULT_CONFIDENCE_GATE, enabled: false } });
    const b = await step5Body('pullback_ema');
    expect(b.confidence_caution_below).toBeUndefined();
    expect(b.confidence_reject_below).toBeUndefined();
  });
});

describe('T4 — the panel\'s unsaved edits win', () => {
  it('an edited, unsaved field is sent; nothing else differs from Step 3/4', async () => {
    const b5 = await step5Body('pullback_ema', () => {
      const input = screen.getByText('Pullback EMA period').closest('label')!.querySelector('input')!;
      fireEvent.change(input, { target: { value: '34' } });
    });
    expect(useScanParamsStore.getState().pullbackEmaPeriod).toBe(21);   // not saved
    expect(b5.pullback_ema_period).toBe(34);
    const b34 = await step34Body('pullback_ema');
    expect(b5).toEqual({ ...b34, pullback_ema_period: 34 });
  });
});

describe('T5 — account size stays the user\'s portfolio value', () => {
  it('sends riskStore portfolioValue, not a hardcoded 50k', async () => {
    reset(123_456);
    const b = await step5Body('breakout_base');
    expect(b.account_size).toBe(123_456);
  });
});
