import '@testing-library/jest-dom';
import { render, screen, fireEvent } from '@testing-library/react';
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

function candidate(
  symbol: string,
  stock_score: number,
  confidence: number | null,
  fundamentals?: { score: number },
): PositionCardData {
  return {
    symbol, company: symbol, price: 100, direction: 'Bullish',
    strategy: { strategy: 'pullback_ema', entry_price: 100, stop_price: 95, target_price: 110, rr_ratio: 2, atr: 1, detail: {} },
    backtest: { n_trades: 18, win_rate: .6, total_return_pct: 10, max_drawdown_pct: -5, expectancy: 1, sharpe: 1, confidence: 60, passes_gate: true, summary_text: 'summary' },
    stock_score, stock_status: 'PASS', shares: 10, dollar_risk: 50, dollar_size: 1000,
    confidence, confidence_text: null, next_event_days: 30, sector_rs_pct: 0,
    ...(fundamentals ? { fundamentals: fundamentals as never } : {}),
  };
}

function renderCandidates(rows: PositionCardData[]) {
  useScanParamsStore.setState({ eventFilter: 'include' });
  useScanStore.setState({
    stockScanResult: { scan_id: 's', timestamp: 't', candidates: rows, rejected: [] },
    stockScanRequest: { strategy: 'pullback_ema', bt_min_trades: 10, bt_min_win_rate: 0.4 } as never,
    stockScanFeedback: { error: null, notice: null },
    selectedSymbol: null,
    stockBasket: [],
    stockScanAt: null,
  });
  render(<Page />);
}

function symbolOrder(symbols: string[]): string[] {
  const pattern = new RegExp(`^(${symbols.join('|')})$`);
  return screen.getAllByText(pattern).map(el => el.textContent ?? '');
}

beforeEach(() => {
  useScanParamsStore.setState({ eventFilter: 'include' });
});

it('sorts by score descending, then ascending, then back to scan order', () => {
  const symbols = ['AAPL', 'MSFT', 'NVDA'];
  renderCandidates([
    candidate('AAPL', 10, null),
    candidate('MSFT', 30, null),
    candidate('NVDA', 20, null),
  ]);
  expect(symbolOrder(symbols)).toEqual(['AAPL', 'MSFT', 'NVDA']);
  const score = screen.getByRole('button', { name: 'Sort by score' });
  fireEvent.click(score);
  expect(symbolOrder(symbols)).toEqual(['MSFT', 'NVDA', 'AAPL']);
  expect(score).toHaveTextContent('↓');
  fireEvent.click(score);
  expect(symbolOrder(symbols)).toEqual(['AAPL', 'NVDA', 'MSFT']);
  expect(score).toHaveTextContent('↑');
  fireEvent.click(score);
  expect(symbolOrder(symbols)).toEqual(['AAPL', 'MSFT', 'NVDA']);
  expect(score).toHaveTextContent('↕');
});

it('sorts null confidence last when descending and drops that order when score is chosen', () => {
  const symbols = ['AAPL', 'MSFT', 'NVDA'];
  renderCandidates([
    candidate('AAPL', 10, 10),
    candidate('MSFT', 50, null),
    candidate('NVDA', 20, 40),
  ]);
  fireEvent.click(screen.getByRole('button', { name: 'Sort by confidence' }));
  expect(symbolOrder(symbols)).toEqual(['NVDA', 'AAPL', 'MSFT']);
  fireEvent.click(screen.getByRole('button', { name: 'Sort by score' }));
  expect(symbolOrder(symbols)).toEqual(['MSFT', 'NVDA', 'AAPL']);
  expect(screen.getByRole('button', { name: 'Sort by confidence' })).toHaveTextContent('↕');
  expect(screen.getByRole('button', { name: 'Sort by score' })).toHaveTextContent('↓');
});

it('sorts a missing health score below zero and clears an ascending score sort', () => {
  const symbols = ['GAP', 'NIL', 'TOP'];
  renderCandidates([
    candidate('GAP', 20, null),
    candidate('NIL', 10, null, { score: 0 }),
    candidate('TOP', 30, null, { score: 5 }),
  ]);
  const score = screen.getByRole('button', { name: 'Sort by score' });
  fireEvent.click(score);
  fireEvent.click(score);
  expect(symbolOrder(symbols)).toEqual(['NIL', 'GAP', 'TOP']);
  const health = screen.getByRole('button', { name: 'Sort by fundamental health score' });
  fireEvent.click(health);
  expect(symbolOrder(symbols)).toEqual(['TOP', 'NIL', 'GAP']);
  expect(score).toHaveTextContent('↕');
  expect(health).toHaveTextContent('↓');
  expect(screen.getAllByText('SCORE')).toHaveLength(1);
  expect(screen.getAllByText('CONF')).toHaveLength(1);
  expect(screen.getAllByText('HEALTH')).toHaveLength(1);
  expect(screen.getByText('HEALTH').closest('button')).toBeNull();
});
