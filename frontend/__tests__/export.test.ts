import { exportToXlsx, exportValidationToXlsx } from '@/lib/export';
import type { WatchlistRow } from '@/types/domain';

const mockWriteFile = jest.fn();
jest.mock('xlsx', () => ({
  utils: {
    json_to_sheet: jest.fn(() => ({})),
    book_new: jest.fn(() => ({})),
    book_append_sheet: jest.fn(),
  },
  writeFile: (...args: unknown[]) => mockWriteFile(...args),
}));

const makeRow = (i: number): WatchlistRow => ({
  symbol: `SYM${i}`, company: `Company ${i}`, price: 100 + i,
  direction: 'Bullish', horizon: 'Swing', score: 70 + i, rankDelta: 0,
  scoreDelta: 1, status: 'PASS',
  breakdown: { trend: 80, pullback: 70, trigger: 75, event: 65, volatility: 72 },
});

describe('exportToXlsx', () => {
  it('does not throw when called with 10 rows', () => {
    const rows = Array.from({ length: 10 }, (_, i) => makeRow(i));
    expect(() => exportToXlsx(rows, 'test-export')).not.toThrow();
  });

  it('appends .xlsx extension if missing', () => {
    exportToXlsx([makeRow(0)], 'no-ext');
    expect(mockWriteFile).toHaveBeenCalledWith(expect.any(Object), 'no-ext.xlsx');
  });
});

describe('exportValidationToXlsx', () => {
  it('exports validation data with all 5 rule scores per candidate', () => {
    const candidates = [
      {
        symbol: 'AAPL', company: 'Apple Inc.', price: 185, direction: 'Bullish' as const,
        status: 'PASS' as const, stockScore: 82, stockConfidence: 'PASS' as const,
        stockBreakdown: { trend: 85, pullback: 62, trigger: 78, event: 90, volatility: 45 },
        contract: '', contractScore: 0, contractConfidence: 'PENDING' as const,
        contractBreakdown: { dteFit: 0, delta: 0, ivAttractiveness: 0, liquidity: 0, spread: 0 },
        entry: { limit: 0, maxFill: 0, orderType: 'Limit' as const },
        exit: { invalidation: 0, premiumStop: 0, timeStopDays: 0, target: 0, targets: [] },
        rrRatio: 0, rrModel: 'Heston repriced' as const, finalStatus: 'PASS' as const,
      },
    ];
    expect(() => exportValidationToXlsx(candidates, 'validation')).not.toThrow();
  });

  it('appends .xlsx extension if missing', () => {
    exportValidationToXlsx([], 'val-export');
    expect(mockWriteFile).toHaveBeenCalledWith(expect.any(Object), 'val-export.xlsx');
  });

  it('handles empty candidate list', () => {
    expect(() => exportValidationToXlsx([], 'empty')).not.toThrow();
  });
});
