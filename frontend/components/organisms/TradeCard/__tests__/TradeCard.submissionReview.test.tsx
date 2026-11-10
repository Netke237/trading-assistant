/**
 * TC-REVIEW-06 (#581) — the decision section (the Final Recommendation until
 * #608) hosts the submission review.
 * The "Execution …" echo rows are consolidated into it; standalone (no review
 * supplied) the rows remain, with the premium stop on the Exit Plan's basis.
 */
import '@testing-library/jest-dom';
import { render as renderCard, screen, within, fireEvent } from '@testing-library/react';
import { TradeCard } from '@/components/organisms/TradeCard';
import { useSettingsStore } from '@/lib/settingsStore';
import type { TradeCardData } from '@/types/domain';

// These existing calculation/flow tests exercise all methods explicitly.
const render = (...args: Parameters<typeof renderCard>) => {
  const view = renderCard(...args);
  for (const name of ['Arithmetic', 'Ladder']) {
    const toggle = screen.queryByRole('checkbox', { name });
    if (toggle && toggle.getAttribute('aria-checked') !== 'true') fireEvent.click(toggle);
  }
  fireEvent.click(screen.getByText('Recorded decision details'));
  const transport = screen.queryByText('What Track basket and direct sends will submit');
  if (transport) fireEvent.click(transport);
  return view;
};

jest.mock('@/lib/api', () => ({
  api: {
    getStructuralStop: jest.fn(), getStockQuote: jest.fn(), getContractQuote: jest.fn(),
    getFirstPassageEstimate: jest.fn(), getExitPlan: jest.fn(),
  },
}));
jest.mock('@/components/organisms/InlineChartPanel', () => ({ InlineChartPanel: () => <div /> }));
jest.mock('@/components/molecules/SymbolHeader', () => ({ SymbolHeader: () => <div /> }));
jest.mock('@/components/molecules/ScoreCardPanel', () => ({ ScoreCardPanel: () => <div /> }));
jest.mock('@/components/molecules/LabeledStatusBadge', () => ({ LabeledStatusBadge: () => <div /> }));

const card = (o: Partial<TradeCardData> = {}): TradeCardData => ({
  symbol: 'AAPL', company: 'Apple Inc.', price: 185.2, direction: 'Bullish', status: 'PASS',
  stockScore: 82, stockConfidence: 'PASS',
  stockBreakdown: { trend: 85, pullback: 78, trigger: 72, event: 90, volatility: 65 },
  contract: 'AAPL 190C 05/15', contractScore: 70, contractConfidence: 'PASS',
  contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
  contractDetails: { strike: 190, expiry: '2026-05-15', right: 'C', mid: 5.2, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
  entry: { limit: 5.2, maxFill: 5.4, orderType: 'Limit' },
  exit: {
    invalidation: 179.64, premiumStop: 3.12, timeStopDays: 10, target: 200.02,
    targets: [{ id: 'tp1', stockPrice: 200.02, targetPrice: 200.02, estimatedOptionPrice: 8.0, contractsToSell: 1, status: 'PENDING', rrContribution: 1.0 }],
  },
  rrRatio: 2.5, rrModel: 'Heston repriced', finalStatus: 'PASS',
  ...o,
});
const arithmeticPlan = {
  computedAt: '2026-09-14T10:00:00Z',
  stop: { price: 178, source: 'atr_widened', contractPrice: 1.2, rrModel: 'Heston repriced', structuralSource: null, structuralConfidence: null, structuralPrice: null, atrFloorPrice: 178, distanceDollar: null,
    stopCost: { basis: 'bs_today', stopPrice: 178, premium: 5.0, valueAtStop: 1.2, lossDollar: 3.8, fraction: 0.76, passMaxFraction: 0.5, status: 'CAUTION' } },
  targets: [{ rrRatio: 2, arithmeticPrice: 210.5, price: 210.5, tpSource: 'arithmetic', structuralPrice: null, contractPrice: 9, rrModel: 'Heston repriced', probability: 0.4, expectedDays: 9, qualityGood: true, qualityReasons: [], distanceDollar: null, toleranceDollar: 1 }],
  atr: 4,
} as any;

const final = () => within(screen.getByRole('region', { name: 'Decision and execution' }));
const radio = (name: string) => screen.getByRole('radio', { name });

beforeEach(() => { localStorage.clear(); useSettingsStore.setState({ premiumStopPct: 0.6 }); });

describe('the decision section hosts the submission review', () => {
  it('a supplied review replaces the Execution echo rows, inside the decision section', () => {
    render(<TradeCard data={card()} submissionReview={<section aria-label="Submission review">REVIEW</section>} />);
    expect(final().getByRole('region', { name: 'Submission review' })).toHaveTextContent('REVIEW');
    expect(screen.queryByText('Execution order / limit')).not.toBeInTheDocument();
    expect(screen.queryByText('Execution stock stop')).not.toBeInTheDocument();
    expect(screen.queryByText('Execution premium stop')).not.toBeInTheDocument();
    expect(screen.queryByText('Execution time exit')).not.toBeInTheDocument();
  });

  it('standalone, tiny premium untouched: the premium stop reads global % against the fill (Exit Plan basis), not $/share', () => {
    render(<TradeCard data={card()} liveMid={0.01} />);
    const row = final().getByText('Execution premium stop').parentElement!;
    expect(row).toHaveTextContent('Global 60% — resolved against fill');
    expect(row).not.toHaveTextContent('/share');
  });

  it('standalone, untouched with a scan mid: the global applies; the scan seed is not sent', () => {
    render(<TradeCard data={card()} />);
    const row = final().getByText('Execution premium stop').parentElement!;
    expect(row).toHaveTextContent('Global 60% — resolved against fill');
  });

  it('standalone, pinned: the kept dollar amount', () => {
    render(<TradeCard data={card()} initialPremiumStop={2.0} />);
    expect(final().getByText('Execution premium stop').parentElement!).toHaveTextContent('$2.00 /share · pinned');
  });

  it('the chosen Arithmetic row shows its full-position estimated dollar outcome, gross before costs', () => {
    render(<TradeCard data={card({ exit: { ...card().exit, exitPlan: arithmeticPlan } })} contracts={2} />);
    fireEvent.click(radio('Arithmetic'));
    fireEvent.click(radio('2:1'));
    const summary = within(screen.getByRole('region', { name: 'Selected target review' }));
    const row = summary.getByText('Estimated dollar outcome (full position, before costs)').parentElement!;
    // (9.00 − 5.00 calculation premium) × 2 contracts × 100
    expect(row).toHaveTextContent('$800.00');
  });

  it('a chosen Ladder row has no matched premium basis, so its outcome is unavailable', () => {
    render(<TradeCard data={card()} contracts={2} />);
    fireEvent.click(radio('Ladder'));
    fireEvent.click(radio('TP1'));
    const summary = within(screen.getByRole('region', { name: 'Selected target review' }));
    expect(summary.getByText('Estimated dollar outcome (full position, before costs)').parentElement!)
      .toHaveTextContent('Unavailable — no matched calculation premium basis');
  });
});

it('starts inline transport review closed and keeps chart/export in the footer', () => {
  renderCard(<TradeCard data={card()} submissionReview={<section aria-label="Submission review">REVIEW</section>} />);
  const disclosure = final().getByText('What Track basket and direct sends will submit').closest('details')!;
  expect(disclosure).not.toHaveAttribute('open');
  expect(screen.getByText('REVIEW')).not.toBeVisible();
  fireEvent.click(final().getByText('What Track basket and direct sends will submit'));
  expect(screen.getByText('REVIEW')).toBeVisible();
  expect(final().queryByRole('button', { name: /export json/i })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: /export json/i })).toBeVisible();
});
