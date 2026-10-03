import '@testing-library/jest-dom';
import { fireEvent, render, screen } from '@testing-library/react';
import AlertsPage from '../page';
import { useAlertStore, DEFAULT_CONFIG } from '@/lib/alertStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useScanStore } from '@/lib/scanStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { useChartAlertStore, OFFLINE_SAVE_REASON } from '@/lib/chartAlertStore';

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

    // The Alert-types toggle row names the TYPE, which covers options and both
    // stock sides (STOP-SEMANTICS-2026-10-02).
    expect(screen.getByText('Premium / stock stop (±60%)')).toBeInTheDocument();
    expect(screen.queryByText(/–40%/)).not.toBeInTheDocument();
  });

  it('reflects a non-default premiumStopPct instead of a hardcoded value', () => {
    useSettingsStore.setState({ premiumStopPct: 0.45 } as any);

    render(<AlertsPage />);

    expect(screen.getByText('Premium / stock stop (±45%)')).toBeInTheDocument();
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

    expect(screen.getByText('Premium / stock stop (±60%)')).toBeInTheDocument();
  });
});

// ── STOP-SEMANTICS-2026-10-02 ───────────────────────────────────────────────
describe('Alerts page — a fired row is labelled with the SIDE it fired under', () => {
  const row = (over: Record<string, unknown>) => ({
    id: 't1', recId: 'r1', symbol: 'AAPL', kind: 'Critical', alertType: 'PREMIUM_STOP',
    reason: 'x', firedAt: new Date().toISOString(), acknowledged: false,
    premiumStopPct: 0.25, ...over,
  });
  const shortPosition = { recId: 'r1', symbol: 'AAPL', contract: 'AAPL|STOCK', direction: 'Bearish', premiumStopPct: 0.25 };

  beforeEach(() => { useSettingsStore.setState({ premiumStopPct: 0.60 } as any); });

  it.each([
    ['short-stock', 'Stock stop (+25%)'],
    ['long-stock', 'Stock stop (–25%)'],
    ['option', 'Premium stop (–25%)'],
  ])('%s -> %s', (stopSide, label) => {
    useAlertStore.setState({ toasts: [row({ stopSide })], config: DEFAULT_CONFIG } as any);
    render(<AlertsPage />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it('an UNSTAMPED row for a short keeps the legacy label (it fired on the old fall-side rule)', () => {
    usePortfolioStore.setState({ positions: [shortPosition] } as any);
    useAlertStore.setState({ toasts: [row({})], config: DEFAULT_CONFIG } as any);
    render(<AlertsPage />);
    expect(screen.getByText('Premium stop (–25%)')).toBeInTheDocument();
    expect(screen.queryByText(/Stock stop \(\+/)).not.toBeInTheDocument();
  });
});

// ── A4f-rules ────────────────────────────────────────────────────────────────
// The backend migrates stored HMM_intraday composite rules off '1D'/'1W' to '5min'
// and marks the name. The rules table reads the persisted local copy, so the page
// must refresh from GET /alerts/rules on mount -- otherwise it shows (and a toggle
// re-PUTs) the stale '1D'.
describe('Alerts page — rules are refreshed from the backend on mount (A4f-rules)', () => {
  const composite = { primary: { model: 'HMM_intraday', to_state: 'Bull' }, confirmations: [] };
  const rule = (over: Record<string, unknown>) => ({
    id: 'r1', name: 'X', symbol: 'AAPL', interval: '1D', enabled: true,
    group: { logic: 'AND', conditions: [] }, cooldown_minutes: 60, expiry_date: null,
    created_at: '2026-09-01T00:00:00', last_triggered_at: null,
    rule_type: 'composite', composite_def: composite, ...over,
  });

  it('shows the server copy of a migrated rule, not the stale local one', async () => {
    useChartAlertStore.setState({ rules: [rule({})] } as any);
    const fetchMock = jest.fn((url: string) => {
      if (String(url).endsWith('/alerts/rules')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([rule({ interval: '5min', name: 'X (interval was 1D)' })]),
        });
      }
      return Promise.resolve({ ok: false });
    });
    global.fetch = fetchMock as unknown as typeof fetch;

    render(<AlertsPage />);
    fireEvent.click(screen.getByRole('button', { name: 'Rules' }));

    expect(await screen.findByText('X (interval was 1D)')).toBeInTheDocument();
    expect(screen.getByText('5min')).toBeInTheDocument();
    expect(screen.queryByText('1D')).not.toBeInTheDocument();
    const ruleGets = fetchMock.mock.calls.filter(([u]) => String(u).endsWith('/alerts/rules'));
    expect(ruleGets).toHaveLength(1);
  });
});

describe('Alerts page — P4a rule rows', () => {
  const r = {
    id: 'c1', name: 'Bull flip', symbol: 'AAPL', interval: '15min', enabled: true,
    group: { logic: 'AND', conditions: [] }, rule_type: 'composite',
    composite_def: { primary: { model: 'OMM', to_state: 'Bull' }, confirmations: [] },
    cooldown_minutes: 60, expiry_date: null, created_at: '2026-09-01T00:00:00', last_triggered_at: null,
  };
  const openRules = () => {
    const tab = screen.queryByRole('button', { name: /^rules/i }) ?? screen.queryByText(/^Rules/);
    if (tab) fireEvent.click(tab);
  };

  it('shows "Not saved to server" with the reason for a refused rule', () => {
    useChartAlertStore.setState({ rules: [r], unsavedRules: { c1: 'HMM_intraday needs an intraday interval' } } as any);
    useChartAlertStore.setState({ syncRules: async () => {} } as any);
    render(<AlertsPage />);
    openRules();
    expect(screen.getByText('Not saved to server: HMM_intraday needs an intraday interval')).toBeInTheDocument();
  });

  it('CHART-RULE-OFFLINE-SAVE-MARK T6: shows the offline reason for an unconfirmed save', () => {
    useChartAlertStore.setState({ rules: [r], unsavedRules: { c1: OFFLINE_SAVE_REASON } } as any);
    useChartAlertStore.setState({ syncRules: async () => {} } as any);
    render(<AlertsPage />);
    openRules();
    expect(screen.getByText(
      'Not saved to server: could not reach the server; retried when the Alerts page or a chart next opens',
    )).toBeInTheDocument();
  });

  it('the toggle calls setRuleEnabled, not updateRule', () => {
    const setRuleEnabled = jest.fn();
    const updateRule = jest.fn();
    useChartAlertStore.setState({ rules: [r], unsavedRules: {}, setRuleEnabled, updateRule, syncRules: async () => {} } as any);
    render(<AlertsPage />);
    openRules();
    fireEvent.click(screen.getByRole('switch'));
    expect(setRuleEnabled).toHaveBeenCalledWith('c1', false);
    expect(updateRule).not.toHaveBeenCalled();
  });
});
