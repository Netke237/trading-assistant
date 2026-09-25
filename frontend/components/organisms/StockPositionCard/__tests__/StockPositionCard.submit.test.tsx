import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { StockPositionCard } from '@/components/organisms/StockPositionCard';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useScanStore } from '@/lib/scanStore';
import { api } from '@/lib/api';
import type { PositionCardData } from '@/types/stockDomain';
import type { MethodPick } from '@/types/domain';

// Phase G piece 5, build step 4 — this suite is about broker submit(), not
// the method-pick gate, so every fixture stamps a satisfied pick or the new
// `pickMissing` check leaves the order buttons disabled regardless of what
// these tests exercise (see StockPositionCard.methodPickSendGate.test.tsx
// for the gate's own tests).
const pick = (): MethodPick => ({
  method: 'ladder',
  rowStockPrice: 160,
  rowOptionPrice: null,
  stopBasis: 'stock',
  pickedAt: '2026-09-14T10:00:00.000Z',
});

jest.mock('@/lib/api', () => ({
  api: {
    postStockOrder: jest.fn(),
    getBrokerStatus: jest.fn().mockResolvedValue({}),
  },
}));
jest.mock('@/components/organisms/StockAutoTradeArm', () => ({ StockAutoTradeArm: () => null }));
jest.mock('@/components/molecules/MarketSentiment', () => ({ MarketSentiment: () => null }));
jest.mock('@/components/molecules/FundamentalHealthCard', () => ({ FundamentalHealthCard: () => null }));

function makeCard(): PositionCardData {
  return {
    symbol: 'AAPL', company: 'Apple Inc.', price: 150, direction: 'Bullish',
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
    sentiment: null, fundamentals: null,
  };
}

const originalFetch = global.fetch;

describe('StockPositionCard — broker order submit()', () => {
  beforeEach(() => {
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
    useSettingsStore.setState({
      ibkrPaper: { baseUrl: 'https://localhost:7499/v1/api', accountId: 'ACC' },
    } as any);
    useScanStore.setState({
      stockScanResult: { scan_id: 'stk-1', timestamp: '2026-09-14T09:00:00Z' } as any,
      stocksCardEdits: {
        scanId: 'stk-1', picks: { AAPL: pick() },
        invalidation: {}, premiumStop: {}, entryLimit: {}, maxLossOverride: {},
      },
    });
    jest.clearAllMocks();
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('creates a local position with a snapshot after a successful broker order', async () => {
    (api.postStockOrder as jest.Mock).mockResolvedValueOnce({ order_id: 'ORD-1' });
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}) }) as unknown as typeof fetch;

    render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    fireEvent.click(screen.getByRole('button', { name: /limit @/i }));

    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    const pos = usePortfolioStore.getState().positions[0];
    expect(pos.source).toBe('broker');
    expect(pos.tradeCardSnapshot).toBeDefined();
    expect(pos.stop).toBe(145);
  });

  it('shows a non-blocking warning (not an error) and permanently disables the order buttons when the order succeeds but local tracking fails', async () => {
    (api.postStockOrder as jest.Mock).mockResolvedValueOnce({ order_id: 'ORD-2' });
    global.fetch = jest.fn().mockRejectedValue(new Error('offline')) as unknown as typeof fetch;

    render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    fireEvent.click(screen.getByRole('button', { name: /limit @/i }));

    expect(await screen.findByText(/not yet tracked in Portfolio/)).toBeInTheDocument();
    // The order genuinely succeeded — clicking again must not be possible, since
    // that would fire a second broker order for shares already bought.
    expect(screen.getByRole('button', { name: /limit @/i })).toBeDisabled();
  });

  // MANUAL-IBKR-CONFIRM-AS-ERROR (2026-09-25). When IBKR answers with a
  // confirmation question the backend now returns a 502 carrying it (it used
  // to be an empty-id 200, which created a phantom Portfolio position). The
  // message below is the exact shape lib/api.ts's apiError produces for it.
  it('an IBKR confirmation question (502) shows as an error and creates no position', async () => {
    (api.postStockOrder as jest.Mock).mockRejectedValueOnce(new Error(
      'API /broker/stock-order → 502: IBKR did not place the order: it asked for a ' +
      'confirmation this app does not send. IBKR said: Are you sure you want to submit this order?',
    ));
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}) }) as unknown as typeof fetch;

    render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    fireEvent.click(screen.getByRole('button', { name: /limit @/i }));

    // Awaited first, so the assertions below run after the rejection was handled.
    expect(await screen.findByText(/IBKR said: Are you sure/)).toBeInTheDocument();
    expect(usePortfolioStore.getState().positions).toHaveLength(0);
    expect(screen.queryByText(/Order placed/)).not.toBeInTheDocument();
    // Nothing was placed, so the user can send again.
    await waitFor(() => expect(screen.getByRole('button', { name: /limit @/i })).toBeEnabled());
  });
});
