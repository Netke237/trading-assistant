import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import SettingsPage from '../page';
import { api } from '@/lib/api';

// Regression test for APP-AUDIT-B-TIMEZONE-RACE (#372):
// OperatorTimezoneSection unconditionally overwrote in-progress operator edits
// and recently submitted saves when a slow initial GET /settings/scheduling resolved.

jest.mock('@/lib/api', () => ({
  api: {
    getSchedulingTimezone: jest.fn(),
    putSchedulingTimezone: jest.fn(),
    getScheduledScanRunRetention: jest.fn(),
    saveScheduledScanRunRetention: jest.fn(),
    getScanSchedule: jest.fn(),
    getScanScheduleEntryRuns: jest.fn(),
  },
  getRiskSettings: jest.fn().mockResolvedValue(undefined),
  saveRiskSettings: jest.fn().mockResolvedValue(undefined),
}));

const mockApi = api as jest.Mocked<typeof api>;

function setupDefaultMocks() {
  mockApi.getScheduledScanRunRetention.mockResolvedValue({ scheduledScanRunRetentionDays: 90 });
  mockApi.getScanSchedule.mockResolvedValue([]);
  mockApi.getScanScheduleEntryRuns.mockResolvedValue([]);
}

function getTimezoneControls() {
  const label = screen.getByText('Timezone');
  // Row layout: row container div has label container div and control container div
  const row = label.closest('div')?.parentElement || label.parentElement!;
  const tzInput = row.querySelector('input') as HTMLInputElement;
  const saveBtn = row.querySelector('button') as HTMLButtonElement;
  return { tzInput, saveBtn, row };
}

describe('OperatorTimezoneSection — race condition protection (#372)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    setupDefaultMocks();
  });

  test('1. late initial GET after operator edit does not overwrite draft', async () => {
    let resolveGet!: (val: { timezone: string }) => void;
    mockApi.getSchedulingTimezone.mockImplementation(
      () => new Promise((resolve) => { resolveGet = resolve; })
    );

    render(<SettingsPage />);
    fireEvent.click(screen.getByText('Scan'));

    const { tzInput } = getTimezoneControls();
    expect(tzInput.value).toBe('Europe/Berlin');

    // Operator edits before initial GET resolves
    fireEvent.change(tzInput, { target: { value: 'America/New_York' } });
    expect(tzInput.value).toBe('America/New_York');

    // Late initial GET arrives from backend with Europe/Berlin
    resolveGet({ timezone: 'Europe/Berlin' });

    // Allow promise microtasks to flush
    await waitFor(() => {
      expect(mockApi.getSchedulingTimezone).toHaveBeenCalled();
    });

    // On unfixed code, tzInput.value was clobbered back to Europe/Berlin.
    // It must remain America/New_York.
    expect(tzInput.value).toBe('America/New_York');
  });

  test('2. slow initial GET without edit hydrates correctly', async () => {
    let resolveGet!: (val: { timezone: string }) => void;
    mockApi.getSchedulingTimezone.mockImplementation(
      () => new Promise((resolve) => { resolveGet = resolve; })
    );

    render(<SettingsPage />);
    fireEvent.click(screen.getByText('Scan'));

    const { tzInput } = getTimezoneControls();
    expect(tzInput.value).toBe('Europe/Berlin');

    // Resolve initial GET with saved server timezone
    resolveGet({ timezone: 'America/Chicago' });

    await waitFor(() => {
      expect(tzInput.value).toBe('America/Chicago');
    });
  });

  test('3. slow failed initial GET preserves operator draft', async () => {
    let rejectGet!: (err: Error) => void;
    mockApi.getSchedulingTimezone.mockImplementation(
      () => new Promise((_, reject) => { rejectGet = reject; })
    );

    render(<SettingsPage />);
    fireEvent.click(screen.getByText('Scan'));

    const { tzInput } = getTimezoneControls();
    fireEvent.change(tzInput, { target: { value: 'Asia/Tokyo' } });

    // Initial GET fails with network error
    rejectGet(new Error('Network failure'));

    await waitFor(() => {
      expect(mockApi.getSchedulingTimezone).toHaveBeenCalled();
    });

    expect(tzInput.value).toBe('Asia/Tokyo');
  });

  test('4. edit and save before initial GET resolves preserves save and confirmation', async () => {
    let resolveGet!: (val: { timezone: string }) => void;
    mockApi.getSchedulingTimezone.mockImplementation(
      () => new Promise((resolve) => { resolveGet = resolve; })
    );
    mockApi.putSchedulingTimezone.mockResolvedValue({ timezone: 'America/New_York' });

    render(<SettingsPage />);
    fireEvent.click(screen.getByText('Scan'));

    const { tzInput, saveBtn } = getTimezoneControls();
    fireEvent.change(tzInput, { target: { value: 'America/New_York' } });

    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(mockApi.putSchedulingTimezone).toHaveBeenCalledWith('America/New_York');
      expect(screen.getByText('Saved')).toBeInTheDocument();
    });

    // Late initial GET arrives afterward
    resolveGet({ timezone: 'Europe/Berlin' });

    await waitFor(() => {
      expect(tzInput.value).toBe('America/New_York');
    });
    expect(tzInput.value).toBe('America/New_York');
  });

  test('5. save without prior typing before delayed GET resolves is not clobbered', async () => {
    let resolveGet!: (val: { timezone: string }) => void;
    mockApi.getSchedulingTimezone.mockImplementation(
      () => new Promise((resolve) => { resolveGet = resolve; })
    );
    mockApi.putSchedulingTimezone.mockResolvedValue({ timezone: 'Europe/Berlin' });

    render(<SettingsPage />);
    fireEvent.click(screen.getByText('Scan'));

    const { tzInput, saveBtn } = getTimezoneControls();
    expect(tzInput.value).toBe('Europe/Berlin');

    // Operator clicks save directly without typing first
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(mockApi.putSchedulingTimezone).toHaveBeenCalledWith('Europe/Berlin');
      expect(screen.getByText('Saved')).toBeInTheDocument();
    });

    // Delayed initial GET resolves with different server value (e.g. America/New_York)
    resolveGet({ timezone: 'America/New_York' });

    // The saved setting Europe/Berlin must not be clobbered
    await waitFor(() => {
      expect(tzInput.value).toBe('Europe/Berlin');
    });
  });

  test('6. editing while save is in flight is not overwritten by older PUT response', async () => {
    mockApi.getSchedulingTimezone.mockResolvedValue({ timezone: 'Europe/Berlin' });
    let resolvePut!: (val: { timezone: string }) => void;
    mockApi.putSchedulingTimezone.mockImplementation(
      () => new Promise((resolve) => { resolvePut = resolve; })
    );

    render(<SettingsPage />);
    fireEvent.click(screen.getByText('Scan'));

    const { tzInput, saveBtn } = getTimezoneControls();
    await waitFor(() => expect(tzInput.value).toBe('Europe/Berlin'));

    fireEvent.change(tzInput, { target: { value: 'America/Chicago' } });
    fireEvent.click(saveBtn);

    expect(mockApi.putSchedulingTimezone).toHaveBeenCalledWith('America/Chicago');

    // Operator continues editing while PUT is in flight
    fireEvent.change(tzInput, { target: { value: 'America/Phoenix' } });
    expect(tzInput.value).toBe('America/Phoenix');

    // PUT resolves with older response America/Chicago
    resolvePut({ timezone: 'America/Chicago' });

    await waitFor(() => {
      expect(screen.getByText('Saved')).toBeInTheDocument();
    });

    // Active draft must remain America/Phoenix, not overwritten by Chicago
    expect(tzInput.value).toBe('America/Phoenix');
  });

  test('7. Save button is disabled during save to prevent concurrent submissions', async () => {
    mockApi.getSchedulingTimezone.mockResolvedValue({ timezone: 'Europe/Berlin' });
    let resolvePut!: (val: { timezone: string }) => void;
    mockApi.putSchedulingTimezone.mockImplementation(
      () => new Promise((resolve) => { resolvePut = resolve; })
    );

    render(<SettingsPage />);
    fireEvent.click(screen.getByText('Scan'));

    const { tzInput, saveBtn } = getTimezoneControls();
    await waitFor(() => expect(tzInput.value).toBe('Europe/Berlin'));

    fireEvent.change(tzInput, { target: { value: 'America/New_York' } });
    fireEvent.click(saveBtn);

    // Save button must be disabled while save is in flight
    expect(saveBtn).toBeDisabled();

    // Clicking while disabled must not fire duplicate PUT
    fireEvent.click(saveBtn);
    expect(mockApi.putSchedulingTimezone).toHaveBeenCalledTimes(1);

    // Resolve PUT
    resolvePut({ timezone: 'America/New_York' });

    await waitFor(() => {
      expect(saveBtn).not.toBeDisabled();
    });
  });

  test('8. unmount during initial GET cancels state update cleanly', async () => {
    let resolveGet!: (val: { timezone: string }) => void;
    mockApi.getSchedulingTimezone.mockImplementation(
      () => new Promise((resolve) => { resolveGet = resolve; })
    );

    const { unmount } = render(<SettingsPage />);
    fireEvent.click(screen.getByText('Scan'));

    unmount();

    // Resolving after unmount should not throw or cause warning
    expect(() => {
      resolveGet({ timezone: 'Europe/Berlin' });
    }).not.toThrow();
  });
});
