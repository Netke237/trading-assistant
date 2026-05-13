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

import { useCallback } from 'react';
import { useScanStore } from '@/lib/scanStore';
import { useUniverseStore } from '@/lib/universeStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useAlertStore } from '@/lib/alertStore';
import { api } from '@/lib/api';
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
  const scanState    = useScanStore((s) => s.scanState);
  const setScanState = useScanStore((s) => s.setScanState);
  const setScanResult = useScanStore((s) => s.setScanResult);
  const context      = useScanStore((s) => s.context);
  const pick         = useUniverseStore((s) => s.pick);
  const customRaw    = useUniverseStore((s) => s.customRaw);
  const minPriceRaw  = useUniverseStore((s) => s.minPriceRaw);
  const maxPriceRaw  = useUniverseStore((s) => s.maxPriceRaw);
  const minCapRaw    = useUniverseStore((s) => s.minCapRaw);
  const maxCapRaw    = useUniverseStore((s) => s.maxCapRaw);
  const capUnit      = useUniverseStore((s) => s.capUnit);
  const scanning = scanState === 'SCANNING';

  const onClick = useCallback(() => {
    if (scanning) return;

    const universe = pick === 'Custom' ? parseSymbols(customRaw) : [pick];
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

    const filters: Record<string, number> = {};
    const minPrice = Number(minPriceRaw);
    const maxPrice = Number(maxPriceRaw);
    const minCap = Number(minCapRaw);
    const maxCap = Number(maxCapRaw);
    const capMultiplier = capUnit === 'B' ? 1e9 : 1;

    if (Number.isFinite(minPrice) && minPriceRaw !== '') filters.min_price = minPrice;
    if (Number.isFinite(maxPrice) && maxPriceRaw !== '') filters.max_price = maxPrice;
    if (Number.isFinite(minCap) && minCapRaw !== '') filters.min_cap_usd = minCap * capMultiplier;
    if (Number.isFinite(maxCap) && maxCapRaw !== '') filters.max_cap_usd = maxCap * capMultiplier;

    setScanState('SCANNING');
    api.postScan(universe, direction, horizon, filters)
      .then((result) => {
        setScanResult(result);
        useScanStore.getState().setRejectedLog(result.rejected ?? []);
        const portfolioSymbols = new Set(usePortfolioStore.getState().positions.map((p) => p.symbol));
        const conflicted = result.candidates
          .map((c) => c.symbol)
          .filter((s) => portfolioSymbols.has(s));
        useScanStore.getState().setConflictedSymbols(conflicted);
        setScanState('COMPLETED', nowLocalISO());
      })
      .catch(() => {
        console.error('[RunScanButton] scan failed, is backend running on port 8000?');
        setScanState('FAILED');
        useAlertStore.getState().addToast({
          kind: 'Critical',
          symbol: 'SYSTEM',
          reason: 'Scan failed — backend unreachable',
          recId: 'SCAN-FAILED',
          alertType: 'SCAN_FAILED',
        });
      });
  }, [scanning, setScanState, setScanResult, context, pick, customRaw, minPriceRaw, maxPriceRaw, minCapRaw, maxCapRaw, capUnit]);

  return (
    <button
      type="button"
      className={styles.fab}
      onClick={onClick}
      disabled={scanning}
      aria-label={scanning ? 'Scan in progress' : 'Run scan'}
      aria-live="polite"
    >
      <span className={`${styles.icon} ${scanning ? styles.spin : ''}`} aria-hidden>
        {scanning ? <SpinnerIcon /> : <PlayIcon />}
      </span>
      <span>{scanning ? 'Scanning…' : 'Run Scan'}</span>
    </button>
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
