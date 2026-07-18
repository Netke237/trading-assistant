import { render, screen, fireEvent, act } from '@testing-library/react';
import { StockPositionCard } from '@/components/organisms/StockPositionCard';
import { usePortfolioStore } from '@/lib/portfolioStore';
import type { PositionCardData } from '@/types/stockDomain';

// api + heavy children are modules (not stores) — mocking them is correct.
jest.mock('@/lib/api', () => ({ api: { getBrokerStatus: jest.fn().mockResolvedValue({}) } }));
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

describe('StockPositionCard — Add to Portfolio outcome states', () => {
  beforeEach(() => {
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
  });
  afterEach(() => {
    global.fetch = originalFetch;
    jest.clearAllMocks();
  });

  async function clickAdd() {
    render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);
    const btn = screen.getByRole('button', { name: /add to portfolio/i });
    await act(async () => {
      fireEvent.click(btn);
    });
  }

  it('shows a distinct Queued state (not "Added") when the backend is unreachable', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('offline')) as unknown as typeof fetch;

    await clickAdd();

    // Caution line renders (unique text) once the pending result settles.
    expect(await screen.findByText(/backend unreachable, will sync automatically/i)).toBeInTheDocument();
    // The confirmed-success label must NOT be shown for an unconfirmed add.
    expect(screen.queryByText('Added to Portfolio')).not.toBeInTheDocument();
    // Re-click is blocked (row is already optimistically in the store).
    expect(screen.getByRole('button', { name: /queued — will sync/i })).toBeDisabled();
  });

  it('shows "Added to Portfolio" (disabled) when the backend confirms the save', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true, json: async () => ({}),
    }) as unknown as typeof fetch;

    await clickAdd();

    expect(await screen.findByText('Added to Portfolio')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /added to portfolio/i })).toBeDisabled();
    expect(screen.queryByText(/will sync/i)).not.toBeInTheDocument();
  });

  it('shows the rejection detail and stays retryable when the backend refuses', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false, status: 422, json: async () => ({ detail: 'risk check failed' }),
    }) as unknown as typeof fetch;

    await clickAdd();

    expect(await screen.findByText(/risk check failed/i)).toBeInTheDocument();
    // Button label back to the action, and NOT disabled — the user can retry.
    const btn = screen.getByRole('button', { name: /add to portfolio/i });
    expect(btn).not.toBeDisabled();
    expect(screen.queryByText(/will sync/i)).not.toBeInTheDocument();
  });
});
