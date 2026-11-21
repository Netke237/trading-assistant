import '@testing-library/jest-dom';
import { render, screen, within, fireEvent } from '@testing-library/react';
import PortfolioPage from '../page';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { usePortfolioUiStore } from '@/lib/portfolioUiStore';
import { usePerformanceStore } from '@/lib/performanceStore';
import type { ExitPlan, PortfolioPosition } from '@/types/domain';
import { ivColumnLabel, ivBasesOf } from '@/lib/ivBasis';
import { portfolio20261117 } from '../../../../test-utils/portfolioFixture20261117';

// PORTFOLIO-RISK-VIEW T3 (#681): derived status + reason, contract under the
// symbol, underlying-vs-stop/T1 range, RISK @ STOP, merged Δ · Θ, row select.

jest.mock('@/components/organisms/PnlChart', () => ({ PnlChart: () => null }));
jest.mock('@/components/organisms/PnlHeatmap', () => ({ PnlHeatmap: () => null }));
jest.mock('../EditDrawer', () => ({ EditDrawer: () => <div data-testid="editor-open" /> }));

const plan = (c: number) => ({ stop: { contractPrice: c } }) as unknown as ExitPlan;

const CMG_KEY = 'CMG|40|2027-06-17|C';
const NCLH_KEY = 'NCLH|20|2027-06-17|C';
const BMY_KEY = 'BMY|67|2027-03-19|C';

function fixtures(): PortfolioPosition[] {
  const [cmg, nclh, bmy] = portfolio20261117();
  return [
    { ...cmg, stop: 33.35, structuralStop: 35.66, targets: [{ stockPrice: 40.71 } as never], exitPlan: plan(0.84), source: 'manual' },
    { ...nclh, stop: 16.0, structuralStop: null, targets: [{ stockPrice: 21 } as never], exitPlan: plan(0.33) },
    { ...bmy, stop: 64.13, structuralStop: null, targets: [{ stockPrice: 70 } as never] },
  ];
}

function renderWith(positions: PortfolioPosition[]) {
  usePortfolioStore.setState({ positions, syncFromBackend: jest.fn().mockResolvedValue(undefined) });
  usePerformanceStore.setState({
    fetchHistory: jest.fn().mockResolvedValue(undefined),
    fetchPerformance: jest.fn().mockResolvedValue(undefined),
  });
  usePortfolioUiStore.setState({ selectedSymbol: null });
  return render(<PortfolioPage />);
}

function rowOf(container: HTMLElement, contract: string): HTMLElement {
  const el = container.querySelector(`[title="${contract}"]`);
  if (!el) throw new Error(`no element titled ${contract}`);
  return el.closest('[role="row"]') as HTMLElement;
}

// Grid tracks: 0 chart, 1 symbol+contract, 2 DIR, 3 DTE, 4 entry->now, 5 P&L,
// 6 IV, 7 Δ · Θ, 8 range, 9 risk, 10 status, 11 edit.
const cell = (row: HTMLElement, i: number) => row.children[i] as HTMLElement;

describe('Portfolio risk view table (PORTFOLIO-RISK-VIEW T3)', () => {
  it('status cell: derived badge and reason line, row tinted with the derived status', () => {
    const { container } = renderWith(fixtures());
    const cmg = rowOf(container, CMG_KEY);
    expect(cmg).toHaveAttribute('data-status', 'CAUTION');
    expect(within(cell(cmg, 10)).getByText('CAUTION')).toBeInTheDocument();
    expect(within(cell(cmg, 10)).getByText('1.1% above struct. stop')).toBeInTheDocument();
    const nclh = rowOf(container, NCLH_KEY);
    expect(nclh).toHaveAttribute('data-status', 'PASS');
    expect(within(cell(nclh, 10)).getByText('Between stop and T1')).toBeInTheDocument();
    const bmy = rowOf(container, BMY_KEY);
    expect(bmy).toHaveAttribute('data-status', 'REJECT');
    expect(within(cell(bmy, 10)).getByText('REJECT')).toBeInTheDocument();
    expect(within(cell(bmy, 10)).getByText('Stop breached')).toBeInTheDocument();
  });

  it('contract sits under the symbol: readable label, raw key as title, source badge kept', () => {
    const { container } = renderWith(fixtures());
    const cmg = rowOf(container, CMG_KEY);
    const symbolCell = cell(cmg, 1);
    expect(within(symbolCell).getByText('CMG')).toBeInTheDocument();
    const titled = symbolCell.querySelector(`[title="${CMG_KEY}"]`) as HTMLElement;
    expect(titled).not.toBeNull();
    expect(within(titled).getByText('40C · 17 Jun 27')).toBeInTheDocument();
    expect(within(symbolCell).getByText('MANUAL')).toBeInTheDocument();
    // No CONTRACT column any more.
    expect(screen.queryByText('CONTRACT')).not.toBeInTheDocument();
  });

  it('range column: text line, accessible name, header', () => {
    const { container } = renderWith(fixtures());
    expect(screen.getByText('UNDERLYING vs STOP / T1')).toBeInTheDocument();
    const cmgRange = cell(rowOf(container, CMG_KEY), 8);
    const text = '$36.06 · stop −7.5% · struct −1.1% · T1 +12.9%';
    expect(within(cmgRange).getByText(text)).toBeInTheDocument();
    expect(within(cmgRange).getByRole('img', { name: text })).toBeInTheDocument();
    expect(within(cell(rowOf(container, BMY_KEY), 8)).getByText('$60.95 · stop +5.2% · T1 +14.8%')).toBeInTheDocument();
  });

  it('range column shows a dash with a reason when there is no stop', () => {
    const { container } = renderWith([{ ...fixtures()[1], stop: null }]);
    const c = cell(rowOf(container, NCLH_KEY), 8);
    expect(within(c).getByText('—')).toBeInTheDocument();
  });

  it('RISK @ STOP column: $206, $208, and a dash with a reason for the row without an exit plan', () => {
    const { container } = renderWith(fixtures());
    expect(screen.getByText('RISK @ STOP')).toBeInTheDocument();
    expect(cell(rowOf(container, CMG_KEY), 9)).toHaveTextContent(/^\$206$/);
    expect(cell(rowOf(container, NCLH_KEY), 9)).toHaveTextContent(/^\$208$/);
    const bmy = cell(rowOf(container, BMY_KEY), 9);
    expect(bmy).toHaveTextContent(/^—$/);
    expect(bmy).toHaveAttribute('title', 'Needs a computed exit plan (options only)');
  });

  it('single Δ · Θ $/DAY column: "0.45 · −$1.10", dashes for absent parts', () => {
    const { container } = renderWith(fixtures());
    expect(screen.getByText('Δ · Θ $/DAY')).toBeInTheDocument();
    expect(screen.queryByText('Θ $/DAY')).not.toBeInTheDocument();
    expect(cell(rowOf(container, CMG_KEY), 7)).toHaveTextContent(/^0\.45 · −\$1\.10$/);
    expect(cell(rowOf(container, NCLH_KEY), 7)).toHaveTextContent(/^0\.48 · −\$0\.71$/);
    expect(cell(rowOf(container, BMY_KEY), 7)).toHaveTextContent(/^— · —$/);
  });

  it('keeps every previously present element', () => {
    const { container } = renderWith(fixtures());
    const cmg = rowOf(container, CMG_KEY);
    expect(within(cmg).getByText('CMG')).toBeInTheDocument();
    expect(within(cmg).getByText('Bull')).toBeInTheDocument();
    expect(within(cmg).getByText('$2.90')).toBeInTheDocument();
    expect(within(cmg).getByText('$3.03')).toBeInTheDocument();
    expect(within(cmg).getByText('+$13')).toBeInTheDocument();
    expect(within(cmg).getByText('+4.5%')).toBeInTheDocument();
    expect(within(cmg).getByTitle('Open in Chart')).toBeInTheDocument();
    expect(within(cmg).getByRole('button', { name: `Edit ${CMG_KEY}` })).toBeInTheDocument();
    for (const h of ['SYMBOL', 'DIR', 'DTE', 'ENTRY → NOW', 'P&L', 'STATUS']) {
      expect(screen.getByText(h)).toBeInTheDocument();
    }
    expect(screen.getByText(ivColumnLabel(ivBasesOf(fixtures())))).toBeInTheDocument();
  });

  it('keeps the empty state', () => {
    renderWith([]);
    expect(screen.getByText('No open positions.')).toBeInTheDocument();
  });

  it('clicking a row selects its symbol; Enter on the row selects too', () => {
    const { container } = renderWith(fixtures());
    fireEvent.click(within(rowOf(container, NCLH_KEY)).getByText('NCLH'));
    expect(usePortfolioUiStore.getState().selectedSymbol).toBe('NCLH');
    const bmyRow = rowOf(container, BMY_KEY);
    const target = bmyRow.closest('[tabindex="0"]') as HTMLElement;
    expect(target).not.toBeNull();
    fireEvent.keyDown(target, { key: 'Enter' });
    expect(usePortfolioUiStore.getState().selectedSymbol).toBe('BMY');
  });

  it('the pencil opens the editor and toggles without a stray row select; the chart button does not select', () => {
    const { container } = renderWith(fixtures());
    const edit = screen.getByRole('button', { name: `Edit ${CMG_KEY}` });
    fireEvent.click(edit);
    expect(screen.getByTestId('editor-open')).toBeInTheDocument();
    expect(usePortfolioUiStore.getState().selectedSymbol).toBe('CMG');
    fireEvent.click(edit);
    expect(screen.queryByTestId('editor-open')).not.toBeInTheDocument();
    expect(usePortfolioUiStore.getState().selectedSymbol).toBeNull();
    window.open = jest.fn();
    fireEvent.click(within(rowOf(container, NCLH_KEY)).getByTitle('Open in Chart'));
    expect(usePortfolioUiStore.getState().selectedSymbol).toBeNull();
  });
});
