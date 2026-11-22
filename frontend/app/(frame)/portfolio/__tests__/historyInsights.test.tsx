import '@testing-library/jest-dom';
import { render, screen, fireEvent, within } from '@testing-library/react';
import PortfolioPage from '../page';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { usePerformanceStore, type ClosedPosition } from '@/lib/performanceStore';
import { useSettingsStore } from '@/lib/settingsStore';

const heatmapSpy = jest.fn();
jest.mock('@/components/organisms/PnlChart', () => ({ PnlChart: () => <div data-testid="chart" /> }));
jest.mock('@/components/organisms/PnlHeatmap', () => ({
  PnlHeatmap: (props: { history: unknown[] }) => { heatmapSpy(props.history); return <div data-testid="heatmap" />; },
}));
jest.mock('@/components/organisms/BrokerAttemptPanel', () => ({ BrokerAttemptPanel: () => null }));
jest.mock('@/lib/alertEngine', () => ({ scanPortfolio: jest.fn().mockReturnValue([]) }));

const EXIT = '2026-06-30';
function entryFor(holdDays: number): string {
  const d = new Date(Date.UTC(2026, 5, 30) - holdDays * 86_400_000);
  return d.toISOString().slice(0, 10);
}

function row(i: number, symbol: string, dollar: number, pct: number, hold: number | null, over: Partial<ClosedPosition> = {}): ClosedPosition {
  return {
    id: `id-${i}`, recId: `rec-${i}`, symbol, contract: `${symbol}|82|2027-01-15|C`, direction: 'Bullish',
    entryPrice: 1, entryDate: hold === null ? undefined : entryFor(hold), exitPrice: 1, exitDate: EXIT,
    qtyClosed: 1, realizedPnlDollar: dollar, realizedPnlPct: pct, closedAt: `${EXIT}T10:00:00Z`, ...over,
  };
}

// API order. Wins +400 +360; losses -1000 -900 -655 -500 -300; one flat.
const FIXTURE: ClosedPosition[] = [
  row(0, 'AAA', 400, 40, 6),
  row(1, 'BBB', -1000, -99, 111),
  row(2, 'CCC', -900, -85, 100),
  row(3, 'DDD', 360, 36, 90),
  row(4, 'EEE', -655, -70, 80),
  row(5, 'FFF', -500, -65, 70),
  row(6, 'GGG', -300, -40, 60),
  row(7, 'HHH', 0, 0, 91),
];

function setup(history: ClosedPosition[] = FIXTURE) {
  heatmapSpy.mockClear();
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

const val = (id: string) => screen.getByTestId(id).textContent;
const order = () => screen.queryAllByTestId('history-symbol').map((e) => e.textContent);
const click = (name: string) => fireEvent.click(screen.getByRole('button', { name }));

describe('History trade statistics strip', () => {
  it('shows the pinned numbers', () => {
    setup();
    expect(val('stat-winrate')).toBe('29%');
    expect(val('stat-avgwin')).toBe('+$380');
    expect(val('stat-avgloss')).toBe('−$671');
    expect(val('stat-losstowin')).toContain('1.8×');
    expect(val('stat-profitfactor')).toBe('0.23');
    expect(val('stat-expectancy')).toBe('−$324');
    expect(val('stat-hold')).toBe('76 days (6–111)');
    expect(screen.getByTestId('stat-paststop-cell')).toHaveTextContent('Past premium stop: 4 of 5 losses');
    expect(screen.getByTestId('stat-paststop-cell').getAttribute('title')).toBe(
      "Compared with today's global premium stop (60%), not the stop that applied at entry — the stop at entry is not stored yet.");
  });

  it('recomputes under the Wins and Losses filters', () => {
    setup();
    click('Wins');
    expect(screen.getByRole('button', { name: 'Wins' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'All' })).toHaveAttribute('aria-pressed', 'false');
    expect(val('stat-winrate')).toBe('100%');
    expect(val('stat-avgwin')).toBe('+$380');
    expect(val('stat-avgloss')).toBe('—');
    expect(val('stat-profitfactor')).toBe('—');
    expect(screen.getByTestId('stat-paststop-cell')).toHaveTextContent('Past premium stop: —');
    expect(order()).toEqual(['AAA', 'DDD']);
    expect(screen.getByText('Showing 2 of 8')).toBeInTheDocument();
    click('Losses');
    expect(val('stat-winrate')).toBe('0%');
    expect(val('stat-avgloss')).toBe('−$671');
    expect(val('stat-profitfactor')).toBe('0.00');
    expect(order()).toEqual(['BBB', 'CCC', 'EEE', 'FFF', 'GGG']);
    click('All');
    expect(order()).toHaveLength(8);
  });

  it('recomputes under symbol search (case-insensitive) and says so when nothing matches', () => {
    setup();
    const input = screen.getByRole('textbox', { name: 'Search symbol' });
    fireEvent.change(input, { target: { value: ' bbb ' } });
    expect(order()).toEqual(['BBB']);
    expect(val('stat-avgloss')).toBe('−$1,000');
    expect(val('stat-hold')).toBe('111 days (111–111)');
    fireEvent.change(input, { target: { value: 'ZZZ' } });
    expect(screen.getByText('No trades match this filter.')).toBeInTheDocument();
    expect(val('stat-winrate')).toBe('—');
    expect(screen.getByText('Showing 0 of 8')).toBeInTheDocument();
  });

  it('shows — hold for a missing entry date and notes the partial hold basis', () => {
    setup([row(0, 'AAA', 400, 40, null), row(1, 'BBB', -100, -50, 10)]);
    expect(screen.getAllByTestId('history-hold').map((e) => e.textContent)).toEqual(['—', '10d']);
    expect(val('stat-hold')).toContain('10 days (10–10)');
    expect(val('stat-hold')).toContain('1 of 2 trades');
  });

  it('shows return, exit check and ignores nothing else; zero-cost entry returns —', () => {
    setup([row(0, 'AAA', -100, -99, 5), row(1, 'BBB', -100, 0, 5, { entryPrice: 0 })]);
    expect(screen.getAllByTestId('history-return').map((e) => e.textContent)).toEqual(['−99.0%', '—']);
    expect(screen.getAllByTestId('history-exitcheck')[0].textContent).toBe('Lost 99%: past 60% premium stop');
    expect(screen.getAllByTestId('history-exitcheck')[1].textContent).toBe('—');
  });

  it('notes invalid P&L rows ignored', () => {
    setup([row(0, 'AAA', Number.NaN, 0, 5), row(1, 'BBB', 100, 10, 5)]);
    expect(screen.getByText('1 rows with invalid P&L ignored')).toBeInTheDocument();
  });
});

describe('History sort', () => {
  const cases: Array<[string, string[], string[]]> = [
    ['SYMBOL', ['AAA', 'BBB', 'CCC', 'DDD', 'EEE', 'FFF', 'GGG', 'HHH'], ['HHH', 'GGG', 'FFF', 'EEE', 'DDD', 'CCC', 'BBB', 'AAA']],
    ['HOLD', ['AAA', 'GGG', 'FFF', 'EEE', 'DDD', 'HHH', 'CCC', 'BBB'], ['BBB', 'CCC', 'HHH', 'DDD', 'EEE', 'FFF', 'GGG', 'AAA']],
    ['P&L', ['BBB', 'CCC', 'EEE', 'FFF', 'GGG', 'HHH', 'DDD', 'AAA'], ['AAA', 'DDD', 'HHH', 'GGG', 'FFF', 'EEE', 'CCC', 'BBB']],
    ['RETURN', ['BBB', 'CCC', 'EEE', 'FFF', 'GGG', 'HHH', 'DDD', 'AAA'], ['AAA', 'DDD', 'HHH', 'GGG', 'FFF', 'EEE', 'CCC', 'BBB']],
  ];
  const API = ['AAA', 'BBB', 'CCC', 'DDD', 'EEE', 'FFF', 'GGG', 'HHH'];

  it.each(cases)('%s cycles asc, desc, off', (name, asc, desc) => {
    setup();
    expect(order()).toEqual(API);
    click(name);
    expect(order()).toEqual(asc);
    expect(screen.getByRole('button', { name }).closest('[aria-sort]')).toHaveAttribute('aria-sort', 'ascending');
    click(name);
    expect(order()).toEqual(desc);
    expect(screen.getByRole('button', { name }).closest('[aria-sort]')).toHaveAttribute('aria-sort', 'descending');
    click(name);
    expect(order()).toEqual(API);
    expect(screen.getByRole('button', { name }).closest('[aria-sort]')).toHaveAttribute('aria-sort', 'none');
  });

  it('ENTRY and EXIT sort buttons; missing values last both ways', () => {
    setup([row(0, 'AAA', 1, 1, null), row(1, 'BBB', 1, 1, 30), row(2, 'CCC', 1, 1, 10)]);
    click('ENTRY');
    expect(order()).toEqual(['BBB', 'CCC', 'AAA']);
    click('ENTRY');
    expect(order()).toEqual(['CCC', 'BBB', 'AAA']);
    click('EXIT'); // all exits equal: stable API order
    expect(order()).toEqual(['AAA', 'BBB', 'CCC']);
    // ENTRY and EXIT share the one DATES header cell, which reports the active sort.
    expect(screen.getByRole('button', { name: 'EXIT' }).closest('[aria-sort]')).toHaveAttribute('aria-sort', 'ascending');
    click('EXIT');
    click('EXIT');
    expect(screen.getByRole('button', { name: 'EXIT' }).closest('[aria-sort]')).toHaveAttribute('aria-sort', 'none');
  });

  it('sorting does not change the statistics', () => {
    setup();
    click('P&L');
    expect(val('stat-winrate')).toBe('29%');
  });
});

describe('History structure', () => {
  it('heatmap still gets the unfiltered history', () => {
    setup();
    click('Wins');
    expect(heatmapSpy).toHaveBeenLastCalledWith(FIXTURE);
  });

  it('existing columns keep their order, new columns sit between P&L and the remove button', () => {
    setup();
    const header = screen.getByTestId('history-header');
    const text = header.textContent ?? '';
    const idx = ['SYMBOL', 'CONTRACT', 'QTY · ENTRY → EXIT', 'ENTRY', 'EXIT', 'P&L', 'RETURN', 'HOLD', 'EXIT CHECK'].map((s) => text.indexOf(s));
    expect([...idx].sort((a, b) => a - b)).toEqual(idx);
    expect(idx.every((i) => i >= 0)).toBe(true);
    const r = within(screen.getAllByTestId('history-row')[0]);
    expect(r.getByRole('button', { name: 'Remove AAA from history' })).toBeInTheDocument();
    expect(screen.getByTestId('history-exitcheck-header')).toHaveAttribute('title', expect.stringContaining('global premium stop (60%)'));
  });

  it('empty history keeps the existing message', () => {
    setup([]);
    expect(screen.getByText('No closed trades yet.')).toBeInTheDocument();
    expect(val('stat-winrate')).toBe('—');
  });
});
