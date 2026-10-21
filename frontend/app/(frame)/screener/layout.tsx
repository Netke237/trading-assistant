'use client';

/*
 * Screener nested layout — spec §4.
 * Adds the mode toggle, scrollable step content, and 52px StepNavBar.
 * The persistent frame (TopBar, NavRail, ContextRail) comes from (frame)/layout.tsx.
 *
 * Structure inside the workspace grid cell:
 *   ┌───────────────────────────────────┐
 *   │  Options / Stocks mode toggle     │
 *   ├───────────────────────────────────┤
 *   │  scrollable step content          │
 *   │  (children)                       │
 *   ├───────────────────────────────────┤
 *   │  StepNavBar (Back | step | Next)  │
 *   └───────────────────────────────────┘
 */

import { useEffect } from 'react';
import { useScanStore } from '@/lib/scanStore';
import { useUniverseStore } from '@/lib/universeStore';
import { isValidUniverse } from '@/lib/universeResolution';
import { StepNavBar } from '@/components/organisms/StepNavBar';
import { ScreenerStepGate } from '@/components/organisms/ScreenerStepGate';
import styles from './screenerLayout.module.css';

export default function ScreenerLayout({ children }: { children: React.ReactNode }) {
  const mode    = useScanStore((s) => s.screenerMode);
  const setMode = useScanStore((s) => s.setScreenerMode);

  useEffect(() => {
    const ctxUniverse = useScanStore.getState().context?.universe;
    if (ctxUniverse && isValidUniverse(ctxUniverse)) {
      useUniverseStore.getState().setPick(ctxUniverse);
    }
  }, []);
  return (
    <div className={styles.wrap}>
      <div className={styles.modeToggle}>
        <button
          type="button"
          className={`${styles.modeBtn} ${mode === 'options' ? styles.modeBtnActive : ''}`}
          onClick={() => setMode('options')}
        >
          Options
        </button>
        <button
          type="button"
          className={`${styles.modeBtn} ${mode === 'stocks' ? styles.modeBtnActive : ''}`}
          onClick={() => setMode('stocks')}
        >
          Stocks
        </button>
        <button
          type="button"
          className={`${styles.modeBtn} ${mode === 'prebreakout' ? styles.modeBtnActive : ''}`}
          onClick={() => setMode('prebreakout')}
        >
          Pre-Breakout
        </button>
      </div>
      <div className={styles.scroll}>
        <ScreenerStepGate>{children}</ScreenerStepGate>
      </div>
      <StepNavBar />
    </div>
  );
}
