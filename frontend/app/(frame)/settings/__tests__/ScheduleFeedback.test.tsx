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

function makeLoopEntry(overrides?: Partial<ScanScheduleEntry>): ScanScheduleEntry {
  return {
    id: 'entry-1',
    label: 'Loop scan',
    mode: 'options',
    profile_id: 'prof-valid-options',
    profile_name: 'Valid options profile',
    profile_synced_at: '2026-10-20T00:00:00Z',
    resolved_request: {
      universe: ['SP500'],
      direction: 'Bullish',
      horizon: 'Intraday',
    } as unknown as ScanScheduleEntry['resolved_request'],
    pattern: 'loop',
    enabled: true,
    days_of_week: [0, 1, 2, 3, 4],
    fire_time: null,
    cadence_minutes: 35,
    window_start_hour: 9,
    window_end_hour: 17,
    ...overrides,
  };
}

const validOptionsProfile: SearchProfile = {
  id: 'prof-valid-options',
  name: 'Valid options profile',
  mode: 'options',
  createdAt: '2026-10-20T00:00:00Z',
  updatedAt: '2026-10-20T00:00:00Z',
  universe: { pick: 'SP500', customRaw: '', minPriceRaw: '', maxPriceRaw: '', minCapRaw: '', maxCapRaw: '', capUnit: 'B' },
  direction: 'Bullish',
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

const legacyOptionsProfile: SearchProfile = {
  id: 'prof-legacy-options',
  name: 'Legacy missing options fields',
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
    // missing fundamentalsGate & spreads
  } as unknown as SearchProfile['scanSettings'],
};

async function renderScanSection(entry: ScanScheduleEntry) {
  mockApi.getScanSchedule.mockResolvedValue([entry]);
  render(<SettingsPage />);
  fireEvent.click(screen.getByText('Scan'));
  await screen.findByDisplayValue(entry.label);
}

describe('Settings → Scan — Schedule error feedback and validation (#402)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockApi.getSchedulingTimezone.mockResolvedValue({ timezone: 'Europe/Berlin' } as never);
    mockApi.getScheduledScanRunRetention.mockResolvedValue({ scheduledScanRunRetentionDays: 90 } as never);
    mockApi.getScanScheduleEntryRuns.mockResolvedValue([]);
    mockApi.updateScanScheduleEntry.mockResolvedValue({} as never);
    mockApi.deleteScanScheduleEntry.mockResolvedValue(undefined as never);

    useSearchProfilesStore.setState({
      profiles: [validOptionsProfile, legacyOptionsProfile],
    });
  });

  it('rejects cadence < 5 with visible error and does not update backend', async () => {
    await renderScanSection(makeLoopEntry());
    const cadenceInputs = screen.getAllByRole('spinbutton');
    const cadenceInput = cadenceInputs.find((el) => el.getAttribute('min') === '5')!;

    fireEvent.change(cadenceInput, { target: { value: '0' } });

    expect(screen.getByTestId('schedule-entry-error-entry-1')).toHaveTextContent(
      /cadence must be between 5 and 1440 minutes/i,
    );
    expect(mockApi.updateScanScheduleEntry).not.toHaveBeenCalled();
  });

  it('displays error on failed label update and retains draft without false success', async () => {
    mockApi.updateScanScheduleEntry.mockRejectedValueOnce(new Error('Network error: 500'));
    await renderScanSection(makeLoopEntry());

    const labelInput = screen.getByDisplayValue('Loop scan');
    fireEvent.change(labelInput, { target: { value: 'Failed draft' } });
    fireEvent.blur(labelInput);

    await waitFor(() => {
      expect(screen.getByTestId('schedule-entry-error-entry-1')).toHaveTextContent(
        /could not update schedule entry/i,
      );
    });
    expect(screen.getByDisplayValue('Failed draft')).toBeInTheDocument();
  });

  it('displays error on failed schedule entry delete', async () => {
    mockApi.deleteScanScheduleEntry.mockRejectedValueOnce(new Error('Delete error: 500'));
    await renderScanSection(makeLoopEntry());

    const deleteBtn = screen.getByRole('button', { name: 'Delete' });
    fireEvent.click(deleteBtn);

    await waitFor(() => {
      expect(screen.getByTestId('schedule-entry-error-entry-1')).toHaveTextContent(
        /could not delete schedule entry/i,
      );
    });
    // Entry row remains displayed
    expect(screen.getByDisplayValue('Loop scan')).toBeInTheDocument();
  });

  it('explains why an unresolvable legacy profile cannot be selected and preserves prior record', async () => {
    await renderScanSection(makeLoopEntry());

    const profileSelect = screen.getByDisplayValue('Valid options profile');
    fireEvent.change(profileSelect, { target: { value: 'prof-legacy-options' } });

    await waitFor(() => {
      expect(screen.getByTestId('schedule-entry-error-entry-1')).toHaveTextContent(
        /missing fundamentalsgate\/spreads/i,
      );
    });
    expect(mockApi.updateScanScheduleEntry).not.toHaveBeenCalled();
  });
});
