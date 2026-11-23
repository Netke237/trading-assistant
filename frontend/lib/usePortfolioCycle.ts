'use client';

import { useEffect, useRef } from 'react';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { usePerformanceStore } from '@/lib/performanceStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useAlertStore } from '@/lib/alertStore';
import { scanPortfolio } from '@/lib/alertEngine';

export const PORTFOLIO_CYCLE_MS = 30_000;

/*
 * The Portfolio page's 30 s cycle: refresh live quotes -> run the alert engine
 * -> refresh the equity curve. Chained so alerts fire on freshly fetched
 * prices, not on a parallel clock.
 *
 * PAUSE: the cycle runs only while `document.visibilityState` is not 'hidden'
 * (the pattern of ConfigHealthBanner). While hidden nothing is called. On
 * return the interval is re-created and ONE cycle runs at once, so the next
 * tick is 30 s after return. A tab mounted while hidden defers its first
 * cycle to the first `visible` event.
 *
 * ALERTS WHILE HIDDEN: the backend monitor keeps running independent of any
 * tab and sends Gmail/Telegram (`notify_alert`, de-duplicated, filtered by
 * `enabledTypes`) plus the websocket broadcast. The in-app toast path is
 * page-only: nothing is evaluated or queued while hidden. A condition that is
 * still true when the tab returns raises its toast from the immediate return
 * cycle (the scan is state-based; `addToast` de-duplicates on `alertKey`). A
 * condition that came and went while hidden gets no in-app toast and nothing
 * is replayed; the external notification is the record.
 *
 * GATE: only an exact `false` from `syncFromBackend` is a failure (mocks and
 * legacy callers resolve `undefined`). After a failed sync the quotes did not
 * refresh, so neither the alert scan (it would toast from stale prices) nor
 * the performance fetch (the curve would be read without the preceding
 * snapshot write) runs.
 */
export function usePortfolioCycle(onSynced?: () => void): void {
  // Latest callback without re-arming the interval.
  const onSyncedRef = useRef(onSynced);
  onSyncedRef.current = onSynced;
  useEffect(() => {
    const visible = () => document.visibilityState !== 'hidden';
    let running = false;
    let first = true;
    let id: ReturnType<typeof setInterval> | null = null;
    let disposed = false;

    const runCycle = async () => {
      if (running || disposed) return;
      running = true;
      const initial = first;
      first = false;
      try {
        // Sync FIRST: GET /api/portfolio writes today's equity snapshot when
        // every position got a quote; only then read performance.
        const ok = await usePortfolioStore.getState().syncFromBackend?.();
        if (disposed || ok === false) return;
        onSyncedRef.current?.();
        if (!initial) {
          const positions = usePortfolioStore.getState().positions;
          const pct = useSettingsStore.getState().premiumStopPct;
          const addToast = useAlertStore.getState().addToast;
          // Read here, not captured, so a Settings change applies next cycle.
          const enabledTypes = useAlertStore.getState().config.enabledTypes;
          for (const r of scanPortfolio(positions, { premiumStopPct: pct, enabledTypes })) addToast(r);
        }
        usePerformanceStore.getState().fetchPerformance();
      } catch {
        /* a failed cycle is retried on the next tick */
      } finally {
        running = false;
      }
    };

    const arm = () => {
      if (id !== null) clearInterval(id);
      id = setInterval(() => { if (visible()) void runCycle(); }, PORTFOLIO_CYCLE_MS);
    };
    const onVisibility = () => {
      if (!visible()) return;
      arm();
      void runCycle();
    };

    if (visible()) void runCycle();
    arm();
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      disposed = true;
      if (id !== null) clearInterval(id);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, []);
}
