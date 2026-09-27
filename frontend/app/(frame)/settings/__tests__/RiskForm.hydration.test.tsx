import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import SettingsPage from '../page';
import { useRiskStore } from '@/lib/riskStore';
import { getRiskSettings, saveRiskSettings } from '@/lib/api';

// Regression test for PLAN_TIER1_RISK_SAFETY.md item 1b: the Settings page's
// backend-fetch effect used to update only the local `useState` mirror of the
// risk limits, never the global `riskStore` that SendToBrokerDialog actually
// enforces against before sending a trade. Between page load and the user's
// first slider touch, the send-dialog gate silently enforced whatever stale
// value was already persisted in the browser, even though the screen (and the
// backend) showed something different.
//
// Round 1's test plan ("save a setting, confirm the store reflects it") would
// have already passed on unfixed code, because every slider's onChange calls
// updateLimit() -> setLimits() in real time. This test instead exercises the
// hydration path in isolation: seed the store with a stale value, mock the
// backend to return a materially different one, mount the page, and assert
// the global store reflects the backend value WITHOUT simulating any slider
// interaction.

jest.mock('@/lib/api', () => ({
  api: {
    postCredentials: jest.fn().mockResolvedValue(undefined),
  },
  getRiskSettings: jest.fn(),
  saveRiskSettings: jest.fn().mockResolvedValue(undefined),
}));

const mockGetRiskSettings = getRiskSettings as jest.MockedFunction<typeof getRiskSettings>;

const STALE_LIMITS = {
  maxSingleTradeExposurePct: 0.05,
  maxTotalExposurePct: 0.25,
  maxConcurrentPositions: 10,
  maxDailyRecommendations: 5,
  portfolioValue: 100000,
  maxLossPerTradePct: 0.0375, maxSingleStockPositionPct: 0.2, maxTotalStockExposurePct: 1,
};

describe('Settings page — risk store hydration', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useRiskStore.setState({
      limits: { ...STALE_LIMITS },
      dailyRecommendations: 0,
      lastResetDate: new Date().toISOString().split('T')[0],
      metrics: {
        totalExposurePct: 0,
        concurrentPositions: 0,
        dailyRecommendations: 0,
        largestConcentrationPct: 0,
        largestConcentrationSymbol: '—', stockExposurePct: 0, largestStockConcentrationPct: 0, largestStockConcentrationSymbol: '—',
        status: 'PASS',
      },
      symbols: [],
    });
  });

  it('applies the backend-fetched risk limits to the global store on mount, without any slider interaction', async () => {
    // The backend holds a materially different maxSinglePositionPct than
    // what's currently persisted in the (pre-seeded) riskStore — simulating
    // a value changed in another session/device.
    mockGetRiskSettings.mockResolvedValue({
      premiumStopPct: 0.60,
      portfolioValue: 250000,
      maxSinglePositionPct: 0.02,
      maxLossPerTradePct: 0.015,
      maxTotalExposurePct: 0.40,
      maxConcurrentPositions: 15,
      maxDailyRecommendations: 8,
      targetT1Pct: 0.20,
      targetT2Pct: 0.35,
      targetT3Pct: 0.50,
    });

    render(<SettingsPage />);

    // Navigate to the Risk section to mount RiskForm and trigger its
    // fetch-on-mount effect — no slider is touched anywhere in this test.
    fireEvent.click(screen.getByText('Risk'));

    await waitFor(() => {
      expect(mockGetRiskSettings).toHaveBeenCalled();
    });

    await waitFor(() => {
      expect(useRiskStore.getState().limits.maxSingleTradeExposurePct).toBe(0.02);
    });
    expect(useRiskStore.getState().limits.portfolioValue).toBe(250000);
    expect(useRiskStore.getState().limits.maxLossPerTradePct).toBe(0.015);
    expect(useRiskStore.getState().limits.maxTotalExposurePct).toBe(0.40);
    expect(useRiskStore.getState().limits.maxConcurrentPositions).toBe(15);
    expect(useRiskStore.getState().limits.maxDailyRecommendations).toBe(8);
  });

  // STOCK-SENDS (plan C1): the stock caps hydrate from the backend and save
  // back with the rest.
  it('hydrates and saves the stock caps', async () => {
    mockGetRiskSettings.mockResolvedValue({
      premiumStopPct: 0.60, portfolioValue: 100000, maxSinglePositionPct: 0.05,
      maxLossPerTradePct: 0.0375, maxTotalExposurePct: 0.25,
      maxSingleStockPositionPct: 0.15, maxTotalStockExposurePct: 0.8,
      maxConcurrentPositions: 10, maxDailyRecommendations: 5,
      targetT1Pct: 0.20, targetT2Pct: 0.35, targetT3Pct: 0.50,
    });
    render(<SettingsPage />);
    fireEvent.click(screen.getByText('Risk'));
    await waitFor(() => expect(useRiskStore.getState().limits.maxSingleStockPositionPct).toBe(0.15));
    expect(useRiskStore.getState().limits.maxTotalStockExposurePct).toBe(0.8);
    const input = screen.getByLabelText('Max single stock position %') as HTMLInputElement;
    expect(input.value).toBe('15');
    fireEvent.change(input, { target: { value: '25' } });
    fireEvent.blur(input);
    await waitFor(() => expect(saveRiskSettings).toHaveBeenCalled());
    expect((saveRiskSettings as jest.Mock).mock.calls.at(-1)[0]).toMatchObject({
      maxSingleStockPositionPct: 0.25, maxTotalStockExposurePct: 0.8,
    });
  });

  it('does not reset the portfolioValue staleness nudge when hydration merely reconciles a divergent backend value', async () => {
    // Regression: the hydration effect's setLimits() call is a resync, not a
    // user edit — a genuinely-stale timestamp must survive a mount that finds
    // the backend disagreeing with the locally-cached portfolioValue (e.g. a
    // value changed in another session/device), exactly the scenario the
    // test above exercises but never asserted on before this diff.
    useRiskStore.setState({ portfolioValueUpdatedAt: '2026-02-01T00:00:00.000Z' });

    mockGetRiskSettings.mockResolvedValue({
      premiumStopPct: 0.60,
      portfolioValue: 250000,
      maxSinglePositionPct: 0.02,
      maxLossPerTradePct: 0.015,
      maxTotalExposurePct: 0.40,
      maxConcurrentPositions: 15,
      maxDailyRecommendations: 8,
      targetT1Pct: 0.20,
      targetT2Pct: 0.35,
      targetT3Pct: 0.50,
    });

    render(<SettingsPage />);
    fireEvent.click(screen.getByText('Risk'));

    await waitFor(() => {
      expect(useRiskStore.getState().limits.portfolioValue).toBe(250000);
    });

    expect(useRiskStore.getState().portfolioValueUpdatedAt).toBe('2026-02-01T00:00:00.000Z');
  });
});
