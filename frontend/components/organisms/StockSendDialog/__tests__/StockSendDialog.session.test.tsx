import '@testing-library/jest-dom';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { StockSendDialog } from '../index';
import { useScanStore } from '@/lib/scanStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { defaultStockOverlay, resolveBasketExecution, stockExecutionIdentity, useStockOrderOwnershipStore } from '@/lib/stockExecutionSession';
import { api } from '@/lib/api';
import type { PositionCardData, StockScanResult } from '@/types/stockDomain';

jest.mock('@/lib/api', () => ({ api: { getBrokerStatus: jest.fn().mockResolvedValue({}), postStockOrder: jest.fn() } }));
const card = { symbol: 'AAPL', company: 'Apple', direction: 'Bearish', shares: 30,
  strategy: { strategy: 'pullback_ema', entry_price: 150, stop_price: 155, target_price: 140, targets: [140, 135, 130] },
} as PositionCardData;
const pick = { method: 'ladder' as const, rowStockPrice: 140, rowOptionPrice: null, stopBasis: 'stock' as const, pickedAt: 'now' };
const originalAdd = usePortfolioStore.getState().addPosition;
function setup() {
  useStockOrderOwnershipStore.setState({ bySymbol: {} });
  useScanStore.setState({ stockExecutionGeneration: 0, stockExecution: {}, stockBasket: [], stockBasketSources: {} });
  useScanStore.getState().setStockScanResult({ scan_id: 'scan', candidates: [card], timestamp: 'now' } as StockScanResult);
  useScanStore.getState().setCardEdit('stocks', 'picks', card.symbol, pick);
  useScanStore.getState().addToStockBasket(card);
  return stockExecutionIdentity(useScanStore.getState(), card.symbol)!;
}
beforeEach(() => { jest.clearAllMocks(); setup(); });
afterEach(() => usePortfolioStore.setState({ addPosition: originalAdd }));
function mount() { return render(<StockSendDialog cards={[card]} onClose={jest.fn()} onSubmit={jest.fn()} />); }
it('uses matching shared edits for totals, saved levels, allocation, snapshot and pick; quantity edits scale shared allocations', async () => {
  const identity = stockExecutionIdentity(useScanStore.getState(), 'AAPL')!;
  useScanStore.getState().patchStockExecution(identity, { overlay: { ...defaultStockOverlay(card), entry: 149, stop: 154, t1: 139, t2: 134, t3: 129 }, structural: { price: 156, source: 'swing_high', confidence: 1, distancePct: 1 } });
  const add = jest.fn().mockResolvedValue({ status: 'ok' });
  usePortfolioStore.setState({ addPosition: add });
  mount();
  expect(screen.getByText('$149.00')).toBeInTheDocument();
  expect(screen.getByText(/Est total/).textContent).toContain('4,470');
  fireEvent.change(screen.getByLabelText('Shares for AAPL'), { target: { value: '60' } });
  expect(useScanStore.getState().stockExecution[identity].overlay?.sharesT1).toBe(20);
  await act(async () => fireEvent.click(screen.getByRole('button', { name: /submit 1 order/i })));
  const pos = add.mock.calls[0][0];
  expect(pos).toMatchObject({ entryPrice: 149, contracts: 60, stop: 154, structuralStop: 156, pickedMethod: 'ladder' });
  expect(pos.targets.map((t: { price: number; stockPrice: number; contractsToSell: number }) => [t.stockPrice, t.contractsToSell])).toEqual([[139, 20], [134, 20], [129, 20]]);
  expect(pos.tradeCardSnapshot.edited).toEqual({ entry: 149, stop: 154, targets: [139, 134, 129], shares: 60 });
});
it('legacy and replacement rows retain pristine saved values and cannot borrow live same-symbol picks or evidence', () => {
  const identity = stockExecutionIdentity(useScanStore.getState(), 'AAPL')!;
  useScanStore.getState().patchStockExecution(identity, { overlay: { ...defaultStockOverlay(card), entry: 90 } });
  useScanStore.setState({ stockBasketSources: {} });
  expect(resolveBasketExecution(useScanStore.getState(), card)).toMatchObject({ entry: 150, stop: 155, shares: 30, pick: null, overlay: undefined });
  mount();
  expect(screen.getByText('$150.00')).toBeInTheDocument();
  expect(screen.getByText(/Saved basket values/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /submit 1 order/i })).toBeDisabled();
});
it.each(['pending', 'ok'])('retains %s research-save ownership across dialog remount without duplicate saves', async status => {
  const add = jest.fn().mockResolvedValue({ status });
  usePortfolioStore.setState({ addPosition: add });
  const view = mount();
  await act(async () => fireEvent.click(screen.getByRole('button', { name: /submit 1 order/i })));
  view.unmount(); mount();
  expect(screen.getByRole('button', { name: /submit 1 order/i })).toBeDisabled();
  expect(add).toHaveBeenCalledTimes(1);
});
it('retains in-flight ownership after close and scan replacement while completing original save bookkeeping', async () => {
  let resolve!: (value: { status: string }) => void;
  const add = jest.fn(() => new Promise(r => { resolve = r; }));
  usePortfolioStore.setState({ addPosition: add as never });
  const view = mount();
  fireEvent.click(screen.getByRole('button', { name: /submit 1 order/i }));
  view.unmount();
  act(() => useScanStore.getState().setStockScanResult({ scan_id: 'scan', timestamp: 'new', candidates: [{ ...card }] } as StockScanResult));
  mount();
  expect(screen.getByRole('button', { name: /submit 1 order/i })).toBeDisabled();
  await act(async () => resolve({ status: 'pending' }));
  expect(useStockOrderOwnershipStore.getState().bySymbol.AAPL.status).toBe('unknown');
  expect(add).toHaveBeenCalledTimes(1);
});
it.each(['Bullish', 'Bearish'])('keeps %s broker sends unavailable while research saves remain available', async direction => {
  card.direction = direction as 'Bullish' | 'Bearish';
  card.strategy.targets = direction === 'Bullish' ? [160, 165, 170] : [140, 135, 130];
  useSettingsStore.setState({ ibkrPaper: { accountId: 'ACC', baseUrl: 'localhost' } });
  const add = jest.fn().mockResolvedValue({ status: 'ok' });
  usePortfolioStore.setState({ addPosition: add });
  mount(); fireEvent.click(screen.getByText('IBKR Paper'));
  await act(async () => fireEvent.click(screen.getByRole('button', { name: /submit 1 order/i })));
  expect(api.postStockOrder).not.toHaveBeenCalled(); expect(add).not.toHaveBeenCalled();
  expect(screen.getByText(direction === 'Bearish' ? BEARISH_REASON : /Unvalidated/)).toBeInTheDocument();
  card.direction = 'Bearish'; card.strategy.targets = [140, 135, 130];
});

const BEARISH_REASON = 'Bearish setups are Unvalidated: no bearish strategy has passed validation yet (decision STOCKS-PARAMS-PER-HORIZON-2026-10-05). Visible for research; no PASS, no auto-trade, no opening order.';

it('B4 disables a Bearish broker basket before saving, while leaving research saves available', async () => {
  useSettingsStore.setState({ ibkrPaper: { accountId: 'ACC', baseUrl: 'localhost' } });
  const add = jest.fn().mockResolvedValue({ status: 'ok' });
  usePortfolioStore.setState({ addPosition: add });
  mount();
  fireEvent.click(screen.getByRole('button', { name: 'IBKR Paper' }));
  const button = screen.getByRole('button', { name: /submit 1 order/i });
  expect(button).toBeDisabled();
  expect(button).toHaveAttribute('title', BEARISH_REASON);
  expect(screen.getByText(BEARISH_REASON)).toBeInTheDocument();
  fireEvent.click(button);
  await act(async () => {});
  expect(add).not.toHaveBeenCalled();
  expect(api.postStockOrder).not.toHaveBeenCalled();
  fireEvent.click(screen.getByLabelText('Auto-send AAPL'));
  expect(button).toBeEnabled();
});
