/** #584 — whole-card flows that the per-ticket suites only cover one section at
 *  a time: one quantity or entry edit reaching every method on its own basis,
 *  stale to re-run, a contract switch, and every disclosure default on a fully
 *  computed card. Every transport is a jest mock. */
import '@testing-library/jest-dom';
import * as fs from 'fs';
import * as path from 'path';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { api } from '@/lib/api';
import { TradeCard } from '@/components/organisms/TradeCard';
import type { BarrierRace, ExitPlan, ExitPlanTargetRow, FirstPassageContext, FirstPassageEstimate, MethodPick, TradeCardData } from '@/types/domain';

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

const row = (ratio: number, contractPrice: number): ExitPlanTargetRow => ({
  rrRatio: ratio, arithmeticPrice: 195, price: 196, tpSource: 'arithmetic',
  structuralPrice: null, contractPrice, rrModel: 'Delta approximation',
  probability: 0.6, expectedDays: 8, qualityGood: true, qualityReasons: [], distanceDollar: null, toleranceDollar: 1.5,
});
const plan = (): ExitPlan => ({
  stop: { price: 180, source: 'structural', contractPrice: 2.2, rrModel: 'Heston repriced',
    structuralSource: 'order_block', structuralConfidence: 80, structuralPrice: 180,
    atrFloorPrice: 175, distanceDollar: 5,
    stopCost: { premium: 4, stopPrice: 180, valueAtStop: 1.8, lossDollar: 2.2,
      fraction: 0.55, passMaxFraction: 0.6, status: 'PASS', basis: 'bs_today' } },
  targets: [row(2, 6.5), row(3, 8.25)],
  atr: 3.5, computedAt: '2026-10-13T12:00:00Z',
});
const raceOf = (premiumStopPrice: number): BarrierRace => ({
  outcomes: [0.25, 0.5].map((targetPct, i) => ({
    targetPct, targetOptionPrice: [6.5, 7.8][i],
    pTargetFirst: 0.27, pStockStopFirst: 0.01, pPremiumStopFirst: 0.68, pNeither: 0.04,
    daysTarget: 7 + i, daysStockStop: 20, daysPremiumStop: 12, daysAnyPathReachedStop: 18,
    weightTargetFirst: 0.27, weightStockStopFirst: 0.01, weightPremiumStopFirst: 0.68, weightNeither: 0.04,
    terminalMean: 4, rewardDollar: [1.3, 2.6][i], repriceDaysStockStop: 18,
    stopRepricedValue: 1.1, riskStockStop: 4.1, riskPremiumStop: 3.12,
    rrStockStop: 0.32, rrPremiumStop: 0.4, edgePerContract: -120,
  })),
  premiumStopPrice, premiumStopPct: 0.6, stockStopPrice: 180, premiumUsed: 5.2, ivSolved: true, nPaths: 2000,
});
const response = (premiumStopPrice: number): FirstPassageEstimate => ({
  targets: [
    { pct: 0.25, optionPrice: 6.5, stockPrice: 194.1, probability: 0.61, expectedDays: 7 },
    { pct: 0.5, optionPrice: 7.8, stockPrice: 198.2, probability: 0.42, expectedDays: 11 },
  ],
  invalidation: { probability: 0.3, expectedDays: 18 },
  race: raceOf(premiumStopPrice),
});
const context: FirstPassageContext = { premium: 5.2, delta: 0.45, targetPct: { t1: 0.25, t2: 0.5, t3: 0.75 } };

const card = (over: Partial<TradeCardData> = {}, exit: Partial<TradeCardData['exit']> = {}): TradeCardData => ({
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
    ],
    exitPlan: plan(),
    ...exit,
  },
  rrRatio: 2.5, rrModel: 'Heston repriced', finalStatus: 'PASS',
  ...over,
});

const cardOf = (method: 'arithmetic' | 'monte_carlo' | 'ladder') =>
  within(document.querySelector(`[data-method-card="${method}"]`) as HTMLElement);
const fieldValues = (method: 'arithmetic' | 'monte_carlo' | 'ladder', field: string) =>
  Array.from((document.querySelector(`[data-method-card="${method}"]`) as HTMLElement).querySelectorAll(`[data-target-row] [data-field="${field}"]`))
    .map((n) => n.textContent);
const raceCount = () => screen.queryAllByTestId('segment-Target first').length;

async function typeInto(label: string, value: string) {
  fireEvent.click(screen.getByLabelText(`Edit ${label}`));
  const input = screen.getByRole('textbox', { name: `Edit ${label}` });
  await act(async () => {
    fireEvent.change(input, { target: { value } });
    fireEvent.blur(input);
  });
}
const callCounts = () => [
  (api.getExitPlan as jest.Mock).mock.calls.length,
  (api.getFirstPassageEstimate as jest.Mock).mock.calls.length,
];

async function runEstimate() {
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i })); });
  await waitFor(() => expect(raceCount()).toBe(2));
}

beforeEach(() => {
  localStorage.clear();
  jest.clearAllMocks();
  (api.getStockQuote as jest.Mock).mockResolvedValue({ symbol: 'AAPL', price: 186.1 });
  (api.getContractQuote as jest.Mock).mockResolvedValue({ price: 5.2, delta: 0.45, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100 });
  (api.getStructuralStop as jest.Mock).mockResolvedValue({ available: true, price: 180, source: 'order_block', confidence: 75, distancePct: 3.3 });
  (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue(response(2.08));
});

describe('comparison layout', () => {
  /* jsdom applies no CSS. The browser check is capture-final-verification.cjs
     (`squeezedTargetRows`); this pins the rule that fixes it. A Ladder row has
     a source note and a pricing badge beside its values. In a comparison-width
     card those two left `.targetMain` (flex: 1, basis 0) no width at all. */
  it('gives a target row\'s values a full line inside the comparison grid', () => {
    const css = fs.readFileSync(path.join(__dirname, '..', 'TradeCard.module.css'), 'utf8');
    const rule = (selector: string) => {
      const at = css.indexOf(`${selector} {`);
      return at < 0 ? '' : css.slice(at, css.indexOf('}', at));
    };
    expect(rule('.methodGrid .targetRow')).toMatch(/flex-wrap:\s*wrap/);
    expect(rule('.methodGrid .targetMain')).toMatch(/flex:\s*1 1 100%/);
  });
});

describe('disclosure defaults on a fully computed card', () => {
  it('every explanation is closed, and the values and warnings it explains stay outside', async () => {
    const data = card({
      alternatives: [{
        symbol: 'AAPL', strike: 195, expiry: '2026-05-15', right: 'C', dte: 24, mid: 3, delta: 0.3, theta: -0.05, ivRank: 40,
        score: 60, contractConfidence: 'CAUTION',
        contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
        rrRatio: 2, rrModel: 'Delta approximation', reason: 'Cheaper premium.',
      }],
    }, { invalidation: null as unknown as number });
    render(<TradeCard data={data} />);
    await runEstimate();
    const details = Array.from(document.querySelectorAll('details'));
    expect(details.length).toBeGreaterThanOrEqual(5);
    expect(details.filter((d) => d.open).map((d) => d.querySelector('summary')?.textContent)).toEqual([]);
    expect(screen.getByRole('button', { name: /Stock & contract scores/ })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByRole('button', { name: /ALTERNATIVES/ })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByRole('button', { name: /Fixed % Ladder Plan/ })).toHaveAttribute('aria-expanded', 'true');
    const warning = screen.getByText(/Invalidation stop required — Send to broker/);
    expect(warning.closest('details')).toBeNull();
    expect(screen.getByRole('checkbox', { name: 'Arithmetic' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Monte Carlo' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Fixed % Ladder' })).toBeChecked();
  });
});

describe('one edit, every method, each on its own basis', () => {
  async function computedCard() {
    render(<TradeCard data={card()} contracts={3} />);
    await runEstimate();
  }

  it('a quantity change rescales every total and no per-contract figure, with no new calculation', async () => {
    await computedCard();
    const before = callCounts();
    expect(fieldValues('arithmetic', 'outcome')[0]).toContain('$750.00');   // (6.50 − 4.00) × 3 × 100
    expect(fieldValues('monte_carlo', 'outcome')[0]).toContain('$390.00');  // (6.50 − 5.20) × 3 × 100
    expect(fieldValues('ladder', 'outcome')[0]).toContain('$900.00');       // (8.00 − 5.00) × 3 × 100
    expect(fieldValues('ladder', 'outcome-rung')[0]).toContain('$300.00');  // 1 contract

    await typeInto('Contracts', '5');

    expect(fieldValues('arithmetic', 'outcome')[0]).toContain('$1250.00');
    expect(fieldValues('monte_carlo', 'outcome')[0]).toContain('$650.00');
    expect(fieldValues('ladder', 'outcome')[0]).toContain('$1500.00');
    expect(fieldValues('ladder', 'outcome-rung')[0]).toContain('$300.00');
    expect(fieldValues('ladder', 'outcome')[0]).toContain('5 contracts');
    expect(screen.getByText('Loss for 5 entered contracts')).toBeInTheDocument();
    expect(screen.getAllByText(/-\$120\.00/).length).toBeGreaterThan(0);     // race edge stays per contract
    expect(raceCount()).toBe(2);
    expect(callCounts()).toEqual(before);
  });

  it('an entry edit moves only the Ladder: calculation premiums are separate bases', async () => {
    await computedCard();
    const before = callCounts();
    expect(fieldValues('ladder', 'rr')[0]).toContain('0.6x');   // the backend's ratio, at the plan's entry

    await typeInto('Limit', '4');

    expect(fieldValues('ladder', 'outcome')[0]).toContain('$1200.00');      // (8.00 − 4.00) × 3 × 100
    expect(fieldValues('ladder', 'rr')[0]).toContain('1.0x');               // (8 − 4) / 4, full premium
    expect(fieldValues('arithmetic', 'outcome')[0]).toContain('$750.00');
    expect(fieldValues('monte_carlo', 'outcome')[0]).toContain('$390.00');
    expect(cardOf('arithmetic').getByText('Calculation premium used').parentElement).toHaveTextContent('$4.00/share');
    expect(cardOf('monte_carlo').getByText('Editable order entry (separate basis)').parentElement).toHaveTextContent('$4.00/share');
    expect(cardOf('ladder').getByText('Editable order entry (outcome and R:R basis)').parentElement).toHaveTextContent('$4.00/share');
    expect(raceCount()).toBe(2);
    expect(callCounts()).toEqual(before);
  });
});

describe('stale to re-run', () => {
  it('a barrier edit clears only the race; a re-run brings it back without choosing or applying anything', async () => {
    const onMethodPickChange = jest.fn<void, [MethodPick | null]>();
    render(<TradeCard data={card()} contracts={3} onMethodPickChange={onMethodPickChange} />);
    await runEstimate();
    expect(screen.getAllByRole('button', { name: /Use Barrier Race/ })).toHaveLength(2);
    onMethodPickChange.mockClear();

    await typeInto('Premium stop', '2.50');

    expect(screen.getByText(/Barriers changed — re-run the estimate/)).toBeInTheDocument();
    expect(raceCount()).toBe(0);
    expect(screen.queryByRole('button', { name: /Use Barrier Race/ })).not.toBeInTheDocument();
    // Independently valid results stay: Arithmetic, Ladder and the target-touch rows.
    expect(fieldValues('arithmetic', 'outcome')[0]).toContain('$750.00');
    expect(fieldValues('ladder', 'outcome')[0]).toContain('$900.00');
    expect(fieldValues('monte_carlo', 'probability')[0]).toContain('61%');

    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue(response(2.7));
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i })); });
    await waitFor(() => expect(raceCount()).toBe(2));

    expect(api.getFirstPassageEstimate).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(/Barriers changed — re-run the estimate/)).not.toBeInTheDocument();
    expect(cardOf('monte_carlo').getByText('Companion race premium exit-value barrier').parentElement).toHaveTextContent('$2.70/share');
    expect(screen.getByLabelText('Edit Premium stop')).toHaveTextContent('2.50');   // the setting is what was typed
    expect(onMethodPickChange).not.toHaveBeenCalledWith(expect.objectContaining({ method: 'barrier_race' }));
  });
});

describe('a contract switch', () => {
  it('borrows nothing from the previous contract and keeps which methods are compared', async () => {
    const { rerender } = render(<TradeCard data={card()} contracts={3} />);
    await runEstimate();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Fixed % Ladder' }));
    const before = callCounts();

    const next = card({
      symbol: 'MSFT', company: 'Microsoft', contract: 'MSFT 400C 05/15',
      contractDetails: { strike: 400, expiry: '2026-05-15', right: 'C', mid: 9, delta: 0.45, theta: -0.1, ivRank: 40, dte: 24 },
    }, { exitPlan: undefined });
    await act(async () => { rerender(<TradeCard data={next} contracts={3} />); });

    expect(raceCount()).toBe(0);
    expect(screen.queryByRole('button', { name: /Use Barrier Race/ })).not.toBeInTheDocument();
    expect(fieldValues('arithmetic', 'outcome')).toEqual([]);
    expect(fieldValues('monte_carlo', 'outcome')).toEqual([]);
    expect(cardOf('arithmetic').getByText('Calculated stock stop').parentElement).toHaveTextContent('Not yet computed');
    expect(screen.getByRole('checkbox', { name: 'Fixed % Ladder' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Arithmetic' })).toBeChecked();
    expect(callCounts()).toEqual(before);
  });
});

describe('a restored contract', () => {
  it('shows restored results as restored, with no calculation on mount and the race withheld', async () => {
    render(<TradeCard data={card({}, { firstPassage: response(2.08), firstPassageContext: context })} contracts={3} />);
    await act(async () => { await Promise.resolve(); });
    expect(callCounts()).toEqual([0, 0]);
    expect(fieldValues('arithmetic', 'outcome')[0]).toContain('$750.00');
    expect(fieldValues('monte_carlo', 'probability')[0]).toContain('61%');
    expect(screen.getAllByText(/Restored Arithmetic calculation/).length).toBeGreaterThan(0);
    expect(raceCount()).toBe(0);
    expect(screen.queryByRole('button', { name: /Use Barrier Race/ })).not.toBeInTheDocument();
  });
});
