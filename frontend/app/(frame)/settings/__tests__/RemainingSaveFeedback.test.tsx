import '@testing-library/jest-dom';
import { act, render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import SettingsPage from '../page';
import * as apiModule from '@/lib/api';
import { useSettingsSaveStatus, outstanding } from '@/lib/settingsSaveStatus';
import { useSettingsStore } from '@/lib/settingsStore';

jest.mock('@/lib/api', () => {
  const actual = jest.requireActual('@/lib/api');
  return { ...actual, api: { ...actual.api,
    getSchedulingTimezone: jest.fn(), putSchedulingTimezone: jest.fn(),
    getScheduledScanRunRetention: jest.fn(), saveScheduledScanRunRetention: jest.fn(),
    getScanSchedule: jest.fn(), getScanScheduleEntryRuns: jest.fn(), updateScanScheduleEntry: jest.fn(), postCredentials: jest.fn(),
  }, getHistoryRetention: jest.fn(), saveHistoryRetention: jest.fn(),
  getIngestionSchedule: jest.fn(), saveIngestionSchedule: jest.fn(), getEdgarSchedule: jest.fn(), saveEdgarSchedule: jest.fn(),
  getSp500Schedule: jest.fn(), saveSp500Schedule: jest.fn(), getTuningSchedule: jest.fn(), saveTuningSchedule: jest.fn(), getTuningJobCount: jest.fn() };
});
const api = apiModule.api as jest.Mocked<typeof apiModule.api>;
const footer = () => within(document.querySelector('footer')!);
const clickFooter = () => fireEvent.click(footer().getByRole('button', { name: 'Save changes' }));
const nav = (name: string) => fireEvent.click(screen.getByText(name, { exact: true }));
const row = (name: string) => screen.getByText(name, { exact: true }).closest('div')!.parentElement!;
const retention = () => ({ input: row('Retention (days)').querySelector('input')!, save: within(row('Retention (days)')).getByRole('button', { name: 'Save' }) });
const deferred = <T,>() => { let resolve!: (v: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; };
const brokers = [
  ['ibkr_paper', 'IBKR Paper', 'IBKR Paper credentials'], ['tradier_paper', 'Tradier Paper', 'Tradier Paper credentials'],
  ['tradier_live', 'Tradier Live', 'Tradier Live credentials'], ['alpaca_paper', 'Alpaca Paper', 'Alpaca Paper credentials'],
  ['tastytrade_paper', 'Tastytrade Paper', 'Tastytrade Paper credentials'],
] as const;
const brokerInput = (name: string) => document.querySelectorAll('input')[({ 'IBKR Paper': 0, 'Tradier Live': 2, 'Tradier Paper': 4, 'Alpaca Paper': 6, 'Tastytrade Paper': 8 } as Record<string, number>)[name]];
beforeEach(() => {
  jest.clearAllMocks(); useSettingsStore.getState().resetToDefaults(); useSettingsSaveStatus.setState({ channels: {}, localFailures: {} });
  api.getSchedulingTimezone.mockResolvedValue({ timezone: 'Europe/Berlin' });
  api.getScheduledScanRunRetention.mockResolvedValue({ scheduledScanRunRetentionDays: 90 });
  api.saveScheduledScanRunRetention.mockImplementation(async days => ({ scheduledScanRunRetentionDays: days }));
  api.getScanSchedule.mockResolvedValue([]); api.getScanScheduleEntryRuns.mockResolvedValue([]); api.postCredentials.mockResolvedValue({} as never);
  (apiModule.getHistoryRetention as jest.Mock).mockResolvedValue({ historyRetentionYears: 10 });
  (apiModule.saveHistoryRetention as jest.Mock).mockResolvedValue({ historyRetentionYears: 12 });
  for (const key of ['Ingestion', 'Edgar', 'Sp500', 'Tuning']) {
    (apiModule[`get${key}Schedule` as keyof typeof apiModule] as jest.Mock).mockResolvedValue({ enabled: true, time: '03:00', next_run: null, days_of_week: [5] });
    (apiModule[`save${key}Schedule` as keyof typeof apiModule] as jest.Mock).mockImplementation(async s => ({ ...s, next_run: null }));
  }
  (apiModule.getTuningJobCount as jest.Mock).mockResolvedValue({ count: 0 });
  global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ gmail: { enabled: false, to: '', smtp_user: '' }, telegram: { enabled: false, chat_id: '' } }) });
});
afterEach(() => jest.restoreAllMocks());
async function checkWarning(text: string) { clickFooter(); await waitFor(() => expect(footer().getByRole('alert')).toHaveTextContent(text)); }
async function checkSaved() { clickFooter(); await waitFor(() => expect(footer().getByRole('status')).toHaveTextContent('Saved')); }
async function openScan() { nav('Scan'); await waitFor(() => expect(api.getScheduledScanRunRetention).toHaveBeenCalled()); }

test('scan retention reports draft, failure, discard and own-save recovery', async () => {
  render(<SettingsPage />); await openScan();
  fireEvent.change(retention().input, { target: { value: '120' } });
  await checkWarning('Scheduled scan history retention: unsaved edit'); expect(api.saveScheduledScanRunRetention).not.toHaveBeenCalled();
  api.saveScheduledScanRunRetention.mockRejectedValueOnce(new Error('synthetic'));
  fireEvent.click(retention().save); await checkWarning('Scheduled scan history retention: save failed');
  nav('Appearance'); expect(footer().getByRole('alert')).toHaveTextContent('edit discarded');
  await openScan(); fireEvent.click(retention().save); await waitFor(() => expect(footer().queryByRole('alert')).not.toBeInTheDocument()); await checkSaved();
});
test.each(['old-first', 'new-first'])('deferred server commits %s cannot certify stale retention', async order => {
  let server = 90; const old = deferred<{ scheduledScanRunRetentionDays: number }>(); const newer = deferred<{ scheduledScanRunRetentionDays: number }>();
  api.getScheduledScanRunRetention.mockImplementation(async () => ({ scheduledScanRunRetentionDays: server }));
  api.saveScheduledScanRunRetention.mockImplementationOnce(() => old.promise).mockImplementationOnce(() => newer.promise).mockImplementation(async days => { server = days; return { scheduledScanRunRetentionDays: server }; });
  render(<SettingsPage />); await openScan();
  fireEvent.change(retention().input, { target: { value: '120' } }); fireEvent.click(retention().save);
  fireEvent.change(retention().input, { target: { value: '180' } }); nav('Appearance'); await openScan();
  await waitFor(() => expect(retention().input).toHaveValue(90)); fireEvent.click(retention().save);
  clickFooter(); expect(footer().getByRole('button', { name: 'Saving…' })).toBeDisabled();
  const commitOld = async () => { server = 120; await act(async () => old.resolve({ scheduledScanRunRetentionDays: 120 })); };
  const commitNew = async () => { server = 90; await act(async () => newer.resolve({ scheduledScanRunRetentionDays: 90 })); };
  if (order === 'new-first') { await commitNew(); expect(footer().getByRole('button', { name: 'Saving…' })).toBeDisabled(); await commitOld(); } else { await commitOld(); await commitNew(); }
  await waitFor(() => expect(footer().getByRole('alert')).toHaveTextContent('Scheduled scan history retention: latest save not confirmed'));
  expect(retention().input).toHaveValue(90); expect(server).toBe(order === 'new-first' ? 120 : 90);
  fireEvent.change(retention().input, { target: { value: '91' } }); fireEvent.change(retention().input, { target: { value: '90' } });
  nav('Appearance'); await openScan(); await checkWarning('latest save not confirmed');
  // Explicitly re-enter the intended value after readback, then Save after all earlier attempts settle.
  fireEvent.change(retention().input, { target: { value: '90' } }); fireEvent.click(retention().save);
  await waitFor(() => expect(api.saveScheduledScanRunRetention).toHaveBeenLastCalledWith(90));
  await waitFor(() => expect(footer().queryByRole('alert')).not.toBeInTheDocument()); expect(server).toBe(90); expect(retention().input).toHaveValue(90); nav('Appearance'); await openScan(); await waitFor(() => expect(retention().input).toHaveValue(90)); await checkSaved();
});
test('history retention failed blur is listed and later successful blur confirms actual payload', async () => {
  (apiModule.saveHistoryRetention as jest.Mock).mockRejectedValueOnce(new Error('synthetic'));
  render(<SettingsPage />); nav('Notifications'); await screen.findByDisplayValue('10');
  const input = screen.getByDisplayValue('10'); fireEvent.change(input, { target: { value: '12' } }); fireEvent.blur(input);
  await checkWarning('Trade history retention: save failed'); fireEvent.blur(input);
  await waitFor(() => expect(footer().queryByRole('alert')).not.toBeInTheDocument());
  expect(apiModule.saveHistoryRetention).toHaveBeenLastCalledWith({ historyRetentionYears: 12 }); await checkSaved();
});

test('notifications raw non-OK is failed, draft/discard persist, own Save clears', async () => {
  render(<SettingsPage />); nav('Notifications'); await screen.findByRole('button', { name: 'Save settings' });
  fireEvent.change(screen.getAllByPlaceholderText('you@gmail.com')[0], { target: { value: 'synthetic@example.test' } });
  await checkWarning('Notifications: unsaved edit'); expect(fetch).toHaveBeenCalledTimes(1);
  (fetch as jest.Mock).mockResolvedValueOnce({ ok: false, status: 500 }); fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));
  await checkWarning('Notifications: save failed'); nav('Appearance'); expect(footer().getByRole('alert')).toHaveTextContent('edit discarded');
  nav('Notifications'); await screen.findByRole('button', { name: 'Save settings' }); fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));
  await waitFor(() => expect(footer().queryByRole('alert')).not.toBeInTheDocument()); await checkSaved();
});
test.each(brokers)('%s draft/discard then failed POST exits saving and own Save recovers', async (id, name, label) => {
  api.postCredentials.mockRejectedValueOnce(new Error('synthetic')); render(<SettingsPage />); nav('Brokers');
  fireEvent.change(brokerInput(name), { target: { value: 'synthetic-edit' } });
  await checkWarning(`${label}: unsaved edit`); expect(api.postCredentials).not.toHaveBeenCalled();
  nav('Appearance'); expect(footer().getByRole('alert')).toHaveTextContent(`${label}: edit discarded`);
  nav('Brokers'); fireEvent.click(screen.getByRole('button', { name: `Save ${name}` }));
  await screen.findByText('Save failed'); await checkWarning(`${label}: save failed`);
  expect(screen.getByRole('button', { name: `Save ${name}` })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: `Save ${name}` }));
  await waitFor(() => expect(footer().queryByRole('alert')).not.toBeInTheDocument()); expect(api.postCredentials).toHaveBeenLastCalledWith(id, expect.any(Object)); await checkSaved();
});
describe.each(brokers)('%s pre-request storage', (_id, name, label) => {
test.each(['QuotaExceededError', 'SecurityError'])('%s prevents POST; footer local retry cannot confirm remote save', async errorName => {
  render(<SettingsPage />); nav('Brokers'); fireEvent.change(brokerInput(name), { target: { value: 'https://synthetic.invalid' } });
  const oldBytes = localStorage.getItem('bamendjou-settings');
  const original = Storage.prototype.setItem; let blocked = true;
  jest.spyOn(Storage.prototype, 'setItem').mockImplementation(function(this: Storage, key, value) { if (blocked && key === 'bamendjou-settings') throw new DOMException('synthetic', errorName); original.call(this, key, value); });
  fireEvent.click(screen.getByRole('button', { name: `Save ${name}` })); await screen.findByText('Save failed');
  expect(localStorage.getItem('bamendjou-settings')).toBe(oldBytes);
  expect(api.postCredentials).not.toHaveBeenCalled(); await checkWarning(`${label}: save failed`);
  blocked = false; await checkWarning(`${label}: save failed`); expect(outstanding().some(x => x.kind === 'local')).toBe(false); expect(localStorage.getItem('bamendjou-settings')).not.toBe(oldBytes); expect(api.postCredentials).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: `Save ${name}` })); await waitFor(() => expect(footer().queryByRole('alert')).not.toBeInTheDocument()); await checkSaved();
});
});
test('broker later edit discarded while earlier request succeeds remains discarded', async () => {
  const pending = deferred<never>(); api.postCredentials.mockImplementationOnce(() => pending.promise);
  render(<SettingsPage />); nav('Brokers'); fireEvent.change(brokerInput('IBKR Paper'), { target: { value: 'https://first.invalid' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save IBKR Paper' })); fireEvent.change(brokerInput('IBKR Paper'), { target: { value: 'https://later.invalid' } }); nav('Appearance');
  await act(async () => pending.resolve({} as never)); await checkWarning('IBKR Paper credentials: edit discarded');
  nav('Brokers'); fireEvent.click(screen.getByRole('button', { name: 'Save IBKR Paper' })); await waitFor(() => expect(footer().queryByRole('alert')).not.toBeInTheDocument()); await checkSaved();
});
const schedules = [['Ingestion', 'Data', 'Nightly OHLCV ingestion'], ['Edgar', 'Data', 'EDGAR fundamentals'], ['Sp500', 'Data', 'S&P 500 liquidity update'], ['Tuning', 'Strategy Tuning', 'Strategy tuning schedule']] as const;
function scheduleControls(index: number) { return { input: document.querySelectorAll('input[type="time"]')[index], save: screen.getAllByRole('button', { name: 'Save schedule' })[index] }; }
test.each(schedules)('%s schedule draft, discard, failure and successful own Save', async (key, section, label) => {
  const index = key === 'Edgar' ? 1 : key === 'Sp500' ? 2 : 0;
  const save = apiModule[`save${key}Schedule` as keyof typeof apiModule] as jest.Mock;
  render(<SettingsPage />); nav(section); await waitFor(() => expect(scheduleControls(index).input).toHaveValue('03:00'));
  fireEvent.change(scheduleControls(index).input, { target: { value: '06:15' } }); await checkWarning(`${label}: unsaved edit`); expect(save).not.toHaveBeenCalled();
  nav('Appearance'); expect(footer().getByRole('alert')).toHaveTextContent(`${label}: edit discarded`);
  nav(section); await waitFor(() => expect(scheduleControls(index).input).toHaveValue('03:00'));
  save.mockRejectedValueOnce(new Error('synthetic')); fireEvent.click(scheduleControls(index).save); await checkWarning(`${label}: save failed`);
  fireEvent.click(scheduleControls(index).save); await waitFor(() => expect(footer().queryByRole('alert')).not.toBeInTheDocument()); await checkSaved();
});

function mockEntry() {
  let server = { id: 'synthetic-entry', label: 'Synthetic scan', enabled: true, mode: 'stocks', profile_id: '', profile_name: '', profile_synced_at: '', resolved_request: {}, pattern: 'fixed_time', days_of_week: [0], fire_time: '09:00', cadence_minutes: null, window_start_hour: null, window_end_hour: null } as apiModule.ScanScheduleEntry;
  api.getScanSchedule.mockImplementation(async () => [{ ...server }]);
  api.updateScanScheduleEntry.mockImplementation(async (_id, payload) => { server = { ...server, ...payload }; return server; });
  return { get: () => server, commit: (payload: Partial<apiModule.ScanScheduleEntry>) => { server = { ...server, ...payload }; return server; } };
}
function entryRow() { return screen.getByDisplayValue('Synthetic scan').parentElement!.parentElement!; }
test('schedule failed enabled field stays failed after successful fire-time; own field save recovers', async () => {
  mockEntry(); api.updateScanScheduleEntry.mockRejectedValueOnce(new Error('synthetic'));
  render(<SettingsPage />); await openScan(); await screen.findByDisplayValue('Synthetic scan');
  fireEvent.click(within(entryRow()).getByRole('switch'));
  await checkWarning('Scheduled scan "Synthetic scan" enabled: save failed');
  fireEvent.change(entryRow().querySelector('input[type="time"]')!, { target: { value: '10:00' } });
  await waitFor(() => expect(api.updateScanScheduleEntry).toHaveBeenCalledTimes(2)); await checkWarning('enabled: save failed');
  fireEvent.click(within(entryRow()).getByRole('switch')); await waitFor(() => expect(footer().queryByRole('alert')).not.toBeInTheDocument()); await checkSaved();
});
test.each(['label-stale', 'enabled-stale'])('successful concurrent full-payload PUTs report UI/server draft %s', async stale => {
  const server = mockEntry(); const label = deferred<apiModule.ScanScheduleEntry>(); const enabled = deferred<apiModule.ScanScheduleEntry>();
  api.updateScanScheduleEntry.mockImplementationOnce(() => label.promise).mockImplementationOnce(() => enabled.promise);
  render(<SettingsPage />); await openScan(); await screen.findByDisplayValue('Synthetic scan');
  const input = screen.getByDisplayValue('Synthetic scan'); fireEvent.change(input, { target: { value: 'Edited scan' } }); fireEvent.blur(input);
  fireEvent.click(screen.getAllByRole('switch').find(el => el.closest('div')?.querySelector('input') === input)!);
  const labelPayload = api.updateScanScheduleEntry.mock.calls[0][1]; const enabledPayload = api.updateScanScheduleEntry.mock.calls[1][1];
  if (stale === 'label-stale') { await act(async () => label.resolve(server.commit(labelPayload))); await act(async () => enabled.resolve(server.commit(enabledPayload))); }
  else { await act(async () => enabled.resolve(server.commit(enabledPayload))); await act(async () => label.resolve(server.commit(labelPayload))); }
  await checkWarning(stale === 'label-stale' ? 'label: unsaved edit' : 'enabled: unsaved edit');
  expect(api.updateScanScheduleEntry).toHaveBeenCalledTimes(2);
  nav('Appearance'); expect(footer().getByRole('alert')).toHaveTextContent('edit discarded');
});

test.each(brokers)('%s explicit Save confirms the displayed draft and actual credential request', async (id, name, label) => {
  render(<SettingsPage />); nav('Brokers'); fireEvent.change(brokerInput(name), { target: { value: 'synthetic-new-value' } });
  await checkWarning(`${label}: unsaved edit`); fireEvent.click(screen.getByRole('button', { name: `Save ${name}` }));
  await waitFor(() => expect(footer().queryByRole('alert')).not.toBeInTheDocument());
  const field = id === 'ibkr_paper' ? 'base_url' : id === 'alpaca_paper' ? 'key_id' : id === 'tastytrade_paper' ? 'client_secret' : 'token';
  expect(api.postCredentials).toHaveBeenCalledWith(id, expect.objectContaining({ [field]: 'synthetic-new-value' }));
  expect(brokerInput(name)).toHaveValue('synthetic-new-value'); await checkSaved();
});
test.each(schedules)('%s explicit schedule Save confirms displayed draft and captured payload', async (key, section, label) => {
  const index = key === 'Edgar' ? 1 : key === 'Sp500' ? 2 : 0;
  const save = apiModule[`save${key}Schedule` as keyof typeof apiModule] as jest.Mock;
  render(<SettingsPage />); nav(section); await waitFor(() => expect(scheduleControls(index).input).toHaveValue('03:00'));
  fireEvent.change(scheduleControls(index).input, { target: { value: '06:15' } }); await checkWarning(`${label}: unsaved edit`);
  fireEvent.click(scheduleControls(index).save); await waitFor(() => expect(footer().queryByRole('alert')).not.toBeInTheDocument());
  expect(save).toHaveBeenCalledWith({ enabled: true, time: '06:15', ...(key === 'Tuning' ? { days_of_week: [5] } : {}) });
  expect(scheduleControls(index).input).toHaveValue('06:15'); await checkSaved();
});
test('notification explicit Save confirms submitted fields, cleared secrets and server readback', async () => {
  let server = { gmail: { enabled: false, to: '', smtp_user: '' }, telegram: { enabled: false, chat_id: '' } };
  (fetch as jest.Mock).mockImplementation(async (_url, options) => { if (options?.method === 'POST') server = JSON.parse(options.body); return { ok: true, json: async () => server }; });
  render(<SettingsPage />); nav('Notifications'); await screen.findByRole('button', { name: 'Save settings' });
  fireEvent.change(screen.getAllByPlaceholderText('you@gmail.com')[0], { target: { value: 'synthetic@example.test' } });
  fireEvent.change(screen.getAllByPlaceholderText('leave blank to keep saved value')[0], { target: { value: 'synthetic-password' } });
  await checkWarning('Notifications: unsaved edit'); fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));
  await waitFor(() => expect(footer().queryByRole('alert')).not.toBeInTheDocument());
  expect(server.gmail.to).toBe('synthetic@example.test'); expect(screen.getAllByPlaceholderText('leave blank to keep saved value')[0]).toHaveValue('');
  nav('Appearance'); nav('Notifications'); await waitFor(() => expect(screen.getAllByPlaceholderText('you@gmail.com')[0]).toHaveValue('synthetic@example.test')); await checkSaved();
});
test('schedule pattern patch shares one failed request across every patched field and later succeeds', async () => {
  mockEntry(); api.updateScanScheduleEntry.mockRejectedValueOnce(new Error('synthetic'));
  render(<SettingsPage />); await openScan(); await screen.findByDisplayValue('Synthetic scan');
  const pattern = within(entryRow()).getByDisplayValue('Fixed time'); fireEvent.change(pattern, { target: { value: 'loop' } });
  await checkWarning('pattern: save failed');
  for (const field of ['pattern', 'fire_time', 'cadence_minutes', 'window_start_hour', 'window_end_hour']) expect(footer().getByRole('alert')).toHaveTextContent(`${field}: save failed`);
  expect(api.updateScanScheduleEntry).toHaveBeenCalledTimes(1);
  expect(api.updateScanScheduleEntry).toHaveBeenCalledWith('synthetic-entry', expect.objectContaining({ pattern: 'loop', fire_time: null, cadence_minutes: 60, window_start_hour: 9, window_end_hour: 17 }));
  fireEvent.change(pattern, { target: { value: 'loop' } }); await waitFor(() => expect(footer().queryByRole('alert')).not.toBeInTheDocument()); expect(api.updateScanScheduleEntry).toHaveBeenCalledTimes(2); await checkSaved();
});
test('schedule label draft is discarded on navigation and only its subsequent blur save clears it', async () => {
  mockEntry(); render(<SettingsPage />); await openScan(); await screen.findByDisplayValue('Synthetic scan');
  fireEvent.change(screen.getByDisplayValue('Synthetic scan'), { target: { value: 'Draft label' } }); await checkWarning('label: unsaved edit');
  expect(api.updateScanScheduleEntry).not.toHaveBeenCalled(); nav('Appearance'); expect(footer().getByRole('alert')).toHaveTextContent('label: edit discarded');
  await openScan(); await screen.findByDisplayValue('Synthetic scan'); const input = screen.getByDisplayValue('Synthetic scan'); fireEvent.change(input, { target: { value: 'Confirmed label' } }); fireEvent.blur(input);
  await waitFor(() => expect(footer().queryByRole('alert')).not.toBeInTheDocument()); expect(api.updateScanScheduleEntry).toHaveBeenCalledWith('synthetic-entry', expect.objectContaining({ label: 'Confirmed label' })); await screen.findByDisplayValue('Confirmed label'); await checkSaved();
});

test('unknown retention baseline keeps edited-then-reverted default dirty until explicit Save', async () => {
  api.getScheduledScanRunRetention.mockRejectedValue(new Error('synthetic load failure'));
  render(<SettingsPage />); await openScan(); fireEvent.change(retention().input, { target: { value: '120' } }); fireEvent.change(retention().input, { target: { value: '90' } });
  await checkWarning('Scheduled scan history retention: unsaved edit'); expect(api.saveScheduledScanRunRetention).not.toHaveBeenCalled();
  fireEvent.click(retention().save); await waitFor(() => expect(footer().queryByRole('alert')).not.toBeInTheDocument()); expect(api.saveScheduledScanRunRetention).toHaveBeenCalledWith(90); await checkSaved();
});
test('unknown notifications baseline keeps edited-then-reverted defaults dirty until explicit Save', async () => {
  (fetch as jest.Mock).mockResolvedValueOnce({ ok: false, status: 500 }); render(<SettingsPage />); nav('Notifications'); await screen.findByRole('button', { name: 'Save settings' });
  await act(async () => {});
  const input = screen.getAllByPlaceholderText('you@gmail.com')[0]; fireEvent.change(input, { target: { value: 'synthetic@example.test' } }); fireEvent.change(input, { target: { value: '' } });
  await checkWarning('Notifications: unsaved edit'); expect(fetch).toHaveBeenCalledTimes(1); fireEvent.click(screen.getByRole('button', { name: 'Save settings' })); await waitFor(() => expect(footer().queryByRole('alert')).not.toBeInTheDocument()); await checkSaved();
});
test.each(schedules)('%s unknown schedule baseline keeps edited-then-reverted defaults dirty until Save', async (key, section, label) => {
  const load = apiModule[`get${key}Schedule` as keyof typeof apiModule] as jest.Mock; load.mockRejectedValueOnce(new Error('synthetic load failure'));
  const index = key === 'Edgar' ? 1 : key === 'Sp500' ? 2 : 0;
  render(<SettingsPage />); nav(section); await waitFor(() => expect(load).toHaveBeenCalled());
  const toggle = screen.getAllByRole('switch')[index]; fireEvent.click(toggle); fireEvent.click(toggle);
  await checkWarning(`${label}: unsaved edit`); fireEvent.click(scheduleControls(index).save); await waitFor(() => expect(footer().queryByRole('alert')).not.toBeInTheDocument()); await checkSaved();
});
