import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { StockPositionCard } from '@/components/organisms/StockPositionCard';
import { InitialStrategyTargets } from '@/components/organisms/StockPositionCard/InitialStrategyTargets';
import { useScanStore } from '@/lib/scanStore';
import { defaultStockOverlay, stockExecutionIdentity, STOCK_VALIDATION_UNAVAILABLE, useStockOrderOwnershipStore } from '@/lib/stockExecutionSession';
import { useSettingsStore } from '@/lib/settingsStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { api } from '@/lib/api';
import type { StockExitPlan, PositionCardData, StockScanResult } from '@/types/stockDomain';

// CSS modules are empty in Jest; retain the real primitive and expose its tone for assertions.
jest.mock('@/components/primitives/Data', () => {
  const actual = jest.requireActual('@/components/primitives/Data');
  const React = jest.requireActual('react');
  return { ...actual, Data: (props: { tone?: string }) => React.cloneElement(actual.Data(props), { 'data-tone': props.tone }) };
});

jest.mock('@/lib/api', () => ({ api: {
  getBrokerStatus: jest.fn().mockResolvedValue({}), getStockQuote: jest.fn(),
  getStockFirstPassage: jest.fn(), getStockExitPlan: jest.fn(), getStructuralStop: jest.fn(),
  postStockOrder: jest.fn(),
} }));
jest.mock('@/components/organisms/StockAutoTradeArm', () => ({ StockAutoTradeArm: () => null }));
jest.mock('@/components/molecules/MarketSentiment', () => ({ MarketSentiment: () => null }));
jest.mock('@/components/molecules/FundamentalHealthCard', () => ({ FundamentalHealthCard: () => null }));

const card = (symbol = 'AAPL', direction: 'Bullish' | 'Bearish' = 'Bullish'): PositionCardData => ({
  symbol, company: symbol, price: 150, direction,
  strategy: { strategy: 'pullback_ema', entry_price: 150, stop_price: 145, target_price: 160, targets: [160, 165, 170], rr_ratio: 2, atr: 3, detail: {} },
  backtest: { n_trades: 20, win_rate: .6, total_return_pct: 12, max_drawdown_pct: 5, expectancy: .4, sharpe: 1.2, confidence: 60, passes_gate: true, summary_text: 'ok' },
  stock_score: 80, stock_status: 'PASS', shares: 30, dollar_risk: 150, dollar_size: 4500, confidence: 70, confidence_text: 'High',
});
const scan = (candidates = [card()]): StockScanResult => ({ scan_id: 'same-scan', timestamp: 't', candidates, rejected: [] } as unknown as StockScanResult);
const estimate = { targets: [{ price: 160, probability: .62, expectedDays: 4 }], invalidation: { probability: .28, expectedDays: 6 }, horizonDays: 10, modelCaveat: null };
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; };
async function edit(label: string, value: string, scope: HTMLElement = document.body) {
  const cell = within(scope).getAllByText(label)[0].closest('div')!;
  fireEvent.click(within(cell).getByRole('button'));
  const input = within(cell).getByRole('spinbutton');
  fireEvent.change(input, { target: { value } }); fireEvent.blur(input);
}
beforeEach(() => {
  jest.clearAllMocks();
  useScanStore.setState({ stockExecution: {}, stockExecutionGeneration: 0, stockScanResult: null, stockScanRequest: null, stocksCardEdits: { scanId: null, picks: {}, invalidation: {}, premiumStop: {}, entryLimit: {}, maxLossOverride: {} } });
  useScanStore.getState().setStockScanResult(scan());
  useStockOrderOwnershipStore.setState({ bySymbol: {} });
  usePortfolioStore.setState({ positions: [] });
  useSettingsStore.setState({ ibkrPaper: { baseUrl: 'https://localhost', accountId: 'ACC' } } as never);
  (api.getStockQuote as jest.Mock).mockResolvedValue({ price: 151 });
  (api.getStockFirstPassage as jest.Mock).mockResolvedValue(estimate);
});


it('opts into the workspace without changing the default embedded card', () => {
  const view = render(<StockPositionCard card={card()} strategyKey="pullback_ema" {...{ presentation: 'position' } as object} />);
  expect(screen.getByRole('navigation', { name: 'Position sections' })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Your decision' })).toBeInTheDocument();
  view.rerender(<StockPositionCard card={card()} strategyKey="pullback_ema" />);
  expect(screen.queryByRole('navigation', { name: 'Position sections' })).not.toBeInTheDocument();
  const sizingGrid = screen.getByText('ENTRY').closest('div')!.parentElement!;
  expect(sizingGrid.parentElement).toBe(view.container.firstElementChild);
  expect(screen.getByRole('button', { name: 'Add to Portfolio' })).toBeDisabled();
});
it('shows real backtest scales, capped status, unavailable provenance and pending risk', () => {
  render(<StockPositionCard card={{ ...card(), stock_status: 'CAUTION' }} strategyKey="pullback_ema" {...{ presentation: 'position' } as object} />);
  expect(screen.getByText('Sharpe')).toBeInTheDocument();
  expect(screen.getByText('1.20')).toBeInTheDocument();
  expect(within(screen.getByRole('region', { name: 'Backtest evidence' })).getByText('70%')).toBeInTheDocument();
  expect(screen.getByText('12.0%')).toBeInTheDocument();
  expect(screen.getByText('Final verdict: CAUTION')).toBeInTheDocument();
  expect(screen.getByText('Scan thresholds unavailable')).toBeInTheDocument();
  expect(screen.getByText('Pending server validation')).toBeInTheDocument();
  expect(screen.getByText('Scorer factors unavailable')).toBeInTheDocument();
});
it('latest calculation is unavailable on remount and cleared edits never fall back', async () => {
  const view = render(<StockPositionCard card={card()} strategyKey="pullback_ema" {...{ presentation: 'position' } as object} />);
  fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));
  expect(await screen.findByText('Latest: Monte Carlo')).toBeInTheDocument();
  expect(within(screen.getByRole('region', { name: 'Latest calculation' })).getByText('T1 160.00 · 62% · ~4d')).toBeInTheDocument();
  await edit('STOP', '144');
  expect(screen.getByText('Latest result unavailable — recalculate')).toBeInTheDocument();
  view.unmount();
  render(<StockPositionCard card={card()} strategyKey="pullback_ema" {...{ presentation: 'position' } as object} />);
  expect(screen.getByText('Calculation chronology unavailable')).toBeInTheDocument();
});

function makePlan(overrides: Partial<StockExitPlan> = {}): StockExitPlan {
  return {
    stop: {
      price: 144.0,
      source: 'atr_widened',
      structuralSource: 'swing_low',
      structuralConfidence: 60,
      structuralPrice: 147.0,
      atrFloorPrice: 144.0,
      distanceDollar: 3.0,
      riskPerShare: 6.0,
      probability: 0.34,
      expectedDays: 6,
    },
    targets: [
      {
        rrRatio: 2, arithmeticPrice: 162.0, price: 162.0, tpSource: 'arithmetic',
        structuralPrice: 170.0, distanceDollar: 8.0, toleranceDollar: 0.9,
        rewardPerShare: 12.0, probability: 0.41, expectedDays: 7,
        qualityGood: false, qualityReasons: ['stop_widened'],
      },
      {
        rrRatio: 3, arithmeticPrice: 168.0, price: 170.0, tpSource: 'structural_snap',
        structuralPrice: 170.0, distanceDollar: 2.0, toleranceDollar: 2.5,
        rewardPerShare: 20.0, probability: 0.19, expectedDays: 9,
        qualityGood: false, qualityReasons: ['stop_widened'],
      },
    ],
    atr: 3.0,
    recommendedShares: 625,
    riskBudget: 3750.0,
    daysBasis: 'trading',
    horizonDays: 10,
    modelCaveat: null,
    race: {
      outcomes: [
        {
          targetPrice: 162.0, pTargetFirst: 0.4, pStopFirst: 0.34, pNeither: 0.26,
          daysTarget: 7, daysStop: 6,
          weightTarget: 0.4, weightStop: 0.34, weightNeither: 0.26,
          terminalMean: 152.4,
        },
        {
          targetPrice: 170.0, pTargetFirst: 0.19, pStopFirst: 0.34, pNeither: 0.47,
          daysTarget: 9, daysStop: 6,
          weightTarget: 0.19, weightStop: 0.34, weightNeither: 0.47,
          terminalMean: 154.1,
        },
      ],
      stopPrice: 144.0,
      nPaths: 2000,
    },
    ...overrides,
  };
}


it('uses recorded thresholds despite changed Settings and preserves zero evidence', () => {
  useScanStore.setState({ stockScanRequest: { bt_min_trades: 0, bt_min_win_rate: 0 } as never });
  useSettingsStore.setState({ confidenceGate: { minTrades: 999, minWinRate: .99 } } as never);
  const c = { ...card(), stock_status: 'CAUTION' as const, confidence: 0, backtest: { ...card().backtest, sharpe: 0, win_rate: 0, n_trades: 0, total_return_pct: 0 } };
  c.stock_explanation = { status: 'PASS', components: { trend: { name: 'Trend', measured: true, raw_score: 0, weight: .3, contribution: 0 }, pullback: { name: 'Pullback', measured: false, raw_score: 0, weight: .2, contribution: 0 } } } as never;
  render(<StockPositionCard card={c} strategyKey="pullback_ema" presentation="position" />);
  expect(screen.getByText('Scan thresholds: ≥ 0 trades · ≥ 0% win rate')).toBeInTheDocument();
  expect(screen.getByText('Final verdict: CAUTION')).toBeInTheDocument();
  expect(screen.getByText('Scorer evidence before final caps: PASS')).toBeInTheDocument();
  expect(within(screen.getByRole('region', { name: 'Stock Scorecard' })).getByText('0')).toBeInTheDocument();
  expect(within(screen.getByRole('region', { name: 'Stock Scorecard' })).getByText('Unavailable')).toBeInTheDocument();
  expect(within(screen.getByRole('region', { name: 'Backtest evidence' })).getByText('0.0%')).toBeInTheDocument();
});
it.each(['Bullish', 'Bearish'] as const)('draws %s race from allocated probabilities and respects accepted chronology', async direction => {
  const plan = makePlan();
  if (direction === 'Bearish') { plan.targets[0].price = 138; plan.targets[0].arithmeticPrice = 138; plan.race!.outcomes[0].targetPrice = 138; }
  (api.getStockExitPlan as jest.Mock).mockResolvedValue(plan);
  render(<StockPositionCard card={card('AAPL', direction)} strategyKey="pullback_ema" presentation="position" />);
  fireEvent.click(screen.getByRole('button', { name: 'Arithmetic plan' }));
  await screen.findByText('Latest: Arithmetic');
  const drawing = screen.getByLabelText(`${direction} target ${plan.race!.outcomes[0].targetPrice.toFixed(2)} race`);
  expect(within(drawing).getAllByRole('meter').map(m => m.getAttribute('value'))).toEqual(['0.4', '0.34', '0.26']);
  expect(screen.getByText('target 40% (~7d)')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Estimate' }));
  await screen.findByText('Latest: Monte Carlo');
  await edit('STOP', '144');
  expect(screen.getByText('Latest result unavailable — recalculate')).toBeInTheDocument();
  expect(screen.queryByText('Latest: Arithmetic')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Arithmetic plan' }));
  await screen.findByText('Latest: Arithmetic');
});
it('ignores an invalidated asynchronous response and repeated runs use the newest accepted result', async () => {
  const pending = deferred<typeof estimate>();
  (api.getStockFirstPassage as jest.Mock).mockReturnValueOnce(pending.promise).mockResolvedValueOnce({ ...estimate, targets: [{ ...estimate.targets[0], probability: 0 }] });
  render(<StockPositionCard card={card()} strategyKey="pullback_ema" presentation="position" />);
  fireEvent.click(screen.getByRole('button', { name: 'Estimate' }));
  await edit('ENTRY', '152');
  await act(async () => pending.resolve(estimate));
  expect(screen.queryByText('Latest: Monte Carlo')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Estimate' }));
  await screen.findByText('Latest: Monte Carlo');
  expect(within(screen.getByRole('region', { name: 'Latest calculation' })).getByText('T1 160.00 · 0% · ~4d')).toBeInTheDocument();
});

it('latest follows successful completion across concurrently running methods in reverse request order', async () => {
  const mc = deferred<typeof estimate>();
  const arithmetic = deferred<StockExitPlan>();
  (api.getStockFirstPassage as jest.Mock).mockReturnValue(mc.promise);
  (api.getStockExitPlan as jest.Mock).mockReturnValue(arithmetic.promise);
  render(<StockPositionCard card={card()} strategyKey="pullback_ema" presentation="position" />);
  fireEvent.click(screen.getByRole('button', { name: 'Arithmetic plan' }));
  fireEvent.click(screen.getByRole('button', { name: 'Estimate' }));
  await act(async () => mc.resolve(estimate));
  expect(screen.getByText('Latest: Monte Carlo')).toBeInTheDocument();
  await act(async () => arithmetic.resolve(makePlan()));
  expect(screen.getByText('Latest: Arithmetic')).toBeInTheDocument();
  expect(within(screen.getByRole('region', { name: 'Latest calculation' })).getByText('Stop 144.00 · risk/share 6.00 · 10 trading days')).toBeInTheDocument();
});

it.each(['Bullish', 'Bearish'] as const)('separates the %s initial strategy ladder from execution edits and uses entered shares', async direction => {
  const c = card('AAPL', direction);
  if (direction === 'Bearish') c.strategy = { ...c.strategy, stop_price: 155, target_price: 140, targets: [140, 135, 130] };
  render(<StockPositionCard card={c} strategyKey="pullback_ema" presentation="position" />);
  const initial = screen.getByRole('region', { name: 'Initial strategy targets' });
  const first = within(initial).getByRole('row', { name: /T1/ });
  expect(within(first).getByText(direction === 'Bullish' ? '$160.00' : '$140.00')).toBeInTheDocument();
  expect(within(first).getByText('$10.00')).toBeInTheDocument();
  expect(within(first).getByText('6.67%')).toBeInTheDocument();
  expect(within(first).getByText('2.00×')).toBeInTheDocument();
  expect(within(first).getByText('$300.00')).toBeInTheDocument();
  expect(within(initial).getByText('Original target allocations unavailable')).toBeInTheDocument();
  expect(within(initial).queryByText(/probability|trading days/i)).not.toBeInTheDocument();
  await edit('ENTRY', '151');
  await edit('T1 TARGET', direction === 'Bullish' ? '162' : '138');
  await edit('SHARES', '12');
  expect(within(first).getByText('$10.00')).toBeInTheDocument();
  expect(within(first).getByText('$120.00')).toBeInTheDocument();
  expect(initial.compareDocumentPosition(screen.getByRole('heading', { name: 'Order & exits' })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it.each([undefined, []])('restores a legacy initial target without inventing extra rungs (%s)', targets => {
  const c = { ...card(), strategy: { ...card().strategy, targets } };
  render(<StockPositionCard card={c} strategyKey="pullback_ema" presentation="position" />);
  const initial = screen.getByRole('region', { name: 'Initial strategy targets' });
  expect(within(initial).getAllByRole('row')).toHaveLength(2);
  expect(within(initial).getByText('$160.00')).toBeInTheDocument();
  expect(within(initial).queryByText('T2')).not.toBeInTheDocument();
});

it('preserves zero outcomes and distinguishes absent original geometry', () => {
  const c = { ...card(), shares: 0, strategy: { ...card().strategy, target_price: 150, targets: [150] } };
  const view = render(<StockPositionCard card={c} strategyKey="pullback_ema" presentation="position" />);
  const initial = screen.getByRole('region', { name: 'Initial strategy targets' });
  expect(within(initial).getAllByText('$0.00')).toHaveLength(2);
  expect(within(initial).getByText('0.00%')).toBeInTheDocument();
  expect(within(initial).getByText('0.00×')).toBeInTheDocument();
  view.unmount();
  render(<InitialStrategyTargets card={{ ...c, strategy: { ...c.strategy, entry_price: undefined as never } }} shares={0} />);
  const missing = screen.getByRole('region', { name: 'Initial strategy targets' });
  expect(within(missing).getAllByText('Unavailable').length).toBeGreaterThanOrEqual(4);
  expect(missing).not.toHaveTextContent('NaN');
});

it('shows source-labelled context with recorded horizon and unavailable legacy horizon', () => {
  useScanStore.setState({ stockScanRequest: { horizon: 'Swing', hold_max_days: 0 } as never, context: { horizon: 'Position' } as never });
  const view = render(<StockPositionCard card={card()} strategyKey="pullback_ema" presentation="position" />);
  const context = screen.getByLabelText('Stock context');
  expect(within(context).getByText('Scan price: $150.00')).toBeInTheDocument();
  expect(within(context).getByText('Recorded horizon: Swing · hold 0 days')).toBeInTheDocument();
  expect(within(context).getByText('Stock score: 80 / 100')).toBeInTheDocument();
  act(() => useScanStore.setState({ stockScanRequest: null }));
  expect(within(context).getByText('Recorded horizon unavailable')).toBeInTheDocument();
  view.rerender(<StockPositionCard card={card()} strategyKey="pullback_ema" />);
  expect(screen.queryByRole('region', { name: 'Initial strategy targets' })).not.toBeInTheDocument();
});

it('keeps direction-aware negative outcomes and source observations without inventing risk ratios', () => {
  const c = { ...card(), strategy: { ...card().strategy, stop_price: 150, targets: [145], detail: { source: 'swing low', observations: 0, measured: false } } };
  render(<InitialStrategyTargets card={c} shares={12} />);
  const initial = screen.getByRole('region', { name: 'Initial strategy targets' });
  expect(within(initial).getByText('$-5.00')).toBeInTheDocument();
  expect(within(initial).getByText('$-60.00')).toBeInTheDocument();
  expect(within(initial).getByText('-3.33%')).toBeInTheDocument();
  expect(within(initial).getByText('Unavailable')).toBeInTheDocument();
  fireEvent.click(within(initial).getByText('Strategy observations'));
  expect(within(initial).getByText('observations: 0')).toBeInTheDocument();
  expect(within(initial).getByText('measured: false')).toBeInTheDocument();
});


it.each(['Bullish', 'Bearish'] as const)('uses current %s execution inputs for reactive value and risk', async direction => {
  const c = card('AAPL', direction);
  if (direction === 'Bearish') c.strategy = { ...c.strategy, stop_price: 155, targets: [140, 135, 130] };
  c.dollar_risk = 999; c.dollar_size = 99999;
  render(<StockPositionCard card={c} strategyKey="pullback_ema" presentation="position" />);
  const risk = screen.getByRole('region', { name: 'Execution risk' });
  expect(within(risk).getByText('Position value').parentElement).toHaveTextContent('$4500.00');
  expect(within(risk).getByText('Execution risk / share').parentElement).toHaveTextContent('$5.00');
  expect(within(risk).getByText('Execution risk / position').parentElement).toHaveTextContent('$150.00');
  await edit('ENTRY', '151.234');
  await edit('STOP', direction === 'Bullish' ? '146.23' : '156.23');
  await edit('SHARES', '12.6');
  expect(within(risk).getByText('Position value').parentElement).toHaveTextContent('$1965.99');
  expect(within(risk).getByText('Execution risk / share').parentElement).toHaveTextContent('$5.00');
  expect(within(risk).getByText('Execution risk / position').parentElement).toHaveTextContent('$65.00');
  expect(risk).toHaveTextContent('Entered 13 shares');
  expect(screen.getByText('Edit T1 / T2 / T3 and share allocations')).toBeInTheDocument();
  await edit('T1 TARGET', direction === 'Bullish' ? '163' : '138');
  expect(within(risk).getByText('Execution risk / position').parentElement).toHaveTextContent('$65.00');
});

it.each([
  ['Bullish', '151'], ['Bullish', '150'], ['Bearish', '149'], ['Bearish', '150'],
] as const)('marks %s stop %s invalid instead of displaying absolute-distance risk', async (direction, stop) => {
  const c = card('AAPL', direction);
  if (direction === 'Bearish') c.strategy = { ...c.strategy, stop_price: 155 };
  render(<StockPositionCard card={c} strategyKey="pullback_ema" presentation="position" />);
  await edit('STOP', stop);
  const risk = screen.getByRole('region', { name: 'Execution risk' });
  expect(within(risk).getAllByText('Unavailable')).toHaveLength(2);
  expect(risk).toHaveTextContent('Execution stop invalid');
  expect(within(risk).getByText('Position value').parentElement).toHaveTextContent('$4500.00');
  expect(screen.getByRole('button', { name: 'Add to Portfolio' })).toBeDisabled();
});

it('preserves zero entered quantity and missing stop rather than borrowing scan risk', () => {
  const c = { ...card(), shares: 0, strategy: { ...card().strategy, stop_price: 0 } };
  render(<StockPositionCard card={c} strategyKey="pullback_ema" presentation="position" />);
  const risk = screen.getByRole('region', { name: 'Execution risk' });
  expect(within(risk).getByText('Position value').parentElement).toHaveTextContent('$0.00');
  expect(within(risk).getAllByText('Unavailable')).toHaveLength(2);
  expect(risk).toHaveTextContent('Execution stop invalid');
});

it.each(['Bullish', 'Bearish'] as const)('keeps the %s execution R:R tone consistent with a losing target', async direction => {
  const c = card('AAPL', direction);
  if (direction === 'Bearish') c.strategy = { ...c.strategy, stop_price: 155, targets: [140, 135, 130] };
  render(<StockPositionCard card={c} strategyKey="pullback_ema" presentation="position" />);
  await edit('T1 TARGET', direction === 'Bullish' ? '140' : '160');
  const row = screen.getByText('T1 TARGET').closest('div')!.parentElement!;
  expect(within(row).getByText('-2.0×')).toHaveAttribute('data-tone', 'reject');
});

it('shows unavailable R:R when cent-rounded stop has no positive risk distance', () => {
  render(<StockPositionCard card={card()} strategyKey="pullback_ema" presentation="position" />);
  const identity = stockExecutionIdentity(useScanStore.getState(), 'AAPL')!;
  act(() => {
    const overlay = useScanStore.getState().stockExecution[identity].overlay ?? defaultStockOverlay(card());
    useScanStore.getState().patchStockExecution(identity, { overlay: { ...overlay, stop: 149.999 } });
  });
  const row = screen.getByText('T1 TARGET').closest('div')!.parentElement!;
  expect(within(row).getByText('Unavailable')).toBeInTheDocument();
  expect(within(screen.getByRole('region', { name: 'Execution risk' })).getAllByText('Unavailable')).toHaveLength(2);
});

it.each([NaN, Infinity, -1])('does not display nonfinite or negative entered quantity %s as money', quantity => {
  render(<StockPositionCard card={card()} strategyKey="pullback_ema" presentation="position" />);
  const identity = stockExecutionIdentity(useScanStore.getState(), 'AAPL')!;
  act(() => {
    const overlay = useScanStore.getState().stockExecution[identity].overlay ?? defaultStockOverlay(card());
    useScanStore.getState().patchStockExecution(identity, { overlay: { ...overlay, shares: quantity } });
  });
  const risk = screen.getByRole('region', { name: 'Execution risk' });
  expect(within(risk).getByText('Position value').parentElement).toHaveTextContent('Unavailable');
  expect(within(risk).getByText('Execution risk / position').parentElement).toHaveTextContent('Unavailable');
  expect(within(risk).getByText('Execution risk / share').parentElement).toHaveTextContent('$5.00');
});

it('keeps quantity/allocation edits independent and clears only matching calculation dependencies', async () => {
  (api.getStockExitPlan as jest.Mock).mockResolvedValue(makePlan());
  (api.getStructuralStop as jest.Mock).mockResolvedValue({ available: true, price: 146, source: 'swing_low' });
  render(<StockPositionCard card={card()} strategyKey="pullback_ema" presentation="position" />);
  fireEvent.click(screen.getByRole('button', { name: 'Arithmetic plan' }));
  await screen.findByText('Latest: Arithmetic');
  fireEvent.click(screen.getByRole('button', { name: 'Check structure' }));
  await screen.findByText('swing_low');
  fireEvent.click(screen.getByRole('button', { name: 'Estimate' }));
  await screen.findByText('Latest: Monte Carlo');
  fireEvent.click(screen.getByRole('radio', { name: 'Monte Carlo' }));
  const identity = stockExecutionIdentity(useScanStore.getState(), 'AAPL')!;
  const record = () => useScanStore.getState().stockExecution[identity];
  const initial = { estimate: record().estimate, plan: record().plan, structural: record().structural };
  expect(initial.estimate).toBeTruthy(); expect(initial.plan).toBeTruthy(); expect(initial.structural).toBeTruthy();
  await edit('SHARES', '60');
  await edit('T1 SHARES', '10');
  expect(record()).toMatchObject(initial);
  expect(screen.getByRole('radio', { name: 'Monte Carlo' })).toBeChecked();
  expect(within(screen.getByRole('region', { name: 'Execution risk' })).getByText('Execution risk / position').parentElement).toHaveTextContent('$300.00');
  await edit('T1 TARGET', '161');
  expect(record().estimate).toBeNull();
  expect(record().plan).toEqual(initial.plan); expect(record().structural).toEqual(initial.structural);
  expect(screen.getByRole('radio', { name: 'Monte Carlo' })).not.toBeChecked();
  await edit('STOP', '143');
  expect(record().plan).toEqual(initial.plan); expect(record().structural).toEqual(initial.structural);
  await edit('ENTRY', '151');
  expect(record().plan).toBeNull(); expect(record().structural).toBeNull();
});

it.each(['symbol', 'run'] as const)('rejects pending calculation after %s identity changes in position presentation', async change => {
  const pending = deferred<typeof estimate>();
  (api.getStockFirstPassage as jest.Mock).mockReturnValue(pending.promise);
  useScanStore.getState().setStockScanResult(scan([card(), card('MSFT')]));
  const view = render(<StockPositionCard card={card()} strategyKey="pullback_ema" presentation="position" />);
  fireEvent.click(screen.getByRole('button', { name: 'Estimate' }));
  if (change === 'symbol') view.rerender(<StockPositionCard card={card('MSFT')} strategyKey="pullback_ema" presentation="position" />);
  else act(() => useScanStore.getState().setStockScanResult(scan([card(), card('MSFT')])));
  await act(async () => pending.resolve(estimate));
  expect(screen.queryByText('Latest: Monte Carlo')).not.toBeInTheDocument();
  expect(screen.queryByText('T1 160.00 · 62% · ~4d')).not.toBeInTheDocument();
  expect(screen.getByText('Calculation chronology unavailable')).toBeInTheDocument();
});


it.each([
  ['entry', NaN], ['entry', Infinity], ['entry', 0], ['entry', -1],
  ['stop', NaN], ['stop', Infinity], ['stop', 0], ['stop', -1],
] as const)('shows unavailable execution risk for invalid %s %s', (field, value) => {
  render(<StockPositionCard card={card()} strategyKey="pullback_ema" presentation="position" />);
  const identity = stockExecutionIdentity(useScanStore.getState(), 'AAPL')!;
  act(() => {
    const overlay = useScanStore.getState().stockExecution[identity].overlay ?? defaultStockOverlay(card());
    useScanStore.getState().patchStockExecution(identity, { overlay: { ...overlay, [field]: value } });
  });
  const risk = screen.getByRole('region', { name: 'Execution risk' });
  expect(within(risk).getByText('Execution risk / share').parentElement).toHaveTextContent('Unavailable');
  expect(within(risk).getByText('Execution risk / position').parentElement).toHaveTextContent('Unavailable');
  expect(risk).toHaveTextContent('Execution stop invalid');
  expect(within(risk).getByText('Position value').parentElement).toHaveTextContent(field === 'entry' ? 'Unavailable' : '$4500.00');
  const row = screen.getByText('T1 TARGET').closest('div')!.parentElement!;
  expect(within(row).getAllByText('Unavailable').length).toBeGreaterThan(0);
});

it('shows zero position risk for zero entered shares with a valid stop', () => {
  render(<StockPositionCard card={{ ...card(), shares: 0 }} strategyKey="pullback_ema" presentation="position" />);
  const risk = screen.getByRole('region', { name: 'Execution risk' });
  expect(within(risk).getByText('Position value').parentElement).toHaveTextContent('$0.00');
  expect(within(risk).getByText('Execution risk / share').parentElement).toHaveTextContent('$5.00');
  expect(within(risk).getByText('Execution risk / position').parentElement).toHaveTextContent('$0.00');
});
