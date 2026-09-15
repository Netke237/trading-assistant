import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { StockPositionCard } from '@/components/organisms/StockPositionCard';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useScanStore } from '@/lib/scanStore';
import { api } from '@/lib/api';
import type { PositionCardData } from '@/types/stockDomain';
import type { MethodPick } from '@/types/domain';

// Phase G piece 5, build step 4 (§7.2, S1/S2, spec test 9) — the send gate
// itself, isolated from StockPositionCard.methodPick.test.tsx (which covers
// the PICKER control, build step 3) and StockPositionCard.submit.test.tsx /
// .pending.test.tsx / .exits.test.tsx (which stamp a satisfied pick so their
// own, unrelated behavior stays reachable).

jest.mock('@/lib/api', () => ({
  api: {
    getBrokerStatus: jest.fn().mockResolvedValue({}),
    postStockOrder: jest.fn(),
  },
}));
jest.mock('@/components/organisms/StockAutoTradeArm', () => ({ StockAutoTradeArm: () => null }));
jest.mock('@/components/molecules/MarketSentiment', () => ({ MarketSentiment: () => null }));
jest.mock('@/components/molecules/FundamentalHealthCard', () => ({ FundamentalHealthCard: () => null }));

const pick = (): MethodPick => ({
  method: 'ladder',
  rowStockPrice: 160,
  rowOptionPrice: null,
  stopBasis: 'stock',
  pickedAt: '2026-09-14T10:00:00.000Z',
});

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

describe('StockPositionCard — the method-pick send gate (S1, S2)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
    useSettingsStore.setState({
      ibkrPaper: { baseUrl: 'https://localhost:7499/v1/api', accountId: 'ACC' },
    } as any);
    useScanStore.setState({
      stockScanResult: null,
      stocksCardEdits: {
        scanId: null, picks: {}, invalidation: {}, premiumStop: {}, entryLimit: {}, maxLossOverride: {},
      },
    });
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('S2 — disables Add to Portfolio and posts nothing when no pick has been made', async () => {
    render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);

    const addBtn = screen.getByRole('button', { name: /add to portfolio/i });
    expect(addBtn).toBeDisabled();
    expect(screen.getByText(/Method pick required/)).toBeInTheDocument();

    fireEvent.click(addBtn);
    await Promise.resolve();
    expect(usePortfolioStore.getState().positions).toHaveLength(0);
  });

  it('S1 — disables both order buttons and posts no broker order when no pick has been made', async () => {
    render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));

    const limitBtn  = screen.getByRole('button', { name: /limit @/i });
    const marketBtn = screen.getByRole('button', { name: /market order/i });
    expect(limitBtn).toBeDisabled();
    expect(marketBtn).toBeDisabled();

    fireEvent.click(limitBtn);
    fireEvent.click(marketBtn);
    await Promise.resolve();
    expect(api.postStockOrder).not.toHaveBeenCalled();
    expect(usePortfolioStore.getState().positions).toHaveLength(0);
  });

  it('unblocks both S1 and S2 once the trader picks a method', async () => {
    (api.postStockOrder as jest.Mock).mockResolvedValueOnce({ order_id: 'ORD-1' });
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}) }) as unknown as typeof fetch;

    useScanStore.setState({
      stockScanResult: { scan_id: 'stk-1', timestamp: '2026-09-14T09:00:00Z' } as any,
      stocksCardEdits: {
        scanId: 'stk-1', picks: { AAPL: pick() },
        invalidation: {}, premiumStop: {}, entryLimit: {}, maxLossOverride: {},
      },
    });

    render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);
    expect(screen.queryByText(/Method pick required/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));

    const limitBtn = screen.getByRole('button', { name: /limit @/i });
    expect(limitBtn).toBeEnabled();
    fireEvent.click(limitBtn);

    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
  });
});
