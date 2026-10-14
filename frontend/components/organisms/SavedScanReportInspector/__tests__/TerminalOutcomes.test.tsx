import React from 'react';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { useScanReportUpdates } from '@/lib/scanReports';
import { SavedScanReportInspector } from '../index';
import { api } from '@/lib/api';
jest.mock('@/lib/api', () => ({ api: { getLatestScanReport: jest.fn(), getLegacyScanReports: jest.fn() } }));
const latest = api.getLatestScanReport as jest.Mock;

// Shape mirrors backend/app/services/scan_report_lifecycle.py Collector.terminal_snapshot (version 1).
const terminal = (overrides: Record<string, unknown> = {}) => ({
  version: 1, resolution_available: true, complete: true,
  input_symbols: ['ACC', 'EXC', 'NOD', 'ERR', 'NOS', 'FIL', 'UNK'],
  evaluated_symbols: ['ACC', 'NOD', 'ERR', 'NOS', 'FIL', 'UNK'],
  outcomes: [
    { symbol: 'ACC', terminal: 'accepted', code: 'candidate_returned', observations: { direction: 'Bullish' } },
    { symbol: 'EXC', terminal: 'excluded', code: 'scan_policy' },
    { symbol: 'NOD', terminal: 'no_data', code: 'missing_history', observations: { direction: 'Bullish' } },
    { symbol: 'ERR', terminal: 'error', code: 'signal_processing_failed', observations: { direction: 'Bullish' } },
    { symbol: 'NOS', terminal: 'no_setup', code: 'setup_not_returned', observations: { direction: 'Bullish' } },
    { symbol: 'FIL', terminal: 'filtered', code: 'ema_side', observations: { current_close: 101.123456, ema_value: 102.987654, direction: 'Bullish' }, thresholds: { ema_period: 50 } },
  ],
  counts: { accepted: 1, excluded: 1, no_data: 1, error_count: 1, no_setup: 1, filtered: 1, input: 7, evaluated: 6 },
  unknown_symbols: ['UNK'],
  ...overrides,
});
const report = (category: string, id: string, diagnostics: Record<string, unknown> | null) => ({
  category, run_id: id, generation: 1, trigger: 'manual', started_at: '2026-10-13T01:00:00Z', ended_at: '2026-10-13T01:01:00Z',
  status: 'complete', persistence: 'saved', inputs: { request: { direction: 'Bullish' }, effective_configuration_complete: false },
  diagnostics_available: diagnostics != null, diagnostics, result: { candidates: [{ symbol: 'ACC' }] },
});
const serve = (byCategory: Record<string, ReturnType<typeof report>>) => latest.mockImplementation((c: string) => Promise.resolve({ category: c, latest_attempt: byCategory[c] ?? null, previous_report: null }));
const breakdown = () => screen.getByRole('region', { name: 'Terminal outcomes' });
beforeEach(() => { jest.clearAllMocks(); useScanReportUpdates.setState({ revision: 0, current: {} }); });

test('unique terminal counts come from the report and, with unknown, add up to input', async () => {
  serve({ prebreakout: report('prebreakout', 'run-1', { accepted_symbols: ['ACC'], terminal_outcomes: terminal() }) });
  render(<SavedScanReportInspector category="prebreakout" tableRunId="run-1" />);
  await screen.findByText('Run run-1');
  const counts = within(breakdown()).getByRole('list', { name: 'Terminal outcome counts' });
  const count = (label: string) => within(counts).getByText(label).closest('li')!.textContent;
  expect(count('Accepted')).toMatch(/1$/);
  expect(count('Excluded by scan policy')).toMatch(/1$/);
  expect(count('No data')).toMatch(/1$/);
  expect(count('Data/processing error')).toMatch(/1$/);
  expect(count('No setup returned')).toMatch(/1$/);
  expect(count('Filtered by a rule')).toMatch(/1$/);
  expect(count('Unknown (no outcome recorded)')).toMatch(/1$/);
  expect(count('Input symbols')).toMatch(/7$/);
  expect(count('Evaluated symbols')).toMatch(/6$/);
  expect(within(breakdown()).getByText(/exactly one terminal outcome/)).toBeInTheDocument();
  expect(within(breakdown()).getByText(/Category counts plus unknown: 7 of 7 input symbols/)).toBeInTheDocument();
  expect(within(breakdown()).queryByText(/Partial diagnostics/)).not.toBeInTheDocument();
});

test('null input and evaluated render unavailable, never zero', async () => {
  serve({ fib: report('fib', 'run-2', { terminal_outcomes: terminal({ resolution_available: false, complete: false, counts: { accepted: 1, excluded: 1, no_data: 1, error_count: 1, no_setup: 1, filtered: 1, input: null, evaluated: null } }) }) });
  render(<SavedScanReportInspector category="fib" />);
  await screen.findByText('Run run-2');
  const counts = within(breakdown()).getByRole('list', { name: 'Terminal outcome counts' });
  expect(within(counts).getByText('Input symbols').closest('li')!.textContent).toMatch(/unavailable$/);
  expect(within(counts).getByText('Evaluated symbols').closest('li')!.textContent).toMatch(/unavailable$/);
  expect(within(breakdown()).getByText(/Symbol resolution unavailable/)).toBeInTheDocument();
});

test('absent terminal outcomes are unavailable, not zero rejected; Options rendering unchanged', async () => {
  serve({ pullback: report('pullback', 'legacy-run', { accepted_symbols: ['ACC'] }), options: report('options', 'opt-run', { accepted_symbols: ['ACC'] }) });
  const r = render(<SavedScanReportInspector category="pullback" />);
  await screen.findByText('Run legacy-run');
  expect(screen.getByText('Terminal outcome diagnostics unavailable for this run.')).toBeInTheDocument();
  expect(screen.queryByRole('list', { name: 'Terminal outcome counts' })).not.toBeInTheDocument();
  r.unmount();
  render(<SavedScanReportInspector category="options" />);
  await screen.findByText('Run opt-run');
  expect(screen.queryByText(/Terminal outcome diagnostics unavailable/)).not.toBeInTheDocument();
  expect(screen.queryByRole('region', { name: 'Terminal outcomes' })).not.toBeInTheDocument();
});

test('partial and conflicting-record diagnostics are labelled', async () => {
  serve({ prebreakout: report('prebreakout', 'run-3', { terminal_outcomes: terminal({ complete: false, diagnostic_unavailable: true }) }) });
  render(<SavedScanReportInspector category="prebreakout" />);
  await screen.findByText('Run run-3');
  expect(within(breakdown()).getByText('Partial diagnostics')).toBeInTheDocument();
  expect(within(breakdown()).getByText(/Conflicting records were dropped/)).toBeInTheDocument();
});

test('symbol search drills into one symbol with recorded observations, thresholds and units', async () => {
  serve({ fib: report('fib', 'run-4', { terminal_outcomes: terminal() }) });
  render(<SavedScanReportInspector category="fib" />);
  await screen.findByText('Run run-4');
  const table = within(breakdown()).getByRole('table', { name: /Per-symbol terminal outcomes/ });
  expect(within(table).getAllByRole('row')).toHaveLength(8); // header + 6 outcomes + 1 unknown
  fireEvent.change(within(breakdown()).getByRole('searchbox', { name: 'Search symbol outcomes' }), { target: { value: 'fil' } });
  const rows = within(table).getAllByRole('row');
  expect(rows).toHaveLength(2);
  expect(rows[1]).toHaveTextContent('FIL');
  expect(rows[1]).toHaveTextContent('Filtered by a rule');
  expect(rows[1]).toHaveTextContent('current_close: $101.123456');
  expect(rows[1]).toHaveTextContent('ema_value: $102.987654');
  expect(rows[1]).toHaveTextContent('ema_period: 50 bars');
  fireEvent.change(within(breakdown()).getByRole('searchbox', { name: 'Search symbol outcomes' }), { target: { value: 'unk' } });
  expect(within(table).getAllByRole('row')[1]).toHaveTextContent(/UNK.*Unknown/);
});

test('backtest and confidence units follow backend scales without rescaling', async () => {
  const outcomes = [
    { symbol: 'BT', terminal: 'filtered', code: 'backtest_gate', observations: { passes_gate: false, win_rate: 0.4, n_trades: 12, strategy: 'pullback_ema', direction: 'Bullish' }, thresholds: { min_trades: 5, min_win_rate: 0.45 } },
    { symbol: 'CF', terminal: 'filtered', code: 'confidence_gate', observations: { confidence: 41 }, thresholds: { confidence_reject_below: 50 } },
    { symbol: 'PX', terminal: 'filtered', code: 'price_min', observations: { price: 4.5 }, thresholds: { min_price: 5 } },
    { symbol: 'SC', terminal: 'filtered', code: 'score_min', observations: { score: 38 }, thresholds: { min_stock_score: 40 } },
  ];
  serve({ pullback: report('pullback', 'run-5', { terminal_outcomes: terminal({ outcomes, input_symbols: ['BT', 'CF', 'PX', 'SC'], evaluated_symbols: ['BT', 'CF', 'PX', 'SC'], unknown_symbols: [], counts: { accepted: 0, excluded: 0, no_data: 0, error_count: 0, no_setup: 0, filtered: 4, input: 4, evaluated: 4 } }) }) });
  render(<SavedScanReportInspector category="pullback" />);
  await screen.findByText('Run run-5');
  const row = (s: string) => within(breakdown()).getByRole('cell', { name: s }).closest('tr')!;
  expect(row('BT')).toHaveTextContent('win_rate: 0.4 (fraction 0–1)');
  expect(row('BT')).toHaveTextContent('min_win_rate: 0.45 (fraction 0–1)');
  expect(row('BT')).toHaveTextContent('n_trades: 12 trades');
  expect(row('BT')).toHaveTextContent('passes_gate: no');
  expect(row('CF')).toHaveTextContent('confidence: 41%');
  expect(row('CF')).toHaveTextContent('confidence_reject_below: 50%');
  expect(row('PX')).toHaveTextContent('price: $4.5');
  expect(row('PX')).toHaveTextContent('min_price: $5');
  expect(row('SC')).toHaveTextContent('score: 38 (0–100 scale)');
});

test('generic no-setup outcome does not name a failed rule', async () => {
  const outcomes = [
    { symbol: 'PB', terminal: 'no_setup', code: 'setup_not_returned', observations: { direction: 'Bullish' } },
    { symbol: 'FB', terminal: 'no_setup', code: 'fib_level_not_returned', observations: { direction: 'Bullish' } },
  ];
  serve({ prebreakout: report('prebreakout', 'run-6', { terminal_outcomes: terminal({ outcomes, input_symbols: ['PB', 'FB'], evaluated_symbols: ['PB', 'FB'], unknown_symbols: [], counts: { accepted: 0, excluded: 0, no_data: 0, error_count: 0, no_setup: 2, filtered: 0, input: 2, evaluated: 2 } }) }) });
  render(<SavedScanReportInspector category="prebreakout" />);
  await screen.findByText('Run run-6');
  for (const s of ['PB', 'FB']) {
    const reason = within(breakdown()).getByRole('cell', { name: s }).closest('tr')!.querySelectorAll('td')[2].textContent!;
    expect(reason).toMatch(/No setup returned/);
    expect(reason).toMatch(/individual failed rules not reported/);
    expect(reason).not.toMatch(/ATR|volume|EMA|proximity|swing|range|Fibonacci level hit|tolerance/i);
  }
});

test('run identity: matching versus different or absent table run', async () => {
  serve({ prebreakout: report('prebreakout', 'run-7', { terminal_outcomes: terminal() }) });
  const r = render(<SavedScanReportInspector category="prebreakout" tableRunId="run-7" />);
  await screen.findByText('Run run-7');
  expect(within(breakdown()).getByText(/Breakdown for saved run run-7/)).toBeInTheDocument();
  expect(within(breakdown()).getByText(/matches the displayed table run/)).toBeInTheDocument();
  r.rerender(<SavedScanReportInspector category="prebreakout" tableRunId="run-other" />);
  expect(within(breakdown()).getByText(/belongs to saved run run-7, not to the rows shown \(table run run-other\)/)).toBeInTheDocument();
  r.rerender(<SavedScanReportInspector category="prebreakout" tableRunId={null} />);
  expect(within(breakdown()).getByText(/belongs to saved run run-7, not to the rows shown \(no table run identified\)/)).toBeInTheDocument();
  expect(within(breakdown()).queryByText(/matches the displayed table run/)).not.toBeInTheDocument();
});

test('sub-mode switch changes category and never relabels the old report as current', async () => {
  serve({ prebreakout: report('prebreakout', 'pre-run', { terminal_outcomes: terminal() }), fib: report('fib', 'fib-run', { terminal_outcomes: terminal() }) });
  const r = render(<SavedScanReportInspector category="prebreakout" tableRunId="pre-run" />);
  await screen.findByText('Run pre-run');
  r.rerender(<SavedScanReportInspector category="fib" tableRunId={null} />);
  await screen.findByText('Run fib-run');
  expect(screen.getByLabelText('Report category')).toHaveValue('fib');
  expect(screen.queryByText(/pre-run/)).not.toBeInTheDocument();
  expect(within(breakdown()).getByText(/belongs to saved run fib-run, not to the rows shown/)).toBeInTheDocument();
});
