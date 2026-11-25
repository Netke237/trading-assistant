import '@testing-library/jest-dom';
import { fireEvent, render, screen } from '@testing-library/react';
import { createChart } from 'lightweight-charts';
import { PnlChart } from '..';
import { useThemeStore } from '@/lib/theme';

jest.mock('lightweight-charts', () => ({
  ...jest.requireActual('../../../../__mocks__/lightweight-charts.js'),
  LineStyle: { Dashed: 2 },
}));

const EQUITY = [{ date: '2026-10-22', value: 10000 }, { date: '2026-10-23', value: 11530 }];
const REALIZED = [{ date: '2026-10-22', value: 5 }, { date: '2026-10-23', value: 7 }];
const SIMPLE = 0;
const WITH_STEPS = 1;

beforeEach(() => {
  jest.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(600);
  jest.spyOn(window, 'getComputedStyle').mockReturnValue({ getPropertyValue: () => '' } as unknown as CSSStyleDeclaration);
  useThemeStore.setState({ theme: 'dark' });
  const original = (createChart as jest.Mock).getMockImplementation()!;
  (createChart as jest.Mock).mockReset().mockImplementation((...args: unknown[]) => {
    const chart = original(...args);
    const ts = { fitContent: jest.fn(), timeToCoordinate: jest.fn(), subscribeVisibleTimeRangeChange: jest.fn(), unsubscribeVisibleTimeRangeChange: jest.fn() };
    chart.timeScale.mockImplementation(() => ts);
    chart.priceScale = jest.fn(() => ({ width: () => 50 }));
    return chart;
  });
});
afterEach(() => jest.restoreAllMocks());

function lineSeries() {
  const chart = (createChart as jest.Mock).mock.results[0].value;
  return chart.addSeries.mock.results[0].value;
}
const lastLineType = () => {
  const calls = lineSeries().applyOptions.mock.calls.filter((c: unknown[]) => c[0] && 'lineType' in (c[0] as object));
  return calls.length ? (calls[calls.length - 1][0] as { lineType: number }).lineType : undefined;
};

describe('PnlChart stepped realized curve', () => {
  it('applies WithSteps for the realized curve', () => {
    render(<PnlChart equityCurve={EQUITY} realizedCurve={REALIZED} defaultKind="realized" />);
    expect(lastLineType()).toBe(WITH_STEPS);
  });

  it('keeps the equity curve a plain line', () => {
    render(<PnlChart equityCurve={EQUITY} realizedCurve={REALIZED} defaultKind="equity" />);
    expect(lastLineType()).not.toBe(WITH_STEPS);
  });

  it('does not step the open curve', () => {
    render(<PnlChart equityCurve={EQUITY} realizedCurve={REALIZED} openPnlCurve={EQUITY} defaultKind="open" />);
    expect(lastLineType()).not.toBe(WITH_STEPS);
  });

  it('restores a plain line when switching back and forth', () => {
    render(<PnlChart equityCurve={EQUITY} realizedCurve={REALIZED} defaultKind="equity" />);
    fireEvent.click(screen.getByRole('button', { name: 'Realized P&L' }));
    expect(lastLineType()).toBe(WITH_STEPS);
    fireEvent.click(screen.getByRole('button', { name: 'Total value' }));
    expect(lastLineType()).toBe(SIMPLE);
    fireEvent.click(screen.getByRole('button', { name: 'Realized P&L' }));
    expect(lastLineType()).toBe(WITH_STEPS);
  });
});
