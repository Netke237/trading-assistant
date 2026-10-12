/*
 * STOCKS-HORIZON-T1 H6 -- both StockPositionCard sends (the broker submit and
 * Add to Portfolio; Step 7's position card renders this component) write the
 * scan's hold onto the position: `ScanContext.holdMax` through
 * `sanitizeHoldDays`. Custom 60-185 -> 185. No scan context -> null.
 */
import { useStockOrderOwnershipStore } from '@/lib/stockExecutionSession';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { StockPositionCard } from '@/components/organisms/StockPositionCard';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useScanStore } from '@/lib/scanStore';
import { api } from '@/lib/api';
import { useDirectSendNotesStore } from '@/lib/directSendNotesStore';
import type { PositionCardData } from '@/types/stockDomain';
import type { MethodPick } from '@/types/domain';

const pick = (): MethodPick => ({
  method: 'ladder', rowStockPrice: 160, rowOptionPrice: null,
  stopBasis: 'stock', pickedAt: '2026-09-14T10:00:00.000Z',
});

jest.mock('@/lib/api', () => ({
  api: {
    postStockOrder: jest.fn(),
    deletePortfolioPosition: jest.fn().mockResolvedValue(undefined),
    getBrokerStatus: jest.fn().mockResolvedValue({}),
  },
}));
// The send mechanics, not the validation authority (covered by
// StockPositionCard.session.test.tsx), are under test here.
jest.mock('@/lib/stockExecutionSession', () => ({
  ...jest.requireActual('@/lib/stockExecutionSession'), stockExecutionBlock: jest.fn(() => null),
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

const CUSTOM_60_185 = {
  universe: 'SP500', direction: 'Bullish' as const, horizon: 'Position (60–185d)',
  horizonPreset: 'Custom' as const, holdMin: 60, holdMax: 185,
};

const originalFetch = global.fetch;
let bodies: Record<string, unknown>[];

describe('StockPositionCard -- the send carries the scan hold', () => {
  beforeEach(() => {
    bodies = [];
    global.fetch = jest.fn().mockImplementation(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith('/api/portfolio') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body));
        bodies.push(body);
        return { ok: true, status: 201, json: async () => body };
      }
      return { ok: true, json: async () => ({}) };
    }) as unknown as typeof fetch;
    usePortfolioStore.setState({ positions: [], lastSyncError: null });
    useDirectSendNotesStore.setState({ notes: [] });
    useStockOrderOwnershipStore.setState({ bySymbol: {} });
    useSettingsStore.setState({
      ibkrPaper: { baseUrl: 'https://localhost:7499/v1/api', accountId: 'ACC' },
    } as any);
    useScanStore.setState({
      context: CUSTOM_60_185,
      stockExecution: {},
      stockScanResult: { scan_id: 'stk-1', timestamp: '2026-09-14T09:00:00Z' } as any,
      stocksCardEdits: {
        scanId: 'stk-1', picks: { AAPL: pick() },
        invalidation: {}, premiumStop: {}, entryLimit: {}, maxLossOverride: {},
      },
    });
    jest.clearAllMocks();
  });
  afterEach(() => { global.fetch = originalFetch; });

  it('broker submit: Custom 60-185 -> hold 185 in the save body and on the row', async () => {
    (api.postStockOrder as jest.Mock).mockResolvedValueOnce({ order_id: 'ORD-1' });
    render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);
    fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    fireEvent.click(screen.getByRole('button', { name: /limit @/i }));
    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    expect(bodies.map((b) => b.holdMaxDays)).toEqual([185]);
    expect(usePortfolioStore.getState().positions[0].holdMaxDays).toBe(185);
  });

  it('Add to Portfolio: Custom 60-185 -> hold 185 in the save body', async () => {
    render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /add to portfolio/i }));
    });
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0].holdMaxDays).toBe(185);
  });

  it('no scan context -> null hold', async () => {
    useScanStore.setState({ context: null });
    render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /add to portfolio/i }));
    });
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0].holdMaxDays).toBeNull();
  });
});
