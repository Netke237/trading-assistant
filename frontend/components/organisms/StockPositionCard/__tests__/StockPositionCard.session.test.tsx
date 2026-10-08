import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { StockPositionCard } from '@/components/organisms/StockPositionCard';
import { useScanStore } from '@/lib/scanStore';
import { stockExecutionIdentity, STOCK_VALIDATION_UNAVAILABLE, useStockOrderOwnershipStore } from '@/lib/stockExecutionSession';
import { useSettingsStore } from '@/lib/settingsStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { api } from '@/lib/api';
import type { PositionCardData, StockScanResult } from '@/types/stockDomain';

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
  backtest: { n_trades: 20, win_rate: .6, total_return_pct: 12, max_drawdown_pct: 5, expectancy: .4, sharpe: 1.2, confidence: .7, passes_gate: true, summary_text: 'ok' },
  stock_score: 80, stock_status: 'PASS', shares: 30, dollar_risk: 150, dollar_size: 4500, confidence: .7, confidence_text: 'High',
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
  useScanStore.setState({ stockExecution: {}, stockExecutionGeneration: 0, stockScanResult: null, stocksCardEdits: { scanId: null, picks: {}, invalidation: {}, premiumStop: {}, entryLimit: {}, maxLossOverride: {} } });
  useScanStore.getState().setStockScanResult(scan());
  useStockOrderOwnershipStore.setState({ bySymbol: {} });
  usePortfolioStore.setState({ positions: [] });
  useSettingsStore.setState({ ibkrPaper: { baseUrl: 'https://localhost', accountId: 'ACC' } } as never);
  (api.getStockQuote as jest.Mock).mockResolvedValue({ price: 151 });
  (api.getStockFirstPassage as jest.Mock).mockResolvedValue(estimate);
});

it('keeps edited levels, exact allocation scaling, completed estimate and its pick after unmount/remount', async () => {
  const first = render(<StockPositionCard card={card()} strategyKey="pullback_ema" />);
  await edit('ENTRY', '152');
  await edit('SHARES', '50');
  fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));
  expect(await screen.findByText('62%')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('radio', { name: 'Monte Carlo' }));
  first.unmount();
  render(<StockPositionCard card={card()} strategyKey="pullback_ema" />);
  expect(screen.getByRole('radio', { name: 'Monte Carlo' })).toBeChecked();
  expect(screen.getByText('62%')).toBeInTheDocument();
  const identity = stockExecutionIdentity(useScanStore.getState(), 'AAPL')!;
  expect(useScanStore.getState().stockExecution[identity].overlay).toMatchObject({ entry: 152, shares: 50, sharesT1: 16, sharesT2: 16, sharesT3: 18 });
  expect(api.getStockFirstPassage).toHaveBeenCalledTimes(1);
});

it('keeps AAPL evidence on candidate navigation, while MSFT starts pristine', async () => {
  useScanStore.getState().setStockScanResult(scan([card(), card('MSFT')]));
  const view = render(<StockPositionCard card={card()} strategyKey="pullback_ema" />);
  await edit('ENTRY', '152');
  fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));
  await screen.findByText('62%');
  view.rerender(<StockPositionCard card={card('MSFT')} strategyKey="pullback_ema" />);
  expect(screen.queryByText('62%')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: '150.00' })).toBeInTheDocument();
  view.rerender(<StockPositionCard card={card()} strategyKey="pullback_ema" />);
  expect(screen.getByText('62%')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '152.00' })).toBeInTheDocument();
});

it('retires evidence/edits/picks and ignores a deferred response after equal-id equal-price replacement', async () => {
  const pending = deferred<typeof estimate>();
  (api.getStockFirstPassage as jest.Mock).mockReturnValue(pending.promise);
  render(<StockPositionCard card={card()} strategyKey="pullback_ema" />);
  await edit('ENTRY', '152');
  fireEvent.click(screen.getByRole('radio', { name: 'Ladder' }));
  fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));
  await act(async () => { useScanStore.getState().setStockScanResult(scan()); pending.resolve(estimate); });
  expect(screen.queryByText('62%')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: '150.00' })).toBeInTheDocument();
  expect(useScanStore.getState().stocksCardEdits.picks).toEqual({});
});

it('ignores another mounted card’s stale estimate after dependency edits, including change then revert', async () => {
  const pending = deferred<typeof estimate>();
  (api.getStockFirstPassage as jest.Mock).mockReturnValue(pending.promise);
  const first = render(<div data-testid="first"><StockPositionCard card={card()} strategyKey="pullback_ema" /></div>);
  const second = render(<div data-testid="second"><StockPositionCard card={card()} strategyKey="pullback_ema" /></div>);
  fireEvent.click(within(screen.getByTestId('first')).getByRole('button', { name: /^estimate$/i }));
  await edit('STOP', '144', screen.getByTestId('second'));
  await edit('STOP', '145', screen.getByTestId('second'));
  await act(async () => pending.resolve(estimate));
  expect(screen.queryByText('62%')).not.toBeInTheDocument();
  first.unmount(); second.unmount();
});

it('ignores stale quote responses on candidate change and shows Now with the current price', async () => {
  const old = deferred<{ price: number }>();
  (api.getStockQuote as jest.Mock).mockReturnValueOnce(old.promise).mockResolvedValueOnce({ price: 200 });
  const view = render(<StockPositionCard card={card()} strategyKey="pullback_ema" />);
  await waitFor(() => expect(api.getStockQuote).toHaveBeenCalledWith('AAPL'));
  view.rerender(<StockPositionCard card={card('MSFT')} strategyKey="pullback_ema" />);
  expect(await screen.findByText('Now: $200.00')).toBeInTheDocument();
  await act(async () => old.resolve({ price: 123 }));
  expect(screen.getByText('Now: $200.00')).toBeInTheDocument();
});

it.each(['Bullish', 'Bearish'] as const)('blocks %s limit/market requests despite a current PASS, explicit pick and forged approval', async direction => {
  const selected = card('AAPL', direction);
  if (direction === 'Bearish') selected.strategy.targets = [140, 135, 130];
  useScanStore.getState().setStockScanResult(scan([selected]));
  (useScanStore.setState as (value: unknown) => void)({ stockValidation: { allowed: true }, executionEligible: true });
  render(<StockPositionCard card={selected} strategyKey="pullback_ema" />);
  fireEvent.click(screen.getByRole('radio', { name: 'Ladder' }));
  fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
  fireEvent.click(screen.getByRole('button', { name: /limit @/i }));
  fireEvent.click(screen.getByRole('button', { name: /market order/i }));
  expect(api.postStockOrder).not.toHaveBeenCalled();
  expect(usePortfolioStore.getState().positions).toEqual([]);
  expect(screen.getAllByText(STOCK_VALIDATION_UNAVAILABLE).length).toBeGreaterThan(0);
});

it('blocks basket initial/retry broker requests with production unavailable authority', async () => {
  const { StockSendDialog } = await import('@/components/organisms/StockSendDialog');
  const selected = card();
  useScanStore.getState().setStockScanResult(scan([selected]));
  useScanStore.getState().addToStockBasket(selected);
  const first = render(<StockPositionCard card={selected} strategyKey="pullback_ema" />);
  fireEvent.click(screen.getByRole('radio', { name: 'Ladder' })); first.unmount();
  const onSubmit = jest.fn();
  render(<StockSendDialog cards={[selected]} onClose={() => {}} onSubmit={onSubmit} />);
  fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
  fireEvent.click(screen.getByRole('button', { name: /submit 1 order/i }));
  await screen.findByText(STOCK_VALIDATION_UNAVAILABLE);
  const retry = screen.getByRole('button', { name: /retry/i });
  fireEvent.click(retry);
  await waitFor(() => expect(screen.getByText(STOCK_VALIDATION_UNAVAILABLE)).toBeInTheDocument());
  expect(api.postStockOrder).not.toHaveBeenCalled();
  expect(usePortfolioStore.getState().positions).toEqual([]);
  expect(onSubmit).not.toHaveBeenCalled();
});

it('an idle second card unmount cannot unlock or duplicate analytics owned by the first card', async () => {
  const pending = deferred<typeof estimate>();
  (api.getStockFirstPassage as jest.Mock).mockReturnValue(pending.promise);
  render(<div data-testid="first"><StockPositionCard card={card()} strategyKey="pullback_ema" /></div>);
  const idle = render(<StockPositionCard card={card()} strategyKey="pullback_ema" />);
  fireEvent.click(within(screen.getByTestId('first')).getByRole('button', { name: /^estimate$/i }));
  idle.unmount();
  const identity = stockExecutionIdentity(useScanStore.getState(), 'AAPL')!;
  expect(useScanStore.getState().stockExecution[identity].estimating).toBe(true);
  expect(api.getStockFirstPassage).toHaveBeenCalledTimes(1);
  await act(async () => pending.resolve(estimate));
  expect(await screen.findByText('62%')).toBeInTheDocument();
  expect(useScanStore.getState().stockExecution[identity].estimating).toBe(false);
});

it('clears a restored selected Ladder row if its price no longer matches, while preserving method-only choices', async () => {
  useScanStore.getState().setCardEdit('stocks', 'picks', 'AAPL', { method: 'ladder', rowStockPrice: 999, rowOptionPrice: null, stopBasis: 'stock', pickedAt: 'now' });
  render(<StockPositionCard card={card()} strategyKey="pullback_ema" />);
  await waitFor(() => expect(useScanStore.getState().stocksCardEdits.picks.AAPL).toBeUndefined());
  expect(screen.getByRole('button', { name: /add to portfolio/i })).toBeDisabled();
  fireEvent.click(screen.getByRole('radio', { name: 'Ladder' }));
  expect(useScanStore.getState().stocksCardEdits.picks.AAPL).toMatchObject({ method: 'ladder', rowStockPrice: null });
  expect(screen.getByRole('button', { name: /add to portfolio/i })).toBeEnabled();
});

it('blocks a same-symbol research Add on another surface when basket ownership survives replacement scan', () => {
  const selected = card();
  useScanStore.getState().setStockScanResult(scan([selected]));
  const oldIdentity = stockExecutionIdentity(useScanStore.getState(), selected.symbol)!;
  useStockOrderOwnershipStore.getState().claim(selected.symbol, { identity: oldIdentity, recId: 'basket-save', status: 'in-flight' });
  useScanStore.getState().setStockScanResult(scan([selected]));
  render(<StockPositionCard card={selected} strategyKey="pullback_ema" />);
  fireEvent.click(screen.getByRole('radio', { name: 'Ladder' }));
  expect(screen.getByRole('button', { name: 'Add to Portfolio' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Add to Portfolio' }));
  expect(usePortfolioStore.getState().positions).toEqual([]);
});

it('owns a direct research save through replacement scan and refuses a fresh basket duplicate', async () => {
  const { StockSendDialog } = await import('@/components/organisms/StockSendDialog');
  const selected = card();
  useScanStore.getState().setStockScanResult(scan([selected]));
  const pending = deferred<{ status: 'pending' }>();
  const original = usePortfolioStore.getState().addPosition;
  const add = jest.fn(() => pending.promise);
  usePortfolioStore.setState({ addPosition: add as never });
  try {
    const first = render(<StockPositionCard card={selected} strategyKey="pullback_ema" />);
    fireEvent.click(screen.getByRole('radio', { name: 'Ladder' }));
    fireEvent.click(screen.getByRole('button', { name: 'Add to Portfolio' }));
    expect(add).toHaveBeenCalledTimes(1);
    first.unmount();
    const replacement = card();
    act(() => {
      useScanStore.getState().setStockScanResult(scan([replacement]));
      useScanStore.getState().setCardEdit('stocks', 'picks', replacement.symbol, { method: 'ladder', rowStockPrice: 160, rowOptionPrice: null, stopBasis: 'stock', pickedAt: 'now' });
      useScanStore.getState().addToStockBasket(replacement);
    });
    render(<StockSendDialog cards={[replacement]} onClose={() => {}} onSubmit={jest.fn()} />);
    const submit = screen.getByRole('button', { name: /submit 1 order/i });
    expect(submit).toBeDisabled(); fireEvent.click(submit);
    await act(async () => pending.resolve({ status: 'pending' }));
    expect(add).toHaveBeenCalledTimes(1);
    expect(useStockOrderOwnershipStore.getState().bySymbol.AAPL.status).toBe('unknown');
  } finally { usePortfolioStore.setState({ addPosition: original }); }
});
