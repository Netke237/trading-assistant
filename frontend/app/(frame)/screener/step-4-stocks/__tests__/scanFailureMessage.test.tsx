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
// This suite does not mock @/lib/api; the row would call the real backend.
jest.mock('../HistoryPrefetchRow', () => ({ HistoryPrefetchRow: () => null }));

/**
 * Replace a store method with one that throws, and hand back the undo.
 *
 * NOT jest.spyOn: zustand builds the next state object by copying the current
 * one, so a spied method is copied along with it and mockRestore() then writes
 * the original back onto the OLD object while the live state keeps the spy —
 * a throwing store write installed that way leaks into every later case.
 */
function breakStoreWrite(key: 'setScanState' | 'setStockScanError'): () => void {
  const original = useScanStore.getState()[key];
  useScanStore.setState({ [key]: () => { throw new Error('QuotaExceededError'); } } as never);
  return () => useScanStore.setState({ [key]: original } as never);
}

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
    // AFTER clearAllMocks (which clears calls but NOT implementations), so the
    // last case's mockRejectedValue cannot leak into a case reordered after
    // it, and so this suite survives clearMocks/resetMocks being turned on.
    failWith(null);
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

  it('says so plainly when no reason was recorded, rather than blaming the backend', async () => {
    failWith(null);
    await runScan();
    expect(await screen.findByText('Scan failed — unknown error')).toBeInTheDocument();
  });

  it('surfaces a rejection that never became a null return', async () => {
    // runStockScan converts its own failures into a null return, but a throw
    // from setScanState itself still escapes; without the handler's try/catch
    // that leaves onRun() with an unhandled rejection and the page shows
    // nothing at all. The mock enters SCANNING before throwing, as the real
    // one does, because clearing that state is half of what the catch is for.
    (runStockScan as jest.Mock).mockImplementation(async () => {
      useScanStore.setState({ scanState: 'SCANNING' } as never);
      throw new Error('store is not hydrated');
    });
    await runScan();
    expect(await screen.findByText('Scan failed — store is not hydrated')).toBeInTheDocument();
    // …and the Run button is usable again: the throw left SCANNING set.
    expect(useScanStore.getState().scanState).toBe('FAILED');
  });

  it('still shows the reason when the store write is itself what failed', async () => {
    // The case this catch is written for is `setScanState` throwing. Resetting
    // the state BEFORE showing the message meant that exact case threw again
    // and the user was told nothing — so the order is load-bearing, not style.
    (runStockScan as jest.Mock).mockRejectedValue(new Error('QuotaExceededError'));
    const undo = breakStoreWrite('setScanState');

    try {
      await runScan();
      expect(await screen.findByText('Scan failed — QuotaExceededError')).toBeInTheDocument();
    } finally { undo(); }
  });

  it('still reaches FAILED when the reason write is what threw', async () => {
    // The belt guards its two store writes ONE EACH: a throw out of the first
    // must not skip the FAILED reset, which is what re-enables the Run button.
    (runStockScan as jest.Mock).mockRejectedValue(new Error('QuotaExceededError'));
    const undo = breakStoreWrite('setStockScanError');

    try {
      await runScan();
      expect(useScanStore.getState().scanState).toBe('FAILED');
    } finally { undo(); }
  });
});
