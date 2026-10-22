// STOCKS-HORIZON-T1 H7: a strategy watch's add request carries params_horizon.
import { api } from '@/lib/api';

function mockFetchOk(body: unknown) {
  const fn = jest.fn().mockResolvedValue({
    ok: true, status: 201, json: async () => body, text: async () => JSON.stringify(body),
  });
  global.fetch = fn as unknown as typeof fetch;
  return fn;
}

function sentBody(fn: jest.Mock): Record<string, unknown> {
  return JSON.parse(fn.mock.calls[0][1].body as string);
}

describe('strategy watch add requests carry params_horizon', () => {
  it('addStrategyWatch sends the tuned horizon', async () => {
    const fn = mockFetchOk({});
    await api.addStrategyWatch('AAPL', 'pullback_ema', 'Bullish', 'Quarterly');
    expect(fn.mock.calls[0][0]).toMatch(/\/api\/strategy-watch\/$/);
    expect(sentBody(fn)).toEqual({
      symbol: 'AAPL', strategy_key: 'pullback_ema', direction: 'Bullish', params_horizon: 'Quarterly',
    });
  });

  it('addStrategyWatch sends params_horizon null when none is given', async () => {
    const fn = mockFetchOk({});
    await api.addStrategyWatch('AAPL', 'pullback_ema');
    expect(sentBody(fn).params_horizon).toBeNull();
  });

  it('addStrategyWatchesBulk sends the tuned horizon', async () => {
    const fn = mockFetchOk({ added: 0, watches: [] });
    await api.addStrategyWatchesBulk(['AAPL', 'MSFT'], 'breakout_base', 'Bearish', 'Annual');
    expect(fn.mock.calls[0][0]).toMatch(/\/api\/strategy-watch\/bulk$/);
    expect(sentBody(fn)).toEqual({
      symbols: ['AAPL', 'MSFT'], strategy_key: 'breakout_base', direction: 'Bearish', params_horizon: 'Annual',
    });
  });
});
