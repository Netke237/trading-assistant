import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import Step4StocksPage from '../page';
import BacktestPage from '../../step-6-backtest/page';
jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn() }) }));
import { useScanStore } from '@/lib/scanStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { api } from '@/lib/api';
import * as execution from '@/lib/stockExecutionSession';
import type { StockScanResult, PositionCardData } from '@/types/stockDomain';

/*
 * Phase G piece 5, build step 4 (§7.3, spec test 9b) — S5, the after-scan
 * auto-executor, is the ONE gateable-looking path Kenneth chose to EXEMPT
 * (§7.3 decision (a)): a pick can never exist for a trade a scan places with
 * no human in the loop, so `step-4-stocks/page.tsx:196`'s auto-execute loop
 * is deliberately NOT touched by build step 4's gate. This test pins BOTH
 * halves spec test 9b calls out:
 *   - the position IS still created (the regression test for decision (b) —
 *     "gate it, which disables it" — being introduced by accident later);
 *   - it carries no method pick and the gate never fires for it.
 */

jest.mock('@/lib/api', () => ({ api: { postStockScan: jest.fn(), getLastStockScanStatus: jest.fn().mockResolvedValue({ status: 'idle' }) } }));
jest.mock('@/components/organisms/StockPositionCard', () => ({
  // A minimal stand-in exposing exactly the one control this test drives —
  // the after-scan arm toggle — rather than the full card.
  StockPositionCard: ({ card, afterScanArmed, onAfterScanToggle }: {
    card: PositionCardData;
    afterScanArmed: boolean;
    onAfterScanToggle: (symbol: string, armed: boolean) => void;
  }) => (
    <button
      type="button"
      onClick={() => onAfterScanToggle(card.symbol, !afterScanArmed)}
    >
      {afterScanArmed ? `Disarm ${card.symbol}` : `Arm ${card.symbol}`}
    </button>
  ),
}));
jest.mock('@/components/organisms/StockSendDialog', () => ({ StockSendDialog: () => null }));
jest.mock('@/components/organisms/StrategyParamsPanel', () => ({
  StrategyParamsPanel: () => null,
}));
jest.mock('@/components/organisms/ScanFunnel', () => ({ ScanFunnel: () => null }));
jest.mock('@/components/atoms/WatchStar', () => ({ WatchStar: () => null }));
// This suite does not mock @/lib/api; the row would call the real backend.
jest.mock('../HistoryPrefetchRow', () => ({ HistoryPrefetchRow: () => null }));

function makeCandidate(
  symbol: string,
  stockStatus: PositionCardData['stock_status'] = 'PASS',
): PositionCardData {
  return {
    symbol, company: `${symbol} Inc.`, price: 150, direction: 'Bullish',
    strategy: {
      strategy: 'pullback_ema', entry_price: 150, stop_price: 145,
      target_price: 160, rr_ratio: 2, atr: 3, detail: {}, targets: [160, 165, 170],
    },
    backtest: {
      n_trades: 20, win_rate: 0.6, total_return_pct: 12, max_drawdown_pct: 5,
      expectancy: 0.4, sharpe: 1.2, confidence: 0.7, passes_gate: true, summary_text: 'ok',
    },
    stock_score: 80, stock_status: stockStatus,
    shares: 30, dollar_risk: 150, dollar_size: 4500,
    confidence: 0.7, confidence_text: 'High',
    sentiment: null, fundamentals: null,
  };
}

function makeScanResult(
  candidates: PositionCardData[] = [makeCandidate('AAPL')],
): StockScanResult {
  return {
    scan_id: 'stk-1', timestamp: '2026-09-14T09:00:00Z',
    candidates,
    rejected: [],
  } as unknown as StockScanResult;
}

const originalFetch = global.fetch;

describe('step-4-stocks — S5 after-scan auto-execute is exempt from the method-pick gate', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.spyOn(execution, 'stockExecutionBlock').mockReturnValue(null);
    useScanStore.setState({ stockAfterScanIntent: {} });
    act(() => {
      useScanStore.setState({
        context: { direction: 'Bullish', universe: 'SP500' } as any,
        activeStrategy: 'pullback_ema',
        combinedRegime: 'PASS' as any,
        stockScanResult: null,
        previousStockScanResult: null,
        scanState: 'IDLE' as any,
        stockBasket: [],
        stockScanAt: null,
        scanOverrides: {},
      });
      usePortfolioStore.setState({ positions: [], lastSyncError: null });
    });
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}) }) as unknown as typeof fetch;
    (api.postStockScan as jest.Mock).mockResolvedValue(makeScanResult());
  });
  afterEach(() => {
    global.fetch = originalFetch;
    jest.restoreAllMocks();
  });

  it('creates the auto-executed position with no picked_method, and the gate never fires', async () => {
    render(<><Step4StocksPage /><BacktestPage /></>);

    // 1) Select the strategy and run the first scan to surface AAPL.
    fireEvent.click(screen.getByRole('button', { name: /pullback/i }));
    fireEvent.click(screen.getByRole('button', { name: /run stock scan/i }));
    await screen.findByText('AAPL');

    // 2) Open AAPL's row and arm it for after-scan auto-execute.
    fireEvent.click(screen.getByRole('button', { name: 'Expand AAPL' }));
    fireEvent.click(await screen.findByRole('button', { name: /arm aapl/i }));

    // 3) Re-run — onRun's own auto-execute loop fires against candidates from
    // THIS run, since afterScanArmedSymbols now has AAPL.
    fireEvent.click(screen.getByRole('button', { name: /run stock scan/i }));

    await waitFor(() => expect(usePortfolioStore.getState().positions).toHaveLength(1));
    const pos = usePortfolioStore.getState().positions[0];
    expect(pos.symbol).toBe('AAPL');
    // No picked_* fields travel this path (§7.3) — the position is created
    // exactly as it always was, with no method-pick payload at all.
    expect((pos as unknown as { pickedMethod?: unknown }).pickedMethod).toBeUndefined();
    // No refusal text anywhere on the page — the gate this build step adds
    // is never consulted for this path.
    expect(screen.queryByText(/Method pick required/)).not.toBeInTheDocument();
  });
});

/*
 * TRADING-REVIEW-PHASE-C T10 (review M8): the after-scan arm promises "fire
 * when next scan PASS" (StockAutoTradeArm). Every candidate has passed the
 * backtest gate, but its stock_status can still be CAUTION — such a candidate
 * must not be auto-executed, and the user is told why it was not.
 */
describe('step-4-stocks — after-scan auto-execute fires on PASS only', () => {
  const realAddPosition = usePortfolioStore.getState().addPosition;

  beforeEach(() => {
    jest.clearAllMocks();
    jest.spyOn(execution, 'stockExecutionBlock').mockReturnValue(null);
    useScanStore.setState({ stockAfterScanIntent: {} });
    act(() => {
      useScanStore.setState({
        context: { direction: 'Bullish', universe: 'SP500' } as any,
        activeStrategy: 'pullback_ema',
        combinedRegime: 'PASS' as any,
        stockScanResult: null,
        previousStockScanResult: null,
        scanState: 'IDLE' as any,
        stockBasket: [],
        stockScanAt: null,
        scanOverrides: {},
      });
      usePortfolioStore.setState({ positions: [], lastSyncError: null });
    });
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({}) }) as unknown as typeof fetch;
    (api.postStockScan as jest.Mock).mockResolvedValue(makeScanResult([makeCandidate('AAPL', 'PASS'), makeCandidate('MSFT', 'CAUTION')]));
  });
  afterEach(() => {
    global.fetch = originalFetch;
    jest.restoreAllMocks();
    act(() => { usePortfolioStore.setState({ addPosition: realAddPosition }); });
  });

  async function armBothAndRescan() {
    render(<><Step4StocksPage /><BacktestPage /></>);
    fireEvent.click(screen.getByRole('button', { name: /pullback/i }));
    fireEvent.click(screen.getByRole('button', { name: /run stock scan/i }));
    await screen.findByText('AAPL');

    fireEvent.click(screen.getByRole('button', { name: 'Expand AAPL' }));
    fireEvent.click(await screen.findByRole('button', { name: /arm aapl/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Expand MSFT' }));
    fireEvent.click(await screen.findByRole('button', { name: /arm msft/i }));

    fireEvent.click(screen.getByRole('button', { name: /run stock scan/i }));
  }

  it('adds a position for the PASS candidate only', async () => {
    const addSpy = jest.fn(realAddPosition);
    act(() => { usePortfolioStore.setState({ addPosition: addSpy }); });

    await armBothAndRescan();

    await waitFor(() => expect(addSpy).toHaveBeenCalled());
    // onRun awaits each addPosition in turn: let the loop run to its end so a
    // second (MSFT) call, if any, has happened before counting.
    await act(async () => { await new Promise((r) => setTimeout(r, 100)); });
    expect(addSpy).toHaveBeenCalledTimes(1);
    expect(addSpy.mock.calls[0][0].symbol).toBe('AAPL');
    expect(usePortfolioStore.getState().positions.map((p) => p.symbol)).toEqual(['AAPL']);
  });

  it('tells the user the CAUTION candidate was not fired, and why', async () => {
    await armBothAndRescan();

    expect((await screen.findAllByText(/Not fired.*MSFT: not PASS \(CAUTION\)/)).length).toBeGreaterThan(0);
  });
});
