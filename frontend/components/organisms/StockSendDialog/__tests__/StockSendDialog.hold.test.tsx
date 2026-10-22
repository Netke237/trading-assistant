/*
 * STOCKS-HORIZON-T1 H6 -- the basket send writes the scan's hold onto each
 * position (`ScanContext.holdMax` through `sanitizeHoldDays`), on both the
 * auto-send (broker) and the research-save branches. Custom 60-185 -> 185.
 */
import type { ReactElement } from 'react';
import { stockExecutionIdentity, useStockOrderOwnershipStore } from '@/lib/stockExecutionSession';
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

const pick = (): MethodPick => ({
  method: 'monte_carlo', rowStockPrice: 197.5, rowOptionPrice: 6.24,
  stopBasis: 'stock', pickedAt: '2026-09-14T10:00:00.000Z',
});

jest.mock('@/lib/api', () => ({
  api: {
    postStockOrder: jest.fn(),
    deletePortfolioPosition: jest.fn().mockResolvedValue(undefined),
    getBrokerStatus: jest.fn().mockResolvedValue({ alpaca_paper: { configured: false } }),
  },
}));
jest.mock('@/lib/stockExecutionSession', () => ({
  ...jest.requireActual('@/lib/stockExecutionSession'), stockExecutionBlock: jest.fn(() => null),
}));

function makeCard(symbol: string): PositionCardData {
  return {
    symbol, company: symbol, price: 100, direction: 'Bullish',
    strategy: {
      strategy: 'pullback_ema', entry_price: 100, stop_price: 95,
      target_price: 110, rr_ratio: 2.0, atr: 2.0, detail: {},
    },
    backtest: {
      n_trades: 20, win_rate: 0.6, total_return_pct: 10, max_drawdown_pct: -5,
      expectancy: 0.5, sharpe: 1.2, confidence: 70, passes_gate: true, summary_text: '',
    },
    stock_score: 80, stock_status: 'PASS',
    shares: 10, dollar_risk: 50, dollar_size: 1000,
    confidence: 70, confidence_text: null,
  };
}

function renderActive(element: ReactElement<{ cards: PositionCardData[] }>) {
  const state = useScanStore.getState();
  const cards = element.props.cards;
  useScanStore.setState({ stockScanResult: { ...state.stockScanResult!, candidates: cards },
    stockBasketSources: Object.fromEntries(cards.map(card => [card.symbol, stockExecutionIdentity(state, card.symbol)])),
    stockExecution: {},
  });
  return render(element);
}

const originalFetch = global.fetch;
let bodies: Record<string, unknown>[];

describe('StockSendDialog -- the send carries the scan hold', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    bodies = [];
    global.fetch = jest.fn().mockImplementation(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith('/api/portfolio') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body));
        bodies.push(body);
        return { ok: true, status: 201, json: async () => body };
      }
      return { ok: true, json: async () => ({}) };
    }) as unknown as typeof fetch;
    (api.postStockOrder as jest.Mock).mockResolvedValue({ order_id: 'ORD-1', status: 'Submitted' });
    act(() => {
      useStockOrderOwnershipStore.setState({ bySymbol: {} });
      usePortfolioStore.setState({ positions: [] });
      useDirectSendNotesStore.setState({ notes: [] });
      useSettingsStore.setState(() => ({
        ibkrPaper: { baseUrl: 'https://localhost:7499/v1/api', accountId: 'ACC' },
      }));
      useScanStore.setState({
        context: {
          universe: 'SP500', direction: 'Bullish', horizon: 'Position (60–185d)',
          horizonPreset: 'Custom', holdMin: 60, holdMax: 185,
        },
        stockScanResult: { scan_id: 'stk-1', timestamp: '2026-09-14T09:00:00Z' } as any,
        stocksCardEdits: {
          scanId: 'stk-1', picks: { AAPL: pick(), MSFT: pick() },
          invalidation: {}, premiumStop: {}, entryLimit: {}, maxLossOverride: {},
        },
      });
    });
  });
  afterEach(() => { global.fetch = originalFetch; });

  it('auto-send and research save both carry hold 185 for Custom 60-185', async () => {
    renderActive(<StockSendDialog cards={[makeCard('AAPL'), makeCard('MSFT')]} onClose={jest.fn()} onSubmit={jest.fn()} />);
    fireEvent.click(screen.getByText('IBKR Paper'));
    fireEvent.click(screen.getByLabelText('Auto-send MSFT')); // MSFT -> research save
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /submit/i }));
    });
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(Object.fromEntries(bodies.map((b) => [b.symbol, b.holdMaxDays]))).toEqual({ AAPL: 185, MSFT: 185 });
  });
});
