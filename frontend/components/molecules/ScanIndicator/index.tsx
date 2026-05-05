'use client';

import { useEffect, useState } from 'react';
import { Text, Data } from '@/components/primitives';
import { StatusDot } from '@/components/atoms/StatusDot';
import type { StatusDotTone } from '@/components/atoms/StatusDot';
import { useScanStore } from '@/lib/scanStore';
import type { ScanState } from '@/lib/scanStore';
import styles from './ScanIndicator.module.css';

const SCAN_DOT: Record<ScanState, StatusDotTone> = {
  IDLE:       'PENDING',
  SCANNING:   'ACCENT',
  COMPLETED:  'PASS',
  FAILED:     'REJECT',
  PARTIAL:    'CAUTION',
  CANCELLED:  'PENDING',
};

const SCAN_LABEL: Record<ScanState, string> = {
  IDLE:       'IDLE',
  SCANNING:   'SCANNING',
  COMPLETED:  'COMPLETED',
  FAILED:     'FAILED',
  PARTIAL:    'PARTIAL',
  CANCELLED:  'CANCELLED',
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

export function ScanIndicator() {
  const scanState = useScanStore((s) => s.scanState);
  const scanAt    = useScanStore((s) => s.scanAt);

  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const timestamp = (scanState === 'COMPLETED' || scanState === 'PARTIAL' || scanState === 'CANCELLED') && scanAt
    ? mounted ? labelWithDate(scanAt) : hhmmFrom(scanAt)
    : null;

  return (
    <div className={styles.root}>
      <StatusDot tone={SCAN_DOT[scanState]} size="sm" />
      <Text size={10} tone="secondary">{SCAN_LABEL[scanState]}</Text>
      {timestamp && <Data size={10} tone="secondary">{timestamp}</Data>}
    </div>
  );
}
