/** TC-ALIGN-05 (#608, D10/D11) — one grouped decision section.
 *
 *  Method choices, optional target rows, the "Judged on" basis, ONE compact
 *  selected-target review and the destination actions sit together; the old
 *  Final Recommendation's latest/all-target results list is gone, with its
 *  unique context kept in the review or the originating method card. The
 *  review reads only the existing pick/row resolution, and a stale, ambiguous,
 *  unmatched or absent selection shows that state instead of old values. */
import '@testing-library/jest-dom';
import { render as renderCard, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { TradeCard } from '@/components/organisms/TradeCard';
import { api } from '@/lib/api';
import type { MethodPick, TradeCardData } from '@/types/domain';

jest.mock('@/lib/api', () => ({
  api: {
    getStructuralStop: jest.fn(), getStockQuote: jest.fn(), getContractQuote: jest.fn(),
    getFirstPassageEstimate: jest.fn(), getExitPlan: jest.fn(),
  },
}));
jest.mock('@/components/organisms/InlineChartPanel', () => ({ InlineChartPanel: () => <div /> }));
jest.mock('@/components/molecules/SymbolHeader', () => ({ SymbolHeader: ({ ticker }: { ticker: string }) => <div>{ticker}</div> }));
jest.mock('@/components/molecules/ScoreCardPanel', () => ({ ScoreCardPanel: () => <div /> }));
jest.mock('@/components/molecules/LabeledStatusBadge', () => ({
  LabeledStatusBadge: ({ label, status }: { label: string; status: string }) => <div data-testid="labeled-badge">{label}: {status}</div>,
}));

// Calculation tests open every method card explicitly, as the other suites do.
const render = (...args: Parameters<typeof renderCard>) => {
  const view = renderCard(...args);
  for (const name of ['Arithmetic', 'Fixed % Ladder']) {
    const toggle = screen.queryByRole('checkbox', { name });
    if (toggle && !(toggle as HTMLInputElement).checked) fireEvent.click(toggle);
  }
  return view;
};

const card: TradeCardData = {
  symbol: 'AAPL', company: 'Apple Inc.', price: 185.2, direction: 'Bullish', status: 'PASS',
  stockScore: 82, stockConfidence: 'PASS',
  stockBreakdown: { trend: 85, pullback: 78, trigger: 72, event: 90, volatility: 65 },
  contract: 'AAPL 190C 05/15', contractScore: 70, contractConfidence: 'PASS',
  contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
  contractDetails: { strike: 190, expiry: '2026-05-15', right: 'C', mid: 2.5, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
  entry: { limit: 2.5, maxFill: 2.63, orderType: 'Limit' },
  exit: {
    invalidation: 179.64, premiumStop: 1.5, timeStopDays: 10, target: 200.02,
    targets: [
      { id: 'tp1', stockPrice: 200.02, targetPrice: 200.02, estimatedOptionPrice: 5.0, contractsToSell: 1, status: 'PENDING', rrContribution: 1.0 },
    ],
  },
  rrRatio: 2.5, rrModel: 'Heston repriced', finalStatus: 'CAUTION',
};
const arithmeticPlan: NonNullable<TradeCardData['exit']['exitPlan']> = {
  stop: { price: 178, source: 'atr_widened', contractPrice: 1.2, rrModel: 'Heston repriced',
    structuralSource: null, structuralConfidence: null, structuralPrice: null,
    atrFloorPrice: 178, distanceDollar: null,
    stopCost: { basis: 'bs_today', stopPrice: 178, premium: 2.5, valueAtStop: 1.2, lossDollar: 1.3,
      fraction: 0.52, passMaxFraction: 0.6, status: 'PASS' } },
  targets: [
    { rrRatio: 2, arithmeticPrice: 210.5, price: 210.5, tpSource: 'arithmetic', structuralPrice: null,
      contractPrice: 5, rrModel: 'Heston repriced', probability: 0.4, expectedDays: 9,
      qualityGood: true, qualityReasons: [], distanceDollar: null, toleranceDollar: 1 },
    { rrRatio: 3, arithmeticPrice: 225, price: 225, tpSource: 'arithmetic', structuralPrice: null,
      contractPrice: 7, rrModel: 'Delta approximation', probability: 0.2, expectedDays: null,
      qualityGood: true, qualityReasons: [], distanceDollar: null, toleranceDollar: 1 },
  ],
  atr: 4, computedAt: '2026-01-01T00:00:00.000Z',
};
const estimate = {
  targets: [{ pct: 0.2, stockPrice: 197.5, optionPrice: 6.24, probability: 0.4, expectedDays: 9 }],
  invalidation: { probability: 0.3, expectedDays: 5 },
  race: {
    premiumStopPrice: 1.5, stockStopPrice: 179.64, nPaths: 2000,
    premiumStopPct: 0.4, premiumUsed: 2.5, ivSolved: true,
    outcomes: [{ targetPct: 0.2, targetOptionPrice: 7.25, pTargetFirst: 0.25,
      pStockStopFirst: 0.3, pPremiumStopFirst: 0.2, pNeither: 0.25,
      daysTarget: 9, daysStockStop: 12, daysPremiumStop: 8,
      daysAnyPathReachedStop: 5, weightTargetFirst: 0.25, weightStockStopFirst: 0.3,
      weightPremiumStopFirst: 0.2, weightNeither: 0.25, terminalMean: 2.5,
      rewardDollar: 4.75, repriceDaysStockStop: 5, stopRepricedValue: 1.2,
      riskStockStop: 1.3, riskPremiumStop: 1, rrPremiumStop: 0.5,
      edgePerContract: 120, rrStockStop: 1.8 }],
  },
};
const pick = (over: Partial<MethodPick> = {}): MethodPick => ({
  method: 'ladder', rowStockPrice: 200.02, rowOptionPrice: null,
  stopBasis: 'stock', pickedAt: '2026-09-14T09:00:00.000Z', ...over,
});

const radio = (name: string) => screen.getByRole('radio', { name });
const decision = () => screen.getByRole('region', { name: 'Decision and execution' });
const review = () => within(screen.getByRole('region', { name: 'Selected target review' }));
const reviewState = () => screen.getByRole('region', { name: 'Selected target review' }).getAttribute('data-review-state');
const valueOf = (label: string) => review().getByText(label).parentElement!;
const runEstimate = async () => {
  (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue(estimate);
  fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
  await waitFor(() => expect(radio('Monte Carlo')).toBeEnabled());
};

beforeEach(() => {
  localStorage.clear();
  jest.clearAllMocks();
  (api.getStructuralStop as jest.Mock).mockResolvedValue({
    available: true, price: 178.5, source: 'order_block', confidence: 75, distancePct: 3.6,
  });
  (api.getStockQuote as jest.Mock).mockResolvedValue({ price: 185.2 });
  (api.getContractQuote as jest.Mock).mockResolvedValue({ price: 2.5 });
});

describe('#608 one grouped decision section', () => {
  it('groups method, row and basis choices, the selected-target review, one Exit Plan link and the destination actions', () => {
    render(
      <TradeCard
        data={card}
        initialMethodPick={pick()}
        onSendToBroker={jest.fn()}
        sendLabel="Track basket"
        destinations={<div role="group" aria-label="Broker execution">BROKER PANEL</div>}
      />,
    );
    const group = within(decision());
    expect(group.getByRole('radiogroup', { name: 'Exit method for this trade' })).toBeVisible();
    for (const m of ['Ladder', 'Arithmetic', 'Monte Carlo', 'Barrier Race']) expect(group.getByRole('radio', { name: m })).toBeInTheDocument();
    expect(group.getByRole('radiogroup', { name: 'Target row' })).toBeVisible();
    expect(group.getByRole('radiogroup', { name: 'Judged on' })).toBeVisible();
    expect(group.getByRole('region', { name: 'Selected target review' })).toBeVisible();
    expect(group.getByRole('button', { name: 'Track basket' })).toBeEnabled();
    expect(group.getByRole('button', { name: /view chart/i })).toBeInTheDocument();
    expect(group.getByRole('button', { name: /export json/i })).toBeInTheDocument();
    expect(group.getByRole('group', { name: 'Broker execution' })).toHaveTextContent('BROKER PANEL');
    const exitLinks = Array.from(decision().querySelectorAll('a[href="#exit-plan"]'));
    expect(exitLinks).toHaveLength(1);
    // The final status stays with the identity, not the decision.
    const identity = within(screen.getByRole('region', { name: 'Selected stock and contract' }));
    expect(identity.getByTestId('labeled-badge')).toHaveTextContent('Final Status: CAUTION');
    expect(group.queryByTestId('labeled-badge')).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Final Recommendation' })).not.toBeInTheDocument();
  });

  it('no longer repeats the latest/all-target results list; its unique context stays reachable', async () => {
    render(<TradeCard data={{ ...card, exit: { ...card.exit, exitPlan: arithmeticPlan } }} />);
    // Latest Arithmetic: the review names it and when, but prints no targets.
    expect(review().getByText(/computed via: Arithmetic/)).toBeVisible();
    expect(within(decision()).queryByText(/\$210\.50/)).not.toBeInTheDocument();
    expect(within(decision()).queryByText('Bottom (final stop)')).not.toBeInTheDocument();
    // The Arithmetic alert caveat moved to its own card.
    expect(within(screen.getByRole('region', { name: 'Arithmetic Profit Target' }))
      .getByText(/not automatically monitored by alerts unless copied into the position's stop field after opening/)).toBeInTheDocument();
    await runEstimate();
    expect(review().getByText(/computed via: Monte Carlo/)).toBeVisible();
    expect(within(decision()).queryByText(/T20%/)).not.toBeInTheDocument();
    expect(within(decision()).queryByText(/6\.24|Armed stop/)).not.toBeInTheDocument();
    expect(reviewState()).toBe('not-selected');
  });

  it('review values follow row changes and quantity edits from the existing resolution', () => {
    render(<TradeCard data={{ ...card, exit: { ...card.exit, exitPlan: arithmeticPlan } }} contracts={2} />);
    fireEvent.click(radio('Arithmetic'));
    expect(reviewState()).toBe('method-only');
    expect(review().getByText('Target not selected')).toBeVisible();
    fireEvent.click(radio('2:1'));
    expect(reviewState()).toBe('selected');
    expect(valueOf('Recorded stock target')).toHaveTextContent('$210.50 stock');
    expect(valueOf('Matched result option premium')).toHaveTextContent('$5.00 /share');
    expect(review().getByText('40%')).toBeVisible();
    expect(review().getByText('~9 calendar days')).toBeVisible();
    // (5.00 − 2.50 calculation premium) × 2 × 100
    expect(valueOf('Estimated dollar outcome (full position, before costs)')).toHaveTextContent('$500.00');
    fireEvent.click(screen.getByLabelText('Edit Contracts'));
    const qty = screen.getByLabelText('Edit Contracts');
    fireEvent.change(qty, { target: { value: '3' } });
    fireEvent.blur(qty);
    expect(valueOf('Estimated dollar outcome (full position, before costs)')).toHaveTextContent('$750.00');
    expect(valueOf('Applicable quantity')).toHaveTextContent('3 entered contracts');
    fireEvent.click(radio('3:1'));
    expect(valueOf('Recorded stock target')).toHaveTextContent('$225.00 stock');
    expect(review().getByText('20%')).toBeVisible();
    expect(review().queryByText('40%')).not.toBeInTheDocument();
    expect(review().queryByText('~9 calendar days')).not.toBeInTheDocument();
    fireEvent.click(radio('Ladder'));
    expect(reviewState()).toBe('method-only');
    expect(review().queryByText('20%')).not.toBeInTheDocument();
    expect(review().queryByText('$225.00 stock')).not.toBeInTheDocument();
  });

  it('separates the recorded choice from estimates', () => {
    render(<TradeCard data={{ ...card, exit: { ...card.exit, exitPlan: arithmeticPlan } }} />);
    fireEvent.click(radio('Arithmetic'));
    fireEvent.click(radio('2:1'));
    const recorded = within(review().getByRole('group', { name: 'Recorded choice' }));
    const estimates = within(review().getByRole('group', { name: 'Estimates at this target' }));
    expect(recorded.getByText('Recorded stock target')).toBeInTheDocument();
    expect(recorded.getByText('Judged on basis')).toBeInTheDocument();
    expect(estimates.getByText('Matched result option premium')).toBeInTheDocument();
    expect(estimates.getByText('Estimated dollar outcome (full position, before costs)')).toBeInTheDocument();
    expect(estimates.queryByText('Recorded stock target')).not.toBeInTheDocument();
  });

  it('a selected race target shows its exclusive probability and edge in the review only for a showable race', async () => {
    render(<TradeCard data={card} />);
    await runEstimate();
    fireEvent.click(radio('Barrier Race'));
    fireEvent.click(radio('T20%'));
    expect(reviewState()).toBe('selected');
    expect(review().getByText('Allocated target-first probability')).toBeVisible();
    expect(review().getByText('25%')).toBeVisible();
    expect(valueOf('Barrier Race edge per contract')).toHaveTextContent('$120.00 at 1.80x');
    expect(review().getByText(/computed via: Barrier Race/)).toBeVisible();
    // Moving a barrier makes the race unshowable: the pick clears and the
    // review shows the unavailable state, never the old race numbers.
    fireEvent.click(screen.getByLabelText('Edit Premium stop'));
    const input = screen.getByLabelText('Edit Premium stop');
    fireEvent.change(input, { target: { value: '0.90' } });
    fireEvent.blur(input);
    await waitFor(() => expect(reviewState()).toBe('unavailable'));
    expect(review().getByText(/Selected method results unavailable/)).toBeVisible();
    expect(review().queryByText(/7\.25|\$120\.00|25%/)).not.toBeInTheDocument();
  });

  it('ambiguous and unmatched stored targets say so instead of borrowing evidence', () => {
    const dup = { ...arithmeticPlan, targets: [arithmeticPlan.targets[0], { ...arithmeticPlan.targets[1], price: 210.5 }] };
    const { unmount } = render(<TradeCard data={{ ...card, exit: { ...card.exit, exitPlan: dup } }}
      initialMethodPick={pick({ method: 'arithmetic', rowStockPrice: 210.5 })} />);
    expect(reviewState()).toBe('ambiguous');
    expect(review().queryByText('40%')).not.toBeInTheDocument();
    unmount();
    render(<TradeCard data={{ ...card, exit: { ...card.exit, exitPlan: arithmeticPlan } }}
      initialMethodPick={pick({ method: 'arithmetic', rowStockPrice: 220 })} />);
    expect(reviewState()).toBe('unmatched');
    expect(review().queryByText('40%')).not.toBeInTheDocument();
  });

  it('a restored Monte Carlo estimate prints no figures in the review and says it was not re-run', () => {
    render(<TradeCard data={{ ...card, exit: { ...card.exit,
      firstPassage: { ...estimate, race: null, computedAt: '2026-09-07T14:32:00.000Z' } } }}
      initialMethodPick={pick({ method: 'monte_carlo', rowStockPrice: 197.5, rowOptionPrice: 6.24 })} />);
    expect(reviewState()).toBe('unavailable');
    expect(review().queryByText(/6\.24|197\.50|40%/)).not.toBeInTheDocument();
  });

  it('choosing a basis changes no Exit Plan setting and leaves both stop alerts in place', () => {
    const onEditsChange = jest.fn();
    render(<TradeCard data={card} initialMethodPick={pick()} onEditsChange={onEditsChange} />);
    const stop = screen.getByLabelText('Edit Invalidation').textContent;
    const premium = screen.getByLabelText('Edit Premium stop').textContent;
    fireEvent.click(radio('Premium stop'));
    expect(within(valueOf('Judged on basis')).getByText('Premium stop')).toBeVisible();
    expect(screen.getByLabelText('Edit Invalidation').textContent).toBe(stop);
    expect(screen.getByLabelText('Edit Premium stop').textContent).toBe(premium);
    expect(onEditsChange).not.toHaveBeenCalled();
    expect(within(decision()).getByText(/the stock stop and the premium stop both keep firing/)).toBeVisible();
  });
});
