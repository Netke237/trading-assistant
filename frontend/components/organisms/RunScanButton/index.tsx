'use client';

/*
 * RunScanButton — floating Run Scan FAB.
 * Spec §4: "Run Scan" surfaces scan state in TopBar pill.
 *
 * Mock flow (v1, no backend):
 *   IDLE/COMPLETED/FAILED → click → SCANNING (1.5s) → COMPLETED with fresh time.
 *
 * Reads + writes useScanStore. The TopBar scan-state pill is already wired to
 * the same store, so the pill animation and context string update together.
 */

import { useCallback } from 'react';
import { useScanStore } from '@/lib/scanStore';
import styles from './index.module.css';

function nowLocalISO(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

export function RunScanButton() {
  const scanState    = useScanStore((s) => s.scanState);
  const setScanState = useScanStore((s) => s.setScanState);

  const scanning = scanState === 'SCANNING';

  const onClick = useCallback(() => {
    if (scanning) return;
    setScanState('SCANNING');
    setTimeout(() => {
      setScanState('COMPLETED', nowLocalISO());
    }, 1500);
  }, [scanning, setScanState]);

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
