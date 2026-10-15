import '@testing-library/jest-dom';
import { render, screen, within, act } from '@testing-library/react';
import Page from '../page';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import type { PositionCardData } from '@/types/stockDomain';

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock('@/components/organisms/StockPositionCard', () => ({ StockPositionCard: () => <div /> }));
jest.mock('@/components/organisms/StockSendDialog', () => ({ StockSendDialog: () => <div /> }));
jest.mock('@/components/organisms/DirectSendNotesPanel', () => ({ DirectSendNotesPanel: () => <div /> }));
jest.mock('@/components/atoms/WatchStar', () => ({ WatchStar: ({ symbol }: { symbol: string }) => <button>Watch {symbol}</button> }));
jest.mock('@/components/organisms/SavedScanReportInspector', () => ({ SavedScanReportInspector: () => <div /> }));

function candidate(symbol: string, days: number | null): PositionCardData {
  return {
    symbol, company: symbol, price: 100, direction: 'Bullish',
    strategy: { strategy: 'pullback_ema', entry_price: 100, stop_price: 95, target_price: 110, rr_ratio: 2, atr: 1, detail: {} },
    backtest: { n_trades: 18, win_rate: .6, total_return_pct: 10, max_drawdown_pct: -5, expectancy: 1, sharpe: 1, confidence: 60, passes_gate: true, summary_text: 'summary' },
    stock_score: 70, stock_status: 'PASS', shares: 10, dollar_risk: 50, dollar_size: 1000,
    confidence: null, confidence_text: null, next_event_days: days, sector_rs_pct: 0,
  };
}

function summary() {
  return within(screen.getByRole('region', { name: 'Scan summary' }));
}

beforeEach(() => {
  useScanParamsStore.setState({ eventFilter: 'include' });
  useScanStore.setState({
    stockScanResult: {
      scan_id: 's', timestamp: 't',
      candidates: [candidate('AAPL', 30), candidate('MSFT', 40)],
      rejected: [],
    },
    stockScanRequest: { strategy: 'pullback_ema', bt_min_trades: 10, bt_min_win_rate: 0.4 } as never,
    stockScanFeedback: { error: null, notice: null },
    selectedSymbol: null,
    stockBasket: [],
    stockScanAt: null,
  });
});

it('shows candidate, rejected, and over-cap counts the header already uses', () => {
  useScanStore.setState({
    stockScanResult: {
      scan_id: 's', timestamp: 't',
      candidates: [candidate('AAPL', 30), candidate('MSFT', 40)],
      rejected: [
        { symbol: 'BAD', reason: 'backtest gate: insufficient trades' },
        { symbol: 'CAP', reason: 'Shortlist cap: rank below limit' },
      ],
    },
  });
  render(<Page />);
  const region = screen.getByRole('region', { name: 'Scan summary' });
  const strip = within(region);
  expect(region).toHaveTextContent('Candidates 2');
  expect(region).toHaveTextContent('Rejected 1');
  expect(region).toHaveTextContent('Over cap 1');
  expect(strip.getByText('Candidates')).toBeInTheDocument();
  expect(screen.getByText('2 candidates · 1 rejected · 1 over cap')).toBeInTheDocument();
});

it('shows the gate this scan used when both minimums are numbers', () => {
  useScanStore.setState({
    stockScanRequest: { strategy: 'pullback_ema', bt_min_trades: 8, bt_min_win_rate: 0.45 } as never,
  });
  render(<Page />);
  expect(summary().getByText('win ≥45% · trades ≥8 · expectancy ≥ 0')).toBeInTheDocument();
});

it('shows threshold provenance unavailable when the scan request is missing', () => {
  useScanStore.setState({ stockScanRequest: null });
  render(<Page />);
  const strip = summary();
  expect(strip.getByText('Threshold provenance unavailable for this scan')).toBeInTheDocument();
  expect(strip.queryByText(/win ≥/)).not.toBeInTheDocument();
});

it('labels the event filter and counts hidden rows without repeating the sentence', () => {
  useScanParamsStore.setState({ eventFilter: 'avoid' });
  useScanStore.setState({
    stockScanResult: {
      scan_id: 's', timestamp: 't',
      candidates: [candidate('AAPL', 2), candidate('MSFT', null)],
      rejected: [],
    },
  });
  render(<Page />);
  const region = screen.getByRole('region', { name: 'Scan summary' });
  const strip = within(region);
  expect(strip.getByText('Avoid')).toBeInTheDocument();
  expect(region).toHaveTextContent('Hidden 1');
  expect(screen.getAllByText('1 of 2 hidden by the event filter.')).toHaveLength(1);
  act(() => useScanParamsStore.setState({ eventFilter: 'only_pre_event' }));
  expect(summary().getByText('Events only')).toBeInTheDocument();
});

it('shows one last stock scan line inside the summary, not the header', () => {
  useScanStore.setState({ stockScanAt: '2026-10-13T15:04:00' });
  render(<Page />);
  const strip = summary();
  expect(screen.getAllByText(/Last stock scan:/)).toHaveLength(1);
  expect(strip.getByText(/Last stock scan:/)).toBeInTheDocument();
  const header = screen.getByText('STEP 5 OF 6').closest('div');
  expect(header).not.toBeNull();
  expect(within(header as HTMLElement).queryByText(/Last stock scan:/)).not.toBeInTheDocument();
});

it('moves Send basket into the header', () => {
  useScanStore.setState({ stockBasket: [candidate('AAPL', 30), candidate('MSFT', 40)] });
  render(<Page />);
  const buttons = screen.getAllByRole('button', { name: 'Send basket (2)' });
  expect(buttons).toHaveLength(1);
  const header = screen.getByText('STEP 5 OF 6').closest('div');
  expect(header).not.toBeNull();
  expect(within(header as HTMLElement).getByRole('button', { name: 'Send basket (2)' })).toBe(buttons[0]);
});
