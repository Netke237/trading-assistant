'use client';

/*
 * TopBar — spec §4. Persistent across every page.
 * Left:        BAMENDJOU wordmark + product tagline
 * Center-left: last-scan context
 * Center-right: scan state pill (IDLE / SCANNING / COMPLETED hh:mm / FAILED)
 * Right:       regime dot + "Regime: PASS" + ModeToggle
 */

import { Title, Text } from '@/components/primitives';
import { StatusDot } from '@/components/atoms/StatusDot';
import { ModeToggle } from '@/components/atoms/ModeToggle';
import { useScanStore } from '@/lib/scanStore';
import type { ScanState } from '@/lib/scanStore';
import styles from './TopBar.module.css';

const PILL_CLASS: Record<ScanState, string> = {
  IDLE:      styles.pillIdle,
  SCANNING:  styles.pillScanning,
  COMPLETED: styles.pillCompleted,
  FAILED:    styles.pillFailed,
};

function pillLabel(state: ScanState, time: string | null): string {
  if (state === 'COMPLETED' && time) return `COMPLETED ${time}`;
  return state;
}

export function TopBar() {
  const scanState = useScanStore((s) => s.scanState);
  const scanTime  = useScanStore((s) => s.scanTime);
  const context   = useScanStore((s) => s.context);
  const regime    = useScanStore((s) => s.regime);

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
        {pillLabel(scanState, scanTime)}
      </span>

      <div className={styles.regimeGroup}>
        <StatusDot tone={regime} />
        <Text size={12}>Regime: {regime === 'NO_DATA' ? 'NO DATA' : regime}</Text>
      </div>

      <ModeToggle />
    </header>
  );
}
