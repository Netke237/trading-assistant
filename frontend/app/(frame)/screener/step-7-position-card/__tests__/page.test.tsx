import { act, render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import Step7PositionCardPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useDirectSendNotesStore } from '@/lib/directSendNotesStore';
import * as execution from '@/lib/stockExecutionSession';
import { api } from '@/lib/api';
import type { PositionCardData, StockScanResult } from '@/types/stockDomain';

jest.mock('@/lib/api', () => ({ api: {
  postStockOrder: jest.fn(), deletePortfolioPosition: jest.fn().mockResolvedValue(undefined),
  getBrokerStatus: jest.fn().mockResolvedValue({}), getStockQuote: jest.fn(),
  getStockFirstPassage: jest.fn(), getStockExitPlan: jest.fn(), getStructuralStop: jest.fn(),
  addStrategyWatch: jest.fn(), removeStrategyWatch: jest.fn(),
} }));
jest.mock('@/components/molecules/MarketSentiment', () => ({ MarketSentiment: () => null }));
jest.mock('@/components/molecules/FundamentalHealthCard', () => ({ FundamentalHealthCard: () => null }));

const card = (symbol = 'AAPL', direction: 'Bullish' | 'Bearish' = 'Bullish'): PositionCardData => ({
  symbol, company: `${symbol} Inc.`, price: 150, direction,
  strategy: { strategy: 'pullback_ema', entry_price: 150, stop_price: direction === 'Bullish' ? 145 : 155,
    target_price: direction === 'Bullish' ? 160 : 140, targets: direction === 'Bullish' ? [160, 165, 170] : [140, 135, 130], rr_ratio: 2, atr: 3, detail: {} },
  backtest: { n_trades: 20, win_rate: .6, total_return_pct: 12, max_drawdown_pct: 5, expectancy: .4, sharpe: 1.2, confidence: .7, passes_gate: true, summary_text: 'ok' },
  stock_score: 80, stock_status: 'PASS', shares: 30, dollar_risk: 150, dollar_size: 4500, confidence: .7, confidence_text: 'High',
});
const scan = (candidates = [card(), card('MSFT')]): StockScanResult => ({ scan_id: 'S1', timestamp: '2026-10-05T00:00:00Z', candidates, rejected: [] } as unknown as StockScanResult);
const estimate = { targets: [{ price: 160, probability: .62, expectedDays: 4 }], invalidation: { probability: .28, expectedDays: 6 }, horizonDays: 10, modelCaveat: null };
const deferred = <T,>() => { let resolve!: (v: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; };
const originalFetch = global.fetch;
const saveCalls = () => (global.fetch as jest.Mock).mock.calls.filter(([url, init]) => String(url).endsWith('/api/portfolio') && init?.method === 'POST');
function echoFetch(adjustedQty?: number) {
  global.fetch = jest.fn(async (_url, init) => {
    const body = init?.body ? JSON.parse(String(init.body)) : {};
    return { ok: true, status: 201, json: async () => ({ ...body, ...(adjustedQty == null ? {} : { adjustedQty }) }) } as Response;
  });
}
async function edit(label: string, value: string) {
  await act(async () => {});
  const cell = screen.getAllByText(label)[0].closest('div')!;
  fireEvent.click(within(cell).getByRole('button'));
  fireEvent.change(within(cell).getByRole('spinbutton'), { target: { value } });
  fireEvent.blur(within(cell).getByRole('spinbutton'));
}
function selectLadderAndBroker() {
  fireEvent.click(screen.getByRole('radio', { name: 'Ladder' }));
  fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
}
function expectSelected(symbol: string) {
  expect(screen.getByRole('region', { name: `${symbol} position` })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: symbol })).toHaveAttribute('aria-current', 'true');
  expect(useScanStore.getState().selectedSymbol).toBe(symbol);
}
beforeEach(() => {
  jest.clearAllMocks();
  useScanStore.setState({ stockScanResult: null, stockExecution: {}, stockExecutionGeneration: 0, selectedSymbol: 'AAPL', stockBasket: [], stockBasketSources: {}, stockAfterScanIntent: {},
    stocksCardEdits: { scanId: null, picks: {}, invalidation: {}, premiumStop: {}, entryLimit: {}, maxLossOverride: {} } });
  useScanStore.getState().setStockScanResult(scan());
  execution.useStockOrderOwnershipStore.setState({ bySymbol: {} });
  usePortfolioStore.setState({ positions: [], lastSyncError: null });
  useDirectSendNotesStore.setState({ notes: [] });
  useSettingsStore.setState({ ibkrPaper: { baseUrl: 'https://localhost', accountId: 'ACC' } } as never);
  (api.getStockQuote as jest.Mock).mockResolvedValue({ price: 151 });
  (api.getStockFirstPassage as jest.Mock).mockResolvedValue(estimate);
  echoFetch();
});
afterEach(async () => { await act(async () => {}); global.fetch = originalFetch; jest.restoreAllMocks(); });

it('honors Backtest selection, synchronizes Prev/Next and candidate buttons, and follows external selection', async () => {
  useScanStore.getState().setSelectedSymbol('MSFT'); render(<Step7PositionCardPage />);
  expectSelected('MSFT'); expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Prev' })); expectSelected('AAPL');
  expect(screen.getByRole('button', { name: 'Prev' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Next' })); expectSelected('MSFT');
  fireEvent.click(screen.getByRole('button', { name: 'AAPL' })); expectSelected('AAPL');
  act(() => useScanStore.getState().setSelectedSymbol('MSFT')); expectSelected('MSFT');
  await screen.findByText('Now: $151.00');
});
it('preserves selection on reorder and recovers from removal, failed gate, empty and replaced results', async () => {
  useScanStore.getState().setSelectedSymbol('MSFT'); render(<Step7PositionCardPage />);
  act(() => useScanStore.getState().setStockScanResult(scan([card('MSFT'), card()])));
  expectSelected('MSFT'); expect(screen.getByText('1 of 2')).toBeInTheDocument();
  const failed = card('MSFT'); failed.backtest.passes_gate = false;
  act(() => useScanStore.getState().setStockScanResult(scan([failed, card('NVDA')])));
  expectSelected('NVDA'); expect(screen.queryByRole('button', { name: 'MSFT' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
  act(() => useScanStore.getState().setStockScanResult(scan([])));
  expect(screen.getByText(/No passing candidates/)).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /go back/i })).toHaveAttribute('href', '/screener/step-6-backtest');
  expect(screen.queryByRole('navigation', { name: 'Position candidates' })).not.toBeInTheDocument();
  act(() => useScanStore.getState().setStockScanResult(null));
  expect(screen.getByText(/No passing candidates/)).toBeInTheDocument();
  act(() => useScanStore.getState().setStockScanResult(scan())); expectSelected('AAPL');
  await screen.findByText('Now: $151.00');
});
it('falls back from an absent symbol and renders full Position information and broker controls', async () => {
  useScanStore.getState().setSelectedSymbol('REMOVED'); render(<Step7PositionCardPage />); expectSelected('AAPL');
  expect(screen.getByText('AAPL Inc.')).toBeInTheDocument(); expect(screen.getByText('Bullish · pullback ema')).toBeInTheDocument();
  for (const label of ['ENTRY', 'STOP', 'T1 TARGET', 'SHARES', 'Execution risk / share', 'Execution risk / position', 'Position value', 'WIN %', 'SELL-TO-CLOSE PLAN']) expect(screen.getAllByText(label).length).toBeGreaterThan(0);
  const targetRow = screen.getByText('T1 TARGET').closest('div')!.parentElement!;
  expect(within(targetRow).getByText('2.0×')).toBeInTheDocument();
  expect(screen.getByText('60%')).toHaveAttribute('title');
  for (const broker of ['Recommendation', 'IBKR Paper', 'Tradier Paper', 'Alpaca Paper', 'Tastytrade Paper']) expect(screen.getByRole('button', { name: broker })).toBeInTheDocument();
  expect(screen.getByRole('radio', { name: 'Ladder' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /^estimate$/i })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /check structure/i })).toBeInTheDocument();
  expect(screen.getByText('Auto-trade mode')).toBeInTheDocument(); await screen.findByText('Now: $151.00');
});
it('preserves edits, allocations, completed evidence and explicit pick across navigation and remount', async () => {
  const view = render(<Step7PositionCardPage />); await edit('ENTRY', '152'); await edit('SHARES', '50');
  fireEvent.click(screen.getByRole('button', { name: /^estimate$/i })); await screen.findByText('62%');
  fireEvent.click(screen.getByRole('radio', { name: 'Monte Carlo' }));
  fireEvent.click(screen.getByRole('button', { name: 'Next' }));
  expect(screen.queryByText('62%')).not.toBeInTheDocument(); expect(screen.getByRole('button', { name: '150.00' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Prev' }));
  expect(screen.getByText('62%')).toBeInTheDocument(); expect(screen.getByRole('radio', { name: 'Monte Carlo' })).toBeChecked();
  view.unmount(); render(<Step7PositionCardPage />);
  expect(screen.getByRole('button', { name: '152.00' })).toBeInTheDocument(); expect(screen.getByText('62%')).toBeInTheDocument();
  expect(api.getStockFirstPassage).toHaveBeenCalledTimes(1);
  const identity = execution.stockExecutionIdentity(useScanStore.getState(), 'AAPL')!;
  expect(useScanStore.getState().stockExecution[identity].overlay).toMatchObject({ entry: 152, shares: 50, sharesT1: 16, sharesT2: 16, sharesT3: 18 });
  await screen.findByText('Now: $151.00');
});
it('retires equal-id replacement evidence and ignores stale quote and analytics responses', async () => {
  const oldQuote = deferred<{ price: number }>(); const oldEstimate = deferred<typeof estimate>();
  (api.getStockQuote as jest.Mock).mockReturnValueOnce(oldQuote.promise).mockResolvedValue({ price: 200 });
  (api.getStockFirstPassage as jest.Mock).mockReturnValueOnce(oldEstimate.promise);
  render(<Step7PositionCardPage />); await waitFor(() => expect(api.getStockQuote).toHaveBeenCalled());
  await edit('ENTRY', '152'); fireEvent.click(screen.getByRole('radio', { name: 'Ladder' }));
  fireEvent.click(screen.getByRole('button', { name: /^estimate$/i }));
  act(() => useScanStore.getState().setStockScanResult(scan()));
  expect(screen.getByRole('button', { name: '150.00' })).toBeInTheDocument(); expect(screen.getByRole('radio', { name: 'Ladder' })).not.toBeChecked();
  await screen.findByText('Now: $200.00');
  await act(async () => { oldQuote.resolve({ price: 123 }); oldEstimate.resolve(estimate); });
  expect(screen.getByText('Now: $200.00')).toBeInTheDocument(); expect(screen.queryByText('62%')).not.toBeInTheDocument();
});
it('opens the shared basket and preserves durable notes on remount and empty results', async () => {
  useScanStore.getState().addToStockBasket(useScanStore.getState().stockScanResult!.candidates[0]);
  useDirectSendNotesStore.getState().addNote({ recId: 'old', kind: 'order-unknown', label: 'AAPL 30 sh', brokerLabel: 'IBKR Paper', orderId: null });
  const view = render(<Step7PositionCardPage />); fireEvent.click(screen.getByRole('button', { name: 'Send basket (1)' }));
  expect(screen.getByRole('button', { name: /submit 1 order/i })).toBeInTheDocument();
  expect(screen.getByText(/AAPL 30 sh: order status UNKNOWN/i)).toBeInTheDocument();
  await act(async () => {}); view.unmount(); act(() => useScanStore.getState().setStockScanResult(scan([]))); render(<Step7PositionCardPage />);
  expect(screen.getByText(/AAPL 30 sh: order status UNKNOWN/i)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Remove (AAPL 30 sh)' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Send basket (1)' })).toBeInTheDocument();
});
it.each(['Bullish', 'Bearish'] as const)('allows %s research saves while blocking manual sends and automatic arms', async direction => {
  useScanStore.getState().setStockScanResult(scan([card('AAPL', direction)])); render(<Step7PositionCardPage />); selectLadderAndBroker();
  fireEvent.click(screen.getByRole('button', { name: /limit @/i })); fireEvent.click(screen.getByRole('button', { name: 'Market Order' }));
  fireEvent.click(screen.getByRole('button', { name: /armed — add/i })); fireEvent.click(screen.getByRole('button', { name: /watch AAPL/i }));
  expect(api.postStockOrder).not.toHaveBeenCalled(); expect(api.addStrategyWatch).not.toHaveBeenCalled(); expect(saveCalls()).toHaveLength(0);
  expect(screen.getAllByText(execution.STOCK_VALIDATION_UNAVAILABLE).length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole('button', { name: /add to portfolio/i })); await screen.findByText('Added to Portfolio');
  expect(saveCalls()).toHaveLength(1); expect(usePortfolioStore.getState().positions[0]).toMatchObject({ symbol: 'AAPL', source: 'paper' });
  expect(api.postStockOrder).not.toHaveBeenCalled(); expect(api.addStrategyWatch).not.toHaveBeenCalled();
});

// Open only validation in this group to verify inherited save-first/recovery;
// production has no positive authority and is exercised unmocked above.
describe('shared send integration behind the validation boundary', () => {
  beforeEach(() => jest.spyOn(execution, 'stockExecutionBlock').mockReturnValue(null));
  it('requires a method and saves edited values before ordering server-approved quantity', async () => {
    const log: string[] = []; echoFetch(12); const inner = (global.fetch as jest.Mock).getMockImplementation()!;
    (global.fetch as jest.Mock).mockImplementation(async (...args) => { log.push('save'); return inner(...args); });
    (api.postStockOrder as jest.Mock).mockImplementationOnce(async () => { log.push('order'); return { order_id: 'ORD-1' }; });
    render(<Step7PositionCardPage />); fireEvent.click(screen.getByRole('button', { name: /ibkr paper/i }));
    expect(screen.getByRole('button', { name: /limit @/i })).toBeDisabled(); expect(screen.getByRole('button', { name: 'Market Order' })).toBeDisabled();
    await edit('ENTRY', '152'); await edit('STOP', '144'); await edit('SHARES', '50'); await edit('T1 TARGET', '162');
    fireEvent.click(screen.getByRole('radio', { name: 'Ladder' })); fireEvent.click(screen.getByRole('button', { name: /limit @/i }));
    await screen.findByText(/Order placed — ID: ORD-1/); expect(log).toEqual(['save', 'order']);
    const payload = JSON.parse(saveCalls()[0][1].body);
    expect(payload).toMatchObject({ entryPrice: 152, qty: 50, stop: 144, pickedMethod: 'ladder', pickedStopBasis: 'stock' });
    expect(payload.targets.map((t: { stockPrice: number }) => t.stockPrice)).toEqual([162, 165, 170]);
    expect((api.postStockOrder as jest.Mock).mock.calls[0][0]).toMatchObject({ symbol: 'AAPL', quantity: 12, limit_price: 152, action: 'BUY', order_type: 'LMT' });
    expect(usePortfolioStore.getState().positions[0].contracts).toBe(12); expect(screen.getByRole('button', { name: /limit @/i })).toBeDisabled();
  });
  it('finishes an in-flight order for its origin after navigation and remount without duplicates', async () => {
    const pending = deferred<{ order_id: string }>(); (api.postStockOrder as jest.Mock).mockReturnValueOnce(pending.promise);
    const view = render(<Step7PositionCardPage />); selectLadderAndBroker(); fireEvent.click(screen.getByRole('button', { name: /limit @/i }));
    await waitFor(() => expect(api.postStockOrder).toHaveBeenCalledTimes(1)); fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expectSelected('MSFT'); expect(screen.queryByText(/Order placed/)).not.toBeInTheDocument();
    view.unmount(); render(<Step7PositionCardPage />); fireEvent.click(screen.getByRole('button', { name: 'Prev' }));
    expect(screen.getByRole('button', { name: 'Placing…' })).toBeDisabled();
    await act(async () => pending.resolve({ order_id: 'ORIGIN' }));
    expect(usePortfolioStore.getState().positions[0].symbol).toBe('AAPL'); expect(screen.getByRole('button', { name: /limit @/i })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'AAPL' })); fireEvent.click(screen.getByRole('button', { name: /limit @/i }));
    expect(api.postStockOrder).toHaveBeenCalledTimes(1);
  });
  it('preserves ambiguous outcomes and notes through navigation, replacement and empty results', async () => {
    (api.postStockOrder as jest.Mock).mockRejectedValueOnce(new Error('API /broker/stock-order → 504: Gateway Timeout'));
    const view = render(<Step7PositionCardPage />); selectLadderAndBroker(); fireEvent.click(screen.getByRole('button', { name: /limit @/i }));
    await screen.findByText(/AAPL 30 sh: order status UNKNOWN/i);
    fireEvent.click(screen.getByRole('button', { name: 'Next' })); fireEvent.click(screen.getByRole('button', { name: 'Prev' }));
    expect(screen.getByRole('button', { name: /limit @/i })).toBeDisabled();
    view.unmount(); act(() => useScanStore.getState().setStockScanResult(scan())); render(<Step7PositionCardPage />); selectLadderAndBroker();
    fireEvent.click(screen.getByRole('button', { name: /limit @/i })); expect(api.postStockOrder).toHaveBeenCalledTimes(1);
    act(() => useScanStore.getState().setStockScanResult(scan([])));
    expect(screen.getByText(/AAPL 30 sh: order status UNKNOWN/i)).toBeInTheDocument();
  });
  it('keeps unconfirmed-save notes and sends no order', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('offline'));
    render(<Step7PositionCardPage />); selectLadderAndBroker(); fireEvent.click(screen.getByRole('button', { name: /limit @/i }));
    await screen.findByText(/AAPL 30 sh: Portfolio tracking could not be confirmed/);
    expect(api.postStockOrder).not.toHaveBeenCalled(); expect(useDirectSendNotesStore.getState().notes[0].kind).toBe('save-unconfirmed');
  });
});

const BEARISH_REASON = 'Bearish setups are Unvalidated: no bearish strategy has passed validation yet (decision STOCKS-PARAMS-PER-HORIZON-2026-10-05). Visible for research; no PASS, no auto-trade, no opening order.';

it('B4 inherits the Bearish refusal through the shared stock card and basket', async () => {
  const selected = card('AAPL', 'Bearish');
  useScanStore.getState().setStockScanResult(scan([selected]));
  useScanStore.getState().addToStockBasket(selected);
  render(<Step7PositionCardPage />);
  selectLadderAndBroker();
  expect(screen.getByRole('button', { name: /limit @/i })).toBeDisabled();
  expect(screen.getByRole('button', { name: /limit @/i })).toHaveAttribute('title', BEARISH_REASON);
  expect(screen.getByRole('button', { name: 'Market Order' })).toHaveAttribute('title', BEARISH_REASON);
  fireEvent.click(screen.getByRole('button', { name: 'Send basket (1)' }));
  const dialog = screen.getByRole('dialog');
  fireEvent.click(within(dialog).getByRole('button', { name: 'IBKR Paper' }));
  const send = within(dialog).getByRole('button', { name: /submit 1 order/i });
  expect(send).toBeDisabled();
  expect(send).toHaveAttribute('title', BEARISH_REASON);
  fireEvent.click(send);
  await act(async () => {});
  expect(saveCalls()).toHaveLength(0);
  expect(api.postStockOrder).not.toHaveBeenCalled();
});

/* STOCKS-HORIZON-P0B B7 — the Step-7 position card inherits the earnings veto
 * through the shared StockPositionCard and StockSendDialog. */
const EARNINGS_VETO_REASON = 'Earnings inside the reject window — no send';

it('B7 inherits the earnings veto through the shared stock card and basket', async () => {
  const selected = { ...card('AAPL'), earnings_days: 40, earnings_veto: true } as PositionCardData;
  useScanStore.getState().setStockScanResult({ ...scan([selected]), veto_days: 60 } as StockScanResult);
  useScanStore.getState().addToStockBasket(selected);
  render(<Step7PositionCardPage />);
  selectLadderAndBroker();
  expect(screen.getByRole('button', { name: /limit @/i })).toBeDisabled();
  expect(screen.getByRole('button', { name: /limit @/i })).toHaveAttribute('title', EARNINGS_VETO_REASON);
  expect(screen.getByRole('button', { name: 'Market Order' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Market Order' })).toHaveAttribute('title', EARNINGS_VETO_REASON);
  fireEvent.click(screen.getByRole('button', { name: /limit @/i }));
  fireEvent.click(screen.getByRole('button', { name: 'Send basket (1)' }));
  const dialog = screen.getByRole('dialog');
  fireEvent.click(within(dialog).getByRole('button', { name: 'IBKR Paper' }));
  const send = within(dialog).getByRole('button', { name: /submit 1 order/i });
  expect(send).toBeDisabled();
  expect(send).toHaveAttribute('title', EARNINGS_VETO_REASON);
  fireEvent.click(send);
  await act(async () => {});
  expect(saveCalls()).toHaveLength(0);
  expect(api.postStockOrder).not.toHaveBeenCalled();
});
