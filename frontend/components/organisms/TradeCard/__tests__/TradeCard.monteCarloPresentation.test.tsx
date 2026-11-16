/** OPT-PRES-06: preserve returned MC targets and their own request basis. */
import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { api } from '@/lib/api';
import { TradeCard } from '@/components/organisms/TradeCard';
import type { BarrierRace, FirstPassageContext, FirstPassageEstimate, TradeCardData } from '@/types/domain';

jest.mock('@/lib/api', () => ({ api: { getStructuralStop: jest.fn(), getStockQuote: jest.fn(), getContractQuote: jest.fn(), getFirstPassageEstimate: jest.fn(), getExitPlan: jest.fn() } }));
jest.mock('@/components/organisms/InlineChartPanel', () => ({ InlineChartPanel: () => <div /> }));
jest.mock('@/components/molecules/SymbolHeader', () => ({ SymbolHeader: () => <div /> }));
jest.mock('@/components/molecules/ScoreCardPanel', () => ({ ScoreCardPanel: () => <div /> }));
jest.mock('@/components/molecules/LabeledStatusBadge', () => ({ LabeledStatusBadge: () => <div /> }));
const card: TradeCardData = {
  symbol: 'AAPL', company: 'Apple', price: 185.2, direction: 'Bullish', status: 'PASS', stockScore: 82, stockConfidence: 'PASS',
  stockBreakdown: { trend: 85, pullback: 78, trigger: 72, event: 90, volatility: 65 },
  contract: 'AAPL 190C 05/15', contractScore: 70, contractConfidence: 'PASS',
  contractBreakdown: { dteFit: 80, delta: 65, ivAttractiveness: 55, liquidity: 75, spread: 60 },
  contractDetails: { strike: 190, expiry: '2026-05-15', right: 'C', mid: 5.2, delta: 0.45, theta: -0.09, ivRank: 45, dte: 24 },
  entry: { limit: 5.2, maxFill: 5.4, orderType: 'Limit' },
  exit: { invalidation: 179.64, premiumStop: 3.12, timeStopDays: 10, target: 200.02, targets: [] },
  rrRatio: 2.5, rrModel: 'Heston repriced', finalStatus: 'PASS',
};
const estimate = (): FirstPassageEstimate => ({
  targets: [
    { pct: 0.25, optionPrice: 5, stockPrice: 195, probability: 0.6, expectedDays: 8 },
    { pct: 0.5, optionPrice: 6, stockPrice: null, probability: 0, expectedDays: null },
    { pct: 0.75, optionPrice: 7, stockPrice: 205, probability: 0.2, expectedDays: 16 },
  ], invalidation: { probability: 0.3, expectedDays: 4 },
});
const context: FirstPassageContext = { premium: 4, delta: 0.45, targetPct: { t1: 0.25, t2: 0.5, t3: 0.75 } };
const show = (ctx: FirstPassageContext | null = context, fp = estimate(), overrides: Partial<TradeCardData> = {}) => {
  render(<TradeCard data={{ ...card, ...overrides, exit: { ...card.exit, ...overrides.exit, firstPassage: fp, firstPassageContext: ctx } }} contracts={2} initialEntryLimit={8} liveMid={9} liveStockPrice={210} />);
  return within(screen.getByText('Monte Carlo Profit Target').closest('section')!);
};
beforeEach(() => { localStorage.clear(); jest.clearAllMocks(); });
it('shows the captured estimate basis, all returned premiums and outcomes rather than scan/order/live prices', () => {
  const region = show();
  // #606: the premium basis the outcomes subtract stays visible beside them;
  // the remaining basis, model and provenance prose sits in the closed
  // disclosure — present, unchanged, one click away.
  expect(region.getByText('Captured request premium (rounded to cents)')).toBeVisible();
  expect(region.getByText('$4.00/share')).toBeVisible();
  // #610 G8: the quantity basis stays visible in the short footnote; its
  // full sentence is in the model disclosure.
  expect(region.getByText(/Outcome: 2 contracts × 100 shares, full exit, before costs/)).toBeVisible();
  expect(region.getAllByText(/2 entered contracts × 100 shares, selected-contract full exit/).length).toBeGreaterThan(0);
  for (const amount of ['$200.00', '$400.00', '$600.00']) expect(region.getByText(amount)).toBeVisible();
  expect(region.getAllByRole('row')).toHaveLength(4);
  expect(region.getByRole('columnheader', { name: 'Probability (independent touch)' })).toBeVisible();
  expect(region.getByRole('columnheader', { name: 'Conditional time (calendar days)' })).toBeVisible();
  expect(region.getByText('~8d')).toBeVisible();
  expect(region.getByText('Unavailable — no conditional median')).toBeVisible();
  expect(region.getByText('not reachable')).toBeVisible();
  const provenance = region.getByText('Monte Carlo model, inputs & provenance').closest('details')!;
  expect(provenance.open).toBe(false);
  const inside = within(provenance);
  expect(inside.getByText('$190.00 Call')).toBeInTheDocument();
  expect(inside.getByText('Scan stock reference')).toBeInTheDocument();
  expect(inside.getByText('$185.20')).toBeInTheDocument();
  expect(inside.getByText(/Stored Monte Carlo run stock entry: unavailable/)).toBeInTheDocument();
  expect(inside.getByText('$8.00/share')).toBeInTheDocument();
  expect(inside.getByText(/2 entered contracts × 100 shares · selected-contract full exit/)).toBeInTheDocument();
  expect(inside.getAllByText('Structural level found')).toHaveLength(1);
  expect(inside.getByText(/GBM simulated stock paths.*Black-Scholes option repricing/)).toBeInTheDocument();
  expect(inside.getByText(/even if a stop is also reached/)).toBeInTheDocument();
  expect(inside.getByText(/calendar-day steps to expiry.*24 DTE/)).toBeInTheDocument();
  expect(inside.getByText(/Monte Carlo does not propose a stop/)).toBeInTheDocument();
  expect(region.queryByText(/Heston/)).not.toBeInTheDocument();
});
it.each([null, { ...context, premium: 0 }, { ...context, premium: NaN }])('does not invent dollar outcomes with absent/invalid request premium %p', (ctx) => {
  const region = show(ctx);
  expect(region.getAllByText('Unavailable — estimate premium basis missing')).toHaveLength(4);
  expect(region.queryByText('$200.00')).not.toBeInTheDocument();
});
it('uses only the same-result echoed race premium when restored request context is absent', () => {
  const fp = estimate();
  fp.race = { premiumUsed: 4.12, outcomes: [], premiumStopPrice: 2.47, premiumStopPct: 0.4, stockStopPrice: 180, ivSolved: true, nPaths: 2000 } satisfies BarrierRace;
  const region = show(null, fp, { spreadType: 'bear_put' });
  expect(region.getByText('Same-estimate echoed premium')).toBeVisible();
  expect(region.getByText('$4.12/share')).toBeVisible();
  expect(region.getByText('$176.00')).toBeVisible();
  expect(region.getByText(/Selected-contract basis only; this is not a whole-spread outcome/)).toBeVisible();
  expect(region.queryByText('$180.00')).not.toBeInTheDocument(); // restored race barrier remains guarded
});
it('rounds the printed request basis and returned premium consistently without rebuilding target prices', () => {
  const fp = estimate(); fp.targets = [{ ...fp.targets[0], optionPrice: 5.17 }];
  const region = show({ ...context, premium: 4.125 }, fp);
  expect(region.getByText('$4.13/share')).toBeVisible();
  expect(region.getByText('$208.00')).toBeVisible();
  expect(region.queryByText('$5.16')).not.toBeInTheDocument();
});
it('restores T1/T2/T3 inputs and retains their clamps without changing saved result rows', () => {
  const region = show();
  const t1 = region.getByRole('spinbutton', { name: 'T1 profit target %' });
  expect(t1).toHaveValue(25);
  expect(region.getByRole('spinbutton', { name: 'T2 profit target %' })).toHaveValue(50);
  expect(region.getByRole('spinbutton', { name: 'T3 profit target %' })).toHaveValue(75);
  expect(t1).toHaveAttribute('min', '1'); expect(t1).toHaveAttribute('max', '500');
  fireEvent.change(t1, { target: { value: '900' } }); expect(t1).toHaveValue(500);
  fireEvent.change(t1, { target: { value: '-10' } }); expect(t1).toHaveValue(1);
  expect(region.getByText('T25%')).toBeVisible();
  expect(region.getByText('$200.00')).toBeVisible();
});
const echo = (premiumUsed: number): BarrierRace => ({ premiumUsed, outcomes: [], premiumStopPrice: 2.47, premiumStopPct: 0.4, stockStopPrice: 180, ivSolved: true, nPaths: 2000 });
it('uses server-rounded cents at a half-cent captured request premium', () => {
  const fp = estimate(); fp.targets = [{ ...fp.targets[0], optionPrice: 5.17 }]; fp.race = echo(4.12);
  const region = show({ ...context, premium: 4.125 }, fp);
  expect(region.getByText('Same-estimate echoed premium')).toBeVisible();
  expect(region.getByText('$4.12/share')).toBeVisible();
  expect(region.getByText('$210.00')).toBeVisible();
  expect(region.getByText(/Captured request premium: \$4.125\/share/)).toBeInTheDocument();
  expect(region.queryByText('$4.13/share')).not.toBeInTheDocument();
});
it.each([3.5, 0, NaN])('guards mismatched or invalid same-estimate echo %p', (premiumUsed) => {
  const fp = estimate(); fp.race = echo(premiumUsed);
  const region = show(context, fp);
  expect(region.getAllByText('Unavailable — estimate premium basis missing')).toHaveLength(4);
  expect(region.getAllByRole('row')).toHaveLength(4);
});
it('allows the valid server half-cent echo despite binary floating residue', () => {
  const fp = estimate(); fp.race = echo(2.67); fp.targets = [{ ...fp.targets[0], optionPrice: 3.21 }];
  const region = show({ ...context, premium: 2.675 }, fp);
  expect(region.getByText('$2.67/share')).toBeVisible();
  expect(region.getByText('$108.00')).toBeVisible();
});
it('preserves missing returned prices and medians instead of printing nonfinite values', () => {
  const fp = estimate(); fp.targets = [{ ...fp.targets[0], optionPrice: NaN, stockPrice: NaN, probability: NaN, expectedDays: NaN }];
  const region = show(context, fp);
  expect(region.getAllByText('Unavailable')).toHaveLength(4);
  expect(region.getByText('Unavailable — no conditional median')).toBeVisible();
});
// #606: Monte Carlo no longer repeats the actual Exit Plan settings; the
// execution loss amount is read once, in the shared Exit Plan, on the same
// live-global and low-premium pinned rules.
it('reads the execution loss amount once, in the Exit Plan, on the live global basis rather than the old scan seed', () => {
  const region = show();
  expect(region.queryByText('Execution premium-stop loss amount')).not.toBeInTheDocument();
  const exitPlan = within(screen.getByRole('region', { name: 'Exit Plan' }));
  expect(exitPlan.getByText('60% loss · global')).toBeVisible();
  expect(exitPlan.getByLabelText('Edit Premium stop')).toHaveTextContent('5.40');
  expect(exitPlan.getByLabelText('Edit Premium stop')).not.toHaveTextContent('3.12');
});
it('uses the primary low-premium global/pinned rules for the Exit Plan loss amount, not repeated by Monte Carlo', () => {
  const { rerender } = render(<TradeCard data={card} liveMid={0.01} />);
  let exitPlan = within(screen.getByRole('region', { name: 'Exit Plan' }));
  expect(exitPlan.getByText('global (60%)')).toBeVisible();
  expect(within(screen.getByText('Monte Carlo Profit Target').closest('section')!).queryByText(/Global loss allowance/)).not.toBeInTheDocument();
  rerender(<TradeCard data={{ ...card, contract: 'AAPL 200C 05/15' }} liveMid={0.01} initialPremiumStop={0.005} />);
  exitPlan = within(screen.getByRole('region', { name: 'Exit Plan' }));
  expect(exitPlan.getByText('$0.01 (pinned)')).toBeVisible();
  expect(within(screen.getByText('Monte Carlo Profit Target').closest('section')!).queryByText(/· pinned/)).not.toBeInTheDocument();
});

// ── #579: Monte Carlo pre-run state, barrier inputs versus settings, stale race ─
describe('Monte Carlo and Barrier Race (#579)', () => {
  const RUN_RACE: BarrierRace = {
    outcomes: [0.25, 0.5, 0.75].map((targetPct, i) => ({
      targetPct, targetOptionPrice: [6.5, 7.8, 9.1][i],
      pTargetFirst: 0.2685, pStockStopFirst: 0.0045, pPremiumStopFirst: 0.682, pNeither: 0.045,
      daysTarget: 7 + i, daysStockStop: 20, daysPremiumStop: 12, daysAnyPathReachedStop: 18,
      weightTargetFirst: 0.27, weightStockStopFirst: 0.01, weightPremiumStopFirst: 0.68, weightNeither: 0.04,
      terminalMean: 4, rewardDollar: [1.3, 2.6, 3.9][i], repriceDaysStockStop: 18,
      stopRepricedValue: 1.1, riskStockStop: 4.1, riskPremiumStop: 3.12,
      rrStockStop: [1.3, 2.6, 3.9][i] / 4.1, rrPremiumStop: 0.4, edgePerContract: -120,
    })),
    premiumStopPrice: 2.08, premiumStopPct: 0.6, stockStopPrice: 180, premiumUsed: 5.2, ivSolved: true, nPaths: 2000,
  };
  const RUN_RESPONSE = {
    targets: [
      { pct: 0.25, optionPrice: 6.5, stockPrice: 194.1, probability: 0.61, expectedDays: 7 },
      { pct: 0.5, optionPrice: 7.8, stockPrice: 198.2, probability: 0.42, expectedDays: 11 },
      { pct: 0.75, optionPrice: 9.1, stockPrice: 202.3, probability: 0.27, expectedDays: 15 },
    ],
    invalidation: { probability: 0.3, expectedDays: 18 },
    race: RUN_RACE,
  };
  const mcRegion = () => within(screen.getByText('Monte Carlo Profit Target').closest('section')!);

  beforeEach(() => {
    (api.getStockQuote as jest.Mock).mockResolvedValue({ symbol: 'AAPL', price: 186.1 });
    (api.getContractQuote as jest.Mock).mockResolvedValue({
      price: 5.2, delta: 0.45, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100,
    });
    (api.getStructuralStop as jest.Mock).mockResolvedValue({
      available: true, price: 180, source: 'order_block', confidence: 75, distancePct: 3.3,
    });
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue(RUN_RESPONSE);
  });

  const run = async () => {
    render(<TradeCard data={card} />);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
    });
    await waitFor(() => expect(screen.getAllByTestId('segment-Target first')).toHaveLength(3));
  };

  it('before a run: fires no simulation, offers the explicit action and says nothing has run', async () => {
    render(<TradeCard data={card} />);
    await act(async () => { await Promise.resolve(); });
    expect(api.getFirstPassageEstimate).not.toHaveBeenCalled();
    const region = mcRegion();
    expect(region.getByRole('button', { name: 'Run Monte Carlo Estimate' })).toBeEnabled();
    expect(region.getByText('Not yet estimated')).toBeVisible();
    expect(region.getByText(/No estimate yet\. Nothing runs automatically/)).toBeVisible();
    // Both run barriers and both barrier-time stop values (#606), stated once
    // before any estimate (#610 G7).
    expect(region.getAllByText('Unavailable — run or re-run estimate to confirm barriers')).toHaveLength(1);
    expect(region.queryByRole('table', { name: 'Monte Carlo targets' })).not.toBeInTheDocument();
    expect(screen.queryByText(/Same simulation as the Monte Carlo card above/)).not.toBeInTheDocument();
  });

  it('after a run: every returned target row keeps its own premium, stock target, touch probability and time', async () => {
    await run();
    const region = mcRegion();
    expect(region.queryByText(/No estimate yet/)).not.toBeInTheDocument();
    expect(within(region.getByRole('table', { name: 'Monte Carlo targets' })).getAllByRole('row')).toHaveLength(4);
    for (const [label, premium, stock, prob, time] of [
      ['T25%', '$6.50', '$194.10', '61%', '~7d'],
      ['T50%', '$7.80', '$198.20', '42%', '~11d'],
      ['T75%', '$9.10', '$202.30', '27%', '~15d'],
    ]) {
      // The label's id cell, then the row body that holds that target's own values.
      const row = within(region.getByText(label).parentElement!.parentElement!);
      expect(row.getByText(premium)).toBeVisible();
      expect(row.getByText(stock)).toBeVisible();
      expect(row.getByText(prob)).toBeVisible();
      expect(row.getByText(time)).toBeVisible();
    }
  });

  it('labels the race barriers as simulation inputs and points to, rather than repeats, the actual Exit Plan settings', async () => {
    await run();
    const region = mcRegion();
    expect(region.getByText('Stop context · simulation inputs and barrier-time race values')).toBeVisible();
    expect(region.getByText('Stock barrier (run input)').parentElement).toHaveTextContent('$180.00 stock');
    expect(region.queryByText('Execution stock invalidation')).not.toBeInTheDocument();
    expect(region.getByText(/differs from the Exit Plan invalidation \$179\.64/)).toBeVisible();
    const why = region.getByText(/Simulation inputs are what the last run raced against/);
    expect(why).toHaveTextContent(/Arithmetic Plan structural \+ ATR stop.*structural level.*Exit Plan stock invalidation/);
    expect(why).toHaveTextContent(/Premium stop field when you changed it to a loss below the run's premium, else the risk-rules default percentage/);
    expect(why).toHaveTextContent(/never copies one into the other/);
  });

  it('after a premium-stop edit: hides the race and its inputs but keeps the target-touch rows and stock-stop touch', async () => {
    await run();
    fireEvent.click(screen.getByLabelText('Edit Premium stop'));
    const input = screen.getByDisplayValue('3.12');
    await act(async () => {
      fireEvent.change(input, { target: { value: '2.50' } });
      fireEvent.blur(input);
    });
    expect(screen.getByText(/Barriers changed — re-run the estimate/)).toBeInTheDocument();
    expect(screen.queryAllByTestId('segment-Target first')).toHaveLength(0);
    expect(screen.queryByText(/Stock-stop value at barrier time/)).not.toBeInTheDocument();
    expect(document.querySelector('details summary')?.textContent ?? '').not.toMatch(/Stop medians, full risk/);
    expect(screen.getByText(/stock-stop probability is unaffected by the premium stop: 30%/)).toBeInTheDocument();
    const region = mcRegion();
    expect(region.getAllByText('Unavailable — run or re-run estimate to confirm barriers')).toHaveLength(4);
    expect(region.getAllByRole('row')).toHaveLength(4);
    expect(region.getByText('61%')).toBeVisible();
  });
});
