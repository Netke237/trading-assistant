import '@testing-library/jest-dom';
import { render, screen, fireEvent } from '@testing-library/react';
import PortfolioPage from '../page';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { usePerformanceStore, type ClosedPosition } from '@/lib/performanceStore';
import { useSettingsStore } from '@/lib/settingsStore';

jest.mock('@/components/organisms/PnlChart', () => ({ PnlChart: () => <div data-testid="chart" /> }));
jest.mock('@/components/organisms/PnlHeatmap', () => ({ PnlHeatmap: () => <div data-testid="heatmap" /> }));
jest.mock('@/components/organisms/BrokerAttemptPanel', () => ({ BrokerAttemptPanel: () => null }));
jest.mock('@/lib/alertEngine', () => ({ scanPortfolio: jest.fn().mockReturnValue([]) }));
// Every *.module.css maps to one style mock; give it the tone class the flag must carry.
jest.mock('@/components/primitives/Text.module.css', () => ({ toneReject: 'toneReject', toneSecondary: 'toneSecondary' }));

const FLAG = 'Reached target, closed at a loss';
// Midday UTC, so the local date is the same in every zone from UTC-11 to UTC+11.
const HIT = '2026-10-20T12:00:00+00:00';

function row(i: number, symbol: string, dollar: number, pct: number, over: Partial<ClosedPosition> = {}): ClosedPosition {
  return {
    id: `id-${i}`, recId: `rec-${i}`, symbol, contract: `${symbol}|82|2027-01-15|C`, direction: 'Bullish',
    entryPrice: 1, entryDate: '2026-10-01', exitPrice: 1, exitDate: '2026-11-17',
    qtyClosed: 1, realizedPnlDollar: dollar, realizedPnlPct: pct, closedAt: '2026-11-17T10:00:00Z', ...over,
  };
}

function setup(history: ClosedPosition[]) {
  useSettingsStore.setState({ premiumStopPct: 0.6 } as never);
  usePortfolioStore.setState({
    positions: [], syncFromBackend: jest.fn().mockResolvedValue(undefined),
    lastSyncAt: 1, lastSyncFailedAt: null, firstSyncAt: 1,
  } as never);
  usePerformanceStore.setState({
    history,
    fetchHistory: jest.fn().mockResolvedValue(undefined),
    fetchPerformance: jest.fn().mockResolvedValue(undefined),
  } as never);
  render(<PortfolioPage />);
  fireEvent.click(screen.getByRole('tab', { name: /^History/ }));
}

describe('History EXIT CHECK: target-then-loss flag', () => {
  it('flags only rows that reached their target and closed at a loss', () => {
    setup([
      row(0, 'FTNT', -655, -70, { targetFirstHitAt: HIT }),           // target, then loss
      row(1, 'COP', -100, -45, { targetFirstHitAt: HIT }),            // target, then loss (within stop)
      row(2, 'AAPL', 360, 36, { targetFirstHitAt: HIT }),             // target, then win
      row(3, 'MSFT', 0, 0, { targetFirstHitAt: HIT }),                // target, flat
      row(4, 'NFLX', -1000, -99, { targetFirstHitAt: null }),         // loss, target never reached
      row(5, 'BAC', -900, -85),                                       // loss, older row with no field
    ]);
    const cells = screen.getAllByTestId('history-exitcheck');
    const flags = cells.map((c) => c.querySelector('[data-testid="history-target-flag"]'));
    expect(flags.map((f) => f !== null)).toEqual([true, true, false, false, false, false]);
    for (const f of flags.slice(0, 2)) {
      expect(f).toHaveTextContent(FLAG);
      expect(f).toHaveAttribute('title', 'Target first reached 2026-10-20');
    }
    expect(screen.getAllByText(FLAG)).toHaveLength(2);
    // The first line (the stop check) is unchanged.
    expect(cells[0].textContent).toBe(`Lost 70%: past 60% premium stop${FLAG}`);
    expect(cells[1].textContent).toBe(`Within premium stop${FLAG}`);
    expect(cells[2].textContent).toBe('Win');
    expect(cells[3].textContent).toBe('Flat');
    expect(cells[4].textContent).toBe('Lost 99%: past 60% premium stop');
  });

  it('renders the flag in the reject tone', () => {
    setup([row(0, 'FTNT', -655, -70, { targetFirstHitAt: HIT })]);
    expect(screen.getByText(FLAG)).toHaveClass('toneReject');
  });
});
