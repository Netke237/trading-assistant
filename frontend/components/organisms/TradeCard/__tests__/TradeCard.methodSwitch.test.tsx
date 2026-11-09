/** #610 acceptance fixes G6–G8 (presentation only): the segmented method
 *  switch, the compact Monte Carlo inputs and pre-run state, and readable
 *  target tables. Switching or comparing never calculates, never changes the
 *  recorded method and never edits a field; every transport is a jest mock. */
import '@testing-library/jest-dom';
import { readFileSync } from 'fs';
import { join } from 'path';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { api } from '@/lib/api';
import { TradeCard } from '@/components/organisms/TradeCard';
import type { ExitPlan, FirstPassageContext, FirstPassageEstimate, MethodPick, TradeCardData } from '@/types/domain';

// Echo the class keys so the primary-button class is observable.
jest.mock('@/components/organisms/TradeCard/TradeCard.module.css', () =>
  new Proxy({}, { get: (_t, k) => (k === '__esModule' ? false : k) }));
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

const plan = (): ExitPlan => ({
  stop: { price: 180, source: 'structural', contractPrice: 2.2, rrModel: 'Heston repriced',
    structuralSource: 'order_block', structuralConfidence: 80, structuralPrice: 180,
    atrFloorPrice: 175, distanceDollar: 5 },
  targets: [
    { rrRatio: 2, arithmeticPrice: 195, price: 196, tpSource: 'structural_snap', structuralPrice: 196,
      contractPrice: 6.5, rrModel: 'Delta approximation', probability: 0.6, expectedDays: 8,
      qualityGood: true, qualityReasons: [], distanceDollar: 1, toleranceDollar: 1.5 },
  ],
  atr: 3.5, computedAt: '2026-10-13T12:00:00Z',
});
const estimate = (): FirstPassageEstimate => ({
  targets: [
    { pct: 0.25, optionPrice: 5, stockPrice: 195, probability: 0.6, expectedDays: 7.4 },
    { pct: 0.5, optionPrice: 6, stockPrice: 199, probability: 0.3, expectedDays: null },
  ],
  invalidation: { probability: 0.3, expectedDays: 4 },
});
const context: FirstPassageContext = { premium: 4, delta: 0.45, targetPct: { t1: 0.25, t2: 0.5, t3: 0.75 } };

const card = (exit: Partial<TradeCardData['exit']> = {}): TradeCardData => ({
  symbol: 'AAPL', company: 'Apple Inc.', price: 185.2, direction: 'Bullish', status: 'PASS',
  stockScore: 82, stockConfidence: 'PASS',
  stockBreakdown: { trend: 85, pullback: 78, trigger: 72, event: 90, volatility: 65 },
  contract: 'AAPL 190C 05/15', contractScore: 70, contractConfidence: 'PASS',
  contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
  contractDetails: { strike: 190, expiry: '2026-05-15', right: 'C', mid: 5, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
  entry: { limit: 5, maxFill: 5.2, orderType: 'Limit' },
  exit: {
    invalidation: 179.64, premiumStop: 2, timeStopDays: 10, target: 200.02, rrRiskBasis: 'full_premium',
    targets: [{ id: 'tp1', stockPrice: 200.02, targetPrice: 200.02, estimatedOptionPrice: 8, contractsToSell: 1, status: 'PENDING', rrContribution: 0.6 }],
    ...exit,
  },
  rrRatio: 2.5, rrModel: 'Heston repriced', finalStatus: 'PASS',
});

const switcher = () => within(screen.getByRole('group', { name: 'Show methods' }));
const cardOf = (method: 'arithmetic' | 'monte_carlo' | 'ladder') =>
  document.querySelector(`[data-method-card="${method}"]`) as HTMLElement;
const visible = () => (['monte_carlo', 'arithmetic', 'ladder'] as const).filter((m) => !cardOf(m).hidden);
const mc = () => within(screen.getByRole('region', { name: 'Monte Carlo Profit Target' }));
const css = readFileSync(join(__dirname, '..', 'TradeCard.module.css'), 'utf8');
/** Every declaration block whose selector list ends in `selector`, joined. */
const rule = (selector: string) => {
  const blocks: string[] = [];
  for (let at = css.indexOf(`${selector} {`); at >= 0; at = css.indexOf(`${selector} {`, at + 1)) {
    blocks.push(css.slice(at, css.indexOf('}', at)));
  }
  return blocks.join('\n');
};

beforeEach(() => { localStorage.clear(); jest.clearAllMocks(); });

describe('G6 — segmented method switch', () => {
  it('renders Monte Carlo · Arithmetic · Ladder · Compare buttons in the methods head, not a checkbox fieldset', () => {
    render(<TradeCard data={card()} contracts={2} />);
    const head = screen.getByRole('region', { name: 'Profit-target methods' });
    expect(within(head).queryByText('Show side by side')).not.toBeInTheDocument();
    expect(head.querySelector('fieldset')).toBeNull();
    const buttons = switcher().getAllByRole('button').concat(switcher().getAllByRole('checkbox'));
    expect(new Set(buttons.map((b) => b.tagName))).toEqual(new Set(['BUTTON']));
    expect(switcher().getAllByRole('checkbox').map((b) => b.textContent)).toEqual(['Monte Carlo', 'Arithmetic', 'Ladder']);
    expect(switcher().getByRole('button', { name: 'Compare' })).toHaveAttribute('aria-pressed', 'false');
    // Monte Carlo is the default and the last shown card cannot be hidden.
    expect(switcher().getByRole('checkbox', { name: 'Monte Carlo' })).toBeChecked();
    expect(switcher().getByRole('checkbox', { name: 'Monte Carlo' })).toBeDisabled();
    expect(visible()).toEqual(['monte_carlo']);
  });

  it('switches and compares cards without computing, editing or changing the recorded method', async () => {
    const onEditsChange = jest.fn();
    const onMethodPickChange = jest.fn();
    const pick: MethodPick = { method: 'ladder', rowStockPrice: 200.02, rowOptionPrice: null, stopBasis: 'stock', pickedAt: '2026-09-14T09:00:00.000Z' };
    const fetchSpy = jest.fn();
    const originalFetch = global.fetch;
    global.fetch = fetchSpy as unknown as typeof fetch;
    try {
      render(<TradeCard data={card({ exitPlan: plan() })} contracts={2} initialMethodPick={pick}
        onEditsChange={onEditsChange} onMethodPickChange={onMethodPickChange} />);
      await act(async () => { await Promise.resolve(); });
      jest.clearAllMocks(); onEditsChange.mockClear(); onMethodPickChange.mockClear();

      const compare = switcher().getByRole('button', { name: 'Compare' });
      fireEvent.click(compare);
      expect(visible()).toEqual(['monte_carlo', 'arithmetic', 'ladder']);
      expect(compare).toHaveAttribute('aria-pressed', 'true');
      fireEvent.click(switcher().getByRole('checkbox', { name: 'Ladder' }));
      expect(visible()).toEqual(['monte_carlo', 'arithmetic']);
      expect(compare).toHaveAttribute('aria-pressed', 'true');
      fireEvent.click(compare);
      expect(visible()).toEqual(['monte_carlo']);
      expect(compare).toHaveAttribute('aria-pressed', 'false');
      fireEvent.click(switcher().getByRole('checkbox', { name: 'Arithmetic' }));
      fireEvent.click(switcher().getByRole('checkbox', { name: 'Monte Carlo' }));
      expect(visible()).toEqual(['arithmetic']);
      await act(async () => { await Promise.resolve(); });

      for (const fn of Object.values(api)) expect(fn).not.toHaveBeenCalled();
      expect(fetchSpy).not.toHaveBeenCalled();
      expect(onEditsChange).not.toHaveBeenCalled();
      expect(onMethodPickChange).not.toHaveBeenCalled();
      expect(screen.getByRole('radio', { name: 'Ladder' })).toBeChecked();
    } finally {
      global.fetch = originalFetch;
    }
  });

  it('keeps the display-only explanation as one short line, adding the independence note while comparing', () => {
    render(<TradeCard data={card()} contracts={2} />);
    const head = within(screen.getByRole('region', { name: 'Profit-target methods' }));
    expect(head.getByText(/^Display only/)).toBeVisible();
    expect(head.queryByText(/independent and can disagree/)).not.toBeInTheDocument();
    fireEvent.click(switcher().getByRole('button', { name: 'Compare' }));
    expect(head.getByText(/independent and can disagree/)).toBeVisible();
  });
});

describe('G7 — compact Monte Carlo inputs and pre-run state', () => {
  it('puts the three one-line-labelled % inputs and the primary Run button in one row', () => {
    render(<TradeCard data={card()} contracts={2} />);
    const t1 = mc().getByRole('spinbutton', { name: 'T1 profit target %' });
    const row = t1.closest('[data-mc-input-row]') as HTMLElement;
    expect(row).not.toBeNull();
    const runButton = mc().getByRole('button', { name: 'Run Monte Carlo Estimate' });
    expect(row).toContainElement(runButton);
    expect(runButton).toHaveClass('btnPrimary');
    for (const key of ['T1', 'T2', 'T3']) {
      const label = mc().getByRole('spinbutton', { name: `${key} profit target %` }).closest('label')!;
      expect(label).toHaveTextContent(`${key} profit %Editable`);
      expect(row).toContainElement(label);
    }
    // The bounds stay discoverable on the input and in the model disclosure.
    expect(t1).toHaveAttribute('title', expect.stringMatching(/1–500%/));
    const model = mc().getByText('Monte Carlo model, inputs & provenance').closest('details')!;
    expect(within(model).getByText(/editable option-profit percentages, 1–500%/)).toBeInTheDocument();
  });

  it('states the four unavailable stop-context facts once before a run', () => {
    render(<TradeCard data={card()} contracts={2} />);
    const stop = screen.getByRole('region', { name: 'Monte Carlo Profit Target' }).querySelector('[data-slot="stop"]') as HTMLElement;
    const lines = within(stop).getAllByText('Unavailable — run or re-run estimate to confirm barriers');
    expect(lines).toHaveLength(1);
    expect(lines[0].parentElement).toHaveTextContent(/Stock barrier.*option-price barrier.*value.*loss at the stock stop/i);
    expect(stop.querySelector('[data-field="stock-barrier"]')).toBeNull();
    expect(mc().getByText('Not yet estimated')).toBeVisible();
    expect(mc().getByText(/No estimate yet\. Nothing runs automatically/)).toBeVisible();
    expect(api.getFirstPassageEstimate).not.toHaveBeenCalled();
  });

  it('keeps the four facts for a restored estimate, fed by the same guarded values', () => {
    render(<TradeCard data={card({ firstPassage: estimate(), firstPassageContext: context })} contracts={2} />);
    const stop = screen.getByRole('region', { name: 'Monte Carlo Profit Target' }).querySelector('[data-slot="stop"]') as HTMLElement;
    for (const f of ['stock-barrier', 'premium-barrier', 'stop-value', 'stop-loss']) {
      expect(stop.querySelector(`[data-field="${f}"]`)).toHaveTextContent('Unavailable — run or re-run estimate to confirm barriers');
    }
  });
});

describe('G8 — readable target tables', () => {
  it('shows time as ~Nd with the unit in the header, and the Arithmetic ratio without the repeated word', () => {
    render(<TradeCard data={card({ firstPassage: estimate(), firstPassageContext: context, exitPlan: plan() })} contracts={2} />);
    fireEvent.click(switcher().getByRole('button', { name: 'Compare' }));
    const mcTable = within(screen.getByRole('table', { name: 'Monte Carlo targets' }));
    expect(mcTable.getByRole('columnheader', { name: 'Conditional time (calendar days)' })).toBeInTheDocument();
    const [first, second] = Array.from(cardOf('monte_carlo').querySelectorAll('[data-target-row]')) as HTMLElement[];
    expect(first.querySelector('[data-field="time"]')).toHaveTextContent(/^~7d$/);
    expect(second.querySelector('[data-field="time"]')).toHaveTextContent('Unavailable — no conditional median');
    const arith = within(screen.getByRole('table', { name: 'Arithmetic targets' }));
    expect(arith.getByRole('columnheader', { name: 'Conditional time (calendar days)' })).toBeInTheDocument();
    const arow = cardOf('arithmetic').querySelector('[data-target-row]') as HTMLElement;
    expect(within(arow).getByText('2:1')).toBeVisible();
    expect(arow.querySelector('[data-field="time"]')).toHaveTextContent(/^~8d$/);
  });

  it('keeps one short visible footnote and moves the long qualifier into the method disclosure', () => {
    render(<TradeCard data={card({ firstPassage: estimate(), firstPassageContext: context })} contracts={2} />);
    const targets = screen.getByRole('region', { name: 'Monte Carlo Profit Target' }).querySelector('[data-slot="targets"]') as HTMLElement;
    const long = within(targets).getByText(/Probability is each target's touch before expiry measured on its own/);
    expect(long.closest('details')).not.toBeNull();
    const short = within(targets).getByText(/^Probability counts each target's touch on its own/);
    expect(short.closest('details')).toBeNull();
    expect(short).toBeVisible();
  });

  it('styles the tables with readable shaded headers and single-line cells', () => {
    const head = rule('.mcTargetTable thead th');
    expect(head).toMatch(/color:\s*var\(--text-secondary\)/);
    expect(head).not.toMatch(/--text-dim/);
    expect(head).toMatch(/background:/);
    expect(rule('.mcTargetTable td')).toMatch(/white-space:\s*nowrap/);
  });
});
