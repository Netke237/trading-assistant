'use client';

import { useEffect } from 'react';
import { useChartStore } from '@/lib/chartStore';
import { useChartAlertStore } from '@/lib/chartAlertStore';
import { useScanStore, toLocalWallClock } from '@/lib/scanStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useStructureStore } from '@/lib/structureStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { useWatchedContractsStore } from '@/lib/watchedContractsStore';
import { useThemeStore } from '@/lib/theme';
import { useAutoTradeStore } from '@/lib/autoTradeStore';
import { useDrawingStore } from '@/lib/drawingStore';
import { useRiskStore } from '@/lib/riskStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useAlertStore } from '@/lib/alertStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { useSearchProfilesStore } from '@/lib/searchProfilesStore';
import { contextFromScanRequest, resultMatchesContext } from '@/lib/scanContextFromResult';
import { api } from '@/lib/api';
import { useUniverseStore } from '@/lib/universeStore';
import { isValidUniverse } from '@/lib/universeResolution';

// Backend timestamps are real UTC-offset ISO strings (e.g. "...T18:32:10+00:00",
// from Python's `datetime.now(timezone.utc).isoformat()`). Every scanAt/stockScanAt
// consumer in this app (ScanIndicator, TopBar, the dashboard rail) parses the stored
// string via `new Date(iso)` and expects an *offset-free local wall-clock* string —
// toLocalWallClock() (imported from scanStore.ts, shared with its own live-scan
// auto-stamp) converts a backend timestamp into that same convention. Naively
// slicing the backend's UTC string to 19 chars would keep UTC clock digits
// mislabeled as local, shifting the displayed time by the viewer's UTC offset.

export function StoreHydration() {
  useEffect(() => {
    useChartStore.persist.rehydrate();
    useChartAlertStore.persist.rehydrate();
    useSettingsStore.persist.rehydrate();
    useStructureStore.persist.rehydrate();
    useWatchlistStore.persist.rehydrate();
    useWatchedContractsStore.persist.rehydrate();
    useThemeStore.persist.rehydrate();
    useAutoTradeStore.persist.rehydrate();
    useDrawingStore.persist.rehydrate();
    useRiskStore.persist.rehydrate();
    usePortfolioStore.persist.rehydrate();
    useAlertStore.persist.rehydrate();
    useScanParamsStore.persist.rehydrate();
    useSearchProfilesStore.persist.rehydrate();

    (async () => {
      await useScanStore.persist.rehydrate();
      const ctxUniverse = useScanStore.getState().context?.universe;
      if (ctxUniverse && isValidUniverse(ctxUniverse)) {
        useUniverseStore.getState().setPick(ctxUniverse);
      }
      const { scanResult, stockScanResult, setScanResult, setStockScanResult, setScanState } = useScanStore.getState();

      // Both recoveries are fetched FIRST and applied together below: whether
      // the options result's context may be rebuilt depends on whether a
      // stock result is held (STEP3-PARAM-REACH), and the context must be in
      // place before the result appears, or Step 6 -- which fetches as soon
      // as the candidates change -- would grade the restored result under the
      // null context's Bullish / no-hold-days defaults. A failed fetch is
      // null: nothing to recover, state left as it is.
      const [last, lastStock] = await Promise.all([
        scanResult ? null : api.getLastScan().catch(() => null),
        stockScanResult ? null : api.getLastStockScan().catch(() => null),
      ]);

      if (lastStock) {
        setStockScanResult(lastStock);
        // setStockScanResult()'s own auto-stamp (frontend/lib/scanStore.ts:186-190)
        // uses local wall-clock time too — correct for "now", wrong here specifically,
        // since a recovered scan could be hours old. Overwrite with the real timestamp.
        useScanStore.setState({ stockScanAt: toLocalWallClock(lastStock.timestamp) });
      }

      // STEP3-PARAM-REACH: not under a persisted context it was not produced
      // for (direction, preset or hold days changed since -- setContext
      // cleared the result then, for exactly this reason).
      if (last && resultMatchesContext(last.request_context, useScanStore.getState().context)) {
        // An options result restored into an empty browser gets the context
        // it was produced from, so Steps 5-7 read its direction and hold days
        // instead of the Bullish / Swing defaults. Written BEFORE the result,
        // so no subscriber ever sees the result under the null context; set
        // directly, NOT via setContext, whose context-changed branch clears
        // results. ScanContext is SHARED with Stocks mode (strategy list,
        // first-passage and exit-plan horizon, portfolio snapshot), so it is
        // only rebuilt in Options mode with no stock result held: a stock
        // result has its own request and would otherwise be read under the
        // options scan's direction and horizon.
        const now = useScanStore.getState();
        if (now.context === null && now.screenerMode === 'options' && !now.stockScanResult) {
          const restored = contextFromScanRequest(last.request_context);
          if (restored) useScanStore.setState({ context: restored });
        }
        // A recorded result must not appear under null/default context when
        // reconstruction was unsafe or its record was unusable. Leave the
        // options result empty (the user can run a scan); keep the stock result.
        // Legacy results without a record retain their previous fallback.
        if (!last.request_context || useScanStore.getState().context !== null) {
          setScanResult(last);
          setScanState('COMPLETED', toLocalWallClock(last.timestamp));
        }
      }

      // A5: a stock result with no request on record (recovered just above,
      // or persisted before v17) gets the backend's record of the request
      // behind ITS result -- attached only when the scan_ids match at write
      // time, re-read then so a scan finishing meanwhile is never paired with
      // this older request. No match: stays null and Analysis says it is on
      // current settings instead of claiming to mirror the scan.
      {
        const { stockScanResult: held, stockScanRequest } = useScanStore.getState();
        if (held && !stockScanRequest) {
          try {
            const rec = await api.getLastStockScanRequest();
            const now = useScanStore.getState();
            if (rec && now.stockScanResult && !now.stockScanRequest
                && rec.scan_id === now.stockScanResult.scan_id) {
              useScanStore.setState({ stockScanRequest: rec.request });
            }
          } catch {
            // Backend unreachable or no record -- leave null (current-settings basis).
          }
        }
      }

      // Last-run status/strategy metadata — unlike the two blocks above, fetch
      // unconditionally on every load (not just when the store is empty): this
      // can go stale independent of whether a cached result already exists.
      try {
        const optStatus = await api.getLastScanStatus();
        useScanStore.getState().setLastOptionsScanMeta(
          optStatus.status,
          optStatus.updated_at ? toLocalWallClock(optStatus.updated_at) : null,
        );
      } catch {
        // No backend reachable yet, or nothing to recover — leave state as-is.
      }

      try {
        const stkStatus = await api.getLastStockScanStatus();
        useScanStore.getState().setLastStockScanMeta(
          stkStatus.status,
          stkStatus.updated_at ? toLocalWallClock(stkStatus.updated_at) : null,
          stkStatus.strategy ?? null,
        );
      } catch {
        // Same fallback behavior as above.
      }
    })();
  }, []);

  return null;
}
