import type { ReactElement } from 'react';
import { stockExecutionIdentity, useStockOrderOwnershipStore as ownershipStore } from '@/lib/stockExecutionSession';
import { useStockOrderOwnershipStore } from '@/lib/stockExecutionSession';
import '@testing-library/jest-dom';
import { render, screen, act, fireEvent, waitFor } from '@testing-library/react';
import { StockSendDialog } from '@/components/organisms/StockSendDialog';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useScanStore } from '@/lib/scanStore';
import { api } from '@/lib/api';
import { useDirectSendNotesStore } from '@/lib/directSendNotesStore';
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

/** STOCK-SENDS: the save POST answers per symbol -- `refuse` symbols get a
 *  422, `offline` symbols a network error, the rest echo their body (a real
 *  201 carries `entryPrice`), with `adjustedQty` when `resize` names them. */
function saveFetch(opts: { refuse?: string[]; offline?: string[]; resize?: Record<string, number> } = {}): typeof fetch {
  return jest.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    if (String(url).endsWith('/api/portfolio') && init?.method === 'POST') {
      const body = JSON.parse(String(init.body));
      if (opts.offline?.includes(body.symbol)) throw new Error('offline');
      if (opts.refuse?.includes(body.symbol)) {
        return { ok: false, status: 422, json: async () => ({ detail: 'total_exposure_limit_reached' }) };
      }
      const adj = opts.resize?.[body.symbol];
      return { ok: true, status: 201, json: async () => ({ ...body, ...(adj != null ? { adjustedQty: adj } : {}) }) };
    }
    return { ok: true, json: async () => ({}) };
  }) as unknown as typeof fetch;
}
const preSubmit = (why: string) => new Error(`API /broker/stock-order → 422: ${why}`);

describe('StockSendDialog — partial basket failure retry', () => {
  const realAddPosition = usePortfolioStore.getState().addPosition;

  afterEach(() => {
    usePortfolioStore.setState({ addPosition: realAddPosition });
  });

  beforeEach(() => {
    jest.clearAllMocks();
    act(() => {
      usePortfolioStore.setState({ positions: [] });
      useDirectSendNotesStore.setState({ notes: [] });
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

  const originalFetch = global.fetch;
  afterEach(() => { global.fetch = originalFetch; });

  it('only resubmits symbols that failed on the previous attempt', async () => {
    usePortfolioStore.setState({ addPosition: jest.fn().mockResolvedValue({ ok: true, status: 'ok' as const }) });
    global.fetch = saveFetch();
    const cards = [makeCard('AAPL'), makeCard('MSFT'), makeCard('NVDA')];
    const onSubmit = jest.fn();

    // MSFT's order is refused before the broker received it (a 422): its saved
    // row is removed, nothing is tracked and no order exists -> retryable.
    (api.postStockOrder as jest.Mock).mockImplementation(({ symbol }: { symbol: string }) => {
      if (symbol === 'MSFT') return Promise.reject(preSubmit('broker rejected'));
      return Promise.resolve({ order_id: `${symbol}-1`, status: 'Submitted' });
    });

    renderActive(<StockSendDialog cards={cards} onClose={jest.fn()} onSubmit={onSubmit} />);

    fireEvent.click(screen.getByText('IBKR Paper'));

    const submitBtn = screen.getByRole('button', { name: /submit 3 orders/i });
    await act(async () => {
      fireEvent.click(submitBtn);
      await waitFor(() => expect(api.postStockOrder).toHaveBeenCalledTimes(3));
    });

    expect(onSubmit).not.toHaveBeenCalled();
    expect(await screen.findByText(/MSFT 10 sh: Order NOT placed: broker rejected/i)).toBeInTheDocument();
    expect(api.deletePortfolioPosition).toHaveBeenCalledTimes(1);

    (api.postStockOrder as jest.Mock).mockImplementation(() => Promise.resolve({ order_id: 'retry-1', status: 'Submitted' }));

    const retryBtn = screen.getByRole('button', { name: /retry 1 failed order/i });
    await act(async () => {
      fireEvent.click(retryBtn);
      await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    });

    // Only MSFT should have been retried — AAPL/NVDA must NOT be resubmitted.
    expect(api.postStockOrder).toHaveBeenCalledTimes(4);
    const retryCallSymbols = (api.postStockOrder as jest.Mock).mock.calls
      .slice(3)
      .map(([arg]: [{ symbol: string }]) => arg.symbol);
    expect(retryCallSymbols).toEqual(['MSFT']);
    expect(onSubmit.mock.calls[0][0]).toHaveLength(3);
  });

  it('does not permanently disable Submit when one row is queued and another was refused', async () => {
    // AAPL stays Manual and is queued (backend unreachable for its save). MSFT
    // is Auto-send and its save is REFUSED, so no order is sent and it stays
    // retryable. Regression: a queued row must not disable the retry.
    global.fetch = saveFetch({ offline: ['AAPL'], refuse: ['MSFT'] });
    (api.postStockOrder as jest.Mock).mockResolvedValue({ order_id: 'retry-1', status: 'Submitted' });

    const cards = [makeCard('AAPL'), makeCard('MSFT')];
    const onSubmit = jest.fn();

    renderActive(<StockSendDialog cards={cards} onClose={jest.fn()} onSubmit={onSubmit} />);

    fireEvent.click(screen.getByText('IBKR Paper'));
    fireEvent.click(screen.getByLabelText('Auto-send AAPL')); // AAPL -> Manual

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /submit 2 orders/i }));
    });

    expect(onSubmit).not.toHaveBeenCalled();
    expect(await screen.findByText(/queued — backend unreachable, will sync/i)).toBeInTheDocument();
    expect(screen.getByText(/MSFT 10 sh: No order was sent — total_exposure_limit_reached/)).toBeInTheDocument();
    expect(api.postStockOrder).not.toHaveBeenCalled();

    const retryBtn = screen.getByRole('button', { name: /retry 1 failed order/i });
    expect(retryBtn).not.toBeDisabled();

    global.fetch = saveFetch({ offline: ['AAPL'] });
    await act(async () => {
      fireEvent.click(retryBtn);
    });

    await waitFor(() => expect(api.postStockOrder).toHaveBeenCalledTimes(1));
    expect((api.postStockOrder as jest.Mock).mock.calls[0][0].symbol).toBe('MSFT');
    // AAPL is still only queued, so the basket is not reported as placed.
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText(/queued — backend unreachable, will sync/i)).toBeInTheDocument();
    expect(screen.queryByText(/total_exposure_limit_reached/)).not.toBeInTheDocument();
  });

  it('creates a local position with a snapshot after a successful auto-send broker order', async () => {
    global.fetch = saveFetch();
    (api.postStockOrder as jest.Mock).mockResolvedValueOnce({ order_id: 'ORD-1', status: 'filled', broker: 'ibkr_paper' });
    const addPosition = jest.fn().mockResolvedValue({ status: 'ok' });
    usePortfolioStore.setState({ addPosition } as any);

    renderActive(<StockSendDialog cards={[makeCard('AAPL')]} onClose={jest.fn()} onSubmit={jest.fn()} />);
    fireEvent.click(screen.getByText('IBKR Paper'));
    fireEvent.click(screen.getByText(/Submit 1 order/));

    await waitFor(() => expect(addPosition).toHaveBeenCalled());
    const created = addPosition.mock.calls[0][0];
    expect(created.source).toBe('broker');
    expect(created.sourceLabel).toBe('IBKR Paper — Limit (ID: ORD-1)');
    expect(created.tradeCardSnapshot).toBeDefined();
    expect(created.tradeCardSnapshot.strategy.strategy).toBe('pullback_ema');
    expect(created.stop).toBe(95);
  });

  // STOCK-SENDS (plan §A1-A2): save first; the order carries the saved size.
  it('saves each auto-send row BEFORE its order, at the saved (resized) share count', async () => {
    const log: string[] = [];
    const inner = saveFetch({ resize: { AAPL: 4 } });
    global.fetch = jest.fn().mockImplementation(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith('/api/portfolio') && init?.method === 'POST') log.push('save');
      return (inner as unknown as jest.Mock)(url, init);
    }) as unknown as typeof fetch;
    (api.postStockOrder as jest.Mock).mockImplementation(async () => { log.push('order'); return { order_id: 'ORD-4', status: 'Submitted' }; });
    const onSubmit = jest.fn();

    renderActive(<StockSendDialog cards={[makeCard('AAPL')]} onClose={jest.fn()} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByText('IBKR Paper'));
    await act(async () => { fireEvent.click(screen.getByText(/Submit 1 order/)); });

    expect(await screen.findByText(/Portfolio sized it to 4 shares; the order was sent for 4/)).toBeInTheDocument();
    expect(log).toEqual(['save', 'order']);
    expect((api.postStockOrder as jest.Mock).mock.calls[0][0]).toMatchObject({ quantity: 4, limit_price: 100 });
    // The resized row stays on screen (not reported as a plain full-size success).
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('does NOT re-submit a row whose order status is unknown', async () => {
    global.fetch = saveFetch();
    // No recognisable status: the broker may have received it -> keep the row.
    (api.postStockOrder as jest.Mock).mockRejectedValueOnce(new Error('network timeout'));

    renderActive(<StockSendDialog cards={[makeCard('AAPL')]} onClose={jest.fn()} onSubmit={jest.fn()} />);
    fireEvent.click(screen.getByText('IBKR Paper'));
    fireEvent.click(screen.getByText(/Submit 1 order/));
    await waitFor(() => expect(api.postStockOrder).toHaveBeenCalledTimes(1));

    const btn = await screen.findByRole('button', { name: /Placed — close to continue/ });
    expect(btn).toBeDisabled();
    expect(api.postStockOrder).toHaveBeenCalledTimes(1);
    expect(await screen.findByText(/AAPL 10 sh: Order status UNKNOWN/)).toBeInTheDocument();
    expect(useDirectSendNotesStore.getState().notes).toEqual([
      expect.objectContaining({ kind: 'order-unknown', label: 'AAPL 10 sh' }),
    ]);
  });

  // MANUAL-IBKR-CONFIRM-AS-ERROR (2026-09-25): IBKR's confirmation question is
  // a 502 the classifier knows was never placed: the saved row is removed and
  // the symbol stays retryable. AAPL's position proves the success path runs
  // beside the refused row.
  it('an IBKR confirmation question (502) on one auto-send row shows its error and keeps no position for it', async () => {
    global.fetch = saveFetch();
    const addPosition = jest.fn().mockResolvedValue({ ok: true, status: 'ok' as const });
    usePortfolioStore.setState({ addPosition });
    (api.postStockOrder as jest.Mock).mockImplementation(({ symbol }: { symbol: string }) => {
      if (symbol === 'MSFT') {
        return Promise.reject(new Error(
          'API /broker/stock-order → 502: IBKR did not place the order: it asked for a ' +
          'confirmation this app does not send. IBKR said: Are you sure you want to submit this order?',
        ));
      }
      return Promise.resolve({ order_id: `${symbol}-1`, status: 'Submitted' });
    });
    const onSubmit = jest.fn();

    renderActive(<StockSendDialog cards={[makeCard('AAPL'), makeCard('MSFT')]} onClose={jest.fn()} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByText('IBKR Paper'));
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /submit 2 orders/i }));
    });

    expect(await screen.findByText(/IBKR said: Are you sure/)).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
    const savedSymbols = addPosition.mock.calls.map(([p]: [{ symbol: string }]) => p.symbol);
    expect(savedSymbols).toEqual(['AAPL']);
    expect(api.deletePortfolioPosition).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: /retry 1 failed order/i })).not.toBeDisabled();
  });
});

// Downstream save-first/retry parity tests; real unavailable authority is
// covered by StockPositionCard.session.test.tsx without this mock.
jest.mock('@/lib/stockExecutionSession', () => ({
  ...jest.requireActual('@/lib/stockExecutionSession'), stockExecutionBlock: jest.fn(() => null),
}));
beforeEach(() => useStockOrderOwnershipStore.setState({ bySymbol: {} }));

// Existing mechanics fixtures represent freshly pinned active candidates.
function renderActive(element: ReactElement<{ cards: PositionCardData[] }>) {
  const state = useScanStore.getState();
  const cards = element.props.cards;
  useScanStore.setState({ stockScanResult: { ...state.stockScanResult!, candidates: cards },
    stockBasketSources: Object.fromEntries(cards.map(card => [card.symbol, stockExecutionIdentity(state, card.symbol)])),
    stockExecution: {},
  });
  return render(element);
}
beforeEach(() => ownershipStore.setState({ bySymbol: {} }));
