import { render, screen, fireEvent, act, within } from '@testing-library/react';
import { StockPositionCard } from '@/components/organisms/StockPositionCard';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useScanStore } from '@/lib/scanStore';
import type { PositionCardData } from '@/types/stockDomain';
import type { MethodPick } from '@/types/domain';

// Phase G piece 5, build step 4 — this suite is about the Add-to-Portfolio
// OUTCOME states, not the method-pick gate, so every fixture stamps a
// satisfied pick or the new `pickMissing` check leaves the button disabled
// before any of these outcomes can be reached.
const pick = (): MethodPick => ({
  method: 'ladder',
  rowStockPrice: 160,
  rowOptionPrice: null,
  stopBasis: 'stock',
  pickedAt: '2026-09-14T10:00:00.000Z',
});

// api + heavy children are modules (not stores) — mocking them is correct.
jest.mock('@/lib/api', () => ({ api: { getBrokerStatus: jest.fn().mockResolvedValue({}) } }));
// Records the props it was called with so tests can assert on the derived `direction` prop.
const mockStockAutoTradeArm = jest.fn((_props: unknown) => null);
jest.mock('@/components/organisms/StockAutoTradeArm', () => ({
  StockAutoTradeArm: (props: unknown) => mockStockAutoTradeArm(props),
}));
jest.mock('@/components/molecules/MarketSentiment', () => ({ MarketSentiment: () => null }));
jest.mock('@/components/molecules/FundamentalHealthCard', () => ({ FundamentalHealthCard: () => <div>Fundamental Health test</div> }));

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
    useScanStore.setState({
      stockScanResult: { scan_id: 'stk-1', timestamp: '2026-09-14T09:00:00Z' } as any,
      stocksCardEdits: {
        scanId: 'stk-1', picks: { AAPL: pick() },
        invalidation: {}, premiumStop: {}, entryLimit: {}, maxLossOverride: {},
      },
    });
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

  it('places one real stock total above health and preserves it on collapse', async () => {
    localStorage.removeItem('bamendjou:stock-position-scores-collapsed');
    render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);
    const toggle = screen.getByRole('button', { name: /Stock & contract scores/ });
    const bar = screen.getByRole('progressbar');
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(bar).toHaveAttribute('aria-valuenow', '80');
    expect(toggle.compareDocumentPosition(screen.getByText('Fundamental Health test')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByText('Contract Scorecard')).not.toBeInTheDocument();
    toggle.focus();
    expect(toggle).toHaveFocus();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(bar).toBeInTheDocument();
    expect(bar).not.toBeVisible();
    expect(localStorage.getItem('bamendjou:stock-position-scores-collapsed')).toBe('1');
    fireEvent.click(toggle);
    expect(screen.getByRole('progressbar')).toBe(bar);
    expect(screen.getAllByRole('progressbar')).toHaveLength(1);
    await act(async () => { await Promise.resolve(); });
    localStorage.removeItem('bamendjou:stock-position-scores-collapsed');
  });

  it('updates only the captured stock total and status when card data changes', async () => {
    localStorage.removeItem('bamendjou:stock-position-scores-collapsed');
    const { rerender } = render(<StockPositionCard card={makeCard()} strategyKey="pullback_ema" />);
    rerender(<StockPositionCard card={{ ...makeCard(), stock_score: 42, stock_status: 'PENDING', confidence: null }} strategyKey="pullback_ema" />);
    const group = screen.getByRole('button', { name: /Stock & contract scores/ }).closest('section')!;
    expect(within(group).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '42');
    expect(within(group).getByText('PENDING')).toBeInTheDocument();
    expect(within(group).queryByText(/confidence|trend/i)).not.toBeInTheDocument();
    expect(within(group).getAllByRole('progressbar')).toHaveLength(1);
    await act(async () => { await Promise.resolve(); });
  });

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

describe('StockPositionCard — direction forwarded to StockAutoTradeArm', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('forwards direction="Bearish" for a Bearish card', () => {
    render(<StockPositionCard card={{ ...makeCard(), direction: 'Bearish' }} strategyKey="pullback_ema" />);

    expect(mockStockAutoTradeArm).toHaveBeenCalled();
    const props = mockStockAutoTradeArm.mock.calls[0]?.[0] as { direction: string } | undefined;
    expect(props?.direction).toBe('Bearish');
  });
});
