'use client';

/*
 * TopBar — spec §4. Persistent across every page.
 * Left:        BAMENDJOU wordmark + product tagline
 * Center-left: last-scan context
 * Center-right: scan state pill (IDLE / SCANNING / COMPLETED hh:mm / FAILED)
 * Right:       regime dot + "Regime: PASS" + ModeToggle
 */

import { useEffect, useState } from 'react';
import { Title, Text } from '@/components/primitives';
import { RegimeIndicator } from '@/components/molecules/RegimeIndicator';
import { TopBarActions } from '@/components/molecules/TopBarActions';
import { AlertBadge } from '@/components/atoms/AlertBadge';
import { useScanStore } from '@/lib/scanStore';
import { useAlertStore } from '@/lib/alertStore';
import type { ScanState } from '@/lib/scanStore';
import styles from './TopBar.module.css';

const PILL_CLASS: Record<ScanState, string> = {
  IDLE:       styles.pillIdle,
  SCANNING:   styles.pillScanning,
  COMPLETED:  styles.pillCompleted,
  FAILED:     styles.pillFailed,
  PARTIAL:    styles.pillPartial,
  CANCELLED:  styles.pillCancelled,
};

/** Deterministic HH:mm slice from the stored local-ISO string. Safe during SSR. */
function hhmmFrom(iso: string): string {
  return iso.slice(11, 16);
}

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** Client-only label with date prefix when the scan isn't today. */
function labelWithDate(iso: string): string {
  const hhmm = hhmmFrom(iso);
  const scan = new Date(iso);
  const now  = new Date();
  const diffDays = Math.round((startOfDay(now) - startOfDay(scan)) / 86_400_000);
  if (diffDays === 0) return hhmm;
  if (diffDays === 1) return `Yesterday ${hhmm}`;
  const sameYear = scan.getFullYear() === now.getFullYear();
  const mon = scan.toLocaleString(undefined, { month: 'short' });
  const day = scan.getDate();
  return sameYear
    ? `${mon} ${day} ${hhmm}`
    : `${mon} ${day} ${scan.getFullYear()} ${hhmm}`;
}

function pillLabel(state: ScanState, iso: string | null, mounted: boolean): string {
  if ((state === 'COMPLETED' || state === 'PARTIAL' || state === 'CANCELLED') && iso) {
    // Before mount we render just HH:mm to avoid SSR/client timezone mismatch.
    return `${state} ${mounted ? labelWithDate(iso) : hhmmFrom(iso)}`;
  }
  return state;
}

function BellButton() {
  const unreadCount = useAlertStore((s) => s.unreadCount);
  const clearAll = useAlertStore((s) => s.clearAll);
  return (
    <button
      type="button"
      className={styles.bell}
      onClick={clearAll}
      aria-label="Notifications"
      title="Notifications"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="18" height="18">
        <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
        <path d="M13.73 21a2 2 0 0 1-3.46 0" />
      </svg>
      <AlertBadge count={unreadCount} />
    </button>
  );
}

export function TopBar() {
  const scanState = useScanStore((s) => s.scanState);
  const scanAt    = useScanStore((s) => s.scanAt);
  const context   = useScanStore((s) => s.context);
  const scanError = useScanStore((s) => s.scanError);
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  return (
    <header className={styles.bar}>
      <div className={styles.brand}>
        <Title as="span" size={20}>BAMENDJOU</Title>
        <Text size={11} tone="secondary">Options Screener</Text>
      </div>

      <div className={styles.scanContext}>
        {context && (
          <Text size={12} tone="secondary">
            Last scan: {context.universe} · {context.direction} · {context.horizon}
          </Text>
        )}
        {scanError && scanState === 'FAILED' && (
          <Text size={12} tone="reject">
            {scanError}
          </Text>
        )}
      </div>

      <span className={[styles.pill, PILL_CLASS[scanState]].join(' ')}>
        {pillLabel(scanState, scanAt, mounted)}
      </span>

      <RegimeIndicator />

      <BellButton />

      <TopBarActions />
    </header>
  );
}
