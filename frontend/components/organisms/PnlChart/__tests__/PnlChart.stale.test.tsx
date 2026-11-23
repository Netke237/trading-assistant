import '@testing-library/jest-dom';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { createChart } from 'lightweight-charts';
import { PnlChart } from '..';
import { useThemeStore } from '@/lib/theme';
import { staleCurveNotice, type StaleCurveNotice } from '@/lib/staleCurve';

// The shared fake plus LineStyle, with a time scale / price scale that report fixed geometry.
jest.mock('lightweight-charts', () => ({
  ...jest.requireActual('../../../../__mocks__/lightweight-charts.js'),
  LineStyle: { Dashed: 2 },
}));

const NOW = new Date('2026-11-21T15:00:00Z'); // Saturday in ET: reference day is Fri 2026-11-20
const EQUITY = [{ date: '2026-10-22', value: 10000 }, { date: '2026-10-23', value: 11530 }];
const OPEN = [{ date: '2026-10-22', value: 900 }, { date: '2026-10-23', value: 1530 }];
const REALIZED = [{ date: '2026-10-22', value: 5 }, { date: '2026-10-23', value: 7 }];

function notice(kind: 'open' | 'equity', over: Partial<Parameters<typeof staleCurveNotice>[0]> = {}): StaleCurveNotice | null {
  return staleCurveNotice({
    kind,
    lastSnapshotDate: '2026-10-23',
    curve: kind === 'open' ? OPEN : EQUITY,
    positionsCount: 3,
    openPnlToday: -37,
    unquotedSymbols: ['BMY'],
    skippedContracts: ['BMY|67|2027-03-19|C'],
    now: NOW,
    ready: true,
    ...over,
  });
}

const timeToCoordinate = jest.fn((): number | null => 100);
const priceScaleWidth = jest.fn(() => 50);

beforeEach(() => {
  jest.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(600);
  timeToCoordinate.mockClear().mockReturnValue(100);
  jest.spyOn(window, 'getComputedStyle').mockReturnValue({ getPropertyValue: () => '' } as unknown as CSSStyleDeclaration);
  useThemeStore.setState({ theme: 'dark' });
  const original = (createChart as jest.Mock).getMockImplementation()!;
  (createChart as jest.Mock).mockReset().mockImplementation((...args: unknown[]) => {
    const chart = original(...args);
    const ts = { fitContent: jest.fn(), timeToCoordinate, subscribeVisibleTimeRangeChange: jest.fn(), unsubscribeVisibleTimeRangeChange: jest.fn() };
    chart.timeScale.mockImplementation(() => ts);
    chart.priceScale = jest.fn(() => ({ width: priceScaleWidth }));
    chart.__ts = ts;
    return chart;
  });
});
afterEach(() => jest.restoreAllMocks());

function setup(staleNotices: { open: StaleCurveNotice | null; equity: StaleCurveNotice | null }, defaultKind: 'open' | 'equity' | 'realized' = 'open') {
  return render(
    <PnlChart equityCurve={EQUITY} realizedCurve={REALIZED} openPnlCurve={OPEN} defaultKind={defaultKind} staleNotices={staleNotices} />,
  );
}
const charts = () => (createChart as jest.Mock).mock.results.map((r) => r.value);

const OPEN_TEXT = 'Last point: 23 Oct, +$1,530. Open P&L today is −$37. No daily snapshot is written while a position has no quote (BMY now), so the line has stopped.';
const EQUITY_TEXT = 'Last point: 23 Oct, +$11,530. No daily snapshot is written while a position has no quote (BMY now), so the line has stopped.';

test('open and equity show their exact sentences; switching the curve toggles the text; realized has none', () => {
  setup({ open: notice('open'), equity: notice('equity') });
  expect(screen.getByRole('note')).toHaveTextContent(OPEN_TEXT);
  fireEvent.click(screen.getByRole('button', { name: 'Total value' }));
  expect(screen.getByRole('note')).toHaveTextContent(EQUITY_TEXT);
  fireEvent.click(screen.getByRole('button', { name: /Realized/ }));
  expect(screen.queryByRole('note')).toBeNull();
  expect(screen.queryByTestId('stale-gap')).toBeNull();
});

test('Days/Weeks/Months do not change the notice', () => {
  setup({ open: notice('open'), equity: notice('equity') });
  for (const g of ['Weeks', 'Months', 'Days']) {
    fireEvent.click(screen.getByRole('button', { name: g }));
    expect(screen.getByRole('note')).toHaveTextContent(OPEN_TEXT);
  }
});

test('not ready, or last point on/after the reference day: no notice, no gap, no dashed series', () => {
  expect(notice('open', { ready: false })).toBeNull();
  setup({ open: notice('open', { ready: false }), equity: null });
  expect(screen.queryByRole('note')).toBeNull();
  expect(screen.queryByTestId('stale-gap')).toBeNull();
  expect(charts()[0].addSeries).toHaveBeenCalledTimes(1);
});

test('reference-day boundary: equal is hidden, one day older is shown', () => {
  expect(notice('open', { lastSnapshotDate: '2026-11-20', curve: [{ date: '2026-11-20', value: 1 }] })).toBeNull();
  expect(notice('open', { lastSnapshotDate: '2026-11-19', curve: [{ date: '2026-11-19', value: 1 }] })).not.toBeNull();
});

test('gap shading is aria-hidden, non-interactive, and hidden when there is no coordinate', () => {
  const { unmount } = setup({ open: notice('open'), equity: notice('equity') });
  const gap = screen.getByTestId('stale-gap');
  expect(gap).toHaveAttribute('aria-hidden', 'true');
  expect(gap.style.left).toBe('100px');
  expect(gap.style.width).toBe('450px'); // 600 - 50 price scale - 100
  unmount();
  timeToCoordinate.mockReturnValue(null);
  setup({ open: notice('open'), equity: notice('equity') });
  expect(screen.queryByTestId('stale-gap')).toBeNull();
});

test('main series gets a trailing whitespace item at the reference day', () => {
  setup({ open: notice('open'), equity: notice('equity') });
  const main = charts()[0].addSeries.mock.results[0].value;
  const last = main.setData.mock.calls.at(-1)[0];
  expect(last.at(-1)).toEqual({ time: '2026-11-20' });
  expect(last.at(-2)).toEqual({ time: '2026-10-23', value: 1530 });
});

test('dashed series only for open, with [lastPoint, {referenceDay, liveValue}]', () => {
  setup({ open: notice('open'), equity: notice('equity') });
  const chart = charts()[0];
  expect(chart.addSeries).toHaveBeenCalledTimes(2);
  const dash = chart.addSeries.mock.results[1].value;
  expect(dash.__options).toEqual(expect.objectContaining({ lineStyle: 2, lastValueVisible: false, priceLineVisible: false }));
  expect(dash.setData).toHaveBeenCalledWith([
    { time: '2026-10-23', value: 1530 },
    { time: '2026-11-20', value: -37 },
  ]);
  fireEvent.click(screen.getByRole('button', { name: 'Total value' }));
  expect(chart.removeSeries).toHaveBeenCalledWith(dash); // gone for equity
  expect(chart.addSeries).toHaveBeenCalledTimes(2);      // none added for equity
});

test('theme rebuild recreates the dashed series on the new chart without removing from the old one', () => {
  const { unmount } = setup({ open: notice('open'), equity: notice('equity') });
  const old = charts()[0];
  act(() => useThemeStore.setState({ theme: 'light' }));
  const next = charts().at(-1);
  expect(next).not.toBe(old);
  expect(old.remove).toHaveBeenCalledTimes(1);
  expect(old.removeSeries).not.toHaveBeenCalled();
  expect(next.addSeries).toHaveBeenCalledTimes(2);
  unmount();
  expect(next.remove).toHaveBeenCalledTimes(1);
  expect(next.removeSeries).not.toHaveBeenCalled();
});
