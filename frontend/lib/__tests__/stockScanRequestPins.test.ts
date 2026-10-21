/**
 * A5b literal pins, moved from step-5-strategy on its removal
 * (STOCKS-STEP-MERGE-S1). A stock scan builds its request with the shared
 * builder (decision A5B-A5C-LOCKED-2026-09-24, item 1), so it carries every
 * Step-3 setting. With one scan path left (runStockScan), the old Step-5 vs
 * Steps 3/4 parity test (T1) is structural and was dropped; T2–T5 pin the
 * body literally. Plans:
 * docs/superpowers/plans/2026-09-24-a5b-step5-shared-request-plan.md,
 * docs/superpowers/plans/2026-10-04-stocks-step-merge-stage1-plan.md
 */
import { runStockScan } from '@/lib/stockScan';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { useSettingsStore, DEFAULT_CONFIDENCE_GATE } from '@/lib/settingsStore';
import { useRiskStore } from '@/lib/riskStore';
import { api } from '@/lib/api';

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
  weight_trend: 50,
  max_delta: 0.4,                        // options-only: must be filtered out
  regime_headwind_caution_pct: -7,
  regime_headwind_reject_pct: -13,
  fundamentals_caution_above: 70,
  fundamentals_reject_above: 90,
  confidence_atr_mult_target: 3.25,
  confidence_atr_mult_stop: 1.75,
  pullback_require_reversal: true,
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

async function step34Body(key: string, overrides = {}) {
  m(api.postStockScan).mockClear();
  await runStockScan(key, overrides);
  return m(api.postStockScan).mock.calls[0][0];
}

beforeEach(() => reset());

describe('T2 — literal pins', () => {
  it('carries every Step-3 setting', async () => {
    const b = await step34Body('mean_reversion_rsi');
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
    // P3a: the user's max loss per trade from Settings → Risk, not a hardcoded 1%.
    expect(b.risk_pct).toBe(useRiskStore.getState().limits.maxLossPerTradePct);
    expect(b.mean_reversion_variants).toBeUndefined();
  });

  it('mean_reversion_multi carries its four fields from the store', async () => {
    const b = await step34Body('mean_reversion_multi');
    expect(b.mean_reversion_variants).toEqual(['mean_reversion_rsi', 'mean_reversion_bb']);
    expect(b.mean_reversion_min_confirmations).toBe(2);
    expect(b.vwap_lookback).toBe(15);
    expect(b.vwap_deviation_pct).toBe(0.025);
  });
});

describe('T3 — confidence gate disabled', () => {
  it('sends no confidence thresholds', async () => {
    useSettingsStore.setState({ confidenceGate: { ...DEFAULT_CONFIDENCE_GATE, enabled: false } });
    const b = await step34Body('pullback_ema');
    expect(b.confidence_caution_below).toBeUndefined();
    expect(b.confidence_reject_below).toBeUndefined();
  });
});

describe('T4 — the panel\'s unsaved edits win', () => {
  // The overrides argument is how Step 4 passes the panel's unsaved edits
  // (runStockScan(activeStrategy, params)).
  it('an edited, unsaved field is sent without being saved', async () => {
    const b = await step34Body('pullback_ema', { pullbackEmaPeriod: 34 });
    expect(useScanParamsStore.getState().pullbackEmaPeriod).toBe(21);   // not saved
    expect(b.pullback_ema_period).toBe(34);
  });
});

describe('T5 — account size stays the user\'s portfolio value', () => {
  it('sends riskStore portfolioValue, not a hardcoded 50k', async () => {
    reset(123_456);
    const b = await step34Body('breakout_base');
    expect(b.account_size).toBe(123_456);
  });
});

describe('B6 (STOCKS-HORIZON-P0B) — the scan\'s hold travels as hold_max_days', () => {
  it('sends the context hold, not the preset table', async () => {
    useScanStore.setState({
      context: { universe: 'NDX100', direction: 'Bullish', horizon: 'Swing (5–15d)',
        horizonPreset: 'Swing', holdMin: 5, holdMax: 15 },
    } as never);
    const b = await step34Body('pullback_ema');
    expect(b.hold_max_days).toBe(15);
  });

  it('a Custom 60-185 context sends 185 (the Custom preset row says 15)', async () => {
    useScanStore.setState({
      context: { universe: 'NDX100', direction: 'Bullish', horizon: 'Position (60–185d)',
        horizonPreset: 'Custom', holdMin: 60, holdMax: 185 },
    } as never);
    const b = await step34Body('pullback_ema');
    expect(b.horizon).toBe('Position');
    expect(b.hold_max_days).toBe(185);
  });
});
