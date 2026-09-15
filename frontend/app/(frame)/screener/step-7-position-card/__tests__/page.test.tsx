import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Step7PositionCardPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { api } from '@/lib/api';
import type { StockScanResult } from '@/types/stockDomain';
import type { MethodPick } from '@/types/domain';

// Phase G piece 5, build step 4 (§7.2, S3) — this suite is about broker
// submit(), not the method-pick gate, so every fixture stamps a satisfied
// pick for both candidates or the new `pickMissing` check leaves the order
// buttons disabled regardless of what these tests exercise.
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
    getBrokerStatus: jest.fn().mockResolvedValue({}),
    getStockQuote: jest.fn().mockResolvedValue({ price: 150 }),
  },
}));

function makeScanResult(): StockScanResult {
  const candidate = (symbol: string) => ({
    symbol, company: `${symbol} Inc.`, price: 150, direction: 'Bullish',
    strategy: {
      strategy: 'pullback_ema', entry_price: 150, stop_price: 145,
      target_price: 160, rr_ratio: 2, atr: 3, detail: {},
    },
    backtest: {
      n_trades: 20, win_rate: 0.6, total_return_pct: 12, max_drawdown_pct: 5,
      expectancy: 0.4, sharpe: 1.2, confidence: 0.7, passes_gate: true, summary_text: 'ok',
    },
    stock_score: 80, stock_status: 'PASS',
    shares: 30, dollar_risk: 150, dollar_size: 4500,
    confidence: 0.7, confidence_text: 'High',
  });
  return {
    scan_id: 'S1', timestamp: '2026-08-01T00:00:00Z',
    candidates: [candidate('AAPL'), candidate('MSFT')],
    rejected: [],
  } as unknown as StockScanResult;
}

const originalFetch = global.fetch;

describe('step-7-position-card — broker order submit()', () => {
  beforeEach(() => {
    useScanStore.setState({
      stockScanResult: makeScanResult(), selectedSymbol: 'AAPL',
      stocksCardEdits: {
        scanId: 'S1', picks: { AAPL: pick(), MSFT: pick() },
        invalidation: {}, premiumStop: {}, entryLimit: {}, maxLossOverride: {},
      },
    } as any);
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
    useSettingsStore.setState({
      ibkrPaper: { baseUrl: 'https://localhost:7499/v1/api', accountId: 'ACC' },
    } as any);
    jest.clearAllMocks();
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('creates a local position with a snapshot after a successful broker order', async () => {
    (api.postStockOrder as jest.Mock).mockResolvedValueOnce({ order_id: 'ORD-1' });
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}) }) as unknown as typeof fetch;

    render(<Step7PositionCardPage />);
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    fireEvent.click(screen.getByRole('button', { name: /place limit order/i }));

    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    const pos = usePortfolioStore.getState().positions[0];
    expect(pos.source).toBe('broker');
    expect(pos.tradeCardSnapshot).toBeDefined();
    expect(pos.stop).toBe(145);
    // Confirmed gap as of build step 4 (S3): the gate blocked an UNPICKED
    // send, but nothing carried a MADE pick's values into the position
    // submit() creates here — a real send silently discarded it.
    expect(pos.pickedMethod).toBe('monte_carlo');
    expect(pos.pickedRowStockPrice).toBe(197.5);
    expect(pos.pickedRowOptionPrice).toBe(6.24);
    expect(pos.pickedStopBasis).toBe('stock');
  });

  it('shows a non-blocking warning and permanently disables the order buttons when the order succeeds but local tracking fails', async () => {
    (api.postStockOrder as jest.Mock).mockResolvedValueOnce({ order_id: 'ORD-2' });
    global.fetch = jest.fn().mockRejectedValue(new Error('offline')) as unknown as typeof fetch;

    render(<Step7PositionCardPage />);
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    fireEvent.click(screen.getByRole('button', { name: /place limit order/i }));

    expect(await screen.findByText(/not yet tracked in Portfolio/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /place limit order/i })).toBeDisabled();
  });

  it('does not let a stale order response from a previous candidate disable the newly-selected one', async () => {
    // orderId/error/warning are shared, not per-candidate, state. Submitting
    // on AAPL, switching to MSFT before the broker responds, then letting
    // that AAPL response land, must not stamp its outcome (disabling the Buy
    // buttons via orderId !== null) onto MSFT, which was never submitted.
    let resolveOrder!: (v: { order_id: string }) => void;
    (api.postStockOrder as jest.Mock).mockReturnValueOnce(new Promise((res) => { resolveOrder = res; }));
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}) }) as unknown as typeof fetch;

    render(<Step7PositionCardPage />);
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    fireEvent.click(screen.getByRole('button', { name: /place limit order/i }));

    // Switching candidates while AAPL's submit is still in flight — placingType
    // is also shared state, reset unconditionally once that request settles
    // (not something this fix touches), so MSFT's buttons briefly still read
    // "Placing…" here. The fix under test is specifically about what happens
    // to orderId once the stale response actually lands below.
    fireEvent.click(screen.getByRole('button', { name: 'MSFT' }));

    resolveOrder({ order_id: 'ORD-STALE' });
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByRole('button', { name: /place limit order/i })).toBeEnabled());
    expect(usePortfolioStore.getState().positions).toHaveLength(1);
    expect(usePortfolioStore.getState().positions[0].symbol).toBe('AAPL');
  });

  it('re-clicking the already-active candidate tab does not re-arm a placed order', async () => {
    // orderIds is keyed by candidate index — re-clicking the tab that's
    // ALREADY selected (e.g. a stray double-click) must not reset it and
    // silently re-enable the Buy buttons for a candidate that already has
    // a live (paper) order placed, which would permit a duplicate submission.
    (api.postStockOrder as jest.Mock).mockResolvedValueOnce({ order_id: 'ORD-1' });
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}) }) as unknown as typeof fetch;

    render(<Step7PositionCardPage />);
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    fireEvent.click(screen.getByRole('button', { name: /place limit order/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /place limit order/i })).toBeDisabled());

    fireEvent.click(screen.getByRole('button', { name: 'AAPL' }));

    expect(screen.getByRole('button', { name: /place limit order/i })).toBeDisabled();
  });

  it('still shows a placed order as disabled after navigating away to another candidate and back', async () => {
    // The same duplicate-submission risk as the same-tab-re-click case above,
    // reached via a more natural path: switching to a DIFFERENT candidate
    // (which correctly shows ITS own, unordered state) and then switching
    // BACK to the one that already has a live order. orderId/orderedIdx must
    // stay correctly attributed to AAPL regardless of what got viewed in
    // between — nothing about navigating away should un-order it.
    (api.postStockOrder as jest.Mock).mockResolvedValueOnce({ order_id: 'ORD-1' });
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}) }) as unknown as typeof fetch;

    render(<Step7PositionCardPage />);
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    fireEvent.click(screen.getByRole('button', { name: /place limit order/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /place limit order/i })).toBeDisabled());
    expect(screen.getByText(/Order placed — ID: ORD-1/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'MSFT' }));
    expect(screen.getByRole('button', { name: /place limit order/i })).toBeEnabled();
    expect(screen.queryByText(/Order placed — ID:/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'AAPL' }));
    expect(screen.getByRole('button', { name: /place limit order/i })).toBeDisabled();
    expect(screen.getByText(/Order placed — ID: ORD-1/)).toBeInTheDocument();
  });
});

/* Phase G piece 5, build step 4 (§7.2, S3, spec test 9). A SEPARATE component
 * from StockPositionCard (§2.5) — its own gate needed its own test. */
describe('step-7-position-card — refuses to order a candidate with no method pick', () => {
  beforeEach(() => {
    useScanStore.setState({
      stockScanResult: makeScanResult(), selectedSymbol: 'AAPL',
      stocksCardEdits: {
        scanId: 'S1', picks: {},
        invalidation: {}, premiumStop: {}, entryLimit: {}, maxLossOverride: {},
      },
    } as any);
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
    useSettingsStore.setState({
      ibkrPaper: { baseUrl: 'https://localhost:7499/v1/api', accountId: 'ACC' },
    } as any);
    jest.clearAllMocks();
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('disables both order buttons and places NO order when no candidate has a pick', async () => {
    render(<Step7PositionCardPage />);
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));

    const limitBtn  = screen.getByRole('button', { name: /place limit order/i });
    const marketBtn = screen.getByRole('button', { name: /right now — market order/i });
    expect(limitBtn).toBeDisabled();
    expect(marketBtn).toBeDisabled();

    fireEvent.click(limitBtn);
    fireEvent.click(marketBtn);
    await Promise.resolve();
    expect(api.postStockOrder).not.toHaveBeenCalled();
    expect(usePortfolioStore.getState().positions).toHaveLength(0);
  });

  it('says why', async () => {
    render(<Step7PositionCardPage />);
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    expect(screen.getByText(/Method pick required/)).toBeInTheDocument();
  });

  it('unblocks once the candidate has a pick', async () => {
    (api.postStockOrder as jest.Mock).mockResolvedValueOnce({ order_id: 'ORD-3' });
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}) }) as unknown as typeof fetch;

    useScanStore.setState((s) => ({
      stocksCardEdits: { ...s.stocksCardEdits, picks: { AAPL: pick() } },
    }));

    render(<Step7PositionCardPage />);
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    expect(screen.queryByText(/Method pick required/)).not.toBeInTheDocument();
    const limitBtn = screen.getByRole('button', { name: /place limit order/i });
    expect(limitBtn).toBeEnabled();

    fireEvent.click(limitBtn);
    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
  });
});
