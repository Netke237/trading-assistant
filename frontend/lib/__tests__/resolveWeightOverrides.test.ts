import { buildStockScanRequestBody, normalizeWeightOverride } from '@/lib/resolveStockScanRequest';
import { buildOptionsScanRequestBody } from '@/lib/resolveOptionsScanRequest';
import { resolveProfileToScanRequest } from '@/lib/scanScheduleResolve';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { DEFAULT_CONFIDENCE_GATE, DEFAULT_FUNDAMENTALS_GATE, DEFAULT_SPREADS } from '@/lib/settingsStore';
import type { SearchProfile } from '@/types/searchProfile';

describe('normalizeWeightOverride helper', () => {
  it('converts whole percentage numbers to canonical decimal fractions', () => {
    expect(normalizeWeightOverride(0)).toBe(0);
    expect(normalizeWeightOverride(1)).toBe(0.01);
    expect(normalizeWeightOverride(40)).toBe(0.40);
    expect(normalizeWeightOverride(100)).toBe(1.0);
  });

  it('clamps negative values to 0', () => {
    expect(normalizeWeightOverride(-5)).toBe(0);
  });

  it('passes non-numbers through unchanged', () => {
    expect(normalizeWeightOverride('auto')).toBe('auto');
    expect(normalizeWeightOverride(true)).toBe(true);
  });
});

describe('buildStockScanRequestBody weight override normalization', () => {
  function makeStockReq(overrides: Record<string, number | boolean | string>) {
    return buildStockScanRequestBody({
      universe: ['SP500'],
      direction: 'Bullish',
      horizon: 'Swing',
      strategy: 'pullback_ema',
      params: useScanParamsStore.getState(),
      requireReversal: false,
      scanOverrides: overrides,
      confidenceGate: DEFAULT_CONFIDENCE_GATE,
      accountSize: 50_000,
      riskPct: 0.01,
      holdMinDays: 5,
      holdMaxDays: 15,
      paramsHorizon: null,
    });
  }

  it('normalizes all 5 score weight controls from Step 3 percentages to fractions', () => {
    const req = makeStockReq({
      weight_trend: 40,
      weight_pullback: 20,
      weight_trigger: 15,
      weight_event: 1,
      weight_vol: 100,
      fast_ema: 12,
    });

    expect(req.overrides?.weight_trend).toBe(0.40);
    expect(req.overrides?.weight_pullback).toBe(0.20);
    expect(req.overrides?.weight_trigger).toBe(0.15);
    expect(req.overrides?.weight_event).toBe(0.01);
    expect(req.overrides?.weight_vol).toBe(1.0);
    expect(req.overrides?.fast_ema).toBe(12);
  });
});

describe('buildOptionsScanRequestBody weight override normalization', () => {
  function makeOptionsReq(overrides: Record<string, number | boolean | string>) {
    return buildOptionsScanRequestBody({
      universe: ['SP500'],
      direction: 'Bullish',
      horizon: 'Swing',
      horizonPreset: 'Swing',
      holdMinDays: 5,
      holdMaxDays: 15,
      minPriceRaw: '',
      maxPriceRaw: '',
      minCapRaw: '',
      maxCapRaw: '',
      capUnit: 'B',
      scanOverrides: overrides,
      confidenceGate: DEFAULT_CONFIDENCE_GATE,
      fundamentalsGate: DEFAULT_FUNDAMENTALS_GATE,
      shortlistMaxCandidates: 10,
      spreads: DEFAULT_SPREADS,
    });
  }

  it('normalizes score weight controls to decimal fractions and preserves non-weights', () => {
    const req = makeOptionsReq({
      weight_trend: 1,
      weight_pullback: 40,
      weight_vol: 100,
      iv_abs_pass_max: 45,
    });

    expect(req.overrides.weight_trend).toBe(0.01);
    expect(req.overrides.weight_pullback).toBe(0.40);
    expect(req.overrides.weight_vol).toBe(1.0);
    expect(req.overrides.iv_abs_pass_max).toBe(45);
  });
});

describe('scanScheduleResolve scheduled request normalization', () => {
  it('resolves options scan schedule with normalized weight overrides', () => {
    const profile: SearchProfile = {
      id: 'prof-opt',
      name: 'Options Profile',
      mode: 'options',
      createdAt: '2026-01-01T00:00:00.000Z',
      updatedAt: '2026-01-01T00:00:00.000Z',
      direction: 'Bullish',
      horizonPreset: 'Swing',
      holdMin: 5,
      holdMax: 15,
      universe: {
        pick: 'SP500',
        customRaw: '',
        minPriceRaw: '',
        maxPriceRaw: '',
        minCapRaw: '',
        maxCapRaw: '',
        capUnit: 'B',
      },
      scanSettings: {
        confidenceGate: DEFAULT_CONFIDENCE_GATE,
        fundamentalsGate: DEFAULT_FUNDAMENTALS_GATE,
        spreads: DEFAULT_SPREADS,
        shortlistMaxCandidates: 10,
      },
      scanOverrides: {
        weight_trend: 40,
        weight_event: 1,
      },
    };

    const resolved = resolveProfileToScanRequest(profile);
    expect((resolved as { overrides: Record<string, unknown> }).overrides.weight_trend).toBe(0.40);
    expect((resolved as { overrides: Record<string, unknown> }).overrides.weight_event).toBe(0.01);
  });
});
