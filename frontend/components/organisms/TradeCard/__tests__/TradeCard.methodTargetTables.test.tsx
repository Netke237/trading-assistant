/** TC-ALIGN-04 (#607): Arithmetic and Ladder use Monte Carlo's stop context
 *  (four slots) and its target-table column order, with method-specific
 *  geometry, allocation and pricing detail in default-closed disclosures that
 *  stay mounted. Viewing, comparing or opening a disclosure never calculates. */
import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { api } from '@/lib/api';
import { TradeCard } from '@/components/organisms/TradeCard';
import type { ExitPlan, ExitPlanTargetRow, FirstPassageContext, FirstPassageEstimate, TradeCardData } from '@/types/domain';

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
  targets: [row(2), row(3, { arithmeticPrice: 199, price: 200, contractPrice: 8.25, probability: 0.4, expectedDays: null, qualityReasons: [] })],
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
      { id: 'tp1', stockPrice: 200.02, targetPrice: 200.02, estimatedOptionPrice: 8, contractsToSell: 1, status: 'PENDING', rrContribution: 0.6, pricingMethod: 'Delta approximation' },
      { id: 'tp2', stockPrice: 205, targetPrice: 205, estimatedOptionPrice: 10, status: 'PENDING', rrContribution: 1.0 },
    ],
    exitPlan: plan(),
    firstPassage: estimate(),
    firstPassageContext: context,
    ...o,
  },
  rrRatio: 2.5, rrModel: 'Heston repriced', finalStatus: 'PASS',
});

type Method = 'arithmetic' | 'monte_carlo' | 'ladder';
const cardEl = (m: Method) => document.querySelector(`[data-method-card="${m}"]`) as HTMLElement;
const slot = (m: Method, name: string) => cardEl(m).querySelector(`[data-slot="${name}"]`) as HTMLElement;
const box = (name: string) => screen.getByRole('checkbox', { name });
const openAll = () => { fireEvent.click(box('Arithmetic')); fireEvent.click(box('Ladder')); };
const MC_ORDER = ['stock', 'option', 'probability', 'time', 'outcome'];
const cells = (r: HTMLElement) => Array.from(r.querySelectorAll('th,td')).map((c) => c.textContent);
const fieldOrder = (r: HTMLElement) => Array.from(r.querySelectorAll('[data-field]'))
  .map((n) => n.getAttribute('data-field')!).filter((f) => MC_ORDER.includes(f));
const stopFields = (m: Method) => Array.from(slot(m, 'stop').querySelectorAll('[data-field]'))
  .map((n) => n.getAttribute('data-field'));
const kv = (m: Method, label: string) => within(slot(m, 'stop')).getByText(label).parentElement!;

beforeEach(() => { localStorage.clear(); jest.clearAllMocks(); });

describe('Arithmetic in Monte Carlo order', () => {
  it('lists every returned target in one table with the Monte Carlo column order and the resolved target', () => {
    render(<TradeCard data={card()} contracts={3} />);
    openAll();
    const table = within(cardEl('arithmetic')).getByRole('table', { name: 'Arithmetic targets' });
    const headers = within(table).getAllByRole('columnheader').map((h) => h.textContent ?? '');
    ['Target', 'Stock price', 'Option value', 'Probability', 'Conditional time'].forEach((prefix, i) =>
      expect(headers[i].startsWith(prefix)).toBe(true));
    expect(headers[1]).toMatch(/resolved/i);
    expect(headers[5]).toMatch(/outcome/i);
    const rows = Array.from(table.querySelectorAll('tbody tr')) as HTMLElement[];
    expect(rows).toHaveLength(2);
    for (const r of rows) expect(fieldOrder(r)).toEqual(MC_ORDER);
    // Resolved (snapped) targets used for valuation, not the original $195/$199.
    expect(cells(rows[0]).slice(1)).toEqual(['$196.00', '$6.50', '60%', '~8d', '$750.00']);
    expect(cells(rows[1]).slice(1)).toEqual(['$200.00', '$8.25', '40%', 'Unavailable — no conditional median', '$1275.00']);
    // The capped warning stays with its row, outside any disclosure.
    const capped = within(rows[0]).getByText(/Bearish target capped/);
    expect(capped).toBeVisible();
    expect(capped.closest('details')).toBeNull();
  });

  it('has a four-slot stop context with an explicit current-time Black-Scholes basis', () => {
    render(<TradeCard data={card()} contracts={3} />);
    openAll();
    expect(stopFields('arithmetic')).toEqual(['stock-stop', 'option-stop', 'stop-value', 'stop-loss']);
    expect(stopFields('monte_carlo')).toHaveLength(4);
    expect(kv('arithmetic', 'Calculated stock stop')).toHaveTextContent('$180.00 · structural');
    expect(kv('arithmetic', 'Option-price threshold (shared Exit Plan premium stop)')).toHaveTextContent('$3.00/share');
    expect(kv('arithmetic', 'Option value at stock stop (current time)')).toHaveTextContent('$1.80/share');
    expect(kv('arithmetic', 'Loss at stock stop (current time, per contract)')).toHaveTextContent('$220.00/contract');
    expect(within(slot('arithmetic', 'stop')).getByText('Black–Scholes at current expiry; differs from barrier-time race pricing. Exit Plan unchanged.')).toBeVisible();
    const basis = within(cardEl('arithmetic')).getByText(/Black-Scholes today/);
    expect(basis).not.toBeVisible();
    expect(basis).toHaveTextContent(/today's days to expiry \(no elapsed time\).*calculation's echoed premium, per share.*barrier-time/);
    fireEvent.click(within(cardEl('arithmetic')).getByText('Arithmetic basis, inputs & provenance'));
    expect(basis).toBeVisible();
  });

  it.each<[number, string, string | null]>([
    [2.2, '$220.00/contract', '$2.20/share'],
    [0, '$0.00/contract', '$0.00/share'],
    [-1.25, '-$125.00/contract', '$-1.25/share'],
    [Number.NaN, 'Unavailable — no stop-cost estimate on the calculation premium basis', null],
  ])('retains the current-time source and units for returned loss %s', (loss, headline, perShare) => {
    const computed = plan();
    computed.stop.stopCost = { ...computed.stop.stopCost!, lossDollar: loss,
      valueAtStop: 4 - loss, fraction: loss / 4 };
    render(<TradeCard data={card({ exitPlan: computed })} contracts={3} />);
    fireEvent.click(box('Arithmetic'));
    expect(kv('arithmetic', 'Loss at stock stop (current time, per contract)')).toHaveTextContent(headline);
    const arith = within(cardEl('arithmetic'));
    if (perShare == null) {
      expect(arith.queryByText('Current-time stop loss per share')).not.toBeInTheDocument();
    } else {
      const detail = arith.getByText('Current-time stop loss per share').parentElement!;
      expect(detail).toHaveTextContent(perShare);
      expect(detail).not.toBeVisible();
      fireEvent.click(arith.getByText('Arithmetic basis, inputs & provenance'));
      expect(detail).toBeVisible();
    }
  });

  it('keeps original targets, snap geometry and model detail in a closed, mounted disclosure', () => {
    render(<TradeCard data={card()} contracts={3} />);
    openAll();
    const arith = within(cardEl('arithmetic'));
    const details = arith.getByText('Original targets, snap geometry & pricing model').closest('details') as HTMLDetailsElement;
    expect(details.open).toBe(false);
    const inside = within(details);
    for (const text of ['$195.00', '$199.00', 'Within tolerance — snapped onto the structural level.', 'test_quality_reason']) {
      expect(inside.getAllByText(new RegExp(text.replace(/[.$]/g, '\\$&')))[0]).not.toBeVisible();
    }
    expect(inside.getAllByText('Delta approximation')[0]).not.toBeVisible();
    // Not shown as main-path row text any more.
    const table = arith.getByRole('table', { name: 'Arithmetic targets' });
    expect(within(table).queryByText('Delta approximation')).not.toBeInTheDocument();
    expect(within(table).queryByText(/Within tolerance/)).not.toBeInTheDocument();
    fireEvent.click(arith.getByText('Original targets, snap geometry & pricing model'));
    expect(inside.getAllByText('$195.00')[0]).toBeVisible();
  });

  it('moves the Compute action before the stop context so the table leads the targets slot', () => {
    render(<TradeCard data={card()} contracts={3} />);
    openAll();
    const compute = within(cardEl('arithmetic')).getByRole('button', { name: 'Compute Arithmetic Plan' });
    expect(slot('arithmetic', 'basis')).toContainElement(compute);
    for (const m of ['monte_carlo', 'arithmetic', 'ladder'] as const) {
      expect(slot(m, 'targets').firstElementChild?.querySelector('table') ?? slot(m, 'targets').firstElementChild)
        .toBe(slot(m, 'targets').querySelector('table'));
    }
  });
});

describe('Ladder in Monte Carlo order', () => {
  it('lists every ladder target in one table; probability and time are Not supplied', () => {
    render(<TradeCard data={card()} contracts={3} />);
    openAll();
    const region = screen.getByRole('region', { name: 'Fixed ladder targets' });
    const table = within(region).getByRole('table', { name: 'Ladder targets' });
    const headers = within(table).getAllByRole('columnheader').map((h) => h.textContent ?? '');
    ['Target', 'Stock price', 'Option value', 'Probability', 'Conditional time'].forEach((prefix, i) =>
      expect(headers[i].startsWith(prefix)).toBe(true));
    expect(headers[5]).toBe('Full-position outcome (3 contracts × 100 shares)');
    expect(headers[6]).toMatch(/^Rung outcome/);
    const rows = Array.from(table.querySelectorAll('tbody tr')) as HTMLElement[];
    expect(rows).toHaveLength(2);
    for (const r of rows) {
      expect(fieldOrder(r)).toEqual(MC_ORDER);
      expect(r.querySelector('[data-field="probability"]')).toHaveTextContent('Not supplied');
      expect(r.querySelector('[data-field="time"]')).toHaveTextContent('Not supplied');
    }
    expect(rows[0].querySelector('[data-field="stock"]')).toHaveTextContent('$200.02');
    expect(rows[0].querySelector('[data-field="option"]')).toHaveTextContent('$8.00');
    expect(rows[0].querySelector('[data-field="outcome"]')).toHaveTextContent('$900.00');
    expect(rows[0].querySelector('[data-field="outcome-rung"]')).toHaveTextContent('$300.00');
    expect(rows[1].querySelector('[data-field="outcome"]')).toHaveTextContent('$1500.00');
    expect(rows[1].querySelector('[data-field="outcome-rung"]')).toHaveTextContent(/Unavailable.*allocation unavailable/);
    const scaleOut = within(rows[0]).getByText('Scale out: sell 1 of 3');
    expect(scaleOut).toBeVisible();
    expect(within(region).getByText(/do not add alternative outcomes/)).toBeVisible();
  });

  it('shows the shared Exit Plan stops with source and only the Ladder valuation as not calculated', () => {
    render(<TradeCard data={card()} contracts={3} />);
    openAll();
    expect(stopFields('ladder')).toEqual(['stock-stop', 'option-stop', 'stop-value', 'stop-loss']);
    expect(kv('ladder', 'Exit Plan stock invalidation')).toHaveTextContent('$179.64 stock');
    expect(kv('ladder', 'Exit Plan premium-stop option threshold')).toHaveTextContent('$3.00/share');
    expect(within(slot('ladder', 'stop')).getByText(/Source: shared Exit Plan Invalidation/)).toBeVisible();
    expect(within(slot('ladder', 'stop')).getByText(/Source: shared Exit Plan Premium stop/)).toBeVisible();
    expect(kv('ladder', 'Ladder option value at stock stop')).toHaveTextContent(/not calculated/i);
    expect(kv('ladder', 'Ladder loss at stock stop')).toHaveTextContent(/not calculated/i);
    expect(within(cardEl('ladder')).getAllByText(/not calculated/i)).toHaveLength(2);
    // Stock-stop probability/time stay reachable, in the closed Ladder disclosure.
    const stopProb = within(cardEl('ladder')).getByText('Stock-stop probability');
    expect(stopProb.closest('details')).not.toBeNull();
    expect(stopProb).not.toBeVisible();
  });

  it('keeps full-premium R:R, allocations and pricing labels in a closed, mounted disclosure', () => {
    render(<TradeCard data={card()} contracts={3} />);
    openAll();
    const ladder = within(cardEl('ladder'));
    const details = ladder.getByText('Ladder R:R, allocation & pricing').closest('details') as HTMLDetailsElement;
    expect(details.open).toBe(false);
    const inside = within(details);
    const rrTable = inside.getByRole('table', { name: 'Ladder R:R and allocation' });
    const rows = Array.from(rrTable.querySelectorAll('tbody tr')) as HTMLElement[];
    expect(rows.map(cells)).toEqual([
      ['TP1', '0.6x', '1', 'Scan/restored plan target and stored option estimate', 'Delta approximation'],
      ['TP2', '1.0x', 'Unavailable', 'Scan/restored plan target and stored option estimate', '—'],
    ]);
    expect(rrTable).not.toBeVisible();
    expect(ladder.getByText('R/R risk: full premium (no protective stop order).')).toBeVisible();
  });

  it('editing a target still calls its handler and updates the outcome and R:R without a calculation', () => {
    const onEditsChange = jest.fn();
    render(<TradeCard data={card()} contracts={3} onEditsChange={onEditsChange} />);
    openAll();
    const table = screen.getByRole('table', { name: 'Ladder targets' });
    fireEvent.click(within(table).getByRole('button', { name: 'Edit target stock price for TP1' }));
    const input = within(table).getByRole('spinbutton', { name: 'Edit target stock price for TP1' });
    fireEvent.change(input, { target: { value: '201' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onEditsChange).toHaveBeenCalledWith(expect.objectContaining({ targets: [201, 205] }), expect.anything());
    const first = table.querySelector('tbody tr') as HTMLElement;
    expect(within(first).getByText('edited')).toBeVisible();
    expect(first.querySelector('[data-field="stock"]')).toHaveTextContent('$201.00');
    // Existing local approximation: 5.00 entry + 0.5 × |201 − 185.2| = 12.90.
    expect(first.querySelector('[data-field="option"]')).toHaveTextContent('$12.90');
    expect(first.querySelector('[data-field="outcome"]')).toHaveTextContent('$2370.00');
    const rr = within(cardEl('ladder')).getByRole('table', { name: 'Ladder R:R and allocation' });
    expect(cells(rr.querySelector('tbody tr') as HTMLElement)[3]).toBe('Edited target: local stock-move approximation');
    for (const fn of Object.values(api)) expect(fn).not.toHaveBeenCalled();
  });
});

describe('two and three method comparison', () => {
  it('opens two then three cards with aligned slots and runs nothing', async () => {
    const fetchSpy = jest.fn();
    const originalFetch = global.fetch;
    global.fetch = fetchSpy as unknown as typeof fetch;
    try {
      render(<TradeCard data={card()} contracts={3} />);
      fireEvent.click(box('Arithmetic'));
      for (const m of ['monte_carlo', 'arithmetic'] as const) {
        expect(cardEl(m)).toBeVisible();
        expect(stopFields(m)).toHaveLength(4);
      }
      fireEvent.click(box('Ladder'));
      fireEvent.click(within(cardEl('arithmetic')).getByText('Original targets, snap geometry & pricing model'));
      fireEvent.click(within(cardEl('ladder')).getByText('Ladder R:R, allocation & pricing'));
      await act(async () => { await Promise.resolve(); });
      expect(cardEl('ladder')).toBeVisible();
      for (const m of ['monte_carlo', 'arithmetic', 'ladder'] as const) {
        expect(within(slot(m, 'targets')).getAllByRole('table')[0]).toBeVisible();
      }
      for (const fn of Object.values(api)) expect(fn).not.toHaveBeenCalled();
      expect(fetchSpy).not.toHaveBeenCalled();
    } finally {
      global.fetch = originalFetch;
    }
  });
});
