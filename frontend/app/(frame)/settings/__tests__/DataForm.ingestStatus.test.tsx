import '@testing-library/jest-dom';
import { act, render, screen, fireEvent, waitFor } from '@testing-library/react';
import SettingsPage from '../page';
import { getIngestionStatus, triggerIngestionNow, type IngestionStatus } from '@/lib/api';

// HISTORY-INCREMENTAL-NIGHTLY C1 (#572): DataForm fetches GET /api/data/ingest/status
// on mount and renders the TiingoBudget molecule. A fetch failure must render an
// error line and never numbers (stale or otherwise) labelled as current.

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
  triggerIngestionNow: jest.fn(),
  getIngestionStatus: jest.fn(),
  getEdgarSchedule: jest.fn().mockResolvedValue({ enabled: false, time: '04:00', next_run: null }),
  saveEdgarSchedule: jest.fn().mockResolvedValue({ enabled: false, time: '04:00', next_run: null }),
  triggerEdgarPrefetch: jest.fn().mockResolvedValue({ status: 'ok' }),
  getSp500Schedule: jest.fn().mockResolvedValue({ enabled: false, time: '16:30', next_run: null }),
  saveSp500Schedule: jest.fn().mockResolvedValue({ enabled: false, time: '16:30', next_run: null }),
  triggerSp500Update: jest.fn().mockResolvedValue({ status: 'ok' }),
  getTuningSchedule: jest.fn().mockResolvedValue({ enabled: false, time: '05:00', next_run: null, days_of_week: [5] }),
  saveTuningSchedule: jest.fn(),
  startTuningJob: jest.fn(),
  getTuningJob: jest.fn().mockResolvedValue(null),
  getTuningJobCount: jest.fn().mockResolvedValue({ count: 0 }),
  clearTuningJobs: jest.fn(),
  adoptStrategyParams: jest.fn(),
}));

const statusMock = getIngestionStatus as jest.Mock;
const triggerMock = triggerIngestionNow as jest.Mock;

const STATUS: IngestionStatus = {
  status: 'completed', total: 30, done: 30, failed: 2,
  started_at: '2026-11-05T02:00:00+00:00', finished_at: '2026-11-05T02:10:00+00:00', error: null,
  rebuild_refused: 1, single_provider_failed_symbols: ['AAA'], single_provider_updated: 0,
  suffix_only: 25, adjustment_changed: 0, prefix_refetched: 4, prefix_rescaled: 1, prefix_confirmed: 2,
  confirm_retry: 0, lag_window_full: 1, single_provider_recent: 0, single_provider_skipped_current: 0,
  revalidated: 0, revalidation_skipped_budget: 0, tiingo_requests: 17, tiingo_bytes: 2_500_000,
  tiingo_usage: {
    requests_per_hour: { used: 17, limit: 50, nightly_stop_at: 50, window: 'rolling 1 h' },
    requests_per_day: { used: 17, limit: 1000, nightly_stop_at: 900, window: 'rolling 24 h' },
    symbols_per_month: { used: 9, limit: 500, nightly_stop_at: 475, window: 'rolling 31 d' },
    bytes_per_month: { used: 2_500_000, limit: 1_000_000_000, nightly_stop_at: 900_000_000, window: 'rolling 31 d' },
  },
  tiingo_usage_error: null,
};

function openData() {
  fireEvent.click(screen.getByText('Data', { selector: 'span, div, p' }));
}

beforeEach(() => {
  jest.clearAllMocks();
});

test('a status fetch failure shows the error and no numbers', async () => {
  statusMock.mockRejectedValue(new Error('API /api/data/ingest/status → 500: boom'));
  render(<SettingsPage />);
  openData();
  await waitFor(() => expect(screen.getByText(/Ingestion status unavailable/)).toBeInTheDocument());
  expect(screen.getByText(/500: boom/)).toBeInTheDocument();
  expect(screen.queryAllByRole('meter')).toHaveLength(0);
  expect(screen.queryByRole('region', { name: 'Last ingestion run' })).not.toBeInTheDocument();
  expect(screen.queryByText(/^as of /)).not.toBeInTheDocument();
});

test('renders the molecule with an "as of" stamp on success', async () => {
  statusMock.mockResolvedValue(STATUS);
  render(<SettingsPage />);
  openData();
  await waitFor(() => expect(screen.getAllByRole('meter')).toHaveLength(4));
  expect(screen.getByRole('region', { name: 'Last ingestion run' })).toBeInTheDocument();
  expect(screen.getByText(/^as of /)).toBeInTheDocument();
  expect(statusMock).toHaveBeenCalledTimes(1);
});

test('Refresh refetches; a failed refresh drops the earlier numbers', async () => {
  statusMock.mockResolvedValueOnce(STATUS);
  render(<SettingsPage />);
  openData();
  await waitFor(() => expect(screen.getAllByRole('meter')).toHaveLength(4));

  statusMock.mockRejectedValueOnce(new Error('network down'));
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Refresh' })); });
  await waitFor(() => expect(screen.getByText(/Ingestion status unavailable/)).toBeInTheDocument());
  expect(statusMock).toHaveBeenCalledTimes(2);
  expect(screen.queryAllByRole('meter')).toHaveLength(0);
  expect(screen.queryByRole('region', { name: 'Last ingestion run' })).not.toBeInTheDocument();
  expect(screen.queryByText(/^as of /)).not.toBeInTheDocument();
});

test('a started "Run now" refetches the status', async () => {
  statusMock.mockResolvedValue(STATUS);
  triggerMock.mockResolvedValue({ status: 'started', total: 30 });
  render(<SettingsPage />);
  openData();
  await waitFor(() => expect(statusMock).toHaveBeenCalledTimes(1));
  await act(async () => { fireEvent.click(screen.getAllByRole('button', { name: 'Run now' })[0]); });
  await waitFor(() => expect(statusMock).toHaveBeenCalledTimes(2));
});

test('a failed "Run now" does not refetch', async () => {
  statusMock.mockResolvedValue(STATUS);
  triggerMock.mockRejectedValue(new Error('409'));
  render(<SettingsPage />);
  openData();
  await waitFor(() => expect(statusMock).toHaveBeenCalledTimes(1));
  await act(async () => { fireEvent.click(screen.getAllByRole('button', { name: 'Run now' })[0]); });
  await waitFor(() => expect(screen.getByText('Trigger failed')).toBeInTheDocument());
  expect(statusMock).toHaveBeenCalledTimes(1);
});
