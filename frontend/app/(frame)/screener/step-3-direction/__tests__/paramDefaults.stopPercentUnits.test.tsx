import '@testing-library/jest-dom';
import React from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import Step3Page from '../page';
import { useScanStore } from '@/lib/scanStore';
import { buildStockScanRequestBody } from '@/lib/resolveStockScanRequest';
import { buildOptionsScanRequestBody } from '@/lib/resolveOptionsScanRequest';
import { rrOverridesFrom } from '@/lib/tradeCardOverride';
import { DEFAULT_CONFIDENCE_GATE, DEFAULT_FUNDAMENTALS_GATE } from '@/lib/settingsStore';

jest.mock('@/lib/api', () => ({
  api: {
    getLatestScanReport: jest.fn().mockResolvedValue(null),
    getRegime: jest.fn().mockResolvedValue(null),
    getScanStatus: jest.fn().mockResolvedValue(null),
    getLastScanStatus: jest.fn().mockResolvedValue({ status: null, updated_at: null }),
    getEventThresholds: jest.fn().mockResolvedValue(null),
  },
}));

jest.mock('@/components/organisms/RunScanButton', () => ({
  RunScanButton: () => null,
}));

jest.mock('@/components/organisms/SearchProfileBar', () => ({
  SearchProfileBar: () => null,
}));

jest.mock('@/components/organisms/SavedScanReportInspector', () => ({
  SavedScanReportInspector: () => null,
}));

describe('Step 3 — Stop percentage unit scaling and bounds (Finding C7, #385)', () => {
  beforeEach(() => {
    act(() => {
      useScanStore.setState({
        context: {
          universe: 'SP500',
          direction: 'Bullish',
          horizon: 'Swing',
          horizonPreset: 'Swing',
          holdMin: 5,
          holdMax: 20,
        },
        screenerMode: 'options',
        scanOverrides: {},
        scanResult: null,
      });
    });
  });

  afterEach(() => {
    act(() => {
      useScanStore.setState({ scanOverrides: {} });
    });
  });

  it('renders default stop percentages in whole percent (3, not 0.03)', async () => {
    render(<Step3Page />);

    // Open Execution Parameters panel
    const toggleBtn = screen.getByText('Execution Parameters');
    fireEvent.click(toggleBtn);

    const bullishRow = document.querySelector('[data-param-key="rr_bullish_invalidation_pct"]');
    expect(bullishRow).toBeInTheDocument();
    // Default column shows "3" (not "0.03")
    expect(bullishRow?.children[1]?.textContent).toBe('3');

    const bullishInput = bullishRow?.querySelector('input') as HTMLInputElement;
    expect(bullishInput).toBeInTheDocument();
    expect(bullishInput.value).toBe('3');
    expect(bullishInput.min).toBe('0.5');
    expect(bullishInput.max).toBe('100');
    expect(bullishInput.step).toBe('0.5');

    const bearishRow = document.querySelector('[data-param-key="rr_bearish_invalidation_pct"]');
    expect(bearishRow).toBeInTheDocument();
    expect(bearishRow?.children[1]?.textContent).toBe('3');

    const bearishInput = bearishRow?.querySelector('input') as HTMLInputElement;
    expect(bearishInput.value).toBe('3');
    expect(bearishInput.min).toBe('0.5');
    expect(bearishInput.max).toBe('100');
    expect(bearishInput.step).toBe('0.5');
  });

  it('accepts whole percent input (e.g. 4) and stores fraction (0.04) without clamping to 1.0', async () => {
    render(<Step3Page />);
    fireEvent.click(screen.getByText('Execution Parameters'));

    const bullishInput = document.querySelector('[data-param-key="rr_bullish_invalidation_pct"] input') as HTMLInputElement;

    // Type 4 intending 4% stop
    fireEvent.change(bullishInput, { target: { value: '4' } });
    fireEvent.blur(bullishInput);

    expect(useScanStore.getState().scanOverrides.rr_bullish_invalidation_pct).toBe(0.04);
    expect(bullishInput.value).toBe('4');
  });

  it('supports boundary values 0.5% (0.005) and 100% (1.0)', async () => {
    render(<Step3Page />);
    fireEvent.click(screen.getByText('Execution Parameters'));

    const bullishInput = document.querySelector('[data-param-key="rr_bullish_invalidation_pct"] input') as HTMLInputElement;

    // Minimum boundary: 0.5% -> 0.005
    fireEvent.change(bullishInput, { target: { value: '0.5' } });
    fireEvent.blur(bullishInput);
    expect(useScanStore.getState().scanOverrides.rr_bullish_invalidation_pct).toBe(0.005);
    expect(bullishInput.value).toBe('0.5');

    // Maximum boundary: 100% -> 1.0
    fireEvent.change(bullishInput, { target: { value: '100' } });
    fireEvent.blur(bullishInput);
    expect(useScanStore.getState().scanOverrides.rr_bullish_invalidation_pct).toBe(1.0);
    expect(bullishInput.value).toBe('100');
  });

  it('clamps out-of-bounds inputs on blur (150 -> 100/1.0, 0.1 -> 0.5/0.005)', async () => {
    render(<Step3Page />);
    fireEvent.click(screen.getByText('Execution Parameters'));

    const bullishInput = document.querySelector('[data-param-key="rr_bullish_invalidation_pct"] input') as HTMLInputElement;

    // Above maximum: 150% -> clamps to 100% (1.0)
    fireEvent.change(bullishInput, { target: { value: '150' } });
    fireEvent.blur(bullishInput);
    expect(useScanStore.getState().scanOverrides.rr_bullish_invalidation_pct).toBe(1.0);
    expect(bullishInput.value).toBe('100');

    // Below minimum: 0.1% -> clamps to 0.5% (0.005)
    fireEvent.change(bullishInput, { target: { value: '0.1' } });
    fireEvent.blur(bullishInput);
    expect(useScanStore.getState().scanOverrides.rr_bullish_invalidation_pct).toBe(0.005);
    expect(bullishInput.value).toBe('0.5');
  });

  it('restores default and clears override when typing default value (3) or clearing input', async () => {
    render(<Step3Page />);
    fireEvent.click(screen.getByText('Execution Parameters'));

    const bullishInput = document.querySelector('[data-param-key="rr_bullish_invalidation_pct"] input') as HTMLInputElement;

    // Set non-default
    fireEvent.change(bullishInput, { target: { value: '5' } });
    expect(useScanStore.getState().scanOverrides.rr_bullish_invalidation_pct).toBe(0.05);

    // Type default (3) -> should delete override
    fireEvent.change(bullishInput, { target: { value: '3' } });
    expect(useScanStore.getState().scanOverrides.rr_bullish_invalidation_pct).toBeUndefined();

    // Set non-default again and clear input
    fireEvent.change(bullishInput, { target: { value: '5' } });
    expect(useScanStore.getState().scanOverrides.rr_bullish_invalidation_pct).toBe(0.05);
    fireEvent.change(bullishInput, { target: { value: '' } });
    expect(useScanStore.getState().scanOverrides.rr_bullish_invalidation_pct).toBeUndefined();
  });

  it('displays existing stored fraction (e.g. 0.04 from profile) as whole percent (4)', async () => {
    act(() => {
      useScanStore.setState({
        scanOverrides: { rr_bullish_invalidation_pct: 0.04, rr_bearish_invalidation_pct: 0.025 },
      });
    });

    render(<Step3Page />);
    fireEvent.click(screen.getByText('Execution Parameters'));

    const bullishInput = document.querySelector('[data-param-key="rr_bullish_invalidation_pct"] input') as HTMLInputElement;
    expect(bullishInput.value).toBe('4');

    const bearishInput = document.querySelector('[data-param-key="rr_bearish_invalidation_pct"] input') as HTMLInputElement;
    expect(bearishInput.value).toBe('2.5');
  });

  it('propagates the stored fraction cleanly into stock scan, options scan, and recompute payloads', () => {
    const overrides = { rr_bullish_invalidation_pct: 0.04, rr_bearish_invalidation_pct: 0.05 };

    // Stock scan request resolution
    const stockReq = buildStockScanRequestBody({
      universe: ['AAPL'],
      direction: 'Bullish',
      horizon: 'Swing',
      strategy: 'pullback_ema',
      params: {} as never,
      paramsHorizon: null,
      requireReversal: false,
      scanOverrides: overrides,
      confidenceGate: DEFAULT_CONFIDENCE_GATE,
      accountSize: 100000,
      riskPct: 0.02,
      holdMinDays: 5,
      holdMaxDays: 20,
    });
    expect(stockReq.overrides?.rr_bullish_invalidation_pct).toBe(0.04);
    expect(stockReq.overrides?.rr_bearish_invalidation_pct).toBe(0.05);

    // Options scan request resolution
    const optReq = buildOptionsScanRequestBody({
      universe: ['AAPL'],
      direction: 'Bullish',
      horizon: 'Swing',
      horizonPreset: 'Swing',
      holdMinDays: 5,
      holdMaxDays: 20,
      minPriceRaw: '0',
      maxPriceRaw: '1000',
      minCapRaw: '0',
      maxCapRaw: '1000',
      capUnit: 'B',
      scanOverrides: overrides,
      confidenceGate: DEFAULT_CONFIDENCE_GATE,
      fundamentalsGate: DEFAULT_FUNDAMENTALS_GATE,
      shortlistMaxCandidates: 20,
      spreads: {} as never,
    });
    expect(optReq.overrides?.rr_bullish_invalidation_pct).toBe(0.04);
    expect(optReq.overrides?.rr_bearish_invalidation_pct).toBe(0.05);

    // Recompute plan extraction
    const rrOverrides = rrOverridesFrom(overrides);
    expect(rrOverrides.rr_bullish_invalidation_pct).toBe(0.04);
    expect(rrOverrides.rr_bearish_invalidation_pct).toBe(0.05);
  });
});
