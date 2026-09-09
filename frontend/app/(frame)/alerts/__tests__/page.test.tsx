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

// ── ALERT-THRESHOLD-STAMP-2026-09-05 ────────────────────────────────────────
describe('Alerts page — a fired row is labelled with the threshold it fired at', () => {
  const firedToast = (over: Record<string, unknown> = {}) => ({
    id: 't1',
    recId: 'r1',
    symbol: 'AAPL',
    kind: 'Critical',
    alertType: 'PREMIUM_STOP',
    reason: 'Premium stop — AAPL down 30.0%',
    firedAt: new Date().toISOString(),
    acknowledged: false,
    ...over,
  });

  it('prefers the stamp over what the position resolves to NOW', () => {
    // THE DEFECT. The alert fired at 30%; the user has since re-pinned the
    // position to 55%. Live resolution relabelled the historical row 55%.
    useSettingsStore.setState({ premiumStopPct: 0.60 } as any);
    usePortfolioStore.setState({
      positions: [{ recId: 'r1', symbol: 'AAPL', contract: 'AAPL|190|2026-05-15|C', premiumStopPct: 0.55 }],
    } as any);
    useAlertStore.setState({
      toasts: [firedToast({ premiumStopPct: 0.30 })], config: DEFAULT_CONFIG,
    } as any);

    render(<AlertsPage />);

    expect(screen.getByText('Premium stop (–30%)')).toBeInTheDocument();
    expect(screen.queryByText('Premium stop (–55%)')).not.toBeInTheDocument();
  });

  it('is not disturbed by the position being edited, or closed entirely', () => {
    // A closed position resolves to the global. The stamped row must not move.
    useSettingsStore.setState({ premiumStopPct: 0.60 } as any);
    usePortfolioStore.setState({ positions: [] } as any);
    useAlertStore.setState({
      toasts: [firedToast({ premiumStopPct: 0.30 })], config: DEFAULT_CONFIG,
    } as any);

    render(<AlertsPage />);

    expect(screen.getByText('Premium stop (–30%)')).toBeInTheDocument();
  });

  it('falls back to live resolution for a row persisted before the stamp existed', () => {
    // Absent is meaningful: an unstamped row has no better answer available
    // than what the position resolves to now.
    useSettingsStore.setState({ premiumStopPct: 0.60 } as any);
    usePortfolioStore.setState({
      positions: [{ recId: 'r1', symbol: 'AAPL', contract: 'AAPL|190|2026-05-15|C', premiumStopPct: 0.45 }],
    } as any);
    useAlertStore.setState({
      toasts: [firedToast()], config: DEFAULT_CONFIG,
    } as any);

    render(<AlertsPage />);

    expect(screen.getByText('Premium stop (–45%)')).toBeInTheDocument();
  });

  it('still labels the SETTINGS row with the global — that row IS the global', () => {
    // The settings "Alert types" list is not a fired alert and must keep
    // resolving live, or the toggle would be captioned with some past alert's
    // threshold.
    useSettingsStore.setState({ premiumStopPct: 0.60 } as any);
    usePortfolioStore.setState({ positions: [] } as any);
    useAlertStore.setState({
      toasts: [firedToast({ premiumStopPct: 0.30 })], config: DEFAULT_CONFIG,
    } as any);

    render(<AlertsPage />);

    expect(screen.getByText('Premium stop (–60%)')).toBeInTheDocument();
  });
});
