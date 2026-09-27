import '@testing-library/jest-dom';
import { render, screen, fireEvent } from '@testing-library/react';
import SettingsPage from '../page';
import { api, type ScanScheduleEntry } from '@/lib/api';

// P3c item 3 — decision P3C-SCHEDULE-ZERO-RISK-WARNS-2026-09-25. A stocks
// schedule entry saved with risk_pct 0 runs at the backend's 1% default
// (StockScanRequest._stored_zero_is_unset); its Settings row must say so.
// ScheduleEntryRow is private to page.tsx (a Next 15 page may not add named
// exports), so the whole page is rendered and navigated to the Scan section.
//
// Every api.* call reached while the Scan section mounts is mocked (a missing
// one throws in an effect and fails the render):
//   - OperatorTimezoneSection:       api.getSchedulingTimezone
//   - ScheduledScanRetentionSection: api.getScheduledScanRunRetention
//   - ScheduledScansSection:         api.getScanSchedule, api.getScanScheduleEntryRuns
// ScanForm reads only useSettingsStore / useScanStore (no fetch);
// ScheduledScansSection reads useSearchProfilesStore (no fetch).

jest.mock('@/lib/api', () => ({
  api: {
    getSchedulingTimezone: jest.fn(),
    getScheduledScanRunRetention: jest.fn(),
    getScanSchedule: jest.fn(),
    getScanScheduleEntryRuns: jest.fn(),
  },
  getRiskSettings: jest.fn().mockResolvedValue(undefined),
  saveRiskSettings: jest.fn().mockResolvedValue(undefined),
}));

const mockApi = api as jest.Mocked<typeof api>;

const WARNING = /Saved with 0% max loss per trade — ignored; this schedule runs at the 1% default/;

function stocksEntry(riskPct: number): ScanScheduleEntry {
  return {
    id: 'e1',
    label: 'Stocks nightly',
    mode: 'stocks',
    profile_id: 'p1',
    profile_name: 'Stocks profile',
    profile_synced_at: '2026-09-01T00:00:00Z',
    resolved_request: {
      universe: ['SP500'], direction: 'Bullish', horizon: 'Swing', strategy: 'pullback_ema',
      account_size: 50_000, risk_pct: riskPct,
    } as unknown as ScanScheduleEntry['resolved_request'],
    pattern: 'fixed_time',
    enabled: true,
    days_of_week: [0, 1, 2, 3, 4],
    fire_time: '09:00',
  };
}

async function renderScanSection(entry: ScanScheduleEntry) {
  mockApi.getScanSchedule.mockResolvedValue([entry]);
  render(<SettingsPage />);
  fireEvent.click(screen.getByText('Scan'));
  // The entry's label input appears once getScanSchedule has resolved.
  await screen.findByDisplayValue(entry.label);
}

describe('Settings → Scan — 0% schedule risk warning', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockApi.getSchedulingTimezone.mockResolvedValue({ timezone: 'Europe/Berlin' } as never);
    mockApi.getScheduledScanRunRetention.mockResolvedValue({ scheduledScanRunRetentionDays: 90 } as never);
    mockApi.getScanScheduleEntryRuns.mockResolvedValue([]);
  });

  it('shows the warning for a stocks entry saved with risk_pct 0', async () => {
    await renderScanSection(stocksEntry(0));
    expect(screen.getByText(WARNING)).toBeInTheDocument();
  });

  it('does not show the warning for a stocks entry with risk_pct 0.02', async () => {
    await renderScanSection(stocksEntry(0.02));
    expect(screen.queryByText(WARNING)).not.toBeInTheDocument();
  });
});
