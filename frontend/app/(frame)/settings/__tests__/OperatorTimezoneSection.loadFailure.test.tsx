import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import SettingsPage from '../page';
import { api } from '@/lib/api';

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
  const row = label.closest('div')?.parentElement || label.parentElement!;
  const tzInput = row.querySelector('input') as HTMLInputElement;
  const saveBtn = row.querySelector('button') as HTMLButtonElement;
  return { tzInput, saveBtn, row };
}

describe('OperatorTimezoneSection — initial load failure & retry protection (#404)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    setupDefaultMocks();
  });

  test('1. initial GET failure displays error message and disables Save on unconfirmed default', async () => {
    mockApi.getSchedulingTimezone.mockRejectedValue(new Error('503 Service Unavailable'));

    render(<SettingsPage />);
    fireEvent.click(screen.getByText('Scan'));

    await waitFor(() => {
      expect(mockApi.getSchedulingTimezone).toHaveBeenCalled();
    });

    const errorEl = await screen.findByTestId('timezone-load-error');
    expect(errorEl).toHaveTextContent('Failed to load timezone from server');

    const { tzInput, saveBtn } = getTimezoneControls();
    expect(tzInput.value).toBe('Europe/Berlin');
    expect(saveBtn).toBeDisabled();

    const retryBtn = screen.getByRole('button', { name: 'Retry' });
    expect(retryBtn).toBeInTheDocument();
  });

  test('2. editing input after GET failure enables Save for informed edit and clears error on save', async () => {
    mockApi.getSchedulingTimezone.mockRejectedValue(new Error('503 Service Unavailable'));
    mockApi.putSchedulingTimezone.mockResolvedValue({ timezone: 'America/Chicago' });

    render(<SettingsPage />);
    fireEvent.click(screen.getByText('Scan'));

    await screen.findByTestId('timezone-load-error');
    const { tzInput, saveBtn } = getTimezoneControls();
    expect(saveBtn).toBeDisabled();

    // User types deliberate edit
    fireEvent.change(tzInput, { target: { value: 'America/Chicago' } });
    expect(saveBtn).not.toBeDisabled();

    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(mockApi.putSchedulingTimezone).toHaveBeenCalledWith('America/Chicago');
      expect(screen.getByText('Saved')).toBeInTheDocument();
    });

    expect(screen.queryByTestId('timezone-load-error')).not.toBeInTheDocument();
  });

  test('3. clicking Retry after failure re-attempts fetch, locks Save during flight, and updates on success', async () => {
    mockApi.getSchedulingTimezone.mockRejectedValueOnce(new Error('503 Service Unavailable'));

    let resolveRetry!: (val: { timezone: string }) => void;
    mockApi.getSchedulingTimezone.mockImplementationOnce(
      () => new Promise((resolve) => { resolveRetry = resolve; })
    );

    render(<SettingsPage />);
    fireEvent.click(screen.getByText('Scan'));

    await screen.findByTestId('timezone-load-error');
    const { tzInput, saveBtn } = getTimezoneControls();
    expect(saveBtn).toBeDisabled();

    const retryBtn = screen.getByRole('button', { name: 'Retry' });
    fireEvent.click(retryBtn);

    // Save must remain disabled during retry flight
    expect(saveBtn).toBeDisabled();
    expect(mockApi.getSchedulingTimezone).toHaveBeenCalledTimes(2);

    // Resolve retry GET with server-stored timezone
    resolveRetry({ timezone: 'Asia/Tokyo' });

    await waitFor(() => {
      expect(tzInput.value).toBe('Asia/Tokyo');
    });

    expect(screen.queryByTestId('timezone-load-error')).not.toBeInTheDocument();
    expect(saveBtn).not.toBeDisabled();
  });

  test('4. Retry after prior typing resets draft and accepts server value (F-PLAN-TZ-2)', async () => {
    mockApi.getSchedulingTimezone.mockRejectedValueOnce(new Error('503 Service Unavailable'));
    mockApi.getSchedulingTimezone.mockResolvedValueOnce({ timezone: 'Asia/Tokyo' });

    render(<SettingsPage />);
    fireEvent.click(screen.getByText('Scan'));

    await screen.findByTestId('timezone-load-error');
    const { tzInput } = getTimezoneControls();

    // User types something
    fireEvent.change(tzInput, { target: { value: 'Europe/London' } });
    expect(tzInput.value).toBe('Europe/London');

    // User changes mind and clicks Retry to see server value
    const retryBtn = screen.getByRole('button', { name: 'Retry' });
    fireEvent.click(retryBtn);

    await waitFor(() => {
      expect(tzInput.value).toBe('Asia/Tokyo');
    });

    expect(screen.queryByTestId('timezone-load-error')).not.toBeInTheDocument();
  });

  test('5. typing during retry flight preserves operator edit (race protection)', async () => {
    mockApi.getSchedulingTimezone.mockRejectedValueOnce(new Error('503 Service Unavailable'));

    let resolveRetry!: (val: { timezone: string }) => void;
    mockApi.getSchedulingTimezone.mockImplementationOnce(
      () => new Promise((resolve) => { resolveRetry = resolve; })
    );

    render(<SettingsPage />);
    fireEvent.click(screen.getByText('Scan'));

    await screen.findByTestId('timezone-load-error');
    const { tzInput } = getTimezoneControls();

    const retryBtn = screen.getByRole('button', { name: 'Retry' });
    fireEvent.click(retryBtn);

    // Operator starts typing while retry is in flight
    fireEvent.change(tzInput, { target: { value: 'America/Denver' } });
    expect(tzInput.value).toBe('America/Denver');

    // Late retry response arrives
    resolveRetry({ timezone: 'Asia/Tokyo' });

    await waitFor(() => {
      expect(screen.queryByTestId('timezone-load-error')).not.toBeInTheDocument();
    });

    // The draft America/Denver must not be overwritten by Asia/Tokyo
    expect(tzInput.value).toBe('America/Denver');
  });
});
