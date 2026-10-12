import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { StockPositionCard } from '@/components/organisms/StockPositionCard';
import { useScanStore } from '@/lib/scanStore';
import { stockExecutionIdentity, STOCK_VALIDATION_UNAVAILABLE, useStockOrderOwnershipStore } from '@/lib/stockExecutionSession';
import { useSettingsStore } from '@/lib/settingsStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { api } from '@/lib/api';
import type { StockExitPlan, PositionCardData, StockScanResult } from '@/types/stockDomain';

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
