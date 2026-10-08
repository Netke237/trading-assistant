import { useScanStore } from '@/lib/scanStore';
import { defaultStockOverlay, stockExecutionIdentity, useStockOrderOwnershipStore } from '@/lib/stockExecutionSession';
import type { PositionCardData, StockScanResult } from '@/types/stockDomain';
const candidate = { symbol: 'AAPL', direction: 'Bullish', shares: 30, strategy: { entry_price: 150, stop_price: 145, target_price: 160, targets: [160, 165, 170] } } as PositionCardData;
const result = () => ({ scan_id: 'same', timestamp: 't', candidates: [candidate], rejected: [] } as unknown as StockScanResult);
beforeEach(() => useScanStore.setState({ stockScanResult: null, stockExecution: {}, stockExecutionGeneration: 0, stockAfterScanIntent: {}, stockBasketSources: {} }));
it('retains valid records on request attachment to the same result, but invalidates equal-id replacement evidence/picks', () => {
  const scan = result();
  useScanStore.getState().setStockScanResult(scan);
  const identity = stockExecutionIdentity(useScanStore.getState(), 'AAPL')!;
  useScanStore.getState().patchStockExecution(identity, { overlay: { ...defaultStockOverlay(candidate), entry: 152 } });
  useScanStore.getState().setCardEdit('stocks', 'picks', 'AAPL', { method: 'ladder', rowStockPrice: 160, rowOptionPrice: null, stopBasis: 'stock', pickedAt: 'now' });
  useScanStore.getState().setStockScanResult(scan, { strategy: 'test' } as never);
  expect(stockExecutionIdentity(useScanStore.getState(), 'AAPL')).toBe(identity);
  expect(useScanStore.getState().stockExecution[identity].overlay?.entry).toBe(152);
  useScanStore.getState().setStockScanResult(result());
  expect(stockExecutionIdentity(useScanStore.getState(), 'AAPL')).not.toBe(identity);
  expect(useScanStore.getState().stockExecution[identity]).toBeUndefined();
  expect(useScanStore.getState().stocksCardEdits.picks).toEqual({});
  useScanStore.getState().patchStockExecution(identity, { estimate: { targets: [] } as never });
  expect(useScanStore.getState().stockExecution[identity]).toBeUndefined();
});
it('does not persist or hydrate ephemeral execution fields even from forged same-version blobs', () => {
  useScanStore.getState().setStockScanResult(result());
  useScanStore.getState().setStockAfterScanIntent('AAPL', true);
  useScanStore.getState().addToStockBasket(candidate);
  const state = useScanStore.getState();
  const saved = useScanStore.persist.getOptions().partialize!(state) as Record<string, unknown>;
  for (const field of ['stockExecution', 'stockAfterScanIntent', 'stockBasketSources', 'stockExecutionGeneration', 'stockManualRunToken', 'stockScanFeedback', 'stockAfterScanOutcomes']) expect(saved).not.toHaveProperty(field);
  const merged = useScanStore.persist.getOptions().merge!({
    ...saved, stockExecution: { forged: { overlay: { entry: 1 }, eligible: true } }, stockAfterScanIntent: { AAPL: true }, stockBasketSources: { AAPL: 'forged' }, stockManualRunToken: 999, stockExecutionGeneration: 99, stockAfterScanOutcomes: { fake: { status: 'saving' } }, stockScanFeedback: { error: 'fake' },
  }, state);
  expect(merged.stockExecution).toEqual({});
  expect(merged.stockAfterScanIntent).toEqual({});
  expect(merged.stockBasketSources).toEqual({});
  expect(merged.stockAfterScanOutcomes).toEqual({});
  expect(merged.stockBasket).toEqual([candidate]);
  expect(merged.stockScanResult).toEqual(state.stockScanResult);
  expect(merged.stockManualRunToken).toBe(state.stockManualRunToken + 1);
});
it('keeps started mutation ownership when scan evidence is retired and finishes against the originating identity', () => {
  useScanStore.getState().setStockScanResult(result());
  const identity = stockExecutionIdentity(useScanStore.getState(), 'AAPL')!;
  useScanStore.getState().patchStockExecution(identity, { placingType: 'LMT', overlay: defaultStockOverlay(candidate) });
  useScanStore.getState().setStockScanResult(null);
  expect(useScanStore.getState().stockExecution[identity].placingType).toBe('LMT');
  expect(useScanStore.getState().stockExecution[identity].overlay).toBeUndefined();
  useScanStore.getState().patchStockExecution(identity, { placingType: null, orderId: 'ORDER-1' });
  expect(useScanStore.getState().stockExecution[identity].orderId).toBe('ORDER-1');
  const ownership = useStockOrderOwnershipStore.getState();
  useStockOrderOwnershipStore.setState({ bySymbol: {} });
  expect(ownership.claim('AAPL', { identity, recId: 'one', status: 'in-flight' })).toBe(true);
  expect(ownership.claim('AAPL', { identity: 'another', recId: 'two', status: 'in-flight' })).toBe(false);
  ownership.finish('AAPL', 'one', 'unknown', 'Needs reconciliation');
  expect(ownership.claim('AAPL', { identity: 'new-scan', recId: 'three', status: 'in-flight' })).toBe(false);
});
