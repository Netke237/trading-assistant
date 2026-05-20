'use client';

import { useEffect, useState } from 'react';
import { Title, Text } from '@/components/primitives';
import { RegimeIndicator } from '@/components/molecules/RegimeIndicator';
import { TopBarActions } from '@/components/molecules/TopBarActions';
import { useScanStore } from '@/lib/scanStore';
import styles from './TopBar.module.css';

const PILL_CLASS: Record<import('@/lib/scanStore').ScanState, string> = {
  IDLE:       styles.pillIdle,
  SCANNING:   styles.pillScanning,
  COMPLETED:  styles.pillCompleted,
  FAILED:     styles.pillFailed,
  PARTIAL:    styles.pillPartial,
  CANCELLED:  styles.pillCancelled,
};

function hhmmFrom(iso: string): string {
  return iso.slice(11, 16);
}

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

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

function pillLabel(state: import('@/lib/scanStore').ScanState, iso: string | null, mounted: boolean): string {
  if ((state === 'COMPLETED' || state === 'PARTIAL' || state === 'CANCELLED') && iso) {
    return `${state} ${mounted ? labelWithDate(iso) : hhmmFrom(iso)}`;
  }
  return state;
}

export function TopBar() {
  const scanState = useScanStore((s) => s.scanState);
  const scanAt    = useScanStore((s) => s.scanAt);
  const context   = useScanStore((s) => s.context);
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
      </div>

      <span className={[styles.pill, PILL_CLASS[scanState]].join(' ')}>
        {pillLabel(scanState, scanAt, mounted)}
      </span>

      <RegimeIndicator />

      <TopBarActions />
    </header>
  );
}
