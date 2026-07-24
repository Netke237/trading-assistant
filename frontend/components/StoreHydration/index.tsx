'use client';

import { useEffect } from 'react';
import { useChartStore } from '@/lib/chartStore';
import { useChartAlertStore } from '@/lib/chartAlertStore';
import { useScanStore } from '@/lib/scanStore';
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
import { api } from '@/lib/api';

/** Backend timestamps are real UTC-offset ISO strings (e.g. "...T18:32:10+00:00",
 *  from Python's `datetime.now(timezone.utc).isoformat()`). Every scanAt/stockScanAt
 *  consumer in this app (ScanIndicator, TopBar, the dashboard rail) parses the stored
 *  string via `new Date(iso)` and expects an *offset-free local wall-clock* string —
 *  the same convention RunScanButton's own `nowLocalISO()` produces for a live scan
 *  (frontend/components/organisms/RunScanButton/index.tsx:27-34). Naively slicing the
 *  backend's UTC string to 19 chars would keep UTC clock digits mislabeled as local,
 *  shifting the displayed time by the viewer's UTC offset — this converts properly. */
function toLocalWallClock(isoWithOffset: string): string {
  const d = new Date(isoWithOffset);
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

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
    })();
  }, []);

  return null;
}
