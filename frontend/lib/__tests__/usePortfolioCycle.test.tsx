import { render, act } from '@testing-library/react';
import { usePortfolioCycle } from '../usePortfolioCycle';
import { usePortfolioStore } from '../portfolioStore';
import { usePerformanceStore } from '../performanceStore';
import { useAlertStore } from '../alertStore';
import { scanPortfolio } from '../alertEngine';

jest.mock('../alertEngine', () => ({ scanPortfolio: jest.fn() }));

function Host() { usePortfolioCycle(); return null; }

let vis: 'visible' | 'hidden' = 'visible';
const sync = jest.fn();
const perf = jest.fn();
const toast = jest.fn();

function setVis(v: 'visible' | 'hidden') {
  vis = v;
  document.dispatchEvent(new Event('visibilitychange'));
}
async function flush() { await act(async () => { await Promise.resolve(); await Promise.resolve(); }); }
async function tick(ms: number) { await act(async () => { jest.advanceTimersByTime(ms); }); await flush(); }

beforeEach(() => {
  jest.useFakeTimers();
  vis = 'visible';
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => vis });
  sync.mockReset().mockResolvedValue(true);
  perf.mockReset();
  toast.mockReset();
  (scanPortfolio as jest.Mock).mockReset().mockReturnValue([{ id: 'x' }]);
  usePortfolioStore.setState({ syncFromBackend: sync } as never);
  usePerformanceStore.setState({ fetchPerformance: perf } as never);
  useAlertStore.setState({ addToast: toast } as never);
});
afterEach(() => { jest.useRealTimers(); });

describe('usePortfolioCycle', () => {
  it('runs once on mount, then every 30 s', async () => {
    render(<Host />);
    await flush();
    expect(sync).toHaveBeenCalledTimes(1);
    await tick(30_000);
    expect(sync).toHaveBeenCalledTimes(2);
    await tick(30_000);
    expect(sync).toHaveBeenCalledTimes(3);
  });

  it('the first (mount) cycle reads performance but raises no alert toast', async () => {
    render(<Host />);
    await flush();
    expect(perf).toHaveBeenCalledTimes(1);
    expect(toast).not.toHaveBeenCalled();
    await tick(30_000);
    expect(toast).toHaveBeenCalledTimes(1);
  });

  it('calls nothing across several ticks while hidden', async () => {
    render(<Host />);
    await flush();
    sync.mockClear(); perf.mockClear(); toast.mockClear();
    vis = 'hidden';
    await tick(30_000 * 4);
    expect(sync).not.toHaveBeenCalled();
    expect(perf).not.toHaveBeenCalled();
    expect(toast).not.toHaveBeenCalled();
  });

  it('return runs exactly one immediate cycle, then the next tick is 30 s later', async () => {
    render(<Host />);
    await flush();
    sync.mockClear();
    vis = 'hidden';
    await tick(30_000 * 3);
    await act(async () => { setVis('visible'); });
    await flush();
    expect(sync).toHaveBeenCalledTimes(1);
    await tick(29_000);
    expect(sync).toHaveBeenCalledTimes(1);
    await tick(1_000);
    expect(sync).toHaveBeenCalledTimes(2);
  });

  it('mounted while hidden defers the first cycle to the first visible event', async () => {
    vis = 'hidden';
    render(<Host />);
    await tick(30_000 * 2);
    expect(sync).not.toHaveBeenCalled();
    await act(async () => { setVis('visible'); });
    await flush();
    expect(sync).toHaveBeenCalledTimes(1);
  });

  it('does not start a second cycle while one is still awaiting', async () => {
    let release!: (v: boolean) => void;
    sync.mockImplementation(() => new Promise<boolean>((r) => { release = r; }));
    render(<Host />);
    await flush();
    await tick(30_000 * 3);
    expect(sync).toHaveBeenCalledTimes(1);
    release(true);
    await flush();
    await tick(30_000);
    expect(sync).toHaveBeenCalledTimes(2);
  });

  it('removes the listener and interval on unmount', async () => {
    const { unmount } = render(<Host />);
    await flush();
    sync.mockClear();
    unmount();
    await tick(30_000 * 2);
    await act(async () => { setVis('visible'); });
    await flush();
    expect(sync).not.toHaveBeenCalled();
  });

  it('a sync resolving false raises no toast and does not fetch performance', async () => {
    render(<Host />);
    await flush();
    perf.mockClear(); toast.mockClear();
    sync.mockResolvedValue(false);
    await tick(30_000);
    expect(sync).toHaveBeenCalledTimes(2);
    expect(scanPortfolio).not.toHaveBeenCalled();
    expect(toast).not.toHaveBeenCalled();
    expect(perf).not.toHaveBeenCalled();
  });

  it.each([true, undefined])('a sync resolving %s scans and fetches performance', async (v) => {
    sync.mockResolvedValue(v);
    render(<Host />);
    await flush();
    perf.mockClear();
    await tick(30_000);
    expect(toast).toHaveBeenCalledTimes(1);
    expect(perf).toHaveBeenCalledTimes(1);
  });
});
