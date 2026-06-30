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
import { useScanStore } from '@/lib/scanStore';
import { useUniverseStore } from '@/lib/universeStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useAlertStore } from '@/lib/alertStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { api } from '@/lib/api';
import { runStockScan } from '@/lib/stockScan';
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
      if (!activeStrategy) return;
      void runStockScan(activeStrategy);
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

    const direction   = context?.direction ?? 'Bullish';
    const horizonRaw  = context?.horizon   ?? 'Swing (5–15d)';
    const horizonKey  = horizonRaw.split(' ')[0];  // "Swing (5–15d)" → "Swing"
    // "Custom" is not a valid API horizon — map to nearest preset by max-day value
    let horizon: string = horizonKey;
    if (horizonKey === 'Custom') {
      const maxMatch = horizonRaw.match(/–(\d+)d/);
      const maxDays  = maxMatch ? Number(maxMatch[1]) : 15;
      horizon = maxDays <= 4 ? 'Intraday' : maxDays <= 20 ? 'Swing' : 'Position';
    }

    const currentRegime = useScanStore.getState().combinedRegime;
    if (currentRegime === 'REJECT' && !regimeConfirmedRef.current) {
      setShowRegimeConfirm(true);
      return;
    }

    const filters: Record<string, number | boolean> = {};
    const minPrice = Number(minPriceRaw);
    const maxPrice = Number(maxPriceRaw);
    const minCap = Number(minCapRaw);
    const maxCap = Number(maxCapRaw);
    const capMultiplier = capUnit === 'B' ? 1e9 : 1;

    if (Number.isFinite(minPrice) && minPriceRaw !== '') filters.min_price = minPrice;
    if (Number.isFinite(maxPrice) && maxPriceRaw !== '') filters.max_price = maxPrice;
    if (Number.isFinite(minCap) && minCapRaw !== '') filters.min_cap_usd = minCap * capMultiplier;
    if (Number.isFinite(maxCap) && maxCapRaw !== '') filters.max_cap_usd = maxCap * capMultiplier;

    const scanOverrides = useScanStore.getState().scanOverrides;
    // Confidence gate keys live in scanOverrides for Step-3 panel editing, but
    // they must go in top-level filters, NOT in the score overrides dict.
    // Strip them here so they don't pollute the backend overrides map.
    const { confidence_caution_below: _cb, confidence_reject_below: _rb,
            confidence_atr_mult: _am, ...scoreOnlyOverrides } = scanOverrides;
    const effectiveOverrides = { ...scoreOnlyOverrides, shortlist_max_candidates: shortlistMaxCandidates };

    // Confidence gate: persisted Settings default, overridden per-scan by the
    // Execution Parameters panel (Step 3, Stocks section) which writes scanOverrides.
    // Disabled gate -> send 0/0 thresholds so confidence can never demote.
    // ATR always applies (it changes the computed confidence regardless of the gate).
    const gate = useSettingsStore.getState().confidenceGate;
    const cautionOv = scanOverrides.confidence_caution_below;
    const rejectOv  = scanOverrides.confidence_reject_below;
    const atrOv     = scanOverrides.confidence_atr_mult;
    filters.confidence_atr_mult = typeof atrOv === 'number' ? atrOv : gate.atrMult;
    if (gate.enabled) {
      filters.confidence_caution_below = typeof cautionOv === 'number' ? cautionOv : gate.cautionBelow;
      filters.confidence_reject_below  = typeof rejectOv === 'number' ? rejectOv : gate.rejectBelow;
    } else {
      filters.confidence_caution_below = 0;
      filters.confidence_reject_below  = 0;
    }

    // Fundamentals gate
    const fGate = fundamentalsGate;
    filters.fundamentals_enabled       = fGate.enabled;
    filters.fundamentals_caution_below = fGate.cautionBelow;
    filters.fundamentals_reject_below  = fGate.rejectBelow;
    filters.fundamentals_de_reject     = fGate.deReject;

    const t0 = Date.now();
    const startISO = nowLocalISO();        // capture start time before the async call
    setScanState('SCANNING', startISO);   // scanAt = START time (not end)
    useScanStore.getState().setRejectedLog([]);
    const spreads = useSettingsStore.getState().spreads;
    api.postScan(universe, direction, horizon, filters, effectiveOverrides, {
      spread_width:       spreads.widthPoints,
      short_leg_delta:    spreads.shortLegDelta,
      iv_rank_threshold:  spreads.ivRankThreshold,
      min_credit:         spreads.minCredit,
      max_debit_pct:      spreads.maxDebitPctOfWidth,
    })
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
