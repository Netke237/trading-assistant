'use client';

/*
 * MinWidthGate — spec §6.3 risk #6: desktop-only (≥1200px).
 * Rather than adding responsive breakpoints, block the app under the threshold
 * with a friendly explainer. Uses matchMedia so it responds to window resizes.
 */

import { useEffect, useState } from 'react';
import { Title, Text } from '@/components/primitives';
import styles from './MinWidthGate.module.css';

const MIN_WIDTH = 1200;

export function MinWidthGate({ children }: { children: React.ReactNode }) {
  const [tooNarrow, setTooNarrow] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${MIN_WIDTH - 1}px)`);
    const sync = () => setTooNarrow(mq.matches);
    sync();
    mq.addEventListener('change', sync);
    return () => mq.removeEventListener('change', sync);
  }, []);

  return (
    <>
      {children}
      {tooNarrow && (
        <div className={styles.overlay} role="dialog" aria-modal="true" aria-label="Desktop required">
          <div className={styles.card}>
            <Title as="h2" size={20}>Desktop required</Title>
            <Text size={13} tone="secondary">
              Bamendjou is designed for a trading desktop. Please use a window at least
              1200&nbsp;pixels wide. Current width: {typeof window !== 'undefined' ? window.innerWidth : '—'}&nbsp;px.
            </Text>
          </div>
        </div>
      )}
    </>
  );
}
