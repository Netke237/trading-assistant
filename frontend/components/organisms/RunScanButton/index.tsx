'use client';

/*
 * RunScanButton — floating Run Scan FAB.
 * Spec §4: "Run Scan" surfaces scan state in TopBar pill.
 *
 * Real flow:
 *   IDLE/COMPLETED/FAILED → click → SCANNING → COMPLETED with fresh time.
 *
 * Reads + writes useScanStore. The TopBar scan-state pill is already wired to
 * the same store, so the pill animation and context string update together.
 */

import { useCallback, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useScanStore, toLocalWallClock } from '@/lib/scanStore';
import { useUniverseStore } from '@/lib/universeStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useAlertStore } from '@/lib/alertStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { api } from '@/lib/api';
import { runStockScan } from '@/lib/stockScan';
import { presetByKey, resolveParamsHorizon } from '@/lib/horizonPresets';
import { buildOptionsScanRequestBody } from '@/lib/resolveOptionsScanRequest';
import styles from './index.module.css';

function nowLocalISO(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

function parseSymbols(raw: string): string[] {
  return Array.from(
    new Set(
      raw
        .split(/[\s,;\n]+/)
        .map((s) => s.trim().toUpperCase())
        .filter((s) => /^[A-Z][A-Z0-9.\-]{0,5}$/.test(s)),
    ),
  );
}

export function RunScanButton() {
  const scanState      = useScanStore((s) => s.scanState);
  const setScanState   = useScanStore((s) => s.setScanState);
  const setScanResult  = useScanStore((s) => s.setScanResult);
  const context        = useScanStore((s) => s.context);
  const screenerMode   = useScanStore((s) => s.screenerMode);
  const activeStrategy = useScanStore((s) => s.activeStrategy);
  const pick         = useUniverseStore((s) => s.pick);
  const customRaw    = useUniverseStore((s) => s.customRaw);
  const minPriceRaw  = useUniverseStore((s) => s.minPriceRaw);
  const maxPriceRaw  = useUniverseStore((s) => s.maxPriceRaw);
  const minCapRaw    = useUniverseStore((s) => s.minCapRaw);
  const maxCapRaw    = useUniverseStore((s) => s.maxCapRaw);
  const capUnit      = useUniverseStore((s) => s.capUnit);
  const shortlistMaxCandidates = useSettingsStore((s) => s.shortlistMaxCandidates);
  const fundamentalsGate = useSettingsStore((s) => s.fundamentalsGate);
  const scanning    = scanState === 'SCANNING';
  const router = useRouter();
  const customEmpty = pick === 'Custom' && parseSymbols(customRaw).length === 0;

  const [showRegimeConfirm, setShowRegimeConfirm] = useState(false);
  const regimeConfirmedRef = useRef(false);

  const onClick = useCallback(() => {
    if (scanning) return;

    if (screenerMode === 'prebreakout') {
      router.push('/screener/step-4-prebreakout');
      return;
    }

    if (screenerMode === 'stocks') {
      if (!activeStrategy) {
        useAlertStore.getState().addToast({
          kind: 'Critical',
          symbol: 'SYSTEM',
          reason: 'Pick a strategy on Step 4 before running the scan.',
          recId: 'STRATEGY-NOT-SELECTED',
          alertType: 'SCAN_FAILED',
        });
        return;
      }
      // Fire-and-forget by design (the button reflects progress through
      // scanState), but a failure must not be silent: this path has no inline
      // error area of its own the way step-4-stocks does, so surface the
      // reason runStockScan() parked in the store as a toast, exactly as the
      // options path below does for its own failure.
      void runStockScan(activeStrategy).then((res) => {
        if (res) return;
        useAlertStore.getState().addToast({
          kind: 'Critical',
          symbol: 'SYSTEM',
          reason: `Stock scan failed — ${useScanStore.getState().stockScanError ?? 'unknown error'}`,
          recId: 'STOCK-SCAN-FAILED',
          alertType: 'SCAN_FAILED',
        });
      });
      return;
    }

    const universe =
      pick === 'Custom'
        ? parseSymbols(customRaw)
        : pick === 'Watchlist'
        ? useWatchlistStore.getState().added
        : [pick];

    if (universe.length === 0) {
      useAlertStore.getState().addToast({
        kind: 'Critical',
        symbol: 'SYSTEM',
        reason: 'Watchlist is empty — add symbols before scanning.',
        recId: 'WATCHLIST-EMPTY',
        alertType: 'SCAN_FAILED',
      });
      return;
    }

    const direction = context?.direction ?? 'Bullish';
    const presetKey = context?.horizonPreset ?? 'Swing';
    const holdMin   = context?.holdMin ?? presetByKey('Swing').holdMin;
    const holdMax   = context?.holdMax ?? presetByKey('Swing').holdMax;
    // The backend scorer knows only Intraday/Swing/Position. Long-dated presets
    // and Custom map onto one of those for scoring; the DTE window itself comes
    // from the hold days, computed backend-side.
    // Equivalent to the old ternary for every presetKey value (same reasoning
    // as page.tsx's weightsKey/scoringHz).
    const horizon: string = presetByKey(resolveParamsHorizon(presetKey, holdMax)).scoringHorizon;

    const currentRegime = useScanStore.getState().combinedRegime;
    if (currentRegime === 'REJECT' && !regimeConfirmedRef.current) {
      setShowRegimeConfirm(true);
      return;
    }

    const scanOverrides = useScanStore.getState().scanOverrides;
    const gate = useSettingsStore.getState().confidenceGate;
    const spreads = useSettingsStore.getState().spreads;

    const requestBody = buildOptionsScanRequestBody({
      universe, direction, horizon,
      // The uncollapsed preset key travels alongside the scoring horizon, not
      // instead of it — the repricing table is keyed on this one. Same value
      // the trade card sends to /first-passage as horizon_preset.
      horizonPreset: presetKey,
      holdMinDays: holdMin, holdMaxDays: holdMax,
      minPriceRaw, maxPriceRaw, minCapRaw, maxCapRaw, capUnit,
      scanOverrides,
      confidenceGate: gate,
      fundamentalsGate,
      shortlistMaxCandidates,
      spreads,
    });

    const t0 = Date.now();
    const startISO = nowLocalISO();        // capture start time before the async call
    setScanState('SCANNING', startISO);   // scanAt = START time (not end)
    useScanStore.getState().setRejectedLog([]);
    api.postScanBody(requestBody)
      .then((result) => {
        setScanResult(result);
        useScanStore.getState().setRejectedLog(result.rejected ?? []);
        const portfolioSymbols = new Set(usePortfolioStore.getState().positions.map((p) => p.symbol));
        const conflicted = result.candidates
          .map((c) => c.symbol)
          .filter((s) => portfolioSymbols.has(s));
        useScanStore.getState().setConflictedSymbols(conflicted);
        if (screenerMode === 'options') useScanStore.getState().setOptionsScanAt(startISO);
        setScanState('COMPLETED', startISO, Date.now() - t0);  // keep same startISO
        // Refresh last-run status from the backend so TopBar/Settings reflect
        // this scan immediately, not just after the next full page load.
        api.getLastScanStatus()
          .then((s) => useScanStore.getState().setLastOptionsScanMeta(
            s.status, s.updated_at ? toLocalWallClock(s.updated_at) : null,
          ))
          .catch(() => {});
      })
      .catch(() => {
        console.error('[RunScanButton] scan failed, is backend running on port 8000?');
        useScanStore.getState().setRejectedLog([]);
        setScanState('FAILED', startISO, Date.now() - t0);
        useAlertStore.getState().addToast({
          kind: 'Critical',
          symbol: 'SYSTEM',
          reason: 'Scan failed — backend unreachable',
          recId: 'SCAN-FAILED',
          alertType: 'SCAN_FAILED',
        });
      });
  }, [scanning, setScanState, setScanResult, context, pick, customRaw, minPriceRaw, maxPriceRaw, minCapRaw, maxCapRaw, capUnit, screenerMode, activeStrategy, shortlistMaxCandidates, fundamentalsGate, router]);

  return (
    <>
      {showRegimeConfirm && (
        <div className={styles.regimeOverlay} role="dialog" aria-modal aria-labelledby="regime-run-title">
          <div className={styles.regimeDialog}>
            <p id="regime-run-title" className={styles.regimeDialogTitle}>Market regime is REJECT</p>
            <p className={styles.regimeDialogBody}>
              Running a {context?.direction ?? 'Bullish'} scan while the regime opposes it (REJECT) carries elevated risk.
              Proceed anyway?
            </p>
            <div className={styles.regimeDialogActions}>
              <button type="button" className={styles.regimeCancelBtn}
                onClick={() => setShowRegimeConfirm(false)}>
                Cancel
              </button>
              <button type="button" className={styles.regimeProceedBtn}
                onClick={() => {
                  setShowRegimeConfirm(false);
                  regimeConfirmedRef.current = true;
                  onClick();
                  regimeConfirmedRef.current = false;
                }}>
                Proceed anyway
              </button>
            </div>
          </div>
        </div>
      )}

      <button
        type="button"
        className={styles.fab}
        onClick={onClick}
        disabled={scanning || (screenerMode !== 'prebreakout' && customEmpty)}
        title={customEmpty ? 'Enter at least one valid symbol' : undefined}
        aria-label={scanning ? 'Scan in progress' : screenerMode === 'stocks' ? 'Run stock scan' : screenerMode === 'prebreakout' ? 'Go to Setup Scanner' : 'Run scan'}
        aria-live="polite"
      >
        <span className={`${styles.icon} ${scanning ? styles.spin : ''}`} aria-hidden>
          {scanning ? <SpinnerIcon /> : <PlayIcon />}
        </span>
        <span>{scanning ? 'Scanning…' : screenerMode === 'stocks' ? 'Run Stock Scan' : screenerMode === 'prebreakout' ? 'Go to Setup Scanner' : 'Run Scan'}</span>
      </button>
    </>
  );
}

function PlayIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M3.5 2.5 L11.5 7 L3.5 11.5 Z" fill="currentColor" />
    </svg>
  );
}

function SpinnerIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <circle cx="7" cy="7" r="5.5" stroke="currentColor" strokeOpacity="0.3" strokeWidth="1.5" />
      <path d="M12.5 7 A5.5 5.5 0 0 0 7 1.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}
