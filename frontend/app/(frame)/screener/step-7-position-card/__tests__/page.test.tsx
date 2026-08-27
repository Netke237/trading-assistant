import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Step7PositionCardPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { api } from '@/lib/api';
import type { StockScanResult } from '@/types/stockDomain';

jest.mock('@/lib/api', () => ({
  api: {
    postStockOrder: jest.fn(),
    getBrokerStatus: jest.fn().mockResolvedValue({}),
    getStockQuote: jest.fn().mockResolvedValue({ price: 150 }),
  },
}));

function makeScanResult(): StockScanResult {
  return {
    scan_id: 'S1', timestamp: '2026-08-01T00:00:00Z',
    candidates: [{
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
    }],
    rejected: [],
  } as unknown as StockScanResult;
}

const originalFetch = global.fetch;

describe('step-7-position-card — broker order submit()', () => {
  beforeEach(() => {
    useScanStore.setState({ stockScanResult: makeScanResult(), selectedSymbol: 'AAPL' } as any);
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
});
