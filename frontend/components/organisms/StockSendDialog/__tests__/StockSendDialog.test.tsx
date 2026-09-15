import '@testing-library/jest-dom';
import { render, screen, act, fireEvent, waitFor } from '@testing-library/react';
import { StockSendDialog } from '@/components/organisms/StockSendDialog';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useScanStore } from '@/lib/scanStore';
import { api } from '@/lib/api';
import type { PositionCardData } from '@/types/stockDomain';
import type { MethodPick } from '@/types/domain';

// Phase G piece 5, build step 4 (§7.2, S4) — this suite is about basket
// send/retry mechanics, not the method-pick gate, so every fixture stamps a
// satisfied pick for every symbol used across these tests or the new
// `hasMissingMethodPick` check leaves Submit disabled regardless of what
// these tests exercise (see StockSendDialog.methodPickGate.test.tsx for the
// gate's own tests).
const pick = (): MethodPick => ({
  method: 'monte_carlo',
  rowStockPrice: 197.5,
  rowOptionPrice: 6.24,
  stopBasis: 'stock',
  pickedAt: '2026-09-14T10:00:00.000Z',
});

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
  const realAddPosition = usePortfolioStore.getState().addPosition;

  afterEach(() => {
    usePortfolioStore.setState({ addPosition: realAddPosition });
  });

  beforeEach(() => {
    jest.clearAllMocks();
    act(() => {
      usePortfolioStore.setState({ positions: [] });
      useSettingsStore.setState((s) => ({
        ibkrPaper: { baseUrl: 'https://localhost:7499/v1/api', accountId: 'ACC' },
      }));
      useScanStore.setState({
        stockScanResult: { scan_id: 'stk-1', timestamp: '2026-09-14T09:00:00Z' } as any,
        stocksCardEdits: {
          scanId: 'stk-1', picks: { AAPL: pick(), MSFT: pick(), NVDA: pick() },
          invalidation: {}, premiumStop: {}, entryLimit: {}, maxLossOverride: {},
        },
      });
    });
  });

  it('only resubmits symbols that failed on the previous attempt', async () => {
    usePortfolioStore.setState({ addPosition: jest.fn().mockResolvedValue({ ok: true, status: 'ok' as const }) });
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

    // Regression (round 5): MSFT's retry succeeding must NOT make the dialog
    // report the full basket as placed — AAPL is still only queued, never
    // actually confirmed, since it was correctly never resubmitted. A bug in
    // an earlier fix cleared the queued-state tracking on every retry pass
    // (even for symbols the pass didn't touch), so a successful MSFT retry
    // made the "stay open on any unconfirmed row" gate see nothing
    // unconfirmed and fire onSubmit for the whole basket, AAPL included.
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText(/queued — backend unreachable, will sync/i)).toBeInTheDocument();
    expect(screen.queryByText(/broker rejected/i)).not.toBeInTheDocument();

    global.fetch = originalFetch;
  });

  it('creates a local position with a snapshot after a successful auto-send broker order', async () => {
    (api.postStockOrder as jest.Mock).mockResolvedValueOnce({ order_id: 'ORD-1', status: 'filled', broker: 'ibkr_paper' });
    const addPosition = jest.fn().mockResolvedValue({ status: 'ok' });
    usePortfolioStore.setState({ addPosition } as any);

    render(<StockSendDialog cards={[makeCard('AAPL')]} onClose={jest.fn()} onSubmit={jest.fn()} />);
    fireEvent.click(screen.getByText('IBKR Paper'));
    fireEvent.click(screen.getByText(/Submit 1 order/));

    await waitFor(() => expect(addPosition).toHaveBeenCalled());
    const created = addPosition.mock.calls[0][0];
    expect(created.source).toBe('broker');
    expect(created.tradeCardSnapshot).toBeDefined();
    expect(created.tradeCardSnapshot.strategy.strategy).toBe('pullback_ema');
    expect(created.stop).toBe(95);
  });

  it('does NOT re-submit the broker order on retry when the order succeeded but local tracking failed', async () => {
    (api.postStockOrder as jest.Mock).mockResolvedValueOnce({ order_id: 'ORD-2', status: 'filled', broker: 'ibkr_paper' });
    const addPosition = jest.fn().mockResolvedValueOnce({ status: 'rejected', detail: 'exposure limit' });
    usePortfolioStore.setState({ addPosition } as any);

    render(<StockSendDialog cards={[makeCard('AAPL')]} onClose={jest.fn()} onSubmit={jest.fn()} />);
    fireEvent.click(screen.getByText('IBKR Paper'));
    fireEvent.click(screen.getByText(/Submit 1 order/));
    await waitFor(() => expect(api.postStockOrder).toHaveBeenCalledTimes(1));

    // A local-tracking failure must not put the symbol back in the retryable
    // error set — `errors`/`queued` are both still empty, only `warnings` is
    // set. The button reflects this: it relabels to "Placed — close to
    // continue" and becomes disabled (the same treatment `hasQueued` already
    // gets), so there is nothing left to click that could re-fire the broker
    // order — a stronger guarantee than relying solely on the retry-target
    // filter (`errors`-only) to make a stray click safe.
    const btn = await screen.findByRole('button', { name: /Placed — close to continue/ });
    expect(btn).toBeDisabled();
    expect(api.postStockOrder).toHaveBeenCalledTimes(1);

    // The failure must still be VISIBLE — silently swallowing it (computing
    // `warn` and never rendering it) would mean a real broker order succeeds
    // with zero local record and zero indication anything needs attention.
    expect(await screen.findByText(/not yet tracked in Portfolio/)).toBeInTheDocument();
  });
});
