import { render, screen, fireEvent, act } from '@testing-library/react';
import { StockSendDialog } from '@/components/organisms/StockSendDialog';
import { usePortfolioStore } from '@/lib/portfolioStore';
import type { PositionCardData } from '@/types/stockDomain';

jest.mock('@/lib/api', () => ({
  api: { getBrokerStatus: jest.fn().mockResolvedValue({}), postStockOrder: jest.fn() },
}));

// Single card only: buildPaperStockPosition mints the same PAPER-<ms> recId in a
// tight loop, so a two-card test would collide recIds and muddy the scenario.
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

describe('StockSendDialog — pending (backend-unreachable) submit', () => {
  beforeEach(() => {
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
  });
  afterEach(() => {
    global.fetch = originalFetch;
    jest.clearAllMocks();
  });

  it('keeps the dialog open, surfaces a queued note, and disables re-submit', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('offline')) as unknown as typeof fetch;
    const onSubmit = jest.fn();
    const onClose = jest.fn();

    render(<StockSendDialog cards={[makeCard()]} onClose={onClose} onSubmit={onSubmit} />);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /submit 1 order/i }));
    });

    // Queued caution note renders for the row.
    expect(await screen.findByText(/queued — backend unreachable, will sync/i)).toBeInTheDocument();
    // Did NOT report success / close.
    expect(onSubmit).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    // Same-mount re-submit is blocked (guards against contract-doubling merge),
    // and the primary button communicates the queued state rather than looking stuck.
    expect(screen.getByRole('button', { name: /queued — close to continue/i })).toBeDisabled();
  });

  it('reports success (calls onSubmit) when the backend confirms every row', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true, json: async () => ({}),
    }) as unknown as typeof fetch;
    const onSubmit = jest.fn();
    const onClose = jest.fn();

    render(<StockSendDialog cards={[makeCard()]} onClose={onClose} onSubmit={onSubmit} />);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /submit 1 order/i }));
    });

    // Backend-up happy path is unchanged: onSubmit fires with the order.
    await act(async () => {}); // flush the resolved chain
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/will sync/i)).not.toBeInTheDocument();
  });
});
