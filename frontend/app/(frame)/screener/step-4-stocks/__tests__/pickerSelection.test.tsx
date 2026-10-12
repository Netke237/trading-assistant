import '@testing-library/jest-dom';
import { render, screen, fireEvent, act } from '@testing-library/react';
import Step4StocksPage from '../page';
import BacktestPage from '../../step-6-backtest/page';
import { useScanStore } from '@/lib/scanStore';

const mockCardProps = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => '/screener/step-4-stocks',
}));
jest.mock('@/lib/stockScan', () => ({
  ...jest.requireActual('@/lib/stockScan'),
  runStockScanWithContinuation: async (...args: unknown[]) => {
    const scan = await jest.requireMock('@/lib/stockScan').runStockScan(...args);
    const store = jest.requireActual('@/lib/scanStore').useScanStore.getState();
    const reason = store.stockScanError ?? 'unknown error';
    store.setStockScanFeedback(store.stockManualRunToken, { error: scan ? null : `Scan failed — ${reason}`, notice: null });
    return scan ? { kind: 'success', token: store.stockManualRunToken, result: scan } : { kind: 'failure', token: store.stockManualRunToken, reason };
  },
  isStockManualScanCurrent: (outcome: { kind: string; token: number }) => outcome.kind !== 'obsolete' && outcome.token === jest.requireActual('@/lib/scanStore').useScanStore.getState().stockManualRunToken,
  runStockScan: jest.fn(),
}));
jest.mock('@/lib/api', () => ({
  api: { startHistoryPrefetch: jest.fn(), getHistoryPrefetchStatus: jest.fn() },
  getLastDataRefresh: jest.fn(() => Promise.resolve({ last_refresh: null })),
  API_BASE_URL: 'http://localhost:8000',
}));
jest.mock('@/components/organisms/StockPositionCard', () => ({
  StockPositionCard: (p: { strategyKey: string }) => { mockCardProps(p); return null; },
}));
jest.mock('@/components/organisms/StockSendDialog', () => ({ StockSendDialog: () => null }));
jest.mock('@/components/organisms/ScanFunnel', () => ({ ScanFunnel: () => null }));
jest.mock('@/components/atoms/WatchStar', () => ({ WatchStar: () => null }));
// The shared CSS-module mock is `{}`, so every class name renders as
// `undefined`. Echo the key instead so the selected card's `cardActive`
// class is observable (`__esModule` stays falsy for default-import interop).
jest.mock('../page.module.css', () =>
  new Proxy({}, { get: (_t, k) => (k === '__esModule' ? false : k) }));

const card = (label: RegExp) =>
  screen.getAllByText(label).map((e) => e.closest('button')).find((b) => b !== null) as HTMLButtonElement;

const CANDIDATE = {
  symbol: 'AAPL', company: 'Apple', price: 100, direction: 'Bullish',
  strategy: { strategy: 'pullback_ema', entry_price: 100, stop_price: 95, target_price: 110, targets: [110], rr_ratio: 2, atr: 1, detail: {} },
  backtest: { n_trades: 20, win_rate: 0.55, total_return_pct: 10, max_drawdown_pct: -5, expectancy: 1, sharpe: 1, confidence: 60, passes_gate: true, summary_text: 'ok' },
  stock_score: 80, stock_status: 'PASS', shares: 10, dollar_risk: 50, dollar_size: 1000,
  confidence: 60, confidence_text: null,
};

beforeEach(() => {
  mockCardProps.mockClear();
  useScanStore.setState({
    context: { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)' },
    activeStrategy: null, stockScanResult: null, stockScanRequest: null,
    lastStockScanStrategy: null, scanState: 'IDLE', stockScanError: null,
  } as never);
});

it('clicking a card writes activeStrategy without running a scan', () => {
  const { runStockScan } = jest.requireMock('@/lib/stockScan');
  render(<><Step4StocksPage /><BacktestPage /></>);
  fireEvent.click(card(/^Breakout from tight base$/));
  expect(useScanStore.getState().activeStrategy).toBe('breakout_base');
  expect(runStockScan).not.toHaveBeenCalled();
});

it('a strategy set elsewhere (search profile load) shows as selected', () => {
  render(<Step4StocksPage />);
  act(() => useScanStore.getState().setActiveStrategy('ma_crossover'));
  expect(screen.getByRole('button', { name: 'Run Stock Scan' })).toBeEnabled();
  // The periods come from the backend horizon profile (STOCKS-HORIZON-T1 H5);
  // with none fetched here the card reads "MA Crossover".
  expect(card(/^MA Crossover( \d+\/\d+)?$/).className).toMatch(/cardActive/);
});

it('the position card gets the strategy the rows were scanned with, not the current selection', () => {
  useScanStore.setState({
    activeStrategy: 'pullback_ema',
    stockScanResult: { scan_id: 'S', timestamp: 't', candidates: [CANDIDATE], rejected: [] },
    stockScanRequest: { strategy: 'pullback_ema' },
  } as never);
  render(<><Step4StocksPage /><BacktestPage /></>);
  fireEvent.click(card(/^Breakout from tight base$/));       // change selection after the scan
  fireEvent.click(screen.getByRole('button', { name: 'Expand AAPL' })); // open the row
  expect(mockCardProps).toHaveBeenLastCalledWith(expect.objectContaining({ strategyKey: 'pullback_ema' }));
});

it("with no request on record, uses the row's own strategy, never a mismatching lastStockScanStrategy (P1-F1)", () => {
  useScanStore.setState({
    activeStrategy: 'breakout_base',
    stockScanResult: { scan_id: 'S', timestamp: 't', candidates: [CANDIDATE], rejected: [] },
    stockScanRequest: null, lastStockScanStrategy: 'ma_crossover',
  } as never);
  render(<BacktestPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Expand AAPL' }));
  expect(mockCardProps).toHaveBeenLastCalledWith(expect.objectContaining({ strategyKey: 'pullback_ema' }));
});
