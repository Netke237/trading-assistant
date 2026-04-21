'use client';

/*
 * StepNavBar — bottom bar shown inside the Screener workflow.
 * Layout: [← Back]              Step X of 7              [Next →]
 * Spec §4 — 52px tall, sticky to the bottom of the workspace.
 *
 * Keyboard: Left/Right arrows navigate Back/Next. Drift log G4.
 */

import { useRouter, usePathname } from 'next/navigation';
import { useEffect, useCallback } from 'react';
import { Text } from '@/components/primitives';
import {
  SCREENER_STEPS,
  currentStepFromPath,
} from '@/components/organisms/Stepper';
import styles from './StepNavBar.module.css';

export function StepNavBar() {
  const router   = useRouter();
  const pathname = usePathname();
  const current  = currentStepFromPath(pathname);

  const prev = SCREENER_STEPS[current - 2];
  const next = SCREENER_STEPS[current];

  const goPrev = useCallback(() => {
    if (prev) router.push(`/screener/${prev.slug}`);
  }, [prev, router]);
  const goNext = useCallback(() => {
    if (next) router.push(`/screener/${next.slug}`);
  }, [next, router]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // ignore when focus is inside an input/textarea/contenteditable
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
      if (e.key === 'ArrowLeft')  { e.preventDefault(); goPrev(); }
      if (e.key === 'ArrowRight') { e.preventDefault(); goNext(); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [goPrev, goNext]);

  return (
    <nav className={styles.bar} aria-label="Screener step navigation">
      <button
        type="button"
        className={styles.btn}
        onClick={goPrev}
        disabled={!prev}
      >
        <span aria-hidden="true">←</span>
        <Text size={13} weight={500}>{prev ? `Back: ${prev.label}` : 'Back'}</Text>
      </button>

      <div className={styles.center}>
        <Text size={11} tone="dim" weight={500}>
          STEP {current} OF {SCREENER_STEPS.length}
        </Text>
      </div>

      <button
        type="button"
        className={`${styles.btn} ${styles.btnPrimary}`}
        onClick={goNext}
        disabled={!next}
      >
        <Text size={13} weight={500}>{next ? `Next: ${next.label}` : 'Done'}</Text>
        <span aria-hidden="true">→</span>
      </button>
    </nav>
  );
}
