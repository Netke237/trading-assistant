import { migrateChartStore } from '@/lib/chartStore';

describe('chartStore — migrate (T4)', () => {
  it('v0 -> v1 defaults symbolName to symbol and fills all fields', () => {
    const result = migrateChartStore({ symbol: 'TSLA' }, 0);
    expect(result.symbolName).toBe('TSLA');
    expect(result.interval).toBe('1D');
    expect(result.chartType).toBe('candle');
    expect(result.activeIndicators.length).toBeGreaterThan(0);
  });

  it('v1 -> v2 fills symbolName only if missing, preserving an explicit one', () => {
    const result = migrateChartStore({ symbol: 'TSLA', symbolName: 'Tesla Inc' }, 1);
    expect(result.symbolName).toBe('Tesla Inc');
  });

  it('v1 -> v2 backfills symbolName from symbol when absent', () => {
    const result = migrateChartStore({ symbol: 'TSLA' }, 1);
    expect(result.symbolName).toBe('TSLA');
  });

  it('v2 -> v2 is a passthrough', () => {
    const state = { symbol: 'MSFT', symbolName: 'Microsoft' };
    expect(migrateChartStore(state, 2)).toEqual(state);
  });
});
