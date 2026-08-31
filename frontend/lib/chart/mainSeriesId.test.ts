import { mainSeriesId, isMainSeriesId } from './mainSeriesId';

describe('mainSeriesId / isMainSeriesId', () => {
  it('builds an id per chartType and isMainSeriesId recognizes it', () => {
    expect(mainSeriesId('candle')).toBe('candles-candle');
    expect(mainSeriesId('bar')).toBe('candles-bar');
    expect(mainSeriesId('line')).toBe('candles-line');
    expect(isMainSeriesId(mainSeriesId('candle'))).toBe(true);
    expect(isMainSeriesId(mainSeriesId('bar'))).toBe(true);
    expect(isMainSeriesId(mainSeriesId('line'))).toBe(true);
  });

  it('rejects indicator-shaped ids, including ones that only contain the prefix, not start with it', () => {
    expect(isMainSeriesId('ema-20')).toBe(false);
    expect(isMainSeriesId('ema-1735689600000')).toBe(false);
    expect(isMainSeriesId('vprofile-1735689600000-upper')).toBe(false);
    expect(isMainSeriesId('ema-candles-fake')).toBe(false);
    expect(isMainSeriesId('')).toBe(false);
  });
});
