import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import AlertsPage from '../page';
import { useAlertStore, DEFAULT_CONFIG } from '@/lib/alertStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useScanStore } from '@/lib/scanStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { useChartAlertStore } from '@/lib/chartAlertStore';

jest.mock('@/lib/api', () => ({
  api: {
    listCompositeWatches: jest.fn().mockResolvedValue([]),
    setCompositeWatchEnabled: jest.fn(),
    removeCompositeWatch: jest.fn(),
  },
}));

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn() }) }));

// The alerts page fetches delivery prefs on mount — stub it out so tests don't hit a real
// network endpoint.
beforeEach(() => {
  global.fetch = jest.fn().mockResolvedValue({ ok: false }) as unknown as typeof fetch;

  useAlertStore.setState({
    toasts: [],
    config: DEFAULT_CONFIG,
  } as any);
  useScanStore.setState({ scanResult: null } as any);
  usePortfolioStore.setState({ positions: [] } as any);
  useWatchlistStore.setState({ added: [] } as any);
  useChartAlertStore.setState({ rules: [] } as any);
});

describe('Alerts page — premium-stop label reflects configured percentage', () => {
  it('shows the default 60% premium-stop percentage', () => {
    useSettingsStore.setState({ premiumStopPct: 0.60 } as any);

    render(<AlertsPage />);

    expect(screen.getByText('Premium stop (–60%)')).toBeInTheDocument();
    expect(screen.queryByText(/–40%/)).not.toBeInTheDocument();
  });

  it('reflects a non-default premiumStopPct instead of a hardcoded value', () => {
    useSettingsStore.setState({ premiumStopPct: 0.45 } as any);

    render(<AlertsPage />);

    expect(screen.getByText('Premium stop (–45%)')).toBeInTheDocument();
    expect(screen.queryByText(/–40%/)).not.toBeInTheDocument();
  });

  it('reflects the configured percentage in a fired alert row, not a hardcoded one', () => {
    useSettingsStore.setState({ premiumStopPct: 0.35 } as any);
    useAlertStore.setState({
      toasts: [
        {
          id: 't1',
          symbol: 'AAPL',
          kind: 'trade',
          alertType: 'PREMIUM_STOP',
          reason: 'Premium down 35% from entry',
          firedAt: new Date().toISOString(),
          acknowledged: false,
        },
      ],
      config: DEFAULT_CONFIG,
    } as any);

    render(<AlertsPage />);

    expect(screen.getAllByText('Premium stop (–35%)').length).toBeGreaterThan(0);
  });
});
