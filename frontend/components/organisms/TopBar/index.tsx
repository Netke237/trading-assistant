'use client';

import { useEffect, useState } from 'react';
import { Title, Text } from '@/components/primitives';
import { RegimeIndicator } from '@/components/molecules/RegimeIndicator';
import { TopBarActions } from '@/components/molecules/TopBarActions';
import { MarketClock } from '@/components/molecules/MarketClock';
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

function formatDuration(ms: number): string {
  if (ms < 500) return '';
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const s = Math.round(ms / 1000);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r === 0 ? `${m}m` : `${m}m ${r}s`;
}

function pillLabel(
  state: import('@/lib/scanStore').ScanState,
  iso: string | null,
  mounted: boolean,
  durationMs: number | null,
): string {
  const showDuration =
    state === 'COMPLETED' || state === 'PARTIAL' || state === 'FAILED' || state === 'CANCELLED';
  if ((state === 'COMPLETED' || state === 'PARTIAL' || state === 'CANCELLED') && iso) {
    // iso is the START time; show "COMPLETED started 18:03 · 15m 53s"
    const startLabel = mounted ? labelWithDate(iso) : hhmmFrom(iso);
    const base = `${state} · started ${startLabel}`;
    const dur = showDuration && durationMs ? formatDuration(durationMs) : '';
    return dur ? `${base} · ${dur}` : base;
  }
  if (state === 'FAILED') {
    const dur = durationMs ? formatDuration(durationMs) : '';
    return dur ? `FAILED · ${dur}` : 'FAILED';
  }
  return state;
}

export function TopBar() {
  const scanState    = useScanStore((s) => s.scanState);
  const scanAt       = useScanStore((s) => s.scanAt);
  const scanDuration = useScanStore((s) => s.scanDurationMs);
  const context      = useScanStore((s) => s.context);
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
            {scanAt && mounted && (
              <> · started {labelWithDate(scanAt)}</>
            )}
            {scanDuration != null && scanDuration >= 500 && (
              <> · {formatDuration(scanDuration)}</>
            )}
          </Text>
        )}
      </div>

      <span className={[styles.pill, PILL_CLASS[scanState]].join(' ')}>
        {pillLabel(scanState, scanAt, mounted, scanDuration)}
      </span>

      <RegimeIndicator />

      <MarketClock />

      <TopBarActions />
    </header>
  );
}
