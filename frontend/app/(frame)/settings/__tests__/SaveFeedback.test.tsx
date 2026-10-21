import '@testing-library/jest-dom';
import { act, render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import SettingsPage from '../page';
import { api, getRiskSettings, saveRiskSettings } from '@/lib/api';
import { useSettingsSaveStatus } from '@/lib/settingsSaveStatus';
import { useThemeStore } from '@/lib/theme';
import { useSettingsStore } from '@/lib/settingsStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { useIvThresholdsStore } from '@/lib/ivThresholdsStore';
jest.mock('@/lib/api', () => ({ api: { getSchedulingTimezone: jest.fn(), putSchedulingTimezone: jest.fn(), getScheduledScanRunRetention: jest.fn().mockResolvedValue({ scheduledScanRunRetentionDays: 90 }), getScanSchedule: jest.fn().mockResolvedValue([]), getScanScheduleEntryRuns: jest.fn().mockResolvedValue([]) }, getRiskSettings: jest.fn(), saveRiskSettings: jest.fn() }));
const mockApi = api as jest.Mocked<typeof api>;
const footer = () => within(document.querySelector('footer')!);
const clickFooter = () => fireEvent.click(footer().getByRole('button', { name: 'Save changes' }));
const nav = (name: string) => fireEvent.click(screen.getByText(name, { exact: true }));
function timezone() { const row = screen.getByText('Timezone').closest('div')!.parentElement!; return { input: row.querySelector('input')!, save: within(row).getByRole('button', { name: 'Save' }) }; }
async function scan() { nav('Scan'); await waitFor(() => expect(mockApi.getSchedulingTimezone).toHaveBeenCalled()); }
beforeEach(() => { jest.clearAllMocks(); useSettingsSaveStatus.setState({ channels: {}, localFailures: {} }); mockApi.getSchedulingTimezone.mockResolvedValue({ timezone: 'Europe/Berlin' }); mockApi.putSchedulingTimezone.mockImplementation(async (timezone) => ({ timezone })); (getRiskSettings as jest.Mock).mockResolvedValue({ premiumStopPct: .6, portfolioValue: 50000, targetT1Pct: .2, targetT2Pct: .35, targetT3Pct: .5 }); (saveRiskSettings as jest.Mock).mockResolvedValue(undefined); });
afterEach(() => jest.restoreAllMocks());
test('risk failed blur before footer names Risk limits, then real successful blur confirms', async () => {
    (saveRiskSettings as jest.Mock).mockRejectedValueOnce(new Error('synthetic 500 secret'));
    render(<SettingsPage />);
    nav('Risk');
    await waitFor(() => expect(screen.getByDisplayValue('50000')).toBeInTheDocument());
    const input = screen.getByDisplayValue('50000');
    fireEvent.change(input, { target: { value: '234567' } });
    fireEvent.blur(input);
    clickFooter();
    await waitFor(() => expect(footer().getByRole('alert')).toHaveTextContent('Risk limits: save failed'));
    expect(footer().queryByText('Saved')).not.toBeInTheDocument();
    expect(saveRiskSettings).toHaveBeenCalledWith(expect.objectContaining({ portfolioValue: 234567 }));
    expect(footer().getByRole('alert')).not.toHaveTextContent('secret');
    fireEvent.blur(input);
    await waitFor(() => expect(footer().queryByRole('alert')).not.toBeInTheDocument());
    clickFooter();
    await waitFor(() => expect(footer().getByRole('status')).toHaveTextContent('Saved'));
    expect(saveRiskSettings).toHaveBeenCalledTimes(2);
});
test('footer waits for pending risk blur and reports its real outcome', async () => {
    let reject!: (error: Error) => void;
    (saveRiskSettings as jest.Mock).mockImplementation(() => new Promise((_, r) => { reject = r; }));
    render(<SettingsPage />);
    nav('Risk');
    await waitFor(() => expect(screen.getByDisplayValue('50000')).toBeInTheDocument());
    fireEvent.blur(screen.getByDisplayValue('50000'));
    clickFooter();
    expect(footer().getByRole('button', { name: 'Saving…' })).toBeDisabled();
    await act(async () => reject(new Error('synthetic')));
    expect(footer().getByRole('alert')).toHaveTextContent('Risk limits');
});
test('timezone draft sends zero PUTs; own Save confirms captured value and clears warning', async () => {
    render(<SettingsPage />);
    await scan();
    fireEvent.change(timezone().input, { target: { value: 'Asia/Tokyo' } });
    clickFooter();
    await waitFor(() => expect(footer().getByRole('alert')).toHaveTextContent('Operator timezone: unsaved edit'));
    expect(mockApi.putSchedulingTimezone).not.toHaveBeenCalled();
    fireEvent.click(timezone().save);
    await waitFor(() => expect(footer().queryByRole('alert')).not.toBeInTheDocument());
    expect(mockApi.putSchedulingTimezone).toHaveBeenCalledWith('Asia/Tokyo');
    clickFooter();
    await waitFor(() => expect(footer().getByRole('status')).toHaveTextContent('Saved'));
});
test.each([false, true])('timezone discarded persists including earlier pending completion=%s', async (pending) => {
    let resolve!: (value: {
        timezone: string;
    }) => void;
    if (pending)
        mockApi.putSchedulingTimezone.mockImplementationOnce(() => new Promise((r) => { resolve = r; }));
    render(<SettingsPage />);
    await scan();
    fireEvent.change(timezone().input, { target: { value: 'Asia/Tokyo' } });
    if (pending)
        fireEvent.click(timezone().save);
    fireEvent.change(timezone().input, { target: { value: 'America/Chicago' } });
    nav('Appearance');
    if (pending)
        await act(async () => resolve({ timezone: 'Asia/Tokyo' }));
    clickFooter();
    await waitFor(() => expect(footer().getByRole('alert')).toHaveTextContent('Operator timezone: edit discarded'));
    expect(mockApi.putSchedulingTimezone).toHaveBeenCalledTimes(pending ? 1 : 0);
    await scan();
    fireEvent.click(timezone().save);
    await waitFor(() => expect(footer().queryByRole('alert')).not.toBeInTheDocument());
});
const localCases = [
    { name: 'theme', key: 'bamendjou:theme', label: 'Appearance (this browser)', write: () => useThemeStore.getState().setTheme('light'), read: () => useThemeStore.getState().theme, value: 'light', store: useThemeStore },
    { name: 'Markov', key: 'bamendjou-settings', label: 'Settings (this browser)', write: () => useSettingsStore.getState().setMarkov({ ...useSettingsStore.getState().markov, lookback: 199 }), read: () => useSettingsStore.getState().markov.lookback, value: 199, store: useSettingsStore },
    { name: 'confidence', key: 'bamendjou-settings', label: 'Settings (this browser)', write: () => useSettingsStore.getState().setConfidenceGate({ ...useSettingsStore.getState().confidenceGate, cautionBelow: 67 }), read: () => useSettingsStore.getState().confidenceGate.cautionBelow, value: 67, store: useSettingsStore },
];
describe.each(localCases)('$name storage reporting', ({ key, label, write, read, value, store }) => {
    test.each(['QuotaExceededError', 'SecurityError'])('%s keeps old bytes then footer retry and readback', async (errorName) => {
        act(() => { useThemeStore.setState({ theme: 'dark' }); useSettingsStore.setState({ markov: { ...useSettingsStore.getState().markov, lookback: 20 }, confidenceGate: { ...useSettingsStore.getState().confidenceGate, cautionBelow: 50 } }); });
        const old = localStorage.getItem(key);
        const original = Storage.prototype.setItem;
        let blocked = true;
        jest.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, k, v) { if (blocked && k === key)
            throw new DOMException('synthetic sensitive detail', errorName); original.call(this, k, v); });
        render(<SettingsPage />);
        act(() => { expect(write).toThrow(/synthetic/); });
        expect(read()).toEqual(value);
        expect(localStorage.getItem(key)).toBe(old);
        clickFooter();
        await waitFor(() => expect(footer().getByRole('alert')).toHaveTextContent(label));
        expect(footer().getByRole('alert')).not.toHaveTextContent('sensitive');
        blocked = false;
        clickFooter();
        await waitFor(() => expect(footer().getByRole('status')).toHaveTextContent('Saved'));
        expect(localStorage.getItem(key)).not.toBe(old);
        const newBytes = localStorage.getItem(key)!;
        // Reset memory while preserving the committed bytes to simulate a fresh hydration.
        act(() => {
            if (key === 'bamendjou:theme')
                useThemeStore.setState({ theme: 'dark' });
            else
                useSettingsStore.setState({ markov: { ...useSettingsStore.getState().markov, lookback: 20 }, confidenceGate: { ...useSettingsStore.getState().confidenceGate, cautionBelow: 50 } });
        });
        localStorage.setItem(key, newBytes);
        await act(async () => { await store.persist.rehydrate(); });
        expect(read()).toEqual(value);
    });
});
test.each(['valid commit', 'clear'])('invalid strategy draft discarded until %s', async (action) => {
    useScanParamsStore.setState({ maCrossoverLookback: 5 });
    render(<SettingsPage />);
    nav('Strategy scan');
    fireEvent.change(screen.getByLabelText('MA crossover lookback'), { target: { value: '99' } });
    clickFooter();
    await waitFor(() => expect(footer().getByRole('alert')).toHaveTextContent('MA crossover lookback: invalid value not applied'));
    nav('Appearance');
    expect(footer().getByRole('alert')).toHaveTextContent('edit discarded');
    nav('Strategy scan');
    fireEvent.change(screen.getByLabelText('MA crossover lookback'), { target: { value: action === 'clear' ? '' : '12' } });
    await waitFor(() => expect(footer().queryByRole('alert')).not.toBeInTheDocument());
    expect(useScanParamsStore.getState().maCrossoverLookback).toBe(action === 'clear' ? null : 12);
});
test.each(['Apply thresholds', 'Reset to scoring_rules.yaml'])('IV draft discarded then cleared by %s', async (button) => {
    jest.spyOn(useIvThresholdsStore.getState(), 'fetch').mockResolvedValue(undefined);
    useIvThresholdsStore.setState({ thresholds: { Swing: { abs_pass_max: 45 }, Position: { abs_pass_max: 55 } } as never, overrides: {}, status: 'ready' });
    render(<SettingsPage />);
    await scan();
    fireEvent.change(screen.getByLabelText('Swing pass max'), { target: { value: '60' } });
    clickFooter();
    await waitFor(() => expect(footer().getByRole('alert')).toHaveTextContent('IV thresholds (session): unsaved edit'));
    nav('Appearance');
    expect(footer().getByRole('alert')).toHaveTextContent('edit discarded');
    await scan();
    if (button === 'Apply thresholds')
        fireEvent.change(screen.getByLabelText('Swing pass max'), { target: { value: '61' } });
    fireEvent.click(screen.getByRole('button', { name: button }));
    await waitFor(() => expect(footer().queryByRole('alert')).not.toBeInTheDocument());
});
test('new pending save clears footer Saved during its confirmation window', async () => {
    let resolve!: () => void;
    (saveRiskSettings as jest.Mock).mockImplementation(() => new Promise<void>((r) => { resolve = r; }));
    render(<SettingsPage />);
    nav('Risk');
    await waitFor(() => expect(screen.getByDisplayValue('50000')).toBeInTheDocument());
    clickFooter();
    await waitFor(() => expect(footer().getByRole('status')).toHaveTextContent('Saved'));
    fireEvent.blur(screen.getByDisplayValue('50000'));
    expect(footer().queryByRole('status')).not.toBeInTheDocument();
    await act(async () => resolve());
});
test('timezone baseline clears a reverted edit without a PUT', async () => {
    render(<SettingsPage />);
    await scan();
    fireEvent.change(timezone().input, { target: { value: 'Asia/Tokyo' } });
    clickFooter();
    await waitFor(() => expect(footer().getByRole('alert')).toHaveTextContent('Operator timezone'));
    fireEvent.change(timezone().input, { target: { value: 'Europe/Berlin' } });
    await waitFor(() => expect(footer().queryByRole('alert')).not.toBeInTheDocument());
    expect(mockApi.putSchedulingTimezone).not.toHaveBeenCalled();
});
test('failed timezone load guards untouched default, then edited value saves', async () => {
    mockApi.getSchedulingTimezone.mockRejectedValue(new Error('synthetic'));
    render(<SettingsPage />);
    await scan();
    await screen.findByTestId('timezone-load-error');
    expect(timezone().save).toBeDisabled();
    clickFooter();
    await waitFor(() => expect(footer().getByRole('status')).toHaveTextContent('Saved'));
    expect(mockApi.putSchedulingTimezone).not.toHaveBeenCalled();
    fireEvent.change(timezone().input, { target: { value: 'Asia/Tokyo' } });
    fireEvent.click(timezone().save);
    await waitFor(() => expect(mockApi.putSchedulingTimezone).toHaveBeenCalledWith('Asia/Tokyo'));
});
