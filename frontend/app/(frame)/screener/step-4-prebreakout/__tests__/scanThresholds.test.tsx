/**
 * STOCK-PRES-P5-PREBREAKOUT Task 2 — the thresholds the page prints are the
 * ones the backend applied to the rows in memory (plan round 1, F3).
 * Plan: docs/superpowers/plans/2026-10-11-stock-pres-p5-prebreakout-plan.md
 */
import {
  fmtThreshold,
  rememberPreBreakoutScan,
  preBreakoutScanParams,
  rememberFibScan,
  fibScanParams,
  __resetScanThresholdsForTests,
} from '../scanThresholds';
import { PREBREAKOUT_DEFAULTS } from '@/components/organisms/PreBreakoutParamsPanel';
import { FIB_PULLBACK_DEFAULTS } from '@/components/organisms/FibPullbackParamsPanel';

beforeEach(() => __resetScanThresholdsForTests());

describe('fmtThreshold', () => {
  it.each([
    [0.85, 2, '0.85'],
    [0.9, 2, '0.90'],
    [3, 1, '3.0'],
    [0.875, 2, '0.875'],
    [2.75, 1, '2.75'],
    [0.08 * 100, 1, '8.0'],
    [0.0725 * 100, 1, '7.25'],
    [0.015 * 100, 1, '1.5'],
    [0.12 * 100, 1, '12.0'],
    [0.15 * 100, 1, '15.0'],
    [20, 0, '20'],
  ])('fmtThreshold(%p, %p) = %p', (x, min, want) => {
    expect(fmtThreshold(x, min)).toBe(want);
  });

  it('is byte-identical to today\'s toFixed at the panels\' step values', () => {
    for (let i = 2; i <= 20; i++) {
      const v = i * 0.05; // ATR / volume ratio inputs step 0.05
      expect(fmtThreshold(v, 2)).toBe(v.toFixed(2));
    }
    for (let i = 2; i <= 40; i++) {
      const pct = (i * 0.5) / 100; // proximity input steps 0.5 %
      expect(fmtThreshold(pct * 100, 1)).toBe((pct * 100).toFixed(1));
    }
  });
});

describe('remembered scans', () => {
  it('start empty and reset to empty', () => {
    expect(preBreakoutScanParams()).toBeNull();
    expect(fibScanParams()).toBeNull();
    rememberPreBreakoutScan({ ...PREBREAKOUT_DEFAULTS });
    rememberFibScan({ ...FIB_PULLBACK_DEFAULTS });
    __resetScanThresholdsForTests();
    expect(preBreakoutScanParams()).toBeNull();
    expect(fibScanParams()).toBeNull();
  });

  it('Pre-Breakout: integer keys truncated as Python int() does, floats unchanged', () => {
    rememberPreBreakoutScan({
      atrCompressionRatio: 0.875,
      atrAvgLookback: 30.9,
      rangeAtrMult: 2.75,
      rangeLookbackBars: 10.5,
      volCompressionRatio: 0.9,
      resistanceProximityPct: 0.0725,
      swingLookback: 50.9,
    });
    expect(preBreakoutScanParams()).toEqual({
      atrCompressionRatio: 0.875,
      atrAvgLookback: 30,
      rangeAtrMult: 2.75,
      rangeLookbackBars: 10,
      volCompressionRatio: 0.9,
      resistanceProximityPct: 0.0725,
      swingLookback: 50,
    });
    rememberPreBreakoutScan({ ...PREBREAKOUT_DEFAULTS, rangeLookbackBars: 10.9 });
    expect(preBreakoutScanParams()!.rangeLookbackBars).toBe(10);
  });

  it('Fib: swing lookback truncated, levels and tolerance unchanged, stored as a copy', () => {
    const levels = [50];
    rememberFibScan({ fibSwingLookback: 100.7, fibLevels: levels, fibTolerancePct: 0.0125, emaFilterPeriod: 20 });
    levels.push(61.8);
    expect(fibScanParams()).toEqual({
      fibSwingLookback: 100, fibLevels: [50], fibTolerancePct: 0.0125, emaFilterPeriod: 20,
    });
  });
});
