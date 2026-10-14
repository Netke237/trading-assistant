import { render, screen, fireEvent, within, act } from '@testing-library/react';
import Page from '../page';
import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';
import { useUniverseStore } from '@/lib/universeStore';
import { useScanReportUpdates } from '@/lib/scanReports';
jest.mock('@/lib/api', () => ({ api: { getLatestScanReport: jest.fn(), prebreakoutScan: jest.fn(), fibPullbackScan: jest.fn(), postStockScan: jest.fn(), analyzeStock: jest.fn(() => new Promise(() => {})), getCandles: jest.fn(() => Promise.resolve([])) } }));
jest.mock('@/components/organisms/CompositeAlertDialog', () => ({ CompositeAlertDialog: () => null }));
jest.mock('../SelectedSetupChart', () => ({ SelectedSetupChart: () => null }));
const terminal = { version: 1, resolution_available: true, complete: true, input_symbols: ['AAA', 'BBB', 'ZZZ'], evaluated_symbols: ['AAA', 'BBB', 'ZZZ'],
  outcomes: [{ symbol: 'AAA', terminal: 'accepted', code: 'candidate_returned' }, { symbol: 'BBB', terminal: 'accepted', code: 'candidate_returned' }, { symbol: 'ZZZ', terminal: 'no_setup', code: 'setup_not_returned' }],
  counts: { accepted: 2, excluded: 0, no_data: 0, error_count: 0, no_setup: 1, filtered: 0, input: 3, evaluated: 3 }, unknown_symbols: [] };
const report = (category: string, id: string) => ({ category, run_id: id, generation: 1, trigger: 'manual', started_at: 's', ended_at: 'e', status: 'complete', persistence: 'saved',
  inputs: { request: {}, effective_configuration_complete: false }, diagnostics_available: true, diagnostics: { terminal_outcomes: terminal }, result: { candidates: [] } });
const row = (symbol: string, confidence = 80) => ({ symbol, direction: 'Bullish', confidence, metrics: { atr_ratio: 0.6 } });
beforeEach(() => {
  jest.clearAllMocks();
  useScanReportUpdates.setState({ revision: 0, current: {} });
  useUniverseStore.setState({ pick: 'SP500' });
  useScanStore.setState({ context: null, preBreakoutResults: [row('AAA'), row('BBB', 70)], fibPullbackResults: [] });
  (api.getLatestScanReport as jest.Mock).mockImplementation((c: string) => Promise.resolve({ category: c, latest_attempt: report(c, `${c}-saved`), previous_report: null }));
});

test('candidates heading carries the filter breakdown; opening it keeps controls, rows and selection', async () => {
  render(<Page />);
  expect(screen.getByRole('heading', { name: 'Pre-Breakout candidates' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Select BBB' }));
  const toggle = screen.getByRole('button', { name: 'Filter breakdown' });
  expect(toggle).toHaveAttribute('aria-expanded', 'false');
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute('aria-expanded', 'true');
  const panel = screen.getByRole('region', { name: 'Filter breakdown and analysis log' });
  await within(panel).findByText('Run prebreakout-saved');
  expect(within(panel).getByText(/Each category keeps its latest report until its next run/)).toBeInTheDocument();
  expect(within(panel).getByText(/no client-side filter/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Select AAA' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Select BBB' })).toHaveAttribute('aria-pressed', 'true');
  expect(screen.getByRole('button', { name: 'Run Scan' })).toBeInTheDocument();
  expect(screen.getAllByRole('spinbutton').length).toBeGreaterThan(0);
  // Rows restored from the store carry no run id: the saved report is not relabelled as the table's run.
  expect(within(panel).getByText(/belongs to saved run prebreakout-saved, not to the rows shown/)).toBeInTheDocument();
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute('aria-expanded', 'false');
  expect(screen.getByRole('button', { name: 'Select BBB' })).toHaveAttribute('aria-pressed', 'true');
});

test('a fresh scan links the breakdown to the displayed table run', async () => {
  (api.prebreakoutScan as jest.Mock).mockImplementation((_s, _d, _p, _u, metadata) => { metadata({ run_id: 'prebreakout-saved', generation: 1, persistence: 'saved' }); return Promise.resolve([row('AAA')]); });
  render(<Page />);
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Run Scan' })));
  fireEvent.click(screen.getByRole('button', { name: 'Filter breakdown' }));
  const panel = screen.getByRole('region', { name: 'Filter breakdown and analysis log' });
  await within(panel).findByText('Run prebreakout-saved');
  expect(within(panel).getByText(/Breakdown for saved run prebreakout-saved matches the displayed table run/)).toBeInTheDocument();
  expect(screen.getByText(/Displayed rows: run prebreakout-saved/)).toBeInTheDocument();
});

test.each([
  ['Fib Pullback', 'Fib Pullback candidates', 'fib'],
  [/Pullback to EMA/, 'Pullback candidates', 'pullback'],
] as const)('%s mode has its own candidates heading and breakdown for its own category', async (modeButton, heading, category) => {
  render(<Page />);
  fireEvent.click(screen.getByRole('button', { name: modeButton }));
  expect(screen.getByRole('heading', { name: heading })).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Pre-Breakout candidates' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Filter breakdown' }));
  const panel = screen.getByRole('region', { name: 'Filter breakdown and analysis log' });
  await within(panel).findByText(`Run ${category}-saved`);
  expect(within(panel).getByLabelText('Report category')).toHaveValue(category);
  expect(within(panel).queryByText('Run prebreakout-saved')).not.toBeInTheDocument();
});
