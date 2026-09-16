import '@testing-library/jest-dom';
import { render, screen, fireEvent, act } from '@testing-library/react';
import Step4StocksPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { runStockScan } from '@/lib/stockScan';

/*
 * The inline error under Run Stock Scan used to be a fixed string — "Scan
 * failed — is the backend running on port 8000?" — shown for every failure,
 * because runStockScan() swallowed the error and returned a bare null. A 4xx
 * from a backend that was plainly running (it answered) therefore told the
 * user to go check whether it was running. These pin that the backend's own
 * reason reaches the page, and that the old hint still covers the case it was
 * actually written for.
 */

jest.mock('@/lib/stockScan', () => ({
  ...jest.requireActual('@/lib/stockScan'),
  runStockScan: jest.fn(),
}));
jest.mock('@/components/organisms/StockPositionCard', () => ({ StockPositionCard: () => null }));
jest.mock('@/components/organisms/StockSendDialog', () => ({ StockSendDialog: () => null }));
jest.mock('@/components/organisms/StrategyParamsPanel', () => ({ StrategyParamsPanel: () => null }));
jest.mock('@/components/organisms/ScanFunnel', () => ({ ScanFunnel: () => null }));
jest.mock('@/components/atoms/WatchStar', () => ({ WatchStar: () => null }));

function failWith(reason: string | null) {
  (runStockScan as jest.Mock).mockImplementation(async () => {
    useScanStore.setState({ stockScanError: reason } as never);
    return null;
  });
}

async function runScan() {
  render(<Step4StocksPage />);
  fireEvent.click(screen.getByRole('button', { name: /pullback/i }));
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: /run stock scan/i }));
  });
}

describe('step-4-stocks — a failed scan shows why', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    act(() => {
      useScanStore.setState({
        context: { direction: 'Bullish', universe: 'SP500' } as never,
        activeStrategy: 'pullback_ema',
        combinedRegime: 'PASS' as never,
        stockScanResult: null,
        previousStockScanResult: null,
        scanState: 'IDLE' as never,
        stockBasket: [],
        stockScanAt: null,
        scanOverrides: {},
        stockScanError: null,
      });
    });
  });

  it("shows the backend's own rejection detail", async () => {
    failWith('API /api/stock-scan → 422: rsi_oversold must be < 50');
    await runScan();
    expect(await screen.findByText(
      'Scan failed — API /api/stock-scan → 422: rsi_oversold must be < 50',
    )).toBeInTheDocument();
  });

  it('falls back to the backend-unreachable hint when no reason was recorded', async () => {
    failWith(null);
    await runScan();
    expect(await screen.findByText(
      'Scan failed — is the backend running on port 8000?',
    )).toBeInTheDocument();
  });
});
