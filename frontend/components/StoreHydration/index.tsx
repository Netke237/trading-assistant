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
import { api } from '@/lib/api';

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
      const { scanResult, stockScanResult, setScanResult, setStockScanResult, setScanState } = useScanStore.getState();

      if (!scanResult) {
        try {
          const last = await api.getLastScan();
          if (last) {
            setScanResult(last);
            setScanState('COMPLETED', toLocalWallClock(last.timestamp));
          }
        } catch {
          // No backend reachable yet, or nothing to recover — leave state as-is.
        }
      }

      if (!stockScanResult) {
        try {
          const lastStock = await api.getLastStockScan();
          if (lastStock) {
            setStockScanResult(lastStock);
            // setStockScanResult()'s own auto-stamp (frontend/lib/scanStore.ts:186-190)
            // uses local wall-clock time too — correct for "now", wrong here specifically,
            // since a recovered scan could be hours old. Overwrite with the real timestamp.
            useScanStore.setState({ stockScanAt: toLocalWallClock(lastStock.timestamp) });
          }
        } catch {
          // Same fallback behavior as above.
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
