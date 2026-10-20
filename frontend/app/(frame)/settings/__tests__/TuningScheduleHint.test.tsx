import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import SettingsPage from '../page';
import { formatScheduleCadence, DAY_LABELS } from '../scheduleCadence';
import { api, getTuningSchedule, getTuningJobCount, getTuningJob } from '@/lib/api';

// Regression tests for APP-AUDIT-B-TUNING-HINT (#377):
// Strategy tuning schedule cadence hint says "every day" despite saved weekday selection.

jest.mock('@/lib/api', () => ({
  api: {
    getSchedulingTimezone: jest.fn().mockResolvedValue({ timezone: 'America/New_York' }),
    putSchedulingTimezone: jest.fn().mockResolvedValue({ timezone: 'America/New_York' }),
    getScheduledScanRunRetention: jest.fn().mockResolvedValue({ scheduledScanRunRetentionDays: 90 }),
    saveScheduledScanRunRetention: jest.fn().mockResolvedValue({ scheduledScanRunRetentionDays: 90 }),
    getScanSchedule: jest.fn().mockResolvedValue([]),
    getScanScheduleEntryRuns: jest.fn().mockResolvedValue([]),
  },
  getRiskSettings: jest.fn().mockResolvedValue(undefined),
  saveRiskSettings: jest.fn().mockResolvedValue(undefined),
  getHistoryRetention: jest.fn().mockResolvedValue({ tradeRetentionDays: 365, scanRetentionDays: 30 }),
  saveHistoryRetention: jest.fn().mockResolvedValue({ tradeRetentionDays: 365, scanRetentionDays: 30 }),
  getIngestionSchedule: jest.fn().mockResolvedValue({ enabled: false, time: '01:00', next_run: null }),
  saveIngestionSchedule: jest.fn().mockResolvedValue({ enabled: false, time: '01:00', next_run: null }),
  triggerIngestionNow: jest.fn().mockResolvedValue({ status: 'ok' }),
  getEdgarSchedule: jest.fn().mockResolvedValue({ enabled: false, time: '04:00', next_run: null }),
  saveEdgarSchedule: jest.fn().mockResolvedValue({ enabled: false, time: '04:00', next_run: null }),
  triggerEdgarPrefetch: jest.fn().mockResolvedValue({ status: 'ok' }),
  getSp500Schedule: jest.fn().mockResolvedValue({ enabled: false, time: '16:30', next_run: null }),
  saveSp500Schedule: jest.fn().mockResolvedValue({ enabled: false, time: '16:30', next_run: null }),
  triggerSp500Update: jest.fn().mockResolvedValue({ status: 'ok' }),
  getTuningSchedule: jest.fn(),
  saveTuningSchedule: jest.fn(),
  startTuningJob: jest.fn(),
  getTuningJob: jest.fn(),
  getTuningJobCount: jest.fn(),
  clearTuningJobs: jest.fn(),
  adoptStrategyParams: jest.fn(),
}));

describe('formatScheduleCadence helper (#377)', () => {
  test('returns "every day" when showDaysOfWeek is false regardless of daysOfWeek', () => {
    expect(formatScheduleCadence(false, undefined)).toBe('Runs at the configured time every day');
    expect(formatScheduleCadence(false, [])).toBe('Runs at the configured time every day');
    expect(formatScheduleCadence(false, [5])).toBe('Runs at the configured time every day');
    expect(formatScheduleCadence(false, [0, 2, 5])).toBe('Runs at the configured time every day');
  });

  test('formats default Saturday [5] correctly', () => {
    expect(formatScheduleCadence(true, [5])).toBe('Runs at the configured time on Sat');
  });

  test('formats custom selection [0, 2, 5] (Mon, Wed, Sat) correctly', () => {
    expect(formatScheduleCadence(true, [0, 2, 5])).toBe('Runs at the configured time on Mon, Wed, Sat');
  });

  test('formats standard trading weekdays [0, 1, 2, 3, 4]', () => {
    expect(formatScheduleCadence(true, [0, 1, 2, 3, 4])).toBe('Runs at the configured time on Mon, Tue, Wed, Thu, Fri');
  });

  test('returns "every day" when all 7 days are active', () => {
    expect(formatScheduleCadence(true, [0, 1, 2, 3, 4, 5, 6])).toBe('Runs at the configured time every day');
  });

  test('handles empty or non-array day selections', () => {
    expect(formatScheduleCadence(true, [])).toBe('No active days selected');
    expect(formatScheduleCadence(true, undefined)).toBe('No active days selected');
    expect(formatScheduleCadence(true, null)).toBe('No active days selected');
  });

  test('deduplicates and sorts days correctly', () => {
    expect(formatScheduleCadence(true, [5, 2, 0, 5, 2])).toBe('Runs at the configured time on Mon, Wed, Sat');
  });

  test('filters out invalid or out-of-range day numbers', () => {
    expect(formatScheduleCadence(true, [-1, 0, 7, 99])).toBe('Runs at the configured time on Mon');
    expect(formatScheduleCadence(true, [1.5, NaN as unknown as number, 2])).toBe('Runs at the configured time on Wed');
  });
});

describe('SettingsPage Strategy Tuning schedule cadence hint UI (#377)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (getTuningJobCount as jest.Mock).mockResolvedValue({ count: 0 });
    (getTuningJob as jest.Mock).mockResolvedValue(null);
  });

  test('hydrates saved Mon/Wed/Sat [0, 2, 5] schedule with accurate cadence hint', async () => {
    (getTuningSchedule as jest.Mock).mockResolvedValue({
      enabled: true,
      time: '05:37',
      days_of_week: [0, 2, 5],
      next_run: null,
    });

    render(<SettingsPage />);
    fireEvent.click(screen.getByText('Strategy Tuning', { selector: 'span, div, p' }));

    // Find the hint for the Enable schedule row inside Strategy Tuning
    await waitFor(() => {
      expect(screen.getByText('Runs at the configured time on Mon, Wed, Sat')).toBeInTheDocument();
    });

    // Verify it does NOT say "every day" for the tuning schedule
    expect(screen.queryByText('Runs the ingestion job at the configured time every day')).not.toBeInTheDocument();
  });

  test('hydrates default Saturday [5] schedule with accurate cadence hint', async () => {
    (getTuningSchedule as jest.Mock).mockResolvedValue({
      enabled: false,
      time: '05:00',
      days_of_week: [5],
      next_run: null,
    });

    render(<SettingsPage />);
    fireEvent.click(screen.getByText('Strategy Tuning', { selector: 'span, div, p' }));

    await waitFor(() => {
      expect(screen.getByText('Runs at the configured time on Sat')).toBeInTheDocument();
    });
  });

  test('dynamically updates hint when checkboxes in DaysOfWeekPicker are toggled', async () => {
    (getTuningSchedule as jest.Mock).mockResolvedValue({
      enabled: true,
      time: '05:00',
      days_of_week: [5], // Sat initially
      next_run: null,
    });

    render(<SettingsPage />);
    fireEvent.click(screen.getByText('Strategy Tuning', { selector: 'span, div, p' }));

    await waitFor(() => {
      expect(screen.getByText('Runs at the configured time on Sat')).toBeInTheDocument();
    });

    // Check Mon checkbox
    const monLabel = screen.getByText('Mon');
    const monCheckbox = monLabel.parentElement?.querySelector('input[type="checkbox"]');
    expect(monCheckbox).toBeInTheDocument();
    fireEvent.click(monCheckbox!);

    // Now Mon (0) and Sat (5) are selected
    await waitFor(() => {
      expect(screen.getByText('Runs at the configured time on Mon, Sat')).toBeInTheDocument();
    });

    // Uncheck Sat checkbox
    const satLabel = screen.getByText('Sat');
    const satCheckbox = satLabel.parentElement?.querySelector('input[type="checkbox"]');
    fireEvent.click(satCheckbox!);

    // Only Mon is selected
    await waitFor(() => {
      expect(screen.getByText('Runs at the configured time on Mon')).toBeInTheDocument();
    });
  });

  test('non-daysOfWeek schedules (EDGAR, S&P 500) keep "every day" hint', async () => {
    render(<SettingsPage />);
    fireEvent.click(screen.getByText('Data', { selector: 'span, div, p' }));

    await waitFor(() => {
      expect(screen.getByText('EDGAR fundamentals')).toBeInTheDocument();
    });

    const everyDayHints = screen.getAllByText('Runs at the configured time every day');
    // Both EDGAR fundamentals and S&P 500 list update use ScheduleSection without showDaysOfWeek
    expect(everyDayHints.length).toBeGreaterThanOrEqual(2);
  });
});
