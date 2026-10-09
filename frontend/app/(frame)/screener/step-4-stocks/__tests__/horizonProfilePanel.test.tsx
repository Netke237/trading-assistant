/*
 * STOCKS-HORIZON-T1 H5: the Step-4 strategy panel shows the backend horizon
 * profile's value; an edit is an override; "reset to profile" drops it.
 */
import '@testing-library/jest-dom';
import { render, act, fireEvent, screen } from '@testing-library/react';
import Step4StocksPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore, SCAN_PARAM_DEFAULTS } from '@/lib/scanParamsStore';
import { useStrategyProfilesStore } from '@/lib/strategyProfilesStore';
import { runStockScan } from '@/lib/stockScan';
import { api } from '@/lib/api';
import { profilesPayload, withTuned } from '@/lib/testFixtures/strategyProfiles';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => '/screener/step-4-stocks',
}));
jest.mock('@/lib/stockScan', () => ({
  ...jest.requireActual('@/lib/stockScan'),
  runStockScanWithContinuation: async (...args: unknown[]) => {
    await jest.requireMock('@/lib/stockScan').runStockScan(...args);
    return { kind: 'failure', token: -1, reason: 'mocked' };
  },
  runStockScan: jest.fn(() => Promise.resolve(null)),
}));
jest.mock('@/lib/api', () => ({
  api: {
    startHistoryPrefetch: jest.fn(), getHistoryPrefetchStatus: jest.fn(),
    getStrategyProfiles: jest.fn(),
  },
  getLastDataRefresh: jest.fn(() => Promise.resolve({ last_refresh: null })),
  API_BASE_URL: 'http://localhost:8000',
}));
jest.mock('@/components/organisms/StockPositionCard', () => ({ StockPositionCard: () => null }));
jest.mock('@/components/organisms/StockSendDialog', () => ({ StockSendDialog: () => null }));
jest.mock('@/components/organisms/ScanFunnel', () => ({ ScanFunnel: () => null }));
jest.mock('@/components/atoms/WatchStar', () => ({ WatchStar: () => null }));

const getProfiles = api.getStrategyProfiles as jest.Mock;

beforeEach(() => {
  (runStockScan as jest.Mock).mockClear();
  getProfiles.mockReset();
  useStrategyProfilesStore.setState({ profiles: null, status: 'idle', error: null });
  useScanParamsStore.setState({ ...SCAN_PARAM_DEFAULTS });
  useScanStore.setState({
    context: { universe: 'SP500', direction: 'Bullish', horizon: 'Position (45–60d)',
      horizonPreset: 'Quarterly', holdMin: 45, holdMax: 60 },
    activeStrategy: 'pullback_ema', stockScanResult: null, stockScanRequest: null,
    lastStockScanStrategy: null, scanState: 'IDLE', stockScanError: null,
  } as never);
});

const tolerance = () => screen.getByLabelText('Pullback tolerance') as HTMLInputElement;

it('shows the profile value, then the override after an edit, then the profile after reset', async () => {
  getProfiles.mockResolvedValue(
    withTuned(profilesPayload(), 'pullback_ema', 'Bullish', 'Quarterly', { tolerance: 0.06 }),
  );
  await act(async () => { render(<Step4StocksPage />); });

  expect(tolerance().value).toBe('6');
  expect(screen.getByTestId('profile-source-pullback_ema')).toHaveTextContent('tuned');
  expect(screen.queryByRole('button', { name: 'Reset Pullback tolerance to profile' })).toBeNull();

  fireEvent.change(tolerance(), { target: { value: '7.5' } });
  expect(tolerance().value).toBe('7.5');

  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Run Stock Scan' })); });
  expect(runStockScan).toHaveBeenLastCalledWith('pullback_ema', expect.objectContaining({
    pullbackTolerancePct: 0.075, pullbackEmaPeriod: null,
  }));

  fireEvent.click(screen.getByRole('button', { name: 'Reset Pullback tolerance to profile' }));
  expect(tolerance().value).toBe('6');
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Run Stock Scan' })); });
  expect(runStockScan).toHaveBeenLastCalledWith('pullback_ema', expect.objectContaining({ pullbackTolerancePct: null }));
});

it('Custom names the tuned horizon it uses', async () => {
  getProfiles.mockResolvedValue(profilesPayload());
  useScanStore.setState({
    context: { universe: 'SP500', direction: 'Bullish', horizon: 'Position (60–185d)',
      horizonPreset: 'Custom', holdMin: 60, holdMax: 185 },
  } as never);
  await act(async () => { render(<Step4StocksPage />); });
  expect(screen.getByText('Custom: using Annual settings')).toBeInTheDocument();
});

it('a failed fetch says the scan uses the backend values and shows only overrides', async () => {
  getProfiles.mockRejectedValue(new Error('down'));
  useScanParamsStore.setState({ maCrossoverFast: 12 });
  await act(async () => { render(<Step4StocksPage />); });
  expect(screen.getByText('Profile unavailable — the scan uses the backend\'s values')).toBeInTheDocument();
  expect(tolerance().value).toBe('');
  expect((screen.getByLabelText('MA crossover fast') as HTMLInputElement).value).toBe('12');
});
