import '@testing-library/jest-dom';
import { render, screen, within, fireEvent } from '@testing-library/react';
import PortfolioPage from '../page';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { usePerformanceStore, type ClosedPosition } from '@/lib/performanceStore';
import { formatSignedPct } from '@/lib/portfolioFormat';
import type { PortfolioPosition } from '@/types/domain';
import { portfolio20261117 } from '../../../../test-utils/portfolioFixture20261117';

// PORTFOLIO-NUMBERS (#657) Task 3: theta in dollars per day (column + footer),
// return on cost, readable contracts with the raw key kept as a title, signed
// money with a Unicode minus.

jest.mock('@/components/organisms/PnlChart', () => ({ PnlChart: () => null }));
jest.mock('@/components/organisms/PnlHeatmap', () => ({ PnlHeatmap: () => null }));

const HISTORY_ROW: ClosedPosition = {
  id: 'H-1', recId: 'REC-NFLX', symbol: 'NFLX', contract: 'NFLX|82|2026-10-16|C',
  direction: 'Bullish', entryPrice: 6.0, entryDate: '2026-09-01', exitPrice: 0.36,
  exitDate: '2026-10-10', qtyClosed: 1, realizedPnlDollar: -564, realizedPnlPct: -94,
  closedAt: '2026-10-10T15:00:00Z',
};

function renderWith(positions: PortfolioPosition[]) {
  usePortfolioStore.setState({ positions, syncFromBackend: jest.fn().mockResolvedValue(undefined) });
  usePerformanceStore.setState({
    history: [HISTORY_ROW],
    performance: {
      realizedToday: -2595, realizedWeek: 89, realizedMonth: 0, realizedYear: 0,
      realizedCurve: [], equityCurve: [], openPnlCurve: [],
      lastSnapshotDate: null, snapshotSkippedOn: null, snapshotSkippedContracts: [],
    },
    fetchHistory: jest.fn().mockResolvedValue(undefined),
    fetchPerformance: jest.fn().mockResolvedValue(undefined),
  });
  return render(<PortfolioPage />);
}

/** The row holding the element titled with the raw contract key. */
function rowOf(container: HTMLElement, contract: string): HTMLElement {
  const el = container.querySelector(`[title="${contract}"]`);
  if (!el) throw new Error(`no element titled ${contract}`);
  return el.closest('[role="row"]') as HTMLElement;
}

/** The Δ · Θ $/DAY cell: the 8th grid track of an open-positions row. */
function thetaCell(row: HTMLElement): HTMLElement {
  return row.children[7] as HTMLElement;
}

describe('Portfolio page numbers (PORTFOLIO-NUMBERS T3)', () => {
  it('shows a readable contract with the raw key as its title, never as visible text', () => {
    const { container } = renderWith(portfolio20261117());
    const titled = container.querySelector('[title="CMG|40|2027-06-17|C"]') as HTMLElement;
    expect(titled).not.toBeNull();
    expect(within(titled).getByText('40C · 17 Jun 27')).toBeInTheDocument();
    expect(screen.queryByText('CMG|40|2027-06-17|C')).not.toBeInTheDocument();
    // The edit button still names the raw key.
    expect(screen.getByRole('button', { name: 'Edit CMG|40|2027-06-17|C' })).toBeInTheDocument();
  });

  it('row P&L uses signed money and a signed percent with a Unicode minus', () => {
    const { container } = renderWith(portfolio20261117());
    const cmg = rowOf(container, 'CMG|40|2027-06-17|C');
    expect(within(cmg).getByText('+$13')).toBeInTheDocument();
    expect(within(cmg).getByText('+4.5%')).toBeInTheDocument();
    const nclh = rowOf(container, 'NCLH|20|2027-06-17|C');
    expect(within(nclh).getByText('−$50')).toBeInTheDocument();
    expect(within(nclh).getByText(formatSignedPct(-20.75, 1))).toBeInTheDocument();
  });

  it('Θ column is theta in dollars per day', () => {
    const { container } = renderWith(portfolio20261117());
    expect(screen.getByText('Δ · Θ $/DAY')).toBeInTheDocument();
    expect(screen.queryByText('Θ/DAY')).not.toBeInTheDocument();
    expect(thetaCell(rowOf(container, 'CMG|40|2027-06-17|C'))).toHaveTextContent(/^0\.45 · −\$1\.10$/);
    expect(thetaCell(rowOf(container, 'NCLH|20|2027-06-17|C'))).toHaveTextContent(/^0\.48 · −\$0\.71$/);
    expect(thetaCell(rowOf(container, 'BMY|67|2027-03-19|C'))).toHaveTextContent(/^— · —$/);
  });

  it('a positive-theta row shows a plus sign', () => {
    const { container } = renderWith([{
      ...portfolio20261117()[0], theta: 0.02, contracts: 1,
    }]);
    expect(thetaCell(rowOf(container, 'CMG|40|2027-06-17|C'))).toHaveTextContent(/^0\.45 · \+\$2\.00$/);
  });

  it('footer: deployed, open P&L, return on cost and theta per day', () => {
    renderWith(portfolio20261117());
    const footer = screen.getByText('Deployed').parentElement!.parentElement!;
    expect(within(footer).getByText('$494')).toBeInTheDocument();
    expect(within(footer).getByText('−$37')).toBeInTheDocument();
    expect(within(footer).getByText('Return on cost')).toBeInTheDocument();
    expect(within(footer).getByText('−7.0%')).toBeInTheDocument();
    expect(within(footer).getByText('Θ per day')).toBeInTheDocument();
    expect(within(footer).getByText('−$1.81')).toBeInTheDocument();
    expect(within(footer).getByText('Excludes 1 position without a quote')).toBeInTheDocument();
  });

  it('perf strip labels say realized and use signed money', () => {
    renderWith(portfolio20261117());
    const stat = (label: string) => screen.getByText(label).parentElement as HTMLElement;
    expect(within(stat('Realized today')).getByText('−$2,595')).toBeInTheDocument();
    expect(within(stat('Realized this week')).getByText('+$89')).toBeInTheDocument();
    expect(within(stat('Realized this month')).getByText('$0')).toBeInTheDocument();
    expect(within(stat('Realized this year')).getByText('$0')).toBeInTheDocument();
  });

  it('history rows: readable contract titled with the raw key, signed money', () => {
    const { container } = renderWith(portfolio20261117());
    fireEvent.click(screen.getByRole('button', { name: 'History (1)' }));
    const titled = container.querySelector('[title="NFLX|82|2026-10-16|C"]') as HTMLElement;
    expect(titled).not.toBeNull();
    expect(within(titled).getByText('82C · 16 Oct 26')).toBeInTheDocument();
    expect(screen.queryByText('NFLX|82|2026-10-16|C')).not.toBeInTheDocument();
    expect(screen.getByText('−$564')).toBeInTheDocument();
  });
});
