/**
 * P2-02 (decision Q7) + R3-1 / R3-5 / R3-6 / R4-1 / R4-2 / R5-1 -- the Settings
 * page's global premium stop: capped at 99%, a stored legacy value is shown
 * and explained truthfully, and the sub-cent entry limit is computed from the
 * stored value. Plan:
 * docs/superpowers/plans/2026-09-25-p2-premium-stop-position-editing-plan.md
 */
import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import SettingsPage from '../page';
import { getRiskSettings, saveRiskSettings } from '@/lib/api';
import { useSettingsStore } from '@/lib/settingsStore';

jest.mock('@/lib/api', () => ({
  api: { postCredentials: jest.fn().mockResolvedValue(undefined) },
  getRiskSettings: jest.fn(),
  saveRiskSettings: jest.fn().mockResolvedValue(undefined),
}));

const mockGet = getRiskSettings as jest.MockedFunction<typeof getRiskSettings>;
const mockSave = saveRiskSettings as jest.MockedFunction<typeof saveRiskSettings>;
const riskBody = (premiumStopPct: number) => ({
  premiumStopPct, portfolioValue: 250000, maxSinglePositionPct: 0.02, maxLossPerTradePct: 0.015,
  maxTotalExposurePct: 0.40, maxConcurrentPositions: 15, maxDailyRecommendations: 8,
  targetT1Pct: 0.20, targetT2Pct: 0.35, targetT3Pct: 0.50,
});

async function openRisk(pct: number) {
  mockGet.mockResolvedValue(riskBody(pct));
  render(<SettingsPage />);
  fireEvent.click(screen.getByText('Risk'));
  await waitFor(() => expect(useSettingsStore.getState().premiumStopPct).toBe(pct));
  const label = screen.getByText('Premium stop loss');
  const row = label.closest('div')!.parentElement!;
  return row.querySelector('input') as HTMLInputElement;
}

beforeEach(() => { jest.clearAllMocks(); useSettingsStore.setState({ premiumStopPct: 0.6 }); });

describe('Settings — global premium stop', () => {
  it('a loaded legacy 1.0: never-fires caution, no "Infinity"; blur saves 0.99 and the caution goes', async () => {
    const input = await openRisk(1.0);
    expect(screen.getByText('Stored 100% can never fire for long positions and options, in this browser or on the server. Save to apply 99%.')).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/Infinity/);
    expect(screen.queryByText(/sub-penny quote/)).not.toBeInTheDocument();

    fireEvent.blur(input);
    await waitFor(() => expect(mockSave).toHaveBeenCalledWith(expect.objectContaining({ premiumStopPct: 0.99 })));
    await waitFor(() => expect(screen.queryByText(/Stored 100% can never fire/)).not.toBeInTheDocument());
    expect(useSettingsStore.getState().premiumStopPct).toBe(0.99);
  });

  it('a loaded 0.995: its real percentage, no never-fires claim, and the sub-cent limit from the RAW value ($2.00)', async () => {
    await openRisk(0.995);
    expect(screen.getByText('Stored 99.5% is above the 99% maximum. Save to apply 99%.')).toBeInTheDocument();
    expect(screen.queryByText(/Stored 100% can never fire/)).not.toBeInTheDocument();
    expect(screen.getByText('At 99.5%, for long positions and options an entry below $2.00 puts the stop threshold below $0.01 — it can never fire.')).toBeInTheDocument();
  });

  it('an ordinary 0.60: no caution; the limit rounds UP to the cent ($0.025 -> $0.03)', async () => {
    await openRisk(0.6);
    expect(screen.queryByText(/Save to apply 99%/)).not.toBeInTheDocument();
    expect(screen.getByText('At 60%, for long positions and options an entry below $0.03 puts the stop threshold below $0.01 — it can never fire.')).toBeInTheDocument();
    // N9 -- the same global governs a short's RISE-side stop.
    expect(screen.getByText('For short stock positions this is how far the price may RISE above entry.')).toBeInTheDocument();
  });

  it('0.99: the limit is exactly $1.00 (no float cent added)', async () => {
    await openRisk(0.99);
    expect(screen.getByText(/an entry below \$1\.00 puts/)).toBeInTheDocument();
  });

  it('0.80: the limit is the first entry that fires ($0.06), not $0.05', async () => {
    // STOP-SEMANTICS (R2-2): the limit is derived THROUGH the sub-cent
    // predicate. $0.05 x (1 - 0.8) is 0.009999999999999998, a few ulps under a
    // cent, so a $0.05 entry never fires; the old closed form named it.
    await openRisk(0.8);
    expect(screen.getByText(/At 80%, for long positions and options an entry below \$0\.06 puts/)).toBeInTheDocument();
  });

  it('typing 1 stores 0.99', async () => {
    const input = await openRisk(0.6);
    fireEvent.change(input, { target: { value: '1' } });
    fireEvent.blur(input);
    await waitFor(() => expect(mockSave).toHaveBeenCalledWith(expect.objectContaining({ premiumStopPct: 0.99 })));
    expect(input).toHaveAttribute('max', '0.99');
    expect(input).toHaveAttribute('step', '0.01');
  });
});
