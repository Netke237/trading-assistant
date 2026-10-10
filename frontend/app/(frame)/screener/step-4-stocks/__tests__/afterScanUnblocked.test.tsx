/**
 * STOCK-PRES-P4-STRATEGY Task 2 (M11) — once the execution block is lifted
 * (stockExecutionBlock() returns null), the after-scan card shows the approved
 * preview sentence. Separate file so this module mock does not leak into the
 * real-block tests in presentationLayout.test.tsx.
 */
import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import Step4StocksPage from '../page';
import { useScanStore } from '@/lib/scanStore';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => '/screener/step-4-stocks',
}));
jest.mock('@/lib/stockScan', () => ({
  ...jest.requireActual('@/lib/stockScan'),
  runStockScanWithContinuation: jest.fn(),
  runStockScan: jest.fn(),
}));
jest.mock('@/lib/api', () => ({
  api: { startHistoryPrefetch: jest.fn(), getHistoryPrefetchStatus: jest.fn() },
  getLastDataRefresh: jest.fn(() => Promise.resolve({ last_refresh: null })),
  API_BASE_URL: 'http://localhost:8000',
}));
jest.mock('@/lib/stockExecutionSession', () => ({
  ...jest.requireActual('@/lib/stockExecutionSession'),
  stockExecutionBlock: () => null,
}));

beforeEach(() => {
  useScanStore.setState({
    context: { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)' },
    activeStrategy: null, stockScanResult: null, stockScanRequest: null,
    lastStockScanStrategy: null, scanState: 'IDLE', stockScanError: null,
    stockAfterScanIntent: { AAPL: true, MSFT: true },
  } as never);
});

it('with no execution block, two armed symbols show the booking preview sentence', () => {
  render(<Step4StocksPage />);
  expect(screen.getByRole('heading', { name: 'After-scan' })).toBeInTheDocument();
  expect(screen.getByText(
    '2 symbols armed — booked to the paper portfolio only if they PASS on the next scan. '
    + 'Arming itself stays on the position card.',
  )).toBeInTheDocument();
  expect(screen.queryByText(/Unvalidated/)).toBeNull();
});
