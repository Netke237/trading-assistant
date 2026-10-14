import '@testing-library/jest-dom';
import { render, screen, within, fireEvent } from '@testing-library/react';
import Page from '../page';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import type { PositionCardData } from '@/types/stockDomain';

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock('@/components/organisms/StockPositionCard', () => ({ StockPositionCard: () => <div>Full shared card</div> }));
jest.mock('@/components/organisms/StockSendDialog', () => ({ StockSendDialog: () => <div /> }));
jest.mock('@/components/organisms/DirectSendNotesPanel', () => ({ DirectSendNotesPanel: () => <div /> }));
jest.mock('@/components/atoms/WatchStar', () => ({ WatchStar: ({ symbol }: { symbol: string }) => <button>Watch {symbol}</button> }));
jest.mock('@/components/organisms/SavedScanReportInspector', () => ({ SavedScanReportInspector: () => <div /> }));

const EXPLANATION = 'One row per candidate. Expand a row for a short summary and the full position card. Open Position to review on Step 6.';
const EARNINGS = 'Earnings inside the reject window — no send';

type CandidateOverrides = Omit<Partial<PositionCardData>, 'backtest' | 'strategy'> & {
  backtest?: Partial<PositionCardData['backtest']>;
  strategy?: Partial<PositionCardData['strategy']>;
};

function candidate(overrides: CandidateOverrides = {}): PositionCardData {
  const { backtest: backtestOverride, strategy: strategyOverride, ...rest } = overrides;
  const symbol = overrides.symbol ?? 'AAPL';
  const strategy: PositionCardData['strategy'] = {
    strategy: 'pullback_ema', entry_price: 100, stop_price: 95, target_price: 110, rr_ratio: 2, atr: 1, detail: {},
    ...strategyOverride,
  };
  const backtest: PositionCardData['backtest'] = {
    n_trades: 18, win_rate: 0.6, total_return_pct: 10, max_drawdown_pct: -5, expectancy: 1, sharpe: 1,
    confidence: 60, passes_gate: true, summary_text: 'summary',
    ...backtestOverride,
  };
  return {
    company: symbol, price: 100, direction: 'Bullish',
    stock_score: 70, stock_status: 'PASS', shares: 10, dollar_risk: 50, dollar_size: 1000,
    confidence: null, confidence_text: null, next_event_days: 30, sector_rs_pct: 0,
    ...rest,
    symbol, strategy, backtest,
  };
}

function load(
  rows: PositionCardData[],
  request: object | null = { strategy: 'pullback_ema', bt_min_trades: 10, bt_min_win_rate: 0.4 },
  result: Record<string, unknown> = {},
) {
  useScanParamsStore.setState({ eventFilter: 'include' });
  useScanStore.setState({
    stockScanResult: {
      scan_id: 's', timestamp: 't', candidates: rows, rejected: [],
      ...result,
    },
    stockScanRequest: request as never,
    stockScanFeedback: { error: null, notice: null },
    selectedSymbol: null,
    stockBasket: [],
    stockScanAt: null,
  });
  render(<Page />);
  const summary = screen.getByText('How this page works');
  expect(summary.closest('details')).not.toHaveAttribute('open');
}

function openSummary(symbol: string) {
  fireEvent.click(screen.getByRole('button', { name: `Expand ${symbol}` }));
  return screen.getByRole('region', { name: `Quick summary ${symbol}` });
}

beforeEach(() => {
  useScanParamsStore.setState({ eventFilter: 'include' });
});

afterEach(() => {
  jest.useRealTimers();
});

it('shows a collapsed page explanation and no quick summary before a row is opened', () => {
  load([candidate()]);
  const details = screen.getByText('How this page works').closest('details');
  expect(details).not.toBeNull();
  expect(details).not.toHaveAttribute('open');
  const text = (details?.textContent ?? '').replace(/\s+/g, ' ').trim();
  expect(text).toContain(EXPLANATION);
  expect(text.replace('How this page works', '').replace(EXPLANATION, '').trim()).toBe('');
  const header = screen.getByText('STEP 5 OF 6').parentElement;
  const strip = screen.getByRole('region', { name: 'Scan summary' });
  expect(header?.nextElementSibling).toBe(details);
  expect(details?.nextElementSibling).toBe(strip);
  expect(screen.queryByRole('region', { name: 'Quick summary AAPL' })).not.toBeInTheDocument();
});

it('puts the quick summary before the full card when the row is expanded', () => {
  load([candidate()]);
  const section = openSummary('AAPL');
  const card = screen.getByText('Full shared card');
  expect(section.contains(card)).toBe(false);
  expect(section.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(section.parentElement).toBe(card.parentElement);
  const row = screen.getByRole('button', { name: 'Expand AAPL' }).parentElement;
  expect(row?.contains(section)).toBe(false);
});

it('removes the quick summary and the full card together on collapse', () => {
  load([candidate()]);
  openSummary('AAPL');
  expect(screen.getByText('Full shared card')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Expand AAPL' }));
  expect(screen.queryByRole('region', { name: 'Quick summary AAPL' })).not.toBeInTheDocument();
  expect(screen.queryByText('Full shared card')).not.toBeInTheDocument();
});

it('lists scorer factors in record order and hides an unmeasured raw score', () => {
  load([candidate({
    stock_score: 42,
    stock_explanation: {
      status: 'REJECT',
      components: {
        trend: { name: 'Trend', measured: true, raw_score: 85.4, weight: 0.3, contribution: 12.5 } as never,
        event: { name: 'Event', measured: false, raw_score: 80, weight: 0.2, contribution: 4 } as never,
      },
    } as never,
  })]);
  const section = openSummary('AAPL');
  const summary = within(section);
  expect(summary.getByText('42')).toBeInTheDocument();
  const trend = summary.getByText('Trend').parentElement as HTMLElement;
  const event = summary.getByText('Event').parentElement as HTMLElement;
  expect(trend).toHaveTextContent('85');
  expect(event).toHaveTextContent('Unavailable');
  expect(event).not.toHaveTextContent('80');
  expect(section).not.toHaveTextContent('80');
  expect(section.textContent?.indexOf('Trend')).toBeLessThan(section.textContent?.indexOf('Event') ?? -1);
  expect(summary.queryByText('REJECT')).not.toBeInTheDocument();
  expect(summary.queryByText(/weight/i)).not.toBeInTheDocument();
  expect(summary.queryByText(/contribution/i)).not.toBeInTheDocument();
});

it('says scorer factors are unavailable when the explanation is absent', () => {
  load([candidate()]);
  const section = within(openSummary('AAPL'));
  expect(section.getByText('Scorer factors unavailable')).toBeInTheDocument();
  expect(section.queryByText('Trend')).not.toBeInTheDocument();
  expect(section.getByText('Fundamentals unavailable')).toBeInTheDocument();
  expect(section.getByText('Recorded gates unavailable')).toBeInTheDocument();
});

it('copies backtest figures into the quick summary without recomputing them', () => {
  load([candidate({
    backtest: {
      win_rate: 0.584, n_trades: 18, expectancy: -0.2, total_return_pct: -1.84, max_drawdown_pct: -6.14, sharpe: 1.1,
    },
  })]);
  const section = within(openSummary('AAPL'));
  expect(section.getByText('58%')).toBeInTheDocument();
  expect(section.getByText('18')).toBeInTheDocument();
  expect(section.getByText('-0.20')).toBeInTheDocument();
  expect(section.getByText('-1.8%')).toBeInTheDocument();
  expect(section.queryByText('1.8%')).not.toBeInTheDocument();
  expect(section.getByText('6.1%')).toBeInTheDocument();
  expect(section.queryByText('-6.1%')).not.toBeInTheDocument();
  expect(section.getByText('1.10')).toBeInTheDocument();
  expect(section.queryByText(/on time|no hold/)).not.toBeInTheDocument();
});

it('keeps a stored gate failure even when the numeric rule would pass', () => {
  load([candidate({
    backtest: { passes_gate: false, win_rate: 0.9, n_trades: 100, expectancy: 1 },
  })]);
  const section = within(openSummary('AAPL'));
  expect(section.getByText('Backtest gate REJECT')).toBeInTheDocument();
  expect(section.queryByText('Backtest gate PASS')).not.toBeInTheDocument();
});

it('ages the earnings veto from the scan clock instead of the stored flag', () => {
  jest.useFakeTimers();
  jest.setSystemTime(new Date(2026, 9, 8, 10, 0, 0));
  try {
    load(
      [
        candidate({ symbol: 'AAPL', earnings_days: 61, earnings_veto: false }),
        candidate({ symbol: 'MSFT', earnings_days: 2, earnings_veto: true }),
      ],
      { strategy: 'pullback_ema', bt_min_trades: 10, bt_min_win_rate: 0.4 },
      { timestamp: '2026-10-05T14:30:00', veto_days: 60 },
    );
    expect(within(openSummary('AAPL')).getByText(EARNINGS)).toBeInTheDocument();
    const msft = within(openSummary('MSFT'));
    expect(screen.queryByRole('region', { name: 'Quick summary AAPL' })).not.toBeInTheDocument();
    expect(msft.queryByText(EARNINGS)).not.toBeInTheDocument();
    expect(screen.queryByText(EARNINGS)).not.toBeInTheDocument();
  } finally {
    jest.useRealTimers();
  }
});

it('prints each recorded gate in order', () => {
  load([candidate({
    fundamentals: { score: 64 } as never,
    gate_flags: [{ gate: 'liquidity', status: 'CAUTION', detail: 'wide spread' }],
  })]);
  const section = within(openSummary('AAPL'));
  expect(section.getByText('liquidity: CAUTION · wide spread')).toBeInTheDocument();
  expect(section.getByText('Fundamentals 64')).toBeInTheDocument();
  expect(section.queryByText('Recorded gates unavailable')).not.toBeInTheDocument();
  expect(section.queryByText('Fundamentals unavailable')).not.toBeInTheDocument();
});

it('says threshold provenance is unavailable inside the quick summary when minimums are null', () => {
  load(
    [candidate()],
    { strategy: 'pullback_ema', bt_min_trades: null, bt_min_win_rate: null },
  );
  const section = within(openSummary('AAPL'));
  expect(section.getByText('Threshold provenance unavailable for this scan')).toBeInTheDocument();
  expect(section.queryByText(/Scan thresholds:/)).not.toBeInTheDocument();
});
