'use client';

import { useEffect, useState, useCallback } from 'react';
import { Text, Data } from '@/components/primitives';
import type { ToastItem } from '@/types/domain';
import styles from './Toast.module.css';

interface ToastProps {
  item: ToastItem;
  onDismiss: (id: string) => void;
}

export function Toast({ item, onDismiss }: ToastProps) {
  const [hovered, setHovered] = useState(false);
  const reducedMotion = typeof window !== 'undefined'
    ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
    : false;

  const handleDismiss = useCallback(() => {
    onDismiss(item.id);
  }, [item.id, onDismiss]);

  useEffect(() => {
    if (hovered) return;
    const timer = setTimeout(handleDismiss, 5000);
    return () => clearTimeout(timer);
  }, [hovered, handleDismiss]);

  return (
    <div
      className={[styles.toast, styles[item.kind.toLowerCase()]].join(' ')}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      role="alert"
    >
      <ToastIcon kind={item.kind} />
      <div className={styles.body}>
        <Data size={12} weight={500}>{item.symbol}</Data>
        <Text size={12} tone="secondary">{item.reason}</Text>
      </div>
      <button
        type="button"
        className={styles.dismiss}
        onClick={handleDismiss}
        aria-label="Dismiss alert"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="14" height="14">
          <path d="M18 6 6 18M6 6l12 12" />
        </svg>
      </button>
      {!reducedMotion && (
        <div className={styles.progress}>
          <div className={styles.progressBar} />
        </div>
      )}
    </div>
  );
}

function ToastIcon({ kind }: { kind: ToastItem['kind'] }) {
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
      width="16"
      height="16"
    >
      <path d={path} />
    </svg>
  );
}
