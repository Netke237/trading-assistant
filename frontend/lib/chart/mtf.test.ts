import { buildMtfRow } from './mtf';

const up = Array.from({ length: 60 }, (_, i) => ({ time: i + 1, open: i, high: i + 1, low: i - 1, close: i + 0.5, volume: 1 }));

describe('buildMtfRow', () => {
  it('reports trendUp true for a rising series', () => {
    const row = buildMtfRow('1h', up, 14);
    expect(row.trendUp).toBe(true);
    expect(row.tf).toBe('1h');
    expect(typeof row.rsi).toBe('number');
  });
});
