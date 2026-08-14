import { migrateScanParams, SCAN_PARAM_DEFAULTS } from '@/lib/scanParamsStore';

describe('scanParamsStore — migrate is cumulative (H7)', () => {
  it('migrating from v2 includes every field added through v11', () => {
    const result = migrateScanParams({}, 2);
    expect(result.pullbackMaType).toBe('EMA');
    expect(result.eventFilter).toBe('include');
    expect(result.stockShortlistMax).toBe(10);
    expect(result.requireChoppyRegime).toBe(false);
    expect(result.meanReversionVariants).toEqual(['mean_reversion_rsi', 'mean_reversion_bb', 'mean_reversion_vwap_daily']);
    expect(result.vwapLookback).toBe(20);
    expect(result.vwapDeviationPct).toBe(0.02);
  });

  it('migrating from v2 leaves btMinWinRate at the current default (never entered the v7/v8 bug window)', () => {
    const result = migrateScanParams({}, 2);
    expect(result.btMinWinRate).toBe(SCAN_PARAM_DEFAULTS.btMinWinRate);
  });

  it('forces btMinWinRate to 0.30 when migrating from exactly v7 (matches the original early-return behavior for a single v7->v11 hop)', () => {
    const result = migrateScanParams({}, 7);
    expect(result.btMinWinRate).toBe(0.30);
  });

  it('corrects a persisted 0.30 to 0.45 when migrating from exactly v8', () => {
    const result = migrateScanParams({ btMinWinRate: 0.30 }, 8);
    expect(result.btMinWinRate).toBe(0.45);
  });

  it('does not touch a genuinely-set btMinWinRate of 0.30 when migrating from v9+', () => {
    const result = migrateScanParams({ btMinWinRate: 0.30 }, 9);
    expect(result.btMinWinRate).toBe(0.30);
  });

  it('preserves an explicit persisted value alongside newly-added fields', () => {
    const result = migrateScanParams({ rsiOversold: 25 }, 3);
    expect(result.rsiOversold).toBe(25);
    expect(result.pullbackMaType).toBe('EMA'); // still added
  });

  it('migrating from the current version (11) is a no-op passthrough plus defaults merge', () => {
    const result = migrateScanParams({ rsiPeriod: 21 }, 11);
    expect(result.rsiPeriod).toBe(21);
    expect(result.btMinWinRate).toBe(SCAN_PARAM_DEFAULTS.btMinWinRate);
  });
});
