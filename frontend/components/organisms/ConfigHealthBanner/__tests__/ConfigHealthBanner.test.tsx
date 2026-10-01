import '@testing-library/jest-dom';
import React from 'react';
import { render, screen, act, fireEvent } from '@testing-library/react';
import { api } from '@/lib/api';
import { ConfigHealthBanner } from '../index';
import { ConfigHealthChip } from '@/components/molecules/ConfigHealthChip';
import { useConfigHealthStore } from '@/lib/configHealthStore';
import {
  CLEAN_REPORT, ERROR_REPORT, STALE_REPORT, WARNING_REPORT, CRASH_REPORT, SHIPPED_CHECKED,
  SHIPPED_NOT_CHECKED,
} from '@/lib/testFixtures/configHealth';

jest.mock('@/lib/api', () => ({ api: { getConfigHealth: jest.fn() } }));
const getHealth = api.getConfigHealth as jest.Mock;
const INITIAL = useConfigHealthStore.getState();
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

let visibility: DocumentVisibilityState = 'visible';
Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => visibility });

const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); });
const banner = () => document.getElementById('config-health-banner');

beforeEach(() => {
  jest.useFakeTimers({ now: 10_000_000 });
  useConfigHealthStore.setState({ ...INITIAL, now: Date.now() }, true);
  getHealth.mockReset();
  visibility = 'visible';
});
afterEach(() => jest.useRealTimers());

describe('ConfigHealthBanner', () => {
  it('B1: polls once on mount, shows nothing until answered, nothing when clean', async () => {
    let resolve!: (v: unknown) => void;
    getHealth.mockReturnValueOnce(new Promise((r) => { resolve = r; }));
    render(<ConfigHealthBanner />);
    expect(getHealth).toHaveBeenCalledTimes(1);
    expect(banner()).toBeNull();
    resolve(clone(CLEAN_REPORT));
    await flush();
    expect(banner()).toBeNull();
  });

  it.each([
    ['error', ERROR_REPORT, /Config error: 1 problem in scoring_rules\.yaml\. The stock scan and every auto-trade fire are refused/],
    ['stale', STALE_REPORT, /Config changed on disk: restart the backend/],
    ['warning', WARNING_REPORT, /Config warning: 1 warning\./],
  ])('B2: %s tier headline, detail and scope', async (tier, report, head) => {
    getHealth.mockResolvedValueOnce(clone(report));
    render(<ConfigHealthBanner />);
    await flush();
    const b = banner()!;
    expect(b).toHaveAttribute('data-tier', tier);
    expect(b).toHaveTextContent(head);
    const line = [...report.errors, ...report.stale, ...report.warnings][0];
    expect(b).toHaveTextContent(`${line.file} · ${line.path}: ${line.message}`);
    if (tier === 'error') {
      expect(b).toHaveTextContent('Blocks: the stock scan and every auto-trade fire');
      expect(screen.getByRole('alert')).toBe(b);
    } else {
      expect(screen.queryByRole('alert')).toBeNull();
    }
    expect(b).toHaveTextContent(`Checked: ${SHIPPED_CHECKED.join('; ')}`);
    expect(b).toHaveTextContent(`Not checked: ${SHIPPED_NOT_CHECKED[0]}`);
    expect(b).toHaveTextContent('Last checked');
  });

  it('B2b: the crash shape has no empty subject and says nothing was checked', async () => {
    getHealth.mockResolvedValueOnce(clone(CRASH_REPORT));
    render(<ConfigHealthBanner />);
    await flush();
    const b = banner()!;
    expect(b).toHaveTextContent(/^Config error: 1 problem\.(?! )/);
    expect(b).not.toHaveTextContent('are refused');
    expect(b).toHaveTextContent('Checked: nothing, the health check itself failed');
  });

  it('B2c: the worst tier leads and the others are counted', async () => {
    getHealth.mockResolvedValueOnce({
      ...clone(ERROR_REPORT), stale: STALE_REPORT.stale, warnings: WARNING_REPORT.warnings,
    });
    render(<ConfigHealthBanner />);
    await flush();
    expect(banner()).toHaveAttribute('data-tier', 'error');
    expect(banner()).toHaveTextContent('· also 1 stale, 1 warning');
  });

  it('B3: a 500 shows unknown with the status; the next good poll clears it', async () => {
    getHealth.mockRejectedValueOnce(new Error('API /api/config/health → 500: Internal'));
    render(<ConfigHealthBanner />);
    await flush();
    expect(banner()).toHaveTextContent('Config health unknown: API /api/config/health → 500');
    expect(banner()).toHaveTextContent('Nothing could be checked.');
    getHealth.mockResolvedValueOnce(clone(CLEAN_REPORT));
    await act(async () => { jest.advanceTimersByTime(30_000); });
    await flush();
    expect(banner()).toBeNull();
  });

  it('B3b: after a 500 the pending retry keeps the strip, and the chip is not "checking"', async () => {
    getHealth.mockRejectedValueOnce(new Error('API /api/config/health → 500'));
    render(<><ConfigHealthChip /><ConfigHealthBanner /></>);
    await flush();
    getHealth.mockReturnValueOnce(new Promise(() => {}));
    await act(async () => { jest.advanceTimersByTime(30_000); });
    expect(getHealth).toHaveBeenCalledTimes(2);
    expect(useConfigHealthStore.getState().status).toBe('loading');
    expect(banner()).toHaveTextContent('Config health unknown');
    expect(screen.queryByText(/checking/)).toBeNull();
    expect(screen.getByRole('button', { name: 'Config unknown' })).toBeInTheDocument();
  });

  it('B4: hidden tabs do not poll; visible polls at once; focus right after does not', async () => {
    getHealth.mockResolvedValue(clone(CLEAN_REPORT));
    render(<ConfigHealthBanner />);
    await flush();
    expect(getHealth).toHaveBeenCalledTimes(1);
    visibility = 'hidden';
    await act(async () => { jest.advanceTimersByTime(90_000); });
    expect(getHealth).toHaveBeenCalledTimes(1);
    visibility = 'visible';
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')); });
    expect(getHealth).toHaveBeenCalledTimes(2);
    await act(async () => { window.dispatchEvent(new Event('focus')); });
    expect(getHealth).toHaveBeenCalledTimes(2);
    await act(async () => { jest.advanceTimersByTime(2_000); window.dispatchEvent(new Event('focus')); });
    expect(getHealth).toHaveBeenCalledTimes(3);
  });

  it('B5: collapse keeps the headline; a changed finding re-expands; the same one does not', async () => {
    getHealth.mockResolvedValue(clone(WARNING_REPORT));
    render(<ConfigHealthBanner />);
    await flush();
    fireEvent.click(screen.getByRole('button', { name: 'Collapse' }));
    expect(banner()).toHaveTextContent('Config warning');
    expect(banner()).not.toHaveTextContent('Checked:');
    expect(screen.getByRole('button', { name: 'Show details' })).toHaveAttribute('aria-expanded', 'false');

    await act(async () => { jest.advanceTimersByTime(30_000); });
    await flush();
    expect(banner()).not.toHaveTextContent('Checked:');

    getHealth.mockResolvedValue({ ...clone(WARNING_REPORT),
      warnings: [{ ...WARNING_REPORT.warnings[0], message: 'another' }] });
    await act(async () => { jest.advanceTimersByTime(30_000); });
    await flush();
    expect(banner()).toHaveTextContent('Checked:');
  });

  it('B6: a clean report aged past 70 s behind a hidden tab is unknown on return, via rule 3', async () => {
    getHealth.mockResolvedValueOnce(clone(CLEAN_REPORT));
    render(<ConfigHealthBanner />);
    await flush();
    expect(banner()).toBeNull();
    visibility = 'hidden';
    jest.setSystemTime(Date.now() + 75_000);
    getHealth.mockReturnValueOnce(new Promise(() => {}));   // the return poll hangs
    visibility = 'visible';
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')); });
    expect(useConfigHealthStore.getState().report).not.toBeNull();   // rule 3, not rule 2
    expect(banner()).toHaveTextContent('Config health unknown: last check is older than 70 s');
    expect(banner()).toHaveTextContent('Nothing could be checked.');
    expect(banner()).not.toHaveTextContent('Checked:');
  });

  it('B3c: an empty failure reason falls back; a long one is cut', async () => {
    getHealth.mockRejectedValueOnce(new Error(''));
    render(<ConfigHealthBanner />);
    await flush();
    expect(banner()).toHaveTextContent('Config health unknown: no details. Retrying');
    getHealth.mockRejectedValueOnce(new Error('<html>' + 'x'.repeat(500)));
    await act(async () => { jest.advanceTimersByTime(30_000); });
    await flush();
    expect(banner()!.textContent!.length).toBeLessThan(600);
    expect(banner()).toHaveTextContent('…');
  });

  it('B5b: a clean poll resets collapse, so the same finding returns expanded', async () => {
    getHealth.mockResolvedValue(clone(WARNING_REPORT));
    render(<ConfigHealthBanner />);
    await flush();
    fireEvent.click(screen.getByRole('button', { name: 'Collapse' }));
    getHealth.mockResolvedValueOnce(clone(CLEAN_REPORT));
    await act(async () => { jest.advanceTimersByTime(30_000); });
    await flush();
    expect(banner()).toBeNull();
    await act(async () => { jest.advanceTimersByTime(30_000); });
    await flush();
    expect(banner()).toHaveTextContent('Checked:');
  });

  it('B7: unmount clears every interval and listener', async () => {
    getHealth.mockResolvedValue(clone(CLEAN_REPORT));
    const setI = jest.spyOn(global, 'setInterval');
    const clearI = jest.spyOn(global, 'clearInterval');
    const { unmount } = render(<ConfigHealthBanner />);
    await flush();
    const ids = setI.mock.results.map((r) => r.value);
    expect(ids).toHaveLength(2);
    unmount();
    const cleared = clearI.mock.calls.map((c) => c[0]);
    for (const id of ids) expect(cleared).toContain(id);
    await act(async () => {
      jest.advanceTimersByTime(120_000);
      document.dispatchEvent(new Event('visibilitychange'));
      window.dispatchEvent(new Event('focus'));
    });
    expect(getHealth).toHaveBeenCalledTimes(1);
    setI.mockRestore(); clearI.mockRestore();
  });
});
