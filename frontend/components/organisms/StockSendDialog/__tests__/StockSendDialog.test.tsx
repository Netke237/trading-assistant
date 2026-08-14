import '@testing-library/jest-dom';
import { render, screen, act, fireEvent, waitFor } from '@testing-library/react';
import { StockSendDialog } from '@/components/organisms/StockSendDialog';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { api } from '@/lib/api';
import type { PositionCardData } from '@/types/stockDomain';

jest.mock('@/lib/api', () => ({
  api: {
    postStockOrder: jest.fn(),
    getBrokerStatus: jest.fn().mockResolvedValue({ alpaca_paper: { configured: false } }),
  },
}));

function makeCard(symbol: string): PositionCardData {
  return {
    symbol,
    company: symbol,
    price: 100,
    direction: 'Bullish',
    strategy: {
      strategy: 'pullback_ema', entry_price: 100, stop_price: 95,
      target_price: 110, rr_ratio: 2.0, atr: 2.0, detail: {},
    },
    backtest: {
      n_trades: 20, win_rate: 0.6, total_return_pct: 10, max_drawdown_pct: -5,
      expectancy: 0.5, sharpe: 1.2, confidence: 70, passes_gate: true, summary_text: '',
    },
    stock_score: 80,
    stock_status: 'PASS',
    shares: 10,
    dollar_risk: 50,
    dollar_size: 1000,
    confidence: 70,
    confidence_text: null,
  };
}

describe('StockSendDialog — partial basket failure retry', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    act(() => {
      usePortfolioStore.setState({ positions: [] });
      useSettingsStore.setState((s) => ({
        ibkrPaper: { baseUrl: 'https://localhost:7499/v1/api', accountId: 'ACC' },
      }));
    });
  });

  it('only resubmits symbols that failed on the previous attempt', async () => {
    const cards = [makeCard('AAPL'), makeCard('MSFT'), makeCard('NVDA')];
    const onSubmit = jest.fn();

    (api.postStockOrder as jest.Mock).mockImplementation(({ symbol }: { symbol: string }) => {
      if (symbol === 'MSFT') return Promise.reject(new Error('broker rejected'));
      return Promise.resolve({ order_id: `${symbol}-1` });
    });

    render(<StockSendDialog cards={cards} onClose={jest.fn()} onSubmit={onSubmit} />);

    fireEvent.click(screen.getByText('IBKR Paper'));

    const submitBtn = screen.getByRole('button', { name: /submit 3 orders/i });
    await act(async () => {
      fireEvent.click(submitBtn);
      await waitFor(() => expect(api.postStockOrder).toHaveBeenCalledTimes(3));
    });

    // MSFT failed — dialog stays open, error shown, onSubmit not called yet.
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText(/broker rejected/i)).toBeInTheDocument();

    // Make MSFT succeed on retry.
    (api.postStockOrder as jest.Mock).mockImplementation(() => Promise.resolve({ order_id: 'retry-1' }));

    const retryBtn = screen.getByRole('button', { name: /retry 1 failed order/i });
    await act(async () => {
      fireEvent.click(retryBtn);
      await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    });

    // Only MSFT should have been retried — AAPL/NVDA must NOT be resubmitted.
    expect(api.postStockOrder).toHaveBeenCalledTimes(4); // 3 initial + 1 retry
    const retryCallSymbols = (api.postStockOrder as jest.Mock).mock.calls
      .slice(3)
      .map(([arg]: [{ symbol: string }]) => arg.symbol);
    expect(retryCallSymbols).toEqual(['MSFT']);

    // Final onSubmit still reports the full 3-symbol basket to the caller.
    expect(onSubmit.mock.calls[0][0]).toHaveLength(3);
  });

  it('does not permanently disable Submit when one row is queued and another hard-failed', async () => {
    // AAPL stays Manual (routes through addPosition -> queued when the
    // backend is unreachable). MSFT stays Auto-send (routes through
    // postStockOrder -> hard error). Regression for a bug where any queued
    // row disabled the Submit button unconditionally, forever, even when a
    // different row had a real error the user should be able to retry.
    const originalFetch = global.fetch;
    global.fetch = jest.fn().mockRejectedValue(new Error('offline')) as unknown as typeof fetch;
    (api.postStockOrder as jest.Mock).mockRejectedValue(new Error('broker rejected'));

    const cards = [makeCard('AAPL'), makeCard('MSFT')];
    const onSubmit = jest.fn();

    render(<StockSendDialog cards={cards} onClose={jest.fn()} onSubmit={onSubmit} />);

    fireEvent.click(screen.getByText('IBKR Paper'));
    fireEvent.click(screen.getByLabelText('Auto-send AAPL')); // AAPL -> Manual

    const submitBtn = screen.getByRole('button', { name: /submit 2 orders/i });
    await act(async () => {
      fireEvent.click(submitBtn);
      await waitFor(() => expect(api.postStockOrder).toHaveBeenCalledTimes(1));
    });

    expect(onSubmit).not.toHaveBeenCalled();
    expect(await screen.findByText(/queued — backend unreachable, will sync/i)).toBeInTheDocument();
    expect(screen.getByText(/broker rejected/i)).toBeInTheDocument();

    // MSFT's error must still be retryable — the button must not be stuck
    // disabled just because AAPL is queued.
    const retryBtn = screen.getByRole('button', { name: /retry 1 failed order/i });
    expect(retryBtn).not.toBeDisabled();

    (api.postStockOrder as jest.Mock).mockResolvedValue({ order_id: 'retry-1' });
    await act(async () => {
      fireEvent.click(retryBtn);
    });

    // Only MSFT (the errored symbol) gets retried — AAPL's already-queued
    // attempt must not be resubmitted (would mint a fresh recId and double it).
    expect(api.postStockOrder).toHaveBeenCalledTimes(2);
    const retrySymbols = (api.postStockOrder as jest.Mock).mock.calls
      .slice(1)
      .map(([arg]: [{ symbol: string }]) => arg.symbol);
    expect(retrySymbols).toEqual(['MSFT']);

    global.fetch = originalFetch;
  });
});
