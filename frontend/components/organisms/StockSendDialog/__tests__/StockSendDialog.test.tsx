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
    deletePortfolioPosition: jest.fn().mockResolvedValue(undefined),
    getBrokerStatus: jest.fn().mockResolvedValue({ alpaca_paper: { configured: false } }),
  },
}));

/** STOCK-SENDS-SAVE-FIRST-THEN-REAL-SHARES: an auto-send now SAVES first, and
 *  the 201 must carry a positive `entryPrice`. This mock echoes the POST body
 *  back, as the router does; every other request answers `[]`. */
function echoFetch(): typeof fetch {
  return jest.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === 'POST' && String(url).endsWith('/api/portfolio')) {
      const body = JSON.parse(String(init.body));
      return { ok: true, status: 201, json: async () => body } as Response;
    }
    return { ok: true, status: 200, json: async () => [] } as unknown as Response;
  }) as unknown as typeof fetch;
}

/** A broker failure that PROVABLY happened before the order was submitted, so
 *  the saved row is deleted and the symbol stays retryable. (A plain Error is
 *  "status unknown" under save-first and is deliberately NOT retryable.) */
const PRE_SUBMIT = () => new Error('API /broker/stock-order → 503: Broker credentials unavailable: broker rejected');

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
  const suiteFetch = global.fetch;

  afterEach(() => {
    usePortfolioStore.setState({ addPosition: realAddPosition });
    global.fetch = suiteFetch;
  });

  beforeEach(() => {
    jest.clearAllMocks();
    global.fetch = echoFetch();
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
      if (symbol === 'MSFT') return Promise.reject(PRE_SUBMIT());
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
    // backend is unreachable). MSFT stays Auto-send. UPDATED for save-first:
    // with the backend unreachable MSFT's SAVE is unconfirmed, so NO order is
    // sent and MSFT lands in the retryable error set (it used to reach the
    // broker and fail there). Regression kept: a queued row must never disable
    // retrying a different row's real error.
    global.fetch = jest.fn().mockRejectedValue(new Error('offline')) as unknown as typeof fetch;

    const cards = [makeCard('AAPL'), makeCard('MSFT')];
    const onSubmit = jest.fn();

    render(<StockSendDialog cards={cards} onClose={jest.fn()} onSubmit={onSubmit} />);

    fireEvent.click(screen.getByText('IBKR Paper'));
    fireEvent.click(screen.getByLabelText('Auto-send AAPL')); // AAPL -> Manual

    const submitBtn = screen.getByRole('button', { name: /submit 2 orders/i });
    await act(async () => {
      fireEvent.click(submitBtn);
    });

    expect(onSubmit).not.toHaveBeenCalled();
    expect(await screen.findByText(/queued — backend unreachable, will sync/i)).toBeInTheDocument();
    expect(screen.getByText(/could not be confirmed, so NO order was sent/i)).toBeInTheDocument();
    expect(api.postStockOrder).not.toHaveBeenCalled();

    // MSFT's error must still be retryable — the button must not be stuck
    // disabled just because AAPL is queued.
    const retryBtn = screen.getByRole('button', { name: /retry 1 failed order/i });
    expect(retryBtn).not.toBeDisabled();

    global.fetch = echoFetch();
    (api.postStockOrder as jest.Mock).mockResolvedValue({ order_id: 'retry-1' });
    await act(async () => {
      fireEvent.click(retryBtn);
    });

    // Only MSFT (the errored symbol) gets retried — AAPL's already-queued
    // attempt must not be resubmitted (would mint a fresh recId and double it).
    await waitFor(() => expect(api.postStockOrder).toHaveBeenCalledTimes(1));
    const retrySymbols = (api.postStockOrder as jest.Mock).mock.calls
      .map(([arg]: [{ symbol: string }]) => arg.symbol);
    expect(retrySymbols).toEqual(['MSFT']);

    // Regression (round 5): MSFT's retry succeeding must NOT make the dialog
    // report the full basket as placed — AAPL is still only queued.
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText(/queued — backend unreachable, will sync/i)).toBeInTheDocument();
    expect(screen.queryByText(/could not be confirmed, so NO order was sent/i)).not.toBeInTheDocument();
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

  it('does NOT re-submit the broker order on retry when the order MAY be live (status unknown)', async () => {
    // UPDATED for save-first: the old "order succeeded but local tracking
    // failed" case cannot happen any more (the row is saved first). Its
    // save-first equivalent is an order whose fate is unknown: the row is
    // kept, an ORDER-UNKNOWN note is pushed, and the symbol goes to `warn`,
    // never to the retry set — a retry could double-place a live order.
    (api.postStockOrder as jest.Mock).mockRejectedValueOnce(new TypeError('Failed to fetch'));
    const addPosition = jest.fn().mockResolvedValue({ ok: true, status: 'ok' as const });
    usePortfolioStore.setState({ addPosition } as any);

    render(<StockSendDialog cards={[makeCard('AAPL')]} onClose={jest.fn()} onSubmit={jest.fn()} />);
    fireEvent.click(screen.getByText('IBKR Paper'));
    fireEvent.click(screen.getByText(/Submit 1 order/));
    await waitFor(() => expect(api.postStockOrder).toHaveBeenCalledTimes(1));

    const btn = await screen.findByRole('button', { name: /Placed — close to continue/ });
    expect(btn).toBeDisabled();
    expect(api.postStockOrder).toHaveBeenCalledTimes(1);
    // Visible, and the row is kept (the order may exist at the broker).
    expect(await screen.findByText(/Order status UNKNOWN/)).toBeInTheDocument();
    expect(addPosition).toHaveBeenCalledTimes(1);
    expect(api.deletePortfolioPosition).not.toHaveBeenCalled();
  });

  // MANUAL-IBKR-CONFIRM-AS-ERROR (2026-09-25): IBKR's confirmation question is
  // now a 502 (it used to be an empty-id 200, which this dialog turned into a
  // Portfolio position). Both rows are Auto-send, so AAPL's position proves
  // the success path still runs beside the refused row.
  it('an IBKR confirmation question (502) on one auto-send row shows its error and creates no position for it', async () => {
    const addPosition = jest.fn().mockResolvedValue({ ok: true, status: 'ok' as const });
    usePortfolioStore.setState({ addPosition });
    (api.postStockOrder as jest.Mock).mockImplementation(({ symbol }: { symbol: string }) => {
      if (symbol === 'MSFT') {
        return Promise.reject(new Error(
          'API /broker/stock-order → 502: IBKR did not place the order: it asked for a ' +
          'confirmation this app does not send. IBKR said: Are you sure you want to submit this order?',
        ));
      }
      return Promise.resolve({ order_id: `${symbol}-1` });
    });
    const onSubmit = jest.fn();

    render(<StockSendDialog cards={[makeCard('AAPL'), makeCard('MSFT')]} onClose={jest.fn()} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByText('IBKR Paper'));
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /submit 2 orders/i }));
    });

    expect(await screen.findByText(/IBKR said: Are you sure/)).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
    const savedSymbols = addPosition.mock.calls.map(([p]: [{ symbol: string }]) => p.symbol);
    expect(savedSymbols).toEqual(['AAPL']);
    // Nothing was placed for MSFT, so it stays retryable.
    expect(screen.getByRole('button', { name: /retry 1 failed order/i })).not.toBeDisabled();
  });
});
