import { useCallback, useState } from 'react';
import { useScanStore } from './scanStore';
import { stockExecutionIdentity, type StockExecutionRecord } from './stockExecutionSession';

/** Local-only fallback permits read-only cards without a scan identity; it
 * never installs evidence/edits in the execution session. */
export function useStockExecutionField<K extends keyof StockExecutionRecord>(
  identity: string | null, field: K, initial: Exclude<StockExecutionRecord[K], undefined>,
): [Exclude<StockExecutionRecord[K], undefined>, (value: Exclude<StockExecutionRecord[K], undefined> | ((previous: Exclude<StockExecutionRecord[K], undefined>) => Exclude<StockExecutionRecord[K], undefined>)) => void] {
  const [local, setLocal] = useState(initial);
  const stored = useScanStore(s => identity ? s.stockExecution[identity]?.[field] : undefined);
  const value = stored === undefined ? (identity ? initial : local) : stored;
  const setValue = useCallback((next: Exclude<StockExecutionRecord[K], undefined> | ((previous: Exclude<StockExecutionRecord[K], undefined>) => Exclude<StockExecutionRecord[K], undefined>)) => {
    if (!identity) { setLocal(next); return; }
    const state = useScanStore.getState();
    const previous = state.stockExecution[identity]?.[field] ?? initial;
    state.patchStockExecution(identity, { [field]: typeof next === 'function' ? next(previous as Exclude<StockExecutionRecord[K], undefined>) : next });
  }, [identity, field, initial]);
  return [value as Exclude<StockExecutionRecord[K], undefined>, setValue];
}
export function useStockExecutionIdentity(symbol: string): string | null {
  return useScanStore(s => stockExecutionIdentity(s, symbol));
}
