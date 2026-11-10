/** TC-ALIGN-03 (#606): Monte Carlo essentials — inputs and Run, then the run's
 *  stock/option barriers beside the barrier-time stop value and loss from the
 *  CURRENT race, a compact target table, provenance behind a closed disclosure
 *  and the graphical Barrier Race nested in a default-closed expansion.
 *  Every transport is a jest mock; opening a disclosure never calculates. */
import '@testing-library/jest-dom';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { api } from '@/lib/api';
import { TradeCard } from '@/components/organisms/TradeCard';
import type { BarrierRace, BarrierRaceOutcome, FirstPassageContext, TradeCardData } from '@/types/domain';

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

const outcome = (targetPct: number, i: number, o: Partial<BarrierRaceOutcome> = {}): BarrierRaceOutcome => ({
  targetPct, targetOptionPrice: [6.5, 7.8, 9.1][i],
  pTargetFirst: 0.2685, pStockStopFirst: 0.0045, pPremiumStopFirst: 0.682, pNeither: 0.045,
  daysTarget: 7 + i, daysStockStop: 20, daysPremiumStop: 12, daysAnyPathReachedStop: 18,
  weightTargetFirst: 0.27, weightStockStopFirst: 0.01, weightPremiumStopFirst: 0.68, weightNeither: 0.04,
  terminalMean: 4, rewardDollar: [1.3, 2.6, 3.9][i], repriceDaysStockStop: 18,
  stopRepricedValue: 1.1, riskStockStop: 4.1, riskPremiumStop: 3.12,
  rrStockStop: [1.3, 2.6, 3.9][i] / 4.1, rrPremiumStop: 0.4, edgePerContract: -120, ...o,
});
const race = (o: Partial<BarrierRace> = {}, perOutcome: (i: number) => Partial<BarrierRaceOutcome> = () => ({})): BarrierRace => ({
  outcomes: [0.25, 0.5, 0.75].map((pct, i) => outcome(pct, i, perOutcome(i))),
  premiumStopPrice: 2.08, premiumStopPct: 0.6, stockStopPrice: 180, premiumUsed: 5.2, ivSolved: true, nPaths: 2000, ...o,
});
const response = (r: BarrierRace | null = race()) => ({
  targets: [
    { pct: 0.25, optionPrice: 6.5, stockPrice: 194.1, probability: 0.61, expectedDays: 7 },
    { pct: 0.5, optionPrice: 7.8, stockPrice: null, probability: 0.42, expectedDays: null },
    { pct: 0.75, optionPrice: 9.1, stockPrice: 202.3, probability: 0.27, expectedDays: 15 },
  ],
  invalidation: { probability: 0.3, expectedDays: 18 },
  race: r,
});
const context: FirstPassageContext = { premium: 5.2, delta: 0.45, targetPct: { t1: 0.25, t2: 0.5, t3: 0.75 } };

const mcCard = () => screen.getByRole('region', { name: 'Monte Carlo Profit Target' });
const mc = () => within(mcCard());
const stopSlot = () => within(mcCard().querySelector('[data-slot="stop"]') as HTMLElement);
const kv = (label: string) => stopSlot().getByText(label).parentElement!;
const raceDetails = () => mc().getByText('Barrier Race · graphical outcomes & details').closest('details') as HTMLDetailsElement;
const segments = () => screen.queryAllByTestId('segment-Target first');
const callCount = () => Object.values(api).reduce((n, fn) => n + (fn as jest.Mock).mock.calls.length, 0);

async function run() {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: /run monte carlo estimate/i }));
  });
  await waitFor(() => expect(segments()).toHaveLength(3));
}

async function editPremiumStop(value: string) {
  fireEvent.click(screen.getByLabelText('Edit Premium stop'));
  const input = screen.getByDisplayValue('3.12');
  await act(async () => {
    fireEvent.change(input, { target: { value } });
    fireEvent.blur(input);
  });
}

beforeEach(() => {
  localStorage.clear();
  jest.clearAllMocks();
  (api.getStockQuote as jest.Mock).mockResolvedValue({ symbol: 'AAPL', price: 186.1 });
  (api.getContractQuote as jest.Mock).mockResolvedValue({ price: 5.2, delta: 0.45, theta: -0.08, ivRank: 45, spread: 0.1, volume: 100 });
  (api.getStructuralStop as jest.Mock).mockResolvedValue({ available: true, price: 180, source: 'order_block', confidence: 75, distancePct: 3.3 });
  (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue(response());
});

describe('stop consequence beside the barriers', () => {
  it('unrun: inputs and Run come first, every stop value is unavailable and nothing is calculated', async () => {
    render(<TradeCard data={card} />);
    await act(async () => { await Promise.resolve(); });
    expect(api.getFirstPassageEstimate).not.toHaveBeenCalled();
    const inputs = mc().getByRole('spinbutton', { name: 'T1 profit target %' });
    const runButton = mc().getByRole('button', { name: 'Run Monte Carlo Estimate' });
    // #610 G7: before any estimate the four facts are one line that names them.
    const stopLine = stopSlot().getByText('Unavailable — run or re-run estimate to confirm barriers').parentElement!;
    expect(inputs.compareDocumentPosition(runButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(runButton.compareDocumentPosition(stopLine) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(stopLine).toHaveTextContent(
      /Stock barrier, option-price barrier, and option value and loss at the stock stop \(barrier time\)/);
    expect(stopLine).toBeVisible();
  });

  it('fresh run: shows both run barriers and the race value and loss at the stock stop with its barrier-time basis', async () => {
    render(<TradeCard data={card} />);
    await run();
    expect(kv('Stock barrier (run input)')).toHaveTextContent('$180.00 stock');
    expect(kv('Option-price barrier (run input)')).toHaveTextContent('$2.08/share');
    expect(kv('Option value at stock stop (barrier time)')).toHaveTextContent('$1.10/share');
    expect(kv('Loss at stock stop (barrier time, per contract)')).toHaveTextContent('$410.00/contract');
    fireEvent.click(mc().getByText('Monte Carlo model, inputs & provenance'));
    const basis = mc().getByText(/Barrier Race estimate, per share, same for every target/);
    expect(basis).toBeVisible();
    expect(basis).toHaveTextContent('repriced at 18d — the median day any path reaches the stop');
    // Never the current-time (Arithmetic / stop-cost) basis.
    expect(stopSlot().queryByText(/today's days to expiry|priced today|Current-time/)).not.toBeInTheDocument();
  });

  it('labels a target-dependent stop value with the selected race target, and is unavailable without one', async () => {
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue(
      response(race({}, (i) => ({ stopRepricedValue: [1.1, 1.2, 1.3][i], riskStockStop: [4.1, 4.0, 3.9][i] }))),
    );
    render(<TradeCard data={card} />);
    await run();
    expect(kv('Option value at stock stop (barrier time)')).toHaveTextContent(/Unavailable — differs by target/);
    expect(kv('Loss at stock stop (barrier time, per contract)')).toHaveTextContent(/Unavailable — differs by target/);
    fireEvent.click(screen.getByRole('button', { name: 'Use Barrier Race T50%' }));
    expect(kv('Option value at stock stop (barrier time)')).toHaveTextContent('$1.20/share');
    expect(kv('Loss at stock stop (barrier time, per contract)')).toHaveTextContent('$400.00/contract');
    expect(stopSlot().getByText(/Barrier Race estimate · for your selected Barrier Race target T50%/)).toBeVisible();
  });

  it('restored: an earlier saved race never supplies the barriers or stop values', () => {
    render(<TradeCard data={{ ...card, exit: { ...card.exit, firstPassage: response(), firstPassageContext: context } }} />);
    for (const label of ['Stock barrier (run input)', 'Option-price barrier (run input)',
      'Option value at stock stop (barrier time)', 'Loss at stock stop (barrier time, per contract)']) {
      expect(kv(label)).toHaveTextContent(/Unavailable/);
    }
    expect(stopSlot().queryByText('$1.10/share')).not.toBeInTheDocument();
    expect(segments()).toHaveLength(0);
    // The independently valid target-touch rows stay.
    expect(mc().getByRole('table', { name: 'Monte Carlo targets' })).toBeVisible();
  });

  it('stale then re-run: a moved barrier hides the values behind a visible notice; a re-run restores them', async () => {
    render(<TradeCard data={card} />);
    await run();
    await editPremiumStop('2.50');
    expect(kv('Option value at stock stop (barrier time)')).toHaveTextContent(/Unavailable/);
    expect(kv('Loss at stock stop (barrier time, per contract)')).toHaveTextContent(/Unavailable/);
    const notice = stopSlot().getByText(/A barrier moved after this run/);
    expect(notice).toBeVisible();
    expect(notice.closest('details')).toBeNull();
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue(response(race({ premiumStopPrice: 2.7 })));
    await run();
    expect(stopSlot().queryByText(/A barrier moved after this run/)).not.toBeInTheDocument();
    expect(kv('Option-price barrier (run input)')).toHaveTextContent('$2.70/share');
    expect(kv('Loss at stock stop (barrier time, per contract)')).toHaveTextContent('$410.00/contract');
  });

  it('keeps the fallback-volatility caution visible beside the values while the race is closed', async () => {
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue(response(race({ ivSolved: false })));
    render(<TradeCard data={card} />);
    await run();
    expect(raceDetails().open).toBe(false);
    const caution = stopSlot().getByText(/generic fallback volatility/);
    expect(caution).toBeVisible();
  });
});

describe('no duplicated actual Exit Plan readout', () => {
  it('drops the actual-settings block and points to the shared Exit Plan when the run input differs', async () => {
    render(<TradeCard data={card} />);
    await run();
    expect(mc().queryByText('Actual Exit Plan settings (not changed by Monte Carlo)')).not.toBeInTheDocument();
    expect(mc().queryByText('Execution stock invalidation')).not.toBeInTheDocument();
    expect(mc().queryByText('Execution premium-stop loss amount')).not.toBeInTheDocument();
    const note = stopSlot().getByText(/differs from the Exit Plan invalidation \$179\.64/);
    expect(note).toBeVisible();
    expect(note.closest('details')).toBeNull();
    expect(within(note).getByRole('link', { name: /Exit Plan/ })).toHaveAttribute('href', '#exit-plan');
  });
});

describe('compact target table', () => {
  it('lists every target in one table with target, stock, option, probability, time and outcome columns', async () => {
    render(<TradeCard data={card} contracts={2} />);
    await run();
    const table = mc().getByRole('table', { name: 'Monte Carlo targets' });
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual([
      'Target', 'Stock price', 'Option value', 'Probability (independent touch)', 'Conditional time (calendar days)', 'Est. dollar outcome',
    ]);
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows.map((r) => Array.from(r.querySelectorAll('th,td')).map((c) => c.textContent))).toEqual([
      ['T25%', '$194.10', '$6.50', '61%', '~7d', '$260.00'],
      ['T50%', 'not reachable', '$7.80', '42%', 'Unavailable — no conditional median', '$520.00'],
      ['T75%', '$202.30', '$9.10', '27%', '~15d', '$780.00'],
    ]);
    expect(table).toBeVisible();
    // #610 G8: one short visible footnote; the full sentence is in the model disclosure.
    expect(mc().getByText(/^Probability counts each target's touch on its own.*conditional median/)).toBeVisible();
    expect(mc().getByText(/measured on its own.*conditional on reaching the target/)).toBeInTheDocument();
  });
});

describe('disclosures', () => {
  it('nests the graphical race inside the Monte Carlo card, closed by default and still mounted', async () => {
    render(<TradeCard data={card} />);
    await run();
    const details = raceDetails();
    expect(mcCard()).toContainElement(details);
    expect(details.open).toBe(false);
    for (const seg of segments()) {
      expect(details).toContainElement(seg);
      expect(seg).not.toBeVisible();
    }
    expect(within(details).getAllByRole('button', { name: /Use Barrier Race/ })).toHaveLength(3);
  });

  it('opening the race or the provenance disclosure runs nothing and changes nothing', async () => {
    const onMethodPickChange = jest.fn();
    render(<TradeCard data={card} onMethodPickChange={onMethodPickChange} />);
    await run();
    const before = callCount();
    onMethodPickChange.mockClear();
    fireEvent.click(mc().getByText('Barrier Race · graphical outcomes & details'));
    fireEvent.click(mc().getByText('Monte Carlo model, inputs & provenance'));
    await act(async () => { await Promise.resolve(); });
    expect(raceDetails().open).toBe(true);
    expect(segments()[0]).toBeVisible();
    expect(callCount()).toBe(before);
    expect(onMethodPickChange).not.toHaveBeenCalled();
  });

  it('keeps the race expansion open across a re-run (mounted, not recreated)', async () => {
    render(<TradeCard data={card} />);
    await run();
    fireEvent.click(mc().getByText('Barrier Race · graphical outcomes & details'));
    const before = raceDetails();
    await run();
    expect(raceDetails()).toBe(before);
    expect(raceDetails().open).toBe(true);
  });

  it('moves model, formula and provenance prose into a default-closed disclosure', async () => {
    render(<TradeCard data={{ ...card, spreadType: 'bear_put' }} />);
    await run();
    const provenance = mc().getByText('Monte Carlo model, inputs & provenance').closest('details') as HTMLDetailsElement;
    expect(provenance.open).toBe(false);
    for (const text of [/GBM simulated stock paths/, /calendar-day steps to expiry/, /Current inherited holding\/repricing settings/,
      /Simulation inputs are what the last run raced against/, /Stored Monte Carlo run stock entry/]) {
      const node = mc().getByText(text);
      expect(provenance).toContainElement(node);
      expect(node).not.toBeVisible();
    }
    // A caveat that qualifies the visible outcome column stays visible.
    const spread = mc().getAllByText(/Selected-contract basis only; this is not a whole-spread outcome/)
      .filter((n) => n.closest('details') == null);
    expect(spread).toHaveLength(1);
    expect(spread[0]).toBeVisible();
  });
});

// The headline changes units only. Signed, true-zero and missing returned risks
// retain exactly the same availability and time/source basis as the full chain.
it.each<[number | null, number | null, string]>([
  [-1.25, 6.45, '-$125.00/contract · no loss (worth at least as much at the stop as it cost)'],
  [0, 5.2, '$0.00/contract · no loss (worth at least as much at the stop as it cost)'],
  [null, null, 'Unavailable — could not reprice at the stop'],
])('keeps returned stock-stop risk %s honest in the per-contract headline', async (riskStockStop, stopRepricedValue, expected) => {
  (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue(response(race({}, () => ({ riskStockStop, stopRepricedValue }))));
  render(<TradeCard data={card} />);
  await run();
  expect(kv('Loss at stock stop (barrier time, per contract)')).toHaveTextContent(expected);
  expect(stopSlot().getByText(/Barrier Race estimate · same for every target/)).toBeVisible();
});

it.each([undefined, Number.NaN, -1, Infinity])('keeps a sparse race with invalid repricing time %s renderable', async (elapsed) => {
  (api.getFirstPassageEstimate as jest.Mock).mockResolvedValue(response(race({}, () => ({
    repriceDaysStockStop: elapsed as number, riskStockStop: null, stopRepricedValue: null,
  }))));
  render(<TradeCard data={card} />);
  await run();
  // NaN timestamps cannot establish equal stop consequences across rows.
  // Use the existing target selection so the displayed source is explicit.
  fireEvent.click(mc().getByText('Barrier Race · graphical outcomes & details'));
  fireEvent.click(screen.getByRole('button', { name: 'Use Barrier Race T50%' }));
  expect(kv('Loss at stock stop (barrier time, per contract)')).toHaveTextContent('Unavailable — could not reprice at the stop');
  expect(stopSlot().getByText(/Stock-stop repricing time unavailable/)).toBeVisible();
  expect(kv('Stock barrier (run input)')).toHaveTextContent('$180.00 stock');
});
