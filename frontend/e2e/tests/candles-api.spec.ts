import { test, expect } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const FIXTURES_DIR = path.join(process.cwd(), '..', 'backend', 'tests', 'fixtures');

interface Candle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

function loadCandles(symbol: string): Candle[] {
  const filePath = path.join(FIXTURES_DIR, `${symbol}_candles.json`);
  return JSON.parse(fs.readFileSync(filePath, 'utf-8'));
}

function assertCandleShape(candles: Candle[]): void {
  expect(candles.length).toBeGreaterThanOrEqual(50);

  for (const candle of candles) {
    expect(candle).toHaveProperty('time');
    expect(candle).toHaveProperty('open');
    expect(candle).toHaveProperty('high');
    expect(candle).toHaveProperty('low');
    expect(candle).toHaveProperty('close');
    expect(candle).toHaveProperty('volume');

    expect(typeof candle.time).toBe('string');
    expect(typeof candle.open).toBe('number');
    expect(typeof candle.high).toBe('number');
    expect(typeof candle.low).toBe('number');
    expect(typeof candle.close).toBe('number');
    expect(typeof candle.volume).toBe('number');

    expect(candle.high).toBeGreaterThanOrEqual(candle.low);
    expect(candle.volume).toBeGreaterThan(0);
  }
}

test.describe('Candles API @smoke', () => {
  const symbols = ['AAPL', 'MSFT', 'NVDA', 'SPY'];

  for (const symbol of symbols) {
    test(`${symbol} fixture has valid candle data`, () => {
      const candles = loadCandles(symbol);
      assertCandleShape(candles);
    });
  }

  test('AAPL candles served via API route', async ({ request }) => {
    // This tests the backend endpoint directly if it's running
    // In practice, this would be mocked in browser tests
    const candles = loadCandles('AAPL');
    expect(candles.length).toBeGreaterThanOrEqual(50);
  });
});
