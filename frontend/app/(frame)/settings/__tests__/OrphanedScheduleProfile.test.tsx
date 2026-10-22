import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import SettingsPage from '../page';
import { api, type ScanScheduleEntry } from '@/lib/api';
import { useSearchProfilesStore } from '@/lib/searchProfilesStore';
import type { SearchProfile } from '@/types/searchProfile';
import { DEFAULT_CONFIDENCE_GATE, DEFAULT_FUNDAMENTALS_GATE, DEFAULT_SPREADS } from '@/lib/settingsStore';

jest.mock('@/lib/api', () => ({
  api: {
    getSchedulingTimezone: jest.fn(),
    getScheduledScanRunRetention: jest.fn(),
    getScanSchedule: jest.fn(),
    getScanScheduleEntryRuns: jest.fn(),
    updateScanScheduleEntry: jest.fn(),
    deleteScanScheduleEntry: jest.fn(),
    createScanScheduleEntry: jest.fn(),
    runScanScheduleEntryNow: jest.fn(),
  },
  getRiskSettings: jest.fn().mockResolvedValue(undefined),
  saveRiskSettings: jest.fn().mockResolvedValue(undefined),
}));

const mockApi = api as jest.Mocked<typeof api>;

const auditOptionsBProfile: SearchProfile = {
  id: 'audit-options-b',
  name: 'Audit options B',
  mode: 'options',
  createdAt: '2026-10-20T00:00:00Z',
  updatedAt: '2026-10-20T00:00:00Z',
  universe: { pick: 'SP500', customRaw: '', minPriceRaw: '', maxPriceRaw: '', minCapRaw: '', maxCapRaw: '', capUnit: 'B' },
  direction: 'Bearish',
  horizonPreset: 'Intraday',
  holdMin: 0,
  holdMax: 2,
  scanOverrides: {},
  scanSettings: {
    confidenceGate: DEFAULT_CONFIDENCE_GATE,
    fundamentalsGate: DEFAULT_FUNDAMENTALS_GATE,
    shortlistMaxCandidates: 10,
    spreads: DEFAULT_SPREADS,
  },
};

function makeOrphanedEntry(): ScanScheduleEntry {
  return {
    id: 'entry-orphan',
    label: 'Orphaned entry',
    mode: 'options',
    profile_id: 'deleted-profile',
    profile_name: 'Deleted profile',
    profile_synced_at: '2026-10-20T00:00:00Z',
    resolved_request: {
      universe: ['SP500'],
      direction: 'Bullish',
      horizon: 'Intraday',
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
  await screen.findByDisplayValue(entry.label);
}

describe('Settings → Scan — Orphaned schedule profile display (#403)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockApi.getSchedulingTimezone.mockResolvedValue({ timezone: 'Europe/Berlin' } as never);
    mockApi.getScheduledScanRunRetention.mockResolvedValue({ scheduledScanRunRetentionDays: 90 } as never);
    mockApi.getScanScheduleEntryRuns.mockResolvedValue([]);
    mockApi.updateScanScheduleEntry.mockResolvedValue({} as never);

    useSearchProfilesStore.setState({
      profiles: [auditOptionsBProfile],
    });
  });

  it('displays explicit missing profile option and warning without selecting an unrelated profile', async () => {
    await renderScanSection(makeOrphanedEntry());

    // The select must have value 'deleted-profile' and display the missing label
    const select = screen.getByDisplayValue(/deleted profile \(missing\)/i) as HTMLSelectElement;
    expect(select.value).toBe('deleted-profile');

    // Warning is rendered in the row
    expect(
      screen.getByText(/profile missing or deleted/i),
    ).toBeInTheDocument();

    // No update sent to backend on mount
    expect(mockApi.updateScanScheduleEntry).not.toHaveBeenCalled();
  });

  it('allows deliberate reassignment to an available profile', async () => {
    await renderScanSection(makeOrphanedEntry());

    const select = screen.getByDisplayValue(/deleted profile \(missing\)/i) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: 'audit-options-b' } });

    await waitFor(() => {
      expect(mockApi.updateScanScheduleEntry).toHaveBeenCalledWith(
        'entry-orphan',
        expect.objectContaining({
          profile_id: 'audit-options-b',
          profile_name: 'Audit options B',
        }),
      );
    });
  });
});
