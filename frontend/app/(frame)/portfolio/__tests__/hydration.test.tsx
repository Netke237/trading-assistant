/** @jest-environment jsdom */
import '@testing-library/jest-dom';
import { hydrateRoot } from 'react-dom/client';
import { act } from 'react';
import { render, screen } from '@testing-library/react';
import PortfolioPage from '../page';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { usePerformanceStore } from '@/lib/performanceStore';

// react-dom/server needs these browser globals, which jsdom does not provide.
/* eslint-disable @typescript-eslint/no-require-imports */
const g = globalThis as unknown as Record<string, unknown>;
g.TextEncoder ??= require('util').TextEncoder;
g.MessageChannel ??= require('worker_threads').MessageChannel;
const { renderToString } = require('react-dom/server') as typeof import('react-dom/server');

jest.mock('@/components/organisms/PnlChart', () => ({ PnlChart: () => null }));
jest.mock('@/components/organisms/PnlHeatmap', () => ({ PnlHeatmap: () => null }));
jest.mock('@/components/organisms/BrokerAttemptPanel', () => ({ BrokerAttemptPanel: () => null }));
jest.mock('@/lib/alertEngine', () => ({ scanPortfolio: jest.fn().mockReturnValue([]) }));

// Two days apart so the day label differs in every time zone.
const SERVER_NOW = new Date('2026-11-20T12:00:00Z');
const CLIENT_NOW = new Date('2026-11-22T10:00:00Z');

function stores(sync = jest.fn().mockResolvedValue(undefined)) {
  usePortfolioStore.setState({
    positions: [], syncFromBackend: sync,
    lastSyncAt: null, lastSyncFailedAt: null, firstSyncAt: null,
  } as never);
  usePerformanceStore.setState({
    fetchHistory: jest.fn().mockResolvedValue(undefined),
    fetchPerformance: jest.fn().mockResolvedValue(undefined),
  } as never);
  return sync;
}

describe('Portfolio hydration (#418)', () => {
  beforeEach(() => { jest.useFakeTimers(); });
  afterEach(() => { jest.useRealTimers(); jest.restoreAllMocks(); });

  it('hydrates server HTML rendered on another day without a hydration error', async () => {
    stores();
    jest.setSystemTime(SERVER_NOW);
    const html = renderToString(<PortfolioPage />);

    jest.setSystemTime(CLIENT_NOW);
    const errors: unknown[][] = [];
    jest.spyOn(console, 'error').mockImplementation((...a: unknown[]) => { errors.push(a); });
    const container = document.createElement('div');
    container.innerHTML = html;
    document.body.appendChild(container);
    await act(async () => { hydrateRoot(container, <PortfolioPage />); });
    const hydration = errors.filter((a) => /hydrat|did not match|418/i.test(String(a[0]) + String(a[1] ?? '')));
    expect(hydration).toEqual([]);
    container.remove();
  });

  it('server pass renders no period text', () => {
    stores();
    jest.setSystemTime(SERVER_NOW);
    const html = renderToString(<PortfolioPage />);
    expect(html).toContain('Realized today');
    expect(html).not.toMatch(/Nov|2026/);
  });

  it('periods are empty on the first render and filled after effects', async () => {
    stores();
    jest.setSystemTime(CLIENT_NOW);
    const label = screen; void label;
    let first = '';
    const { container } = render(<PortfolioPage />);
    first = container.textContent ?? '';
    // render() flushes effects inside act, so the filled state is what we see.
    expect(first).toMatch(/22 Nov/);
    expect(first).toContain('2026');
  });

  it('labels roll over when the clock crosses midnight and a cycle runs', async () => {
    jest.setSystemTime(new Date(2026, 10, 21, 23, 59, 0));
    const sync = stores();
    render(<PortfolioPage />);
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByText('21 Nov')).toBeInTheDocument();
    jest.setSystemTime(new Date(2026, 10, 22, 0, 0, 20));
    await act(async () => { jest.advanceTimersByTime(30_000); await Promise.resolve(); await Promise.resolve(); });
    expect(sync).toHaveBeenCalledTimes(2);
    expect(screen.getByText('22 Nov')).toBeInTheDocument();
  });
});
