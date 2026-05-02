import { exportToXlsx } from '@/lib/export';
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
