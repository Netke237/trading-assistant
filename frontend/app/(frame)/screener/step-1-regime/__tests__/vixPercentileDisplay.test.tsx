import '@testing-library/jest-dom';
import { render, screen, waitFor } from '@testing-library/react';
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

const MOCK_REGIME = {
  overall: 'PASS',
  regime_direction: 'BULL',
  vix_pct_30d: 0.0,
  vix_pct_252d: 0.0,
  omm: {
    state: 'Bull',
    p_stay: 0.85,
    stability: 'Stable',
    regime_age_days: 15,
    avg_regime_duration: 25,
    transition_row: [0.85, 0.1, 0.05],
    state_order: ['Bull', 'Bear', 'Choppy'],
    conviction_pct: 50,
    conviction_label: 'Strong',
  },
};

describe('Step 1 — VIX percentile display', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useScanStore.setState({ context: null, combinedRegime: 'PENDING' } as never);
  });

  it('renders VIX percentile with the 252-day window label when vix_pct_252d is 0.0 (0th)', async () => {
    (api.getRegime as jest.Mock).mockResolvedValue(MOCK_REGIME);

    render(<Step1RegimePage />);

    await waitFor(() => {
      // Both Swing and Position columns render: "VIX at 0th percentile (252-day window)"
      const elements = screen.getAllByText('VIX at 0th percentile (252-day window)');
      expect(elements.length).toBeGreaterThanOrEqual(1);
    });
  });

  it('renders correct "3rd" ordinal for vix_pct_252d = 2.7 (defect B3-4 reproduction)', async () => {
    (api.getRegime as jest.Mock).mockResolvedValue({
      ...MOCK_REGIME,
      vix_pct_252d: 2.7,
    });

    render(<Step1RegimePage />);

    await waitFor(() => {
      const elements = screen.getAllByText('VIX at 3rd percentile (252-day window)');
      expect(elements.length).toBe(2); // Swing and Position
      expect(screen.queryByText(/3th percentile/)).not.toBeInTheDocument();
    });
  });

  it.each([
    [1.0, '1st'],
    [2.0, '2nd'],
    [11.0, '11th'],
    [12.0, '12th'],
    [13.0, '13th'],
    [21.0, '21st'],
    [22.0, '22nd'],
    [23.0, '23rd'],
  ])('renders correct ordinal %s -> %s for 252-day window', async (pct, expectedOrdinal) => {
    (api.getRegime as jest.Mock).mockResolvedValue({
      ...MOCK_REGIME,
      vix_pct_252d: pct,
    });

    render(<Step1RegimePage />);

    await waitFor(() => {
      const elements = screen.getAllByText(`VIX at ${expectedOrdinal} percentile (252-day window)`);
      expect(elements.length).toBe(2);
    });
  });

  it('renders correct ordinal suffix for 30-day window in intraday HMM column', async () => {
    (api.getRegime as jest.Mock).mockResolvedValue({
      ...MOCK_REGIME,
      vix_pct_30d: 23.4,
      intraday_hmm: {
        state: 'Trending',
        p_stay: 0.9,
        p_transition: [{ to: 'Choppy', prob: 0.1 }],
      },
    });

    render(<Step1RegimePage />);

    await waitFor(() => {
      expect(screen.getByText('VIX at 23rd percentile (30-day window)')).toBeInTheDocument();
    });
  });

  it('renders correct ordinal suffix for 30-day window in intraday OMM fallback column', async () => {
    (api.getRegime as jest.Mock).mockResolvedValue({
      ...MOCK_REGIME,
      vix_pct_30d: 0.9,
      intraday_hmm: null,
      intraday_omm: {
        state: 'Bull',
        p_stay: 0.8,
        stability: 'Stable',
        regime_age_days: 5,
        avg_regime_duration: 10,
        transition_row: [0.8, 0.2],
        state_order: ['Bull', 'Bear'],
      },
    });

    render(<Step1RegimePage />);

    await waitFor(() => {
      expect(screen.getByText('VIX at 1st percentile (30-day window)')).toBeInTheDocument();
    });
  });

  it('omits 252-day percentile text when vix_pct_252d is null', async () => {
    (api.getRegime as jest.Mock).mockResolvedValue({
      ...MOCK_REGIME,
      vix_pct_252d: null,
    });

    render(<Step1RegimePage />);

    await waitFor(() => {
      expect(screen.queryByText(/252-day window/)).not.toBeInTheDocument();
    });
  });

  it('omits 30-day percentile text when vix_pct_30d is null', async () => {
    (api.getRegime as jest.Mock).mockResolvedValue({
      ...MOCK_REGIME,
      vix_pct_30d: null,
      intraday_hmm: {
        state: 'Trending',
        p_stay: 0.9,
        p_transition: [],
      },
    });

    render(<Step1RegimePage />);

    await waitFor(() => {
      expect(screen.queryByText(/30-day window/)).not.toBeInTheDocument();
    });
  });
});
