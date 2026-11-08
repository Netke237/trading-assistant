/** TC-REVIEW-05 (#580): Arithmetic and Ladder on Monte Carlo's stop/target
 *  order, and a display-only comparison of two or three methods in the same
 *  results area. Opening or comparing never calculates, never chooses the
 *  Final Recommendation method and never rewrites a setting. */
import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { api } from '@/lib/api';
import { TradeCard } from '@/components/organisms/TradeCard';
import type { ExitPlan, ExitPlanTargetRow, FirstPassageContext, FirstPassageEstimate, MethodPick, TradeCardData } from '@/types/domain';

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

const row = (ratio: number, o: Partial<ExitPlanTargetRow> = {}): ExitPlanTargetRow => ({
  rrRatio: ratio, arithmeticPrice: 195, price: 196, tpSource: 'structural_snap',
  structuralPrice: 196, contractPrice: 6.5, rrModel: 'Delta approximation',
  probability: 0.6, expectedDays: 8, qualityGood: false,
  qualityReasons: ['target_capped', 'test_quality_reason'], distanceDollar: 1, toleranceDollar: 1.5, ...o,
});
const plan = (): ExitPlan => ({
  stop: { price: 180, source: 'structural', contractPrice: 2.2, rrModel: 'Heston repriced',
    structuralSource: 'order_block', structuralConfidence: 80, structuralPrice: 180,
    atrFloorPrice: 175, distanceDollar: 5,
    stopCost: { premium: 4, stopPrice: 180, valueAtStop: 1.8, lossDollar: 2.2,
      fraction: 0.55, passMaxFraction: 0.6, status: 'PASS', basis: 'bs_today' } },
  targets: [row(2), row(3, { arithmeticPrice: 199, price: 200, contractPrice: 8.25, probability: 0.4, expectedDays: null })],
  atr: 3.5, computedAt: '2026-10-13T12:00:00Z',
});
const estimate = (): FirstPassageEstimate => ({
  targets: [
    { pct: 0.25, optionPrice: 5, stockPrice: 195, probability: 0.6, expectedDays: 8 },
    { pct: 0.5, optionPrice: 6, stockPrice: 199, probability: 0.3, expectedDays: 12 },
  ],
  invalidation: { probability: 0.3, expectedDays: 4 },
});
const context: FirstPassageContext = { premium: 4, delta: 0.45, targetPct: { t1: 0.25, t2: 0.5, t3: 0.75 } };

const card = (o: Partial<TradeCardData['exit']> = {}): TradeCardData => ({
  symbol: 'AAPL', company: 'Apple Inc.', price: 185.2, direction: 'Bullish', status: 'PASS',
  stockScore: 82, stockConfidence: 'PASS',
  stockBreakdown: { trend: 85, pullback: 78, trigger: 72, event: 90, volatility: 65 },
  contract: 'AAPL 190C 05/15', contractScore: 70, contractConfidence: 'PASS',
  contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
  contractDetails: { strike: 190, expiry: '2026-05-15', right: 'C', mid: 5, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
  entry: { limit: 5, maxFill: 5.2, orderType: 'Limit' },
  exit: {
    invalidation: 179.64, premiumStop: 2, timeStopDays: 10, target: 200.02,
    rrRiskBasis: 'full_premium',
    targets: [
      { id: 'tp1', stockPrice: 200.02, targetPrice: 200.02, estimatedOptionPrice: 8, contractsToSell: 1, status: 'PENDING', rrContribution: 0.6 },
      { id: 'tp2', stockPrice: 205, targetPrice: 205, estimatedOptionPrice: 10, status: 'PENDING', rrContribution: 1.0 },
    ],
    exitPlan: plan(),
    firstPassage: estimate(),
    firstPassageContext: context,
    ...o,
  },
  rrRatio: 2.5, rrModel: 'Heston repriced', finalStatus: 'PASS',
});

const results = () => within(screen.getByRole('region', { name: 'Profit-target methods' }));
const cardOf = (method: 'arithmetic' | 'monte_carlo' | 'ladder') =>
  document.querySelector(`[data-method-card="${method}"]`) as HTMLElement;
const box = (name: string) => results().getByRole('checkbox', { name });
const FIELD_ORDER = ['option', 'outcome', 'stock', 'probability', 'time'];
const fieldOrder = (el: HTMLElement) => Array.from(el.querySelectorAll('[data-field]'))
  .map((n) => n.getAttribute('data-field')!)
  .filter((f) => FIELD_ORDER.includes(f));
const slotOrder = (el: HTMLElement) => Array.from(el.querySelectorAll('[data-slot]'))
  .map((n) => n.getAttribute('data-slot'));

beforeEach(() => { localStorage.clear(); jest.clearAllMocks(); });

describe('display-only comparison in the same results area', () => {
  it('shows all three method cards in one results area with a checked comparison control each', () => {
    render(<TradeCard data={card()} contracts={3} />);
    for (const name of ['Arithmetic', 'Monte Carlo', 'Fixed % Ladder']) expect(box(name)).toBeChecked();
    const area = screen.getByRole('region', { name: 'Profit-target methods' });
    for (const m of ['arithmetic', 'monte_carlo', 'ladder'] as const) {
      expect(area).toContainElement(cardOf(m));
      expect(cardOf(m)).toBeVisible();
    }
    expect(area.querySelector('[data-compare-count]')).toHaveAttribute('data-compare-count', '3');
    expect(area).toContainElement(screen.getByRole('region', { name: 'Fixed ladder targets' }));
  });

  it('compares any two, then three, methods side by side', () => {
    render(<TradeCard data={card()} contracts={3} />);
    fireEvent.click(box('Monte Carlo'));
    expect(cardOf('monte_carlo')).not.toBeVisible();
    expect(cardOf('arithmetic')).toBeVisible();
    expect(cardOf('ladder')).toBeVisible();
    expect(document.querySelector('[data-compare-count]')).toHaveAttribute('data-compare-count', '2');
    fireEvent.click(box('Arithmetic'));
    fireEvent.click(box('Monte Carlo'));
    expect(cardOf('arithmetic')).not.toBeVisible();
    expect(cardOf('monte_carlo')).toBeVisible();
    fireEvent.click(box('Arithmetic'));
    for (const m of ['arithmetic', 'monte_carlo', 'ladder'] as const) expect(cardOf(m)).toBeVisible();
    expect(document.querySelector('[data-compare-count]')).toHaveAttribute('data-compare-count', '3');
  });

  it('keeps at least one method open', () => {
    render(<TradeCard data={card()} contracts={3} />);
    fireEvent.click(box('Monte Carlo'));
    fireEvent.click(box('Fixed % Ladder'));
    expect(box('Arithmetic')).toBeChecked();
    expect(box('Arithmetic')).toBeDisabled();
    expect(cardOf('arithmetic')).toBeVisible();
  });

  it('opening and comparing fires no request, no edit and leaves the method choice unchanged', async () => {
    const onEditsChange = jest.fn();
    const onMethodPickChange = jest.fn();
    const pick: MethodPick = { method: 'ladder', rowStockPrice: 200.02, rowOptionPrice: null, stopBasis: 'stock', pickedAt: '2026-09-14T09:00:00.000Z' };
    const fetchSpy = jest.fn();
    const originalFetch = global.fetch;
    global.fetch = fetchSpy as unknown as typeof fetch;
    try {
      render(<TradeCard data={card()} contracts={3} initialMethodPick={pick}
        onEditsChange={onEditsChange} onMethodPickChange={onMethodPickChange} />);
      await act(async () => { await Promise.resolve(); });
      jest.clearAllMocks();
      onEditsChange.mockClear(); onMethodPickChange.mockClear();
      expect(screen.getByRole('radio', { name: 'Ladder' })).toBeChecked();
      fireEvent.click(box('Monte Carlo'));
      fireEvent.click(box('Arithmetic'));
      fireEvent.click(box('Monte Carlo'));
      fireEvent.click(box('Arithmetic'));
      fireEvent.click(screen.getByRole('button', { name: /Fixed % Ladder Plan/ }));
      fireEvent.click(screen.getByRole('button', { name: /Fixed % Ladder Plan/ }));
      fireEvent.click(within(cardOf('arithmetic')).getAllByText('Original target, snap geometry and pricing')[0]);
      await act(async () => { await Promise.resolve(); });
      for (const fn of Object.values(api)) expect(fn).not.toHaveBeenCalled();
      expect(fetchSpy).not.toHaveBeenCalled();
      expect(onEditsChange).not.toHaveBeenCalled();
      expect(onMethodPickChange).not.toHaveBeenCalled();
      expect(screen.getByRole('radio', { name: 'Ladder' })).toBeChecked();
      expect(screen.getByRole('radio', { name: 'Arithmetic' })).not.toBeChecked();
      expect(screen.getByRole('radio', { name: 'Monte Carlo' })).not.toBeChecked();
    } finally {
      global.fetch = originalFetch;
    }
  });
});

describe('consistent stop/target field order', () => {
  it('orders every card basis → stop → targets', () => {
    render(<TradeCard data={card()} contracts={3} />);
    for (const m of ['arithmetic', 'monte_carlo', 'ladder'] as const) {
      expect(slotOrder(cardOf(m)).filter((s) => s !== 'header')).toEqual(['basis', 'stop', 'targets']);
    }
  });

  it('lists target fields in Monte Carlo order on all three methods', () => {
    render(<TradeCard data={card()} contracts={3} />);
    const mcRows = within(cardOf('monte_carlo')).getAllByText(/^T\d+%$/).map((n) => n.closest('[data-target-row]') as HTMLElement);
    expect(mcRows).toHaveLength(2);
    expect(fieldOrder(mcRows[0])).toEqual(FIELD_ORDER);
    const arithRows = within(cardOf('arithmetic')).getAllByRole('listitem');
    expect(arithRows).toHaveLength(2);
    for (const r of arithRows) expect(fieldOrder(r)).toEqual(FIELD_ORDER);
    const ladderRows = Array.from(cardOf('ladder').querySelectorAll('[data-target-row]')) as HTMLElement[];
    expect(ladderRows).toHaveLength(2);
    for (const r of ladderRows) expect(fieldOrder(r)).toEqual(FIELD_ORDER);
  });
});

describe('Arithmetic card', () => {
  it('shows its calculated stop, current-time stop-cost estimate, every target row and the resolved target', () => {
    render(<TradeCard data={card()} contracts={3} />);
    const arith = within(cardOf('arithmetic'));
    const stop = within(cardOf('arithmetic').querySelector('[data-slot="stop"]') as HTMLElement);
    expect(stop.getByText('Calculated stock stop').parentElement).toHaveTextContent('$180.00 · structural');
    expect(stop.getByText('Current-time stop-cost value at stop').parentElement).toHaveTextContent('$1.80/share');
    expect(stop.getByText('Current-time stop-cost loss').parentElement).toHaveTextContent('$2.20/share');
    expect(stop.getByText(/today's days to expiry/)).toBeVisible();
    expect(stop.getByText(/Restored Arithmetic calculation/)).toBeVisible();
    const rows = arith.getAllByRole('listitem');
    expect(within(rows[0]).getByText('2:1 target')).toBeVisible();
    expect(within(rows[1]).getByText('3:1 target')).toBeVisible();
    expect(within(rows[0]).getByText('Resolved stock target (used for valuation)').parentElement).toHaveTextContent('$196.00');
    expect(within(rows[1]).getByText('Resolved stock target (used for valuation)').parentElement).toHaveTextContent('$200.00');
    expect(within(rows[0]).getByText('Option premium').parentElement).toHaveTextContent('$6.50');
    expect(within(rows[0]).getByText('Estimated dollar outcome').parentElement).toHaveTextContent('$750.00');
    expect(within(rows[0]).getByText('Probability before expiry').parentElement).toHaveTextContent('60%');
    expect(within(rows[0]).getByText('Conditional median time').parentElement).toHaveTextContent('~8 calendar days');
    expect(within(rows[1]).getByText('Conditional median time').parentElement).toHaveTextContent('Unavailable — no conditional median');
    expect(within(rows[0]).getByText('Pricing model').parentElement).toHaveTextContent('Delta approximation');
    // Geometry/quality/capped warnings stay visible on the row.
    expect(within(rows[0]).getByText(/Bearish target capped/)).toBeVisible();
  });

  it('puts the original arithmetic target, snap geometry and pricing explanation in an expansion', () => {
    render(<TradeCard data={card()} contracts={3} />);
    const first = within(within(cardOf('arithmetic')).getAllByRole('listitem')[0]);
    const original = first.getByText('Original arithmetic stock target');
    expect(original).not.toBeVisible();
    expect(original.parentElement).toHaveTextContent('$195.00');
    for (const label of ['Target source', 'Quality', 'Nearest structural level', 'Distance', 'Tolerance']) {
      expect(first.getByText(label)).not.toBeVisible();
    }
    expect(first.getByText(/test_quality_reason/)).not.toBeVisible();
    fireEvent.click(first.getByText('Original target, snap geometry and pricing'));
    expect(original).toBeVisible();
    expect(first.getByText(/echoed calculation premium/)).toBeVisible();
  });

  it('keeps the matched-premium rule for its stop-cost estimate', () => {
    const p = plan();
    p.stop.stopCost = { ...p.stop.stopCost!, stopPrice: 179 };
    render(<TradeCard data={card({ exitPlan: p })} contracts={3} />);
    const stop = within(cardOf('arithmetic').querySelector('[data-slot="stop"]') as HTMLElement);
    expect(stop.getByText('Current-time stop-cost value at stop').parentElement).toHaveTextContent(/^Current-time stop-cost value at stopUnavailable/);
    expect(stop.queryByText('$1.80/share')).not.toBeInTheDocument();
  });

  it('is not a horizontally scrolling table: targets wrap as rows', () => {
    render(<TradeCard data={card()} contracts={3} />);
    expect(within(cardOf('arithmetic')).queryByRole('table')).not.toBeInTheDocument();
    expect(within(cardOf('arithmetic')).getByRole('list', { name: 'Arithmetic target comparison' })).toBeVisible();
  });

  it('states not-yet-computed stop rows without inventing values', () => {
    render(<TradeCard data={card({ exitPlan: undefined })} contracts={3} />);
    const stop = within(cardOf('arithmetic').querySelector('[data-slot="stop"]') as HTMLElement);
    expect(stop.getByText('Calculated stock stop').parentElement).toHaveTextContent('Not yet computed');
    expect(stop.getByText('Current-time stop-cost value at stop').parentElement).toHaveTextContent('Not yet computed');
  });
});

describe('Ladder card', () => {
  it('shows the shared Exit Plan stops with explicit sources and labels only its own stock-stop valuation as not calculated', () => {
    render(<TradeCard data={card()} contracts={3} />);
    const ladder = cardOf('ladder');
    const stop = within(ladder.querySelector('[data-slot="stop"]') as HTMLElement);
    expect(stop.getByText('Exit Plan stock invalidation').parentElement).toHaveTextContent('$179.64 stock');
    expect(stop.getByText(/Source: shared Exit Plan Invalidation/)).toBeVisible();
    // Premium stop $2.00 loss from the $5.00 scan-mid basis → $3.00 option threshold.
    expect(stop.getByText('Exit Plan premium-stop option threshold').parentElement).toHaveTextContent('$3.00/share');
    expect(stop.getByText(/Source: shared Exit Plan Premium stop/)).toBeVisible();
    expect(within(ladder).getAllByText(/not calculated/i)).toHaveLength(2);
    expect(stop.getByText('Ladder option value at stock stop').parentElement).toHaveTextContent(/not calculated/i);
    expect(stop.getByText('Ladder loss at stock stop').parentElement).toHaveTextContent(/not calculated/i);
    // 2 stop rows + probability and time on each of the two targets.
    expect(within(ladder).getAllByText('Not supplied')).toHaveLength(6);
    expect(within(cardOf('arithmetic')).queryByText('Not supplied')).not.toBeInTheDocument();
    expect(within(cardOf('monte_carlo')).queryByText('Not supplied')).not.toBeInTheDocument();
    expect(within(cardOf('arithmetic')).queryByText(/not calculated/i)).not.toBeInTheDocument();
  });

  it('keeps per-share, full-position and rung bases distinct and never adds outcomes together', () => {
    render(<TradeCard data={card()} contracts={3} />);
    const ladder = within(cardOf('ladder'));
    const [tp1, tp2] = Array.from(cardOf('ladder').querySelectorAll('[data-target-row]')) as HTMLElement[];
    expect(within(tp1).getByText('Est. option (per share)').parentElement).toHaveTextContent('$8.00');
    expect(within(tp1).getByText('Full-position outcome (3 contracts × 100 shares)').parentElement).toHaveTextContent('$900.00');
    expect(within(tp1).getByText('Rung outcome (1 contracts × 100 shares)').parentElement).toHaveTextContent('$300.00');
    expect(within(tp2).getByText('Rung outcome (allocation unavailable)').parentElement).toHaveTextContent('Unavailable');
    expect(ladder.getByText(/do not add alternative outcomes/)).toBeVisible();
    expect(ladder.getByText('R/R risk: full premium (no protective stop order).')).toBeVisible();
    expect(within(tp1).getByText('R:R').parentElement).toHaveTextContent('0.6x');
    expect(within(tp1).getByRole('button', { name: 'Edit target stock price for TP1' })).toBeVisible();
  });
});

describe('stale and restored results stay labelled through comparison', () => {
  it('keeps restored Arithmetic and guarded restored race inputs after toggling comparison', () => {
    render(<TradeCard data={card()} contracts={3} />);
    fireEvent.click(box('Arithmetic'));
    fireEvent.click(box('Arithmetic'));
    const stop = within(cardOf('arithmetic').querySelector('[data-slot="stop"]') as HTMLElement);
    expect(stop.getByText(/Restored Arithmetic calculation/)).toBeVisible();
    expect(within(cardOf('monte_carlo')).getAllByText('Unavailable — run or re-run estimate to confirm barriers')).toHaveLength(2);
    expect(within(cardOf('monte_carlo')).getAllByText('Option premium')).toHaveLength(2);
  });
});
