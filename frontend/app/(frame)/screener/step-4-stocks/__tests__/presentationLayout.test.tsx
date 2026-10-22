/**
 * STOCK-PRES-P4-STRATEGY Task 2 — the Strategy page in the Options layout:
 * "How this page works" (M12), a "Looks for" line per card (M3), the
 * after-scan armed count (M11) and the side column (M6-M9, M13).
 * Plan: docs/superpowers/plans/2026-10-10-stock-pres-p4-strategy-plan.md
 */
import '@testing-library/jest-dom';
import { render, screen, within } from '@testing-library/react';
import Step4StocksPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { STOCK_VALIDATION_UNAVAILABLE } from '@/lib/stockExecutionSession';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => '/screener/step-4-stocks',
}));
jest.mock('@/lib/stockScan', () => ({
  ...jest.requireActual('@/lib/stockScan'),
  runStockScanWithContinuation: jest.fn(),
  runStockScan: jest.fn(),
}));
jest.mock('@/lib/api', () => ({
  api: { startHistoryPrefetch: jest.fn(), getHistoryPrefetchStatus: jest.fn() },
  getLastDataRefresh: jest.fn(() => Promise.resolve({ last_refresh: null })),
  API_BASE_URL: 'http://localhost:8000',
}));

const BULLISH = [
  'an uptrend that dips to its moving average',
  'a quiet range that breaks out on volume',
  'a fast average crossing a slow one',
  'an oversold dip inside a longer uptrend',
  'a lower-band touch that turns back up',
  'an intraday stretch below VWAP',
  'several oversold signals agreeing',
];
const BEARISH = [
  'a downtrend that bounces to its moving average',
  'a quiet range that breaks down on volume',
  'a fast average crossing a slow one',
  'an overbought pop inside a longer downtrend',
  'an upper-band touch that turns back down',
  'an intraday stretch above VWAP',
  'several overbought signals agreeing',
];

const EXPLANATION =
  'Click a card to select a strategy (saved at once; the floating Run button on Steps 1–3 uses it). '
  + 'Adjust parameters, then Run Stock Scan. A successful scan opens Backtest; a failed scan stays here with its reason.';

function setContext(direction: 'Bullish' | 'Bearish') {
  useScanStore.setState({
    context: { universe: 'SP500', direction, horizon: 'Swing (5–15d)' },
  } as never);
}

beforeEach(() => {
  useScanStore.setState({
    context: { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)' },
    activeStrategy: null, stockScanResult: null, stockScanRequest: null,
    lastStockScanStrategy: null, scanState: 'IDLE', stockScanError: null,
    stockScanFeedback: { error: null, notice: null },
    stockAfterScanIntent: {},
  } as never);
});

describe('How this page works (M12)', () => {
  it('is a <summary> and the explanation text is in the document', () => {
    render(<Step4StocksPage />);
    const summary = screen.getByText('How this page works');
    expect(summary.tagName).toBe('SUMMARY');
    expect(summary.closest('details')).not.toHaveAttribute('open');
    expect(screen.getByText(EXPLANATION)).toBeInTheDocument();
  });
});

describe('Looks for (M3)', () => {
  it('Bullish: each of the 7 bullish lines is present', () => {
    setContext('Bullish');
    render(<Step4StocksPage />);
    for (const line of BULLISH) {
      expect(screen.getAllByText(`Looks for: ${line}`).length).toBeGreaterThan(0);
    }
    expect(screen.getAllByText(/^Looks for: /)).toHaveLength(7);
  });

  it('Bearish: each of the 7 bearish lines is present and no bullish-only line is', () => {
    setContext('Bearish');
    render(<Step4StocksPage />);
    for (const line of BEARISH) {
      expect(screen.getAllByText(`Looks for: ${line}`).length).toBeGreaterThan(0);
    }
    for (const line of BULLISH.filter((l) => !BEARISH.includes(l))) {
      expect(screen.queryByText(`Looks for: ${line}`)).toBeNull();
    }
    expect(screen.getAllByText(/^Looks for: /)).toHaveLength(7);
  });
});

describe('After-scan armed count (M11) with the real stockExecutionBlock', () => {
  it('two armed symbols state the existing execution block, never the booking preview', () => {
    useScanStore.setState({ stockAfterScanIntent: { AAPL: true, MSFT: true, TSLA: false } } as never);
    render(<Step4StocksPage />);
    expect(screen.getByRole('heading', { name: 'After-scan' })).toBeInTheDocument();
    expect(screen.getByText(
      `2 symbols armed. ${STOCK_VALIDATION_UNAVAILABLE} Arming itself stays on the position card.`,
    )).toBeInTheDocument();
    expect(screen.getByText(
      '2 symbols armed. Unvalidated — research only. Strategy validation is unavailable; broker sending '
      + 'and automatic arming are blocked. Arming itself stays on the position card.',
    )).toBeInTheDocument();
    expect(screen.queryByText(/booked to the paper portfolio/)).toBeNull();
  });

  it('one armed symbol uses the singular noun', () => {
    useScanStore.setState({ stockAfterScanIntent: { AAPL: true } } as never);
    render(<Step4StocksPage />);
    expect(screen.getByText(/^1 symbol armed\. /)).toBeInTheDocument();
  });

  it.each([[{}], [{ AAPL: false }]])('nothing armed (%j) shows no After-scan card', (intent) => {
    useScanStore.setState({ stockAfterScanIntent: intent } as never);
    render(<Step4StocksPage />);
    expect(screen.queryByRole('heading', { name: 'After-scan' })).toBeNull();
    expect(screen.queryByText(/symbols? armed/)).toBeNull();
  });
});

describe('Side column "Scan actions"', () => {
  it('holds Run, Pre-warm, feedback and View Backtest results; not the cards or Parameters', () => {
    useScanStore.setState({
      stockScanFeedback: { error: 'Scan failed — x', notice: 'n' },
      stockScanResult: { scan_id: 'S', timestamp: 't', candidates: [], rejected: [] },
    } as never);
    render(<Step4StocksPage />);
    const aside = screen.getByRole('complementary', { name: 'Scan actions' });
    expect(within(aside).getByRole('button', { name: 'Run Stock Scan' })).toBeInTheDocument();
    expect(within(aside).getByRole('button', { name: 'Pre-warm history' })).toBeInTheDocument();
    expect(within(aside).getByText('Scan failed — x')).toBeInTheDocument();
    expect(within(aside).getByText('n')).toBeInTheDocument();
    expect(within(aside).getByRole('button', { name: 'View Backtest results' })).toBeInTheDocument();

    expect(within(aside).queryByText(/^Breakout from tight base$/)).toBeNull();
    expect(within(aside).queryByText(/^Looks for: /)).toBeNull();
    expect(within(aside).queryByRole('heading', { name: 'Choose a strategy' })).toBeNull();
    expect(within(aside).queryByRole('heading', { name: 'Parameters' })).toBeNull();
    expect(screen.getAllByText(/^Looks for: /)).toHaveLength(7);
    expect(screen.getByRole('heading', { name: 'Choose a strategy' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Parameters' })).toBeInTheDocument();
  });

  it('View Backtest results is absent without a stock result', () => {
    render(<Step4StocksPage />);
    expect(screen.queryByRole('button', { name: 'View Backtest results' })).toBeNull();
  });
});
