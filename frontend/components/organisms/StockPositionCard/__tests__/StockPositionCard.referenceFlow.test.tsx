import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { StockPositionCard } from '..';
import { useScanStore } from '@/lib/scanStore';
import { stockExecutionIdentity, useStockOrderOwnershipStore } from '@/lib/stockExecutionSession';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { api } from '@/lib/api';
import type { PositionCardData, StockExitPlan } from '@/types/stockDomain';

jest.mock('@/lib/api', () => ({ api: {
  getBrokerStatus: jest.fn().mockResolvedValue({}), getStockQuote: jest.fn().mockResolvedValue({ price: 151 }),
  getStockExitPlan: jest.fn(), getStockFirstPassage: jest.fn(), getStructuralStop: jest.fn(),
} }));
jest.mock('@/components/organisms/StockAutoTradeArm', () => ({ StockAutoTradeArm: () => null }));
jest.mock('@/components/molecules/FundamentalHealthCard', () => ({ FundamentalHealthCard: () => <p>Fundamental context</p> }));
const card: PositionCardData = {
  symbol: 'AAPL', company: 'Apple', price: 150, direction: 'Bullish',
  strategy: { strategy: 'pullback_ema', entry_price: 150, stop_price: 145, target_price: 160, targets: [160, 165, 170], rr_ratio: 2, atr: 3, detail: { observation: 'Original strategy observation' } },
  backtest: { n_trades: 20, win_rate: .6, total_return_pct: 12, max_drawdown_pct: 5, expectancy: .4, sharpe: 1.2, confidence: 60, passes_gate: true, summary_text: 'Complete recorded backtest summary' },
  stock_score: 80, stock_status: 'CAUTION', shares: 30, dollar_risk: 150, dollar_size: 4500, confidence: 70, confidence_text: 'Full confidence explanation',
  stock_explanation: { status: 'PASS', components: { trend: { name: 'Trend factor', measured: true, raw_score: 80, weight: .3, contribution: 24, status: 'PASS', detail: { threshold: 0, observation: 'Complete factor observation' } } } } as unknown as PositionCardData['stock_explanation'],
};
const plan: StockExitPlan = {
  stop: { price: 144, riskPerShare: 6, source: 'atr_widened', structuralPrice: 147, structuralSource: 'swing_low', structuralConfidence: 60, atrFloorPrice: 144, distanceDollar: 3, probability: .34, expectedDays: 6.5 },
  targets: [{ rrRatio: 2, arithmeticPrice: 162, price: 162, tpSource: 'arithmetic', structuralPrice: null, distanceDollar: null, toleranceDollar: .9, rewardPerShare: 12, probability: .41, expectedDays: 7.5, qualityGood: false, qualityReasons: ['stop_widened'] }],
  atr: 3, recommendedShares: 83, riskBudget: 498, daysBasis: 'trading', horizonDays: 10, modelCaveat: 'Material model caveat',
  race: { stopPrice: 144, nPaths: 2000, outcomes: [{ targetPrice: 162, pTargetFirst: .3999, pStopFirst: .34, pNeither: .2601, weightTarget: .4, weightStop: .34, weightNeither: .26, daysTarget: 7.5, daysStop: 6.5, terminalMean: 152.4 }] },
};
const originalFetch = global.fetch;
afterEach(() => { global.fetch = originalFetch; });
const before = (first: Element, second: Element) => expect(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
const disclosure = (label: string) => screen.getByText(label, { selector: 'summary, summary > span:first-child' }).closest('summary')!.parentElement as HTMLDetailsElement;
const open = (label: string) => { const el = disclosure(label); fireEvent.click(el.querySelector('summary')!); return el; };
beforeEach(() => {
  jest.clearAllMocks();
  useScanStore.setState({ stockExecution: {}, stockExecutionGeneration: 0, stockScanResult: null, stockScanRequest: { bt_min_trades: 20, bt_min_win_rate: .5 } as never, stocksCardEdits: { scanId: null, picks: {}, invalidation: {}, premiumStop: {}, entryLimit: {}, maxLossOverride: {} } });
  useScanStore.getState().setStockScanResult({ scan_id: 'reference-flow', candidates: [card], rejected: [], timestamp: 't' } as never);
  useScanStore.setState({ stockScanRequest: { bt_min_trades: 20, bt_min_win_rate: .5 } as never });
  useStockOrderOwnershipStore.setState({ bySymbol: {} });
  usePortfolioStore.setState({ positions: [], lastSyncError: null });
  (api.getStockExitPlan as jest.Mock).mockResolvedValue(plan);
});
it('orders sentiment, fundamentals, identity and qualification before execution', async () => {
  const view = render(<StockPositionCard card={card} strategyKey="pullback_ema" presentation="position" />);
  await act(async () => {});
  before(view.container.querySelector('#market-sentiment')!, view.container.querySelector('#fundamentals')!);
  before(view.container.querySelector('#fundamentals')!, screen.getByLabelText('Stock context'));
  before(screen.getByLabelText('Stock context'), view.container.querySelector('#qualification')!);
  before(view.container.querySelector('#qualification')!, screen.getByRole('region', { name: 'Execution risk' }));
});
it('starts qualification and backtest closed and retains every nested evidence value', async () => {
  render(<StockPositionCard card={card} strategyKey="pullback_ema" presentation="position" />);
  await act(async () => {});
  expect(disclosure('Stock Qualification')).not.toHaveAttribute('open');
  expect(disclosure('Backtest Evidence')).not.toHaveAttribute('open');
  expect(screen.getByText('Trend factor')).not.toBeVisible();
  const stock = open('Stock Qualification');
  for (const value of ['Final verdict: CAUTION', 'Scorer evidence before final caps: PASS', 'weight 30% · contribution 24.00', 'Measured · PASS', 'Stock score is a filter, not a probability of profit.']) expect(stock).toHaveTextContent(value);
  fireEvent.click(within(stock).getByText('Observations', { selector: 'summary' }));
  expect(within(stock).getByText('threshold: 0')).toBeVisible();
  expect(within(stock).getByText('observation: Complete factor observation')).toBeVisible();
  const backtest = open('Backtest Evidence');
  for (const value of ['60% win rate', '20', '0.40', '12.0%', '5.0%', '1.20', '70%', 'Full confidence explanation', 'Complete recorded backtest summary', 'Scan thresholds: ≥ 20 trades · ≥ 50% win rate']) expect(within(backtest).getByText(value)).toBeVisible();
});
it('keeps stop and risk before methods, editors after methods, and structure closed', async () => {
  const view = render(<StockPositionCard card={card} strategyKey="pullback_ema" presentation="position" />);
  await act(async () => {});
  const methods = view.container.querySelector('#calculations')!;
  before(screen.getByText('STOP'), methods);
  before(screen.getByRole('region', { name: 'Execution risk' }), methods);
  for (const label of ['ENTRY', 'SHARES', 'T1 TARGET']) before(methods, screen.getByText(label));
  expect(disclosure('Structure & Stops')).not.toHaveAttribute('open');
  expect(screen.getByRole('button', { name: 'Check structure' })).not.toBeVisible();
  open('Structure & Stops');
  expect(screen.getByRole('button', { name: 'Check structure' })).toBeVisible();
});
it('keeps scanned strategy, chronology and complete Arithmetic race in closed method disclosures', async () => {
  const view = render(<StockPositionCard card={card} strategyKey="pullback_ema" presentation="position" />);
  await act(async () => {});
  expect(within(screen.getByRole('region', { name: 'Original ladder evidence' })).getByText('Initial scanned strategy · original targets', { selector: 'summary' })).toBeInTheDocument();
  expect(disclosure('Initial scanned strategy · original targets')).not.toHaveAttribute('open');
  expect(disclosure('Latest calculation')).not.toHaveAttribute('open');
  expect(view.container.querySelector('#calculations')).toContainElement(disclosure('Latest calculation'));
  const initial = open('Initial scanned strategy · original targets');
  expect(within(initial).getByText('Original target allocations unavailable')).toBeVisible();
  fireEvent.click(within(initial).getByText('Strategy observations', { selector: 'summary' }));
  expect(within(initial).getByText('observation: Original strategy observation')).toBeVisible();
  fireEvent.click(calculationButton('Arithmetic plan'));
  await screen.findByText('Material model caveat');
  expect(disclosure('Which comes first · graphical outcomes & full details')).not.toHaveAttribute('open');
  screen.getAllByRole('meter').forEach(meter => expect(meter).not.toBeVisible());
  const race = open('Which comes first · graphical outcomes & full details');
  expect(within(race).getAllByRole('meter').map(m => m.getAttribute('value'))).toEqual(['0.4', '0.34', '0.26']);
  for (const text of ['Target first 40% (~7.5 trading days)', 'Stock stop first 34% (~6.5 trading days)', 'neither 26% (~$152.40)', '2,000 simulated paths', 'every path is counted once']) expect(race).toHaveTextContent(text);
  const latest = open('Latest calculation');
  expect(latest).toHaveTextContent('Stop 144.00 · risk/share 6.00 · 10 trading days');
  expect(latest).toHaveTextContent('T1 162.00 · 41% · ~7.5 trading days');
  expect(screen.getByText('Material model caveat')).toBeVisible();
});
it('leaves default embedded editors and evidence unchanged', async () => {
  const view = render(<StockPositionCard card={card} strategyKey="pullback_ema" />);
  await act(async () => {});
  expect(view.container.querySelector('#calculations')).not.toBeInTheDocument();
  expect(view.container.querySelector('#qualification')).not.toBeInTheDocument();
  expect(screen.queryByText('Stock Qualification')).not.toBeInTheDocument();
  const grid = screen.getByText('ENTRY').closest('div')!.parentElement!;
  expect(grid.parentElement).toBe(view.container.firstElementChild);
  expect(within(grid).getByText('STOP')).toBeVisible();
  expect(within(grid).getByText('T1 TARGET')).toBeVisible();
  expect(screen.getByRole('button', { name: 'Check structure' })).toBeVisible();
});

it('saves the moved execution editors and allocations while Arithmetic selection stays intent', async () => {
  const saves: Record<string, unknown>[] = [];
  global.fetch = jest.fn(async (url, init) => {
    if (String(url).endsWith('/api/portfolio') && init?.method === 'POST') {
      const saved = JSON.parse(String(init.body)); saves.push(saved);
      return { ok: true, status: 201, json: async () => saved } as Response;
    }
    return { ok: true, json: async () => ({}) } as Response;
  });
  render(<StockPositionCard card={card} strategyKey="pullback_ema" presentation="position" />);
  await act(async () => {});
  const edit = (label: string, value: string) => {
    const cell = screen.getAllByText(label).map(el => el.closest('div')!).find(el => el.querySelector('[role="button"]'))!;
    fireEvent.click(within(cell).getByRole('button'));
    fireEvent.change(within(cell).getByRole('spinbutton'), { target: { value } });
    fireEvent.blur(within(cell).getByRole('spinbutton'));
  };
  edit('ENTRY', '151'); edit('STOP', '146'); edit('SHARES', '12');
  open('Edit T1 / T2 / T3 and share allocations');
  edit('T1 TARGET', '163'); edit('T1 SHARES', '2');
  const identity = stockExecutionIdentity(useScanStore.getState(), 'AAPL')!;
  expect(useScanStore.getState().stockExecution[identity].overlay).toMatchObject({ entry: 151, stop: 146, shares: 12, t1: 163, sharesT1: 2, sharesT2: 4, sharesT3: 4 });
  fireEvent.click(calculationButton('Arithmetic plan'));
  await screen.findByText('Material model caveat');
  fireEvent.click(screen.getByRole('radio', { name: 'Arithmetic' }));
  fireEvent.click(screen.getByRole('radio', { name: '2R' }));
  expect(screen.getByRole('region', { name: 'Selected stock plan' })).toHaveTextContent('Arithmetic uses $144.00; your execution stop remains $146.00');
  fireEvent.click(screen.getByRole('button', { name: 'Add to Portfolio' }));
  await screen.findByRole('button', { name: 'Added to Portfolio' });
  expect(saves).toHaveLength(1);
  expect(saves[0]).toMatchObject({ qty: 12, entryPrice: 151, stop: 146, pickedMethod: 'arithmetic', pickedRowStockPrice: 162 });
  expect(saves[0].targets).toEqual([163, 165, 170].map((price, i) => ({ id: `T${i + 1}`, stockPrice: price, targetPrice: price, contractsToSell: i === 0 ? 2 : 4, status: 'PENDING' })));
  expect(saves[0].tradeCardSnapshot).toMatchObject({ edited: { entry: 151, stop: 146, targets: [163, 165, 170], shares: 12 }, strategy: card.strategy });
});

it('starts with Ladder alone and compares two or three methods without requesting or editing execution', async () => {
  render(<StockPositionCard card={card} strategyKey="pullback_ema" presentation="position" />);
  await act(async () => {});
  const controls = screen.getByRole('group', { name: 'View method results' });
  expect(within(controls).getByRole('button', { name: 'Ladder' })).toHaveAttribute('aria-pressed', 'true');
  expect(screen.getByRole('region', { name: 'Original ladder evidence' })).toBeVisible();
  expect(screen.queryByRole('region', { name: 'Arithmetic evidence' })).not.toBeInTheDocument();
  const before = useScanStore.getState();
  fireEvent.click(within(controls).getByRole('button', { name: 'Monte Carlo' }));
  fireEvent.click(within(controls).getByRole('button', { name: 'Compare' }));
  expect(screen.getByRole('region', { name: 'Monte Carlo evidence' })).toBeVisible();
  expect(screen.getByRole('region', { name: 'Arithmetic evidence' })).toBeVisible();
  expect(screen.queryByRole('region', { name: 'Original ladder evidence' })).not.toBeInTheDocument();
  fireEvent.click(within(controls).getByRole('button', { name: 'Ladder' }));
  expect(screen.getAllByTestId('visible-method-card')).toHaveLength(3);
  fireEvent.click(within(controls).getByRole('button', { name: 'Monte Carlo' }));
  expect(screen.getAllByTestId('visible-method-card')).toHaveLength(2);
  expect(within(controls).getByRole('button', { name: 'Arithmetic' })).toBeDisabled();
  expect(api.getStockExitPlan).not.toHaveBeenCalled();
  expect(api.getStockFirstPassage).not.toHaveBeenCalled();
  expect(useScanStore.getState().stockExecution).toBe(before.stockExecution);
  expect(useScanStore.getState().stocksCardEdits).toBe(before.stocksCardEdits);
});

it('keeps a calculated result, disclosures and explicit pick while changing views', async () => {
  render(<StockPositionCard card={card} strategyKey="pullback_ema" presentation="position" />);
  await act(async () => {});
  const controls = screen.getByRole('group', { name: 'View method results' });
  fireEvent.click(within(controls).getByRole('button', { name: 'Arithmetic' }));
  fireEvent.click(screen.getByRole('button', { name: 'Arithmetic plan' }));
  await screen.findByText('Material model caveat');
  expect(screen.getByRole('region', { name: 'Selected stock plan' })).toHaveTextContent('Choose a method');
  fireEvent.click(screen.getByRole('radio', { name: 'Arithmetic' }));
  fireEvent.click(screen.getByRole('radio', { name: '2R' }));
  const race = open('Which comes first · graphical outcomes & full details');
  const state = useScanStore.getState();
  fireEvent.click(within(controls).getByRole('button', { name: 'Ladder' }));
  fireEvent.click(within(controls).getByRole('button', { name: 'Arithmetic' }));
  expect(race).toHaveAttribute('open');
  expect(screen.getByRole('region', { name: 'Arithmetic evidence' })).toHaveTextContent('Material model caveat');
  expect(useScanStore.getState().stockExecution).toBe(state.stockExecution);
  expect(useScanStore.getState().stocksCardEdits).toBe(state.stocksCardEdits);
  expect(api.getStockExitPlan).toHaveBeenCalledTimes(1);
});

function calculationButton(name: string | RegExp) {
  const compare = screen.getByRole('button', { name: 'Compare' });
  if (compare.getAttribute('aria-pressed') !== 'true') fireEvent.click(compare);
  return screen.getByRole('button', { name });
}

it.each(['Bullish', 'Bearish'] as const)('keeps method-owned %s outcomes, zero probability and null/fractional medians in the compact tables', async direction => {
  const bearish = direction === 'Bearish';
  const current = { ...card, direction, strategy: { ...card.strategy, stop_price: bearish ? 155 : 145, targets: bearish ? [140, 135, 130] : [160, 165, 170] } };
  useScanStore.getState().setStockScanResult({ scan_id: `compact-${direction}`, candidates: [current], rejected: [], timestamp: 't' } as never);
  (api.getStockExitPlan as jest.Mock).mockResolvedValue({ ...plan, recommendedShares: 625, stop: { ...plan.stop, price: bearish ? 156 : 144 }, targets: [{ ...plan.targets[0], price: bearish ? 138 : 162, rewardPerShare: 11.99, probability: 0, expectedDays: null }] });
  (api.getStockFirstPassage as jest.Mock).mockResolvedValue({ targets: [{ price: bearish ? 137 : 163, probability: .62, expectedDays: 4.5 }], invalidation: { probability: 0, expectedDays: null }, horizonDays: 10, modelCaveat: 'MC supplied caveat' });
  render(<StockPositionCard card={current} strategyKey="pullback_ema" presentation="position" />);
  await act(async () => {});
  const ladder = screen.getByRole('region', { name: 'Original ladder evidence' });
  const ladderTable = within(ladder).getAllByRole('table')[0];
  expect(within(ladderTable).getAllByText('Not supplied')).toHaveLength(6);
  expect(ladderTable).toHaveTextContent('$300.00');
  fireEvent.click(calculationButton('Arithmetic plan'));
  await screen.findByText('Material model caveat');
  const arithmetic = screen.getByRole('region', { name: 'Arithmetic evidence' });
  const arithmeticTable = within(arithmetic).getAllByRole('table')[0];
  expect(arithmeticTable).toHaveTextContent('$359.70');
  expect(arithmeticTable).toHaveTextContent('0%');
  expect(arithmeticTable).toHaveTextContent('unlikely');
  expect(arithmetic).toHaveTextContent(bearish ? 'Arithmetic final stop $156.00' : 'Arithmetic final stop $144.00');
  expect(arithmetic).toHaveTextContent(`The card's stop is $${bearish ? '155' : '145'}.00`);
  expect(arithmetic).toHaveTextContent('Concentration:');
  fireEvent.click(calculationButton('Estimate'));
  await screen.findByText('MC supplied caveat');
  const mc = screen.getByRole('region', { name: 'Monte Carlo evidence' });
  const mcTable = within(mc).getAllByRole('table')[0];
  expect(mcTable).toHaveTextContent('$390.00');
  expect(mcTable).toHaveTextContent('~4.5 trading days');
  expect(mcTable).toHaveTextContent('62%');
  expect(within(mc).getByText('Probability window: 10 trading days')).toBeVisible();
  expect(mc.querySelector('#race')).toBeNull();
});
