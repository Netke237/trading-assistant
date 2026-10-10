import '@testing-library/jest-dom';
import { render, screen, within } from '@testing-library/react';
import Page from '../page';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import type { BacktestData, PositionCardData } from '@/types/stockDomain';
jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock('@/components/organisms/StockPositionCard', () => ({ StockPositionCard: () => <div /> }));
jest.mock('@/components/organisms/StockSendDialog', () => ({ StockSendDialog: () => <div /> }));
jest.mock('@/components/organisms/DirectSendNotesPanel', () => ({ DirectSendNotesPanel: () => <div /> }));
jest.mock('@/components/organisms/ScanFunnel', () => ({ ScanFunnel: () => <div /> }));
jest.mock('@/components/atoms/WatchStar', () => ({ WatchStar: ({ symbol }: { symbol: string }) => <button>Watch {symbol}</button> }));

const TOOLTIP = "trades closed at the next open after being held the horizon's hold, neither stop nor target reached";

function candidate(symbol: string, extra: Partial<BacktestData>): PositionCardData {
  return {
    symbol, company: symbol, price: 100, direction: 'Bullish',
    strategy: { strategy: 'pullback_ema', entry_price: 100, stop_price: 95, target_price: 110, rr_ratio: 2, atr: 1, detail: {} },
    backtest: { n_trades: 18, win_rate: .6, total_return_pct: 10, max_drawdown_pct: -5, expectancy: 1, sharpe: 1, confidence: 60, passes_gate: true, summary_text: 'summary', ...extra },
    stock_score: 70, stock_status: 'PASS', shares: 10, dollar_risk: 50, dollar_size: 1000,
    confidence: null, confidence_text: null, next_event_days: 30, sector_rs_pct: 0,
  };
}

function renderWith(extra: Partial<BacktestData>) {
  useScanParamsStore.setState({ eventFilter: 'include' });
  useScanStore.setState({
    stockScanResult: { scan_id: 's', timestamp: 't', candidates: [candidate('AAPL', extra)], rejected: [] },
    stockScanRequest: { strategy: 'pullback_ema', bt_min_trades: 10, bt_min_win_rate: .4 } as never,
    stockScanFeedback: { error: null, notice: null }, selectedSymbol: null, stockBasket: [],
  });
  render(<Page />);
  return within(screen.getByTestId('trades-AAPL'));
}

it('shows "3 of 18 on time (hold 15d)" with its tooltip next to the trade count', () => {
  const cell = renderWith({ n_time_exits: 3, hold_max_days: 15 });
  expect(cell.getByText('18')).toBeInTheDocument();
  expect(cell.getByText('3 of 18 on time (hold 15d)')).toBeInTheDocument();
  expect(cell.getByRole('tooltip')).toHaveTextContent(TOOLTIP);
});

it('shows "no hold" for a new result run without a hold', () => {
  const cell = renderWith({ n_time_exits: 0, hold_max_days: null });
  expect(cell.getByText('no hold')).toBeInTheDocument();
  expect(cell.queryByText(/on time/)).not.toBeInTheDocument();
});

it('shows "—" and no hold label when the count is null (unknown)', () => {
  const cell = renderWith({ n_time_exits: null, hold_max_days: null });
  expect(cell.getByText('—')).toBeInTheDocument();
  expect(cell.queryByText(/hold/)).not.toBeInTheDocument();
  expect(cell.queryByText(/on time/)).not.toBeInTheDocument();
  expect(cell.queryByText(/^0/)).not.toBeInTheDocument();
});

it('shows "—" and no hold label when both fields are absent (an old saved row)', () => {
  const cell = renderWith({});
  expect(cell.getByText('—')).toBeInTheDocument();
  expect(cell.queryByText(/hold/)).not.toBeInTheDocument();
  expect(cell.queryByText(/on time/)).not.toBeInTheDocument();
});
