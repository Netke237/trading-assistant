import '@testing-library/jest-dom';
import { render, act, fireEvent, screen } from '@testing-library/react';
import Step4StocksPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore, SCAN_PARAM_DEFAULTS } from '@/lib/scanParamsStore';
import { runStockScan } from '@/lib/stockScan';

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
  runStockScan: jest.fn(() => Promise.resolve(null)),
}));
jest.mock('@/lib/api', () => ({
  api: { startHistoryPrefetch: jest.fn(), getHistoryPrefetchStatus: jest.fn() },
  getLastDataRefresh: jest.fn(() => Promise.resolve({ last_refresh: null })),
  API_BASE_URL: 'http://localhost:8000',
}));
jest.mock('@/components/organisms/StockPositionCard', () => ({ StockPositionCard: () => null }));
jest.mock('@/components/organisms/StockSendDialog', () => ({ StockSendDialog: () => null }));
jest.mock('@/components/organisms/ScanFunnel', () => ({ ScanFunnel: () => null }));
jest.mock('@/components/atoms/WatchStar', () => ({ WatchStar: () => null }));

beforeEach(() => {
  (runStockScan as jest.Mock).mockClear();
  useScanParamsStore.setState({ ...SCAN_PARAM_DEFAULTS });
  useScanStore.setState({
    context: { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)' },
    activeStrategy: null, stockScanResult: null, stockScanRequest: null,
    lastStockScanStrategy: null, scanState: 'IDLE', stockScanError: null,
  } as never);
});

it('a scan run after hydration finishes uses the persisted params, not the pre-hydration defaults', async () => {
  let finish: (() => void) | undefined;
  const persist = useScanParamsStore.persist;
  const hasHydrated = jest.spyOn(persist, 'hasHydrated').mockReturnValue(false);
  const onFinish = jest.spyOn(persist, 'onFinishHydration').mockImplementation((cb) => {
    finish = () => cb(useScanParamsStore.getState());
    return () => {};
  });
  try {
    useScanStore.setState({ activeStrategy: 'pullback_ema', scanState: 'IDLE' } as never);
    render(<Step4StocksPage />);
    // `?.`: a page that never subscribes leaves `finish` unset; the assertion
    // below, not a TypeError here, is what must report that.
    act(() => { useScanParamsStore.setState({ pullbackEmaPeriod: 34 }); finish?.(); });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Run Stock Scan' })); });
    expect(runStockScan).toHaveBeenCalledWith('pullback_ema', expect.objectContaining({ pullbackEmaPeriod: 34 }));
  } finally {
    hasHydrated.mockRestore();
    onFinish.mockRestore();
  }
});
