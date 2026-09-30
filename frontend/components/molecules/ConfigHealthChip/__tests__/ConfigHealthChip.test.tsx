import '@testing-library/jest-dom';
import React from 'react';
import { render, screen, act, fireEvent, within } from '@testing-library/react';
import { api } from '@/lib/api';
import { ConfigHealthChip } from '../index';
import { ConfigHealthBanner } from '@/components/organisms/ConfigHealthBanner';
import { useConfigHealthStore } from '@/lib/configHealthStore';
import {
  CLEAN_REPORT, ERROR_REPORT, STALE_REPORT, WARNING_REPORT, CRASH_REPORT,
  SHIPPED_CHECKED, SHIPPED_NOT_CHECKED,
} from '@/lib/testFixtures/configHealth';

jest.mock('@/lib/api', () => ({ api: { getConfigHealth: jest.fn() } }));
const getHealth = api.getConfigHealth as jest.Mock;
const INITIAL = useConfigHealthStore.getState();
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); });

beforeEach(() => {
  jest.useFakeTimers({ now: 20_000_000 });
  useConfigHealthStore.setState({ ...INITIAL, now: Date.now() }, true);
  getHealth.mockReset();
});
afterEach(() => jest.useRealTimers());

describe('ConfigHealthChip', () => {
  it('C1: "checking" before the first answer, never OK', () => {
    getHealth.mockReturnValue(new Promise(() => {}));
    render(<><ConfigHealthChip /><ConfigHealthBanner /></>);
    expect(screen.getByText('Config: checking…')).toBeInTheDocument();
    expect(screen.queryByText(/Config OK/)).toBeNull();
  });

  it('C2: clean reads "Config OK · 10 checks"; the popover lists both scopes', async () => {
    getHealth.mockResolvedValue(clone(CLEAN_REPORT));
    render(<><ConfigHealthChip /><ConfigHealthBanner /></>);
    await flush();
    const chip = screen.getByRole('button', { name: 'Config OK · 10 checks' });
    fireEvent.click(chip);
    const pop = screen.getByRole('dialog', { name: 'Config health scope' });
    const items = within(pop).getAllByRole('listitem').map((li) => li.textContent);
    expect(items).toEqual([...SHIPPED_CHECKED, ...SHIPPED_NOT_CHECKED]);
    expect(pop).toHaveTextContent('Last checked');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.click(chip);
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('C3: an error shows "Config error"; a click re-expands a collapsed banner and focuses it', async () => {
    getHealth.mockResolvedValue(clone(ERROR_REPORT));
    render(<><ConfigHealthChip /><ConfigHealthBanner /></>);
    await flush();
    fireEvent.click(screen.getByRole('button', { name: 'Collapse' }));
    expect(screen.getByRole('button', { name: 'Show details' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Config error' }));
    expect(screen.getByRole('button', { name: 'Collapse' })).toBeInTheDocument();
    expect(document.activeElement).toBe(document.getElementById('config-health-banner'));
  });

  it.each([
    ['clean', CLEAN_REPORT], ['error', ERROR_REPORT], ['stale', STALE_REPORT],
    ['warning', WARNING_REPORT], ['error', CRASH_REPORT],
  ])('C4: chip and banner agree (%s)', async (tier, report) => {
    getHealth.mockResolvedValue(clone(report));
    const { container } = render(<><ConfigHealthChip /><ConfigHealthBanner /></>);
    await flush();
    const chip = container.querySelector('[data-tier]')!;
    expect(chip).toHaveAttribute('data-tier', tier);
    const b = document.getElementById('config-health-banner');
    if (tier === 'clean') expect(b).toBeNull();
    else expect(b).toHaveAttribute('data-tier', tier);
  });

  it('C4b: they agree on unknown and multiworker too', async () => {
    getHealth.mockRejectedValueOnce(new Error('down'));
    const { container } = render(<><ConfigHealthChip /><ConfigHealthBanner /></>);
    await flush();
    expect(container.querySelector('[data-tier]')).toHaveAttribute('data-tier', 'unknown');
    expect(document.getElementById('config-health-banner')).toHaveAttribute('data-tier', 'unknown');
    act(() => useConfigHealthStore.setState({
      report: CLEAN_REPORT, status: 'ready', error: null, fetchedAt: Date.now(), now: Date.now(),
      multiWorker: true,
    }));
    expect(container.querySelector('[data-tier]')).toHaveAttribute('data-tier', 'multiworker');
    expect(document.getElementById('config-health-banner')).toHaveAttribute('data-tier', 'multiworker');
  });

  it('C5: an aged clean report is not "Config OK" on the chip either', async () => {
    getHealth.mockResolvedValueOnce(clone(CLEAN_REPORT));
    render(<><ConfigHealthChip /><ConfigHealthBanner /></>);
    await flush();
    expect(screen.getByRole('button', { name: /Config OK/ })).toBeInTheDocument();
    getHealth.mockReturnValue(new Promise(() => {}));
    await act(async () => { jest.advanceTimersByTime(75_000); });
    expect(screen.queryByText(/Config OK/)).toBeNull();
    expect(screen.getByRole('button', { name: 'Config unknown' })).toBeInTheDocument();
  });
});
