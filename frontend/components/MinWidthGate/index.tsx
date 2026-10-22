'use client';

/*
 * MinWidthGate — default desktop minimum1280px; the Options Trade Card and
 * Stocks Position workspace support1200px.
 * Rather than adding responsive breakpoints, block the app under the threshold
 * with a friendly explainer. Uses matchMedia so it responds to window resizes.
 */

import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';
import { Title, Text } from '@/components/primitives';
import styles from './MinWidthGate.module.css';

const MIN_WIDTH = 1280;
const TRADE_CARD_MIN_WIDTH = 1200;

export function MinWidthGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // The two Step 7 presentation workspaces support1200px. Keep the original desktop
  // minimum on every other route; children remain mounted behind this overlay.
  const minWidth = pathname === '/screener/step-7-trade-card'
    || pathname === '/screener/step-7-position-card'
    ? TRADE_CARD_MIN_WIDTH : MIN_WIDTH;
  const [tooNarrow, setTooNarrow] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${minWidth - 1}px)`);
    const sync = () => setTooNarrow(mq.matches);
    sync();
    mq.addEventListener('change', sync);
    return () => mq.removeEventListener('change', sync);
  }, [minWidth]);

  return (
    <>
      {children}
      {tooNarrow && (
        <div className={styles.overlay} role="dialog" aria-modal="true" aria-label="Desktop required">
          <div className={styles.card}>
            <Title as="h2" size={20}>Desktop required</Title>
            <Text size={13} tone="secondary">
              Bamendjou is designed for a trading desktop. Please use a window at least
              {minWidth}&nbsp;pixels wide. Current width: {typeof window !== 'undefined' ? window.innerWidth : '—'}&nbsp;px.
            </Text>
          </div>
        </div>
      )}
    </>
  );
}
