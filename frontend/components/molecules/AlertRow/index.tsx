/*
 * AlertRow — alert list item. Icon | symbol (mono) | reason (DM Sans) | time (mono dim).
 */

import { Text, Data } from '@/components/primitives';
import type { AlertKind } from '@/types/domain';
import styles from './AlertRow.module.css';

interface AlertRowProps {
  kind: AlertKind;
  symbol: string;
  reason: string;
  timestamp: string;
  className?: string;
}

const KIND_CLASS: Record<AlertKind, string> = {
  Info:     styles.info,
  Action:   styles.action,
  Critical: styles.critical,
};

export function AlertRow({ kind, symbol, reason, timestamp, className }: AlertRowProps) {
  return (
    <div className={[styles.row, KIND_CLASS[kind], className].filter(Boolean).join(' ')}>
      <AlertIcon kind={kind} />
      <Data size={11} weight={500}>
        {symbol}
      </Data>
      <Text size={13} tone="secondary">
        {reason}
      </Text>
      <Data size={11} tone="dim" className={styles.time}>
        {timestamp}
      </Data>
    </div>
  );
}

function AlertIcon({ kind }: { kind: AlertKind }) {
  /* One icon per kind, kept minimal to avoid visual noise. */
  const path =
    kind === 'Critical'
      ? 'M12 3 2 21h20L12 3zM12 10v5M12 18h.01'
      : kind === 'Action'
      ? 'M12 2a10 10 0 1 0 10 10h-10V2z'
      : 'M12 8v4M12 16h.01M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2z';
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={styles.icon}
      aria-hidden="true"
    >
      <path d={path} />
    </svg>
  );
}
