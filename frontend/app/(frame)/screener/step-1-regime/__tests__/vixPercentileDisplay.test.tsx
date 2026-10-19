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

describe('Step 1 — VIX 252-day percentile display', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useScanStore.setState({ context: null, combinedRegime: 'PENDING' } as never);
  });

  it('renders VIX percentile with the 252-day window label when vix_pct_252d is provided', async () => {
    (api.getRegime as jest.Mock).mockResolvedValue(MOCK_REGIME);

    render(<Step1RegimePage />);

    await waitFor(() => {
      // Both Swing and Position columns render: "VIX at {Math.round(vix252)}th percentile (252-day window)"
      const elements = screen.getAllByText('VIX at 0th percentile (252-day window)');
      expect(elements.length).toBeGreaterThanOrEqual(1);
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
});
