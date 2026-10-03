/**
 * STEP3-PARAM-REACH (code round 3): the Step-1 regime verdict follows the
 * context's direction. StoreHydration can restore a scan's context AFTER the
 * regime fetch resolved; the verdict used to be computed only then, so a
 * Bearish restore left a Bullish verdict on the REJECT gate and the Step-7 rail.
 */
import '@testing-library/jest-dom';
import { act, render, waitFor } from '@testing-library/react';
import Step1RegimePage from '../page';
import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => '/screener/step-1-regime',
}));
jest.mock('@/components/organisms/CandlestickChart', () => ({ CandlestickChart: () => null }));
jest.mock('@/components/organisms/RunScanButton', () => ({ RunScanButton: () => null }));
jest.mock('@/components/molecules/NewsCard', () => ({ NewsCard: () => null }));
jest.mock('@/components/molecules/MarketSentiment', () => ({ MarketSentiment: () => null }));
jest.mock('@/lib/api', () => ({
  api: {
    getRegime: jest.fn(),
    getSectors: jest.fn().mockResolvedValue([]),
    getCandles: jest.fn().mockResolvedValue([]),
    getNews: jest.fn().mockResolvedValue([]),
  },
}));

const BULL_REGIME = {
  overall: 'PASS', regime_direction: 'BULLISH',
  omm: { state: 'Bull', p_stay: 0.8, state_order: ['Bull'], transition_row: [0.8] },
};

describe('Step 1 — the regime verdict follows the context direction', () => {
  beforeEach(() => {
    (api.getRegime as jest.Mock).mockResolvedValue(BULL_REGIME);
    useScanStore.setState({ context: null, combinedRegime: 'PENDING' } as never);
  });

  it('a context restored as Bearish after the regime fetch turns a Bull-regime PASS into REJECT', async () => {
    render(<Step1RegimePage />);
    await waitFor(() => expect(useScanStore.getState().combinedRegime).toBe('PASS'));
    act(() => {
      useScanStore.setState({
        context: { universe: 'SP500', direction: 'Bearish', horizon: 'Position (45–60d)',
          horizonPreset: 'Quarterly', holdMin: 45, holdMax: 60 },
      } as never);
    });
    await waitFor(() => expect(useScanStore.getState().combinedRegime).toBe('REJECT'));
  });

  it('before the regime fetch answers, a direction change leaves the verdict PENDING', async () => {
    (api.getRegime as jest.Mock).mockReturnValue(new Promise(() => {}));
    render(<Step1RegimePage />);
    act(() => {
      useScanStore.setState({ context: { universe: 'SP500', direction: 'Bearish', horizon: 'Swing (5–15d)',
        horizonPreset: 'Swing', holdMin: 5, holdMax: 15 } } as never);
    });
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(useScanStore.getState().combinedRegime).toBe('PENDING');
  });
});
