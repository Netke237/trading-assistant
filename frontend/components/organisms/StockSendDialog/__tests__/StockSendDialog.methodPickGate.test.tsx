import type { ReactElement } from 'react';
import { stockExecutionIdentity, useStockOrderOwnershipStore as ownershipStore } from '@/lib/stockExecutionSession';
import '@testing-library/jest-dom';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { StockSendDialog } from '@/components/organisms/StockSendDialog';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useScanStore } from '@/lib/scanStore';
import { api } from '@/lib/api';
import type { PositionCardData } from '@/types/stockDomain';
import type { MethodPick } from '@/types/domain';

// Phase G piece 5, build step 4 (§7.2, S4, spec test 9) — the stocks basket's
// own method-pick gate, isolated from StockSendDialog.test.tsx's send/retry
// mechanics suite.

jest.mock('@/lib/api', () => ({
  api: { getBrokerStatus: jest.fn().mockResolvedValue({}), postStockOrder: jest.fn() },
}));

const pick = (): MethodPick => ({
  method: 'monte_carlo',
  rowStockPrice: 197.5,
  rowOptionPrice: 6.24,
  stopBasis: 'stock',
  pickedAt: '2026-09-14T10:00:00.000Z',
});

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

const originalFetch = global.fetch;

describe('StockSendDialog — the method-pick gate', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    usePortfolioStore.setState({ positions: [] });
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('disables Submit and places no order when one card has no pick, even though the other does', async () => {
    useScanStore.setState({
      stockScanResult: { scan_id: 'stk-1', timestamp: '2026-09-14T09:00:00Z' } as any,
      stocksCardEdits: {
        scanId: 'stk-1', picks: { AAPL: pick() },
        invalidation: {}, premiumStop: {}, entryLimit: {}, maxLossOverride: {},
      },
    });

    renderActive(<StockSendDialog cards={[makeCard('AAPL'), makeCard('MSFT')]} onClose={jest.fn()} onSubmit={jest.fn()} />);

    expect(screen.getByText(/Method pick required/)).toBeInTheDocument();
    const submitBtn = screen.getByRole('button', { name: /submit 2 orders/i });
    expect(submitBtn).toBeDisabled();

    await act(async () => {
      fireEvent.click(submitBtn);
    });
    expect(api.postStockOrder).not.toHaveBeenCalled();
    expect(usePortfolioStore.getState().positions).toHaveLength(0);
  });

  it('does not block once every card carries a pick', () => {
    useScanStore.setState({
      stockScanResult: { scan_id: 'stk-1', timestamp: '2026-09-14T09:00:00Z' } as any,
      stocksCardEdits: {
        scanId: 'stk-1', picks: { AAPL: pick(), MSFT: pick() },
        invalidation: {}, premiumStop: {}, entryLimit: {}, maxLossOverride: {},
      },
    });

    renderActive(<StockSendDialog cards={[makeCard('AAPL'), makeCard('MSFT')]} onClose={jest.fn()} onSubmit={jest.fn()} />);

    expect(screen.queryByText(/Method pick required/)).not.toBeInTheDocument();
  });

  it('submitting carries each card\'s own pick onto the position it creates', async () => {
    // Confirmed gap as of build step 4 (S4): the gate blocked an UNPICKED
    // basket submit, but nothing carried a MADE pick's values into either
    // position `submit()` creates — a real send silently discarded them
    // regardless of the gate passing. Default row state is autoSend:true
    // with broker left at 'recommendation', which exercises the third of
    // StockSendDialog's three addPosition call sites (the "falls back to
    // paper" branch).
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}) }) as unknown as typeof fetch;
    useScanStore.setState({
      stockScanResult: { scan_id: 'stk-1', timestamp: '2026-09-14T09:00:00Z' } as any,
      stocksCardEdits: {
        scanId: 'stk-1', picks: { AAPL: pick() },
        invalidation: {}, premiumStop: {}, entryLimit: {}, maxLossOverride: {},
      },
    });

    renderActive(<StockSendDialog cards={[makeCard('AAPL')]} onClose={jest.fn()} onSubmit={jest.fn()} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /submit 1 order/i }));
    });

    const positions = usePortfolioStore.getState().positions;
    expect(positions).toHaveLength(1);
    expect(positions[0]!.pickedMethod).toBe('monte_carlo');
    expect(positions[0]!.pickedRowStockPrice).toBe(197.5);
    expect(positions[0]!.pickedRowOptionPrice).toBe(6.24);
    expect(positions[0]!.pickedStopBasis).toBe('stock');
  });

  it('refuses a pick left over from a different scan (the stamp is what makes it gone, not merely old)', () => {
    useScanStore.setState({
      stockScanResult: { scan_id: 'stk-2', timestamp: '2026-09-14T11:00:00Z' } as any,
      // Stamped under the PREVIOUS scan — selectCardEdits must return this as
      // empty against the current stk-2 result.
      stocksCardEdits: {
        scanId: 'stk-1', picks: { AAPL: pick() },
        invalidation: {}, premiumStop: {}, entryLimit: {}, maxLossOverride: {},
      },
    });

    renderActive(<StockSendDialog cards={[makeCard('AAPL')]} onClose={jest.fn()} onSubmit={jest.fn()} />);

    expect(screen.getByText(/Method pick required/)).toBeInTheDocument();
  });
});

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
