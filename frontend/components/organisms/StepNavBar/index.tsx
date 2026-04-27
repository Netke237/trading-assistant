'use client';

/*
 * StepNavBar — bottom bar shown inside the Screener workflow.
 * Layout: [← Back]              Step X of 7              [Next →]
 * Spec §4 — 52px tall, sticky to the bottom of the workspace.
 *
 * Keyboard: Left/Right arrows navigate Back/Next. Drift log G4.
 */

import { useRouter, usePathname } from 'next/navigation';
import { useEffect, useCallback, useState } from 'react';
import { Text } from '@/components/primitives';
import { useScanStore } from '@/lib/scanStore';
import {
  SCREENER_STEPS,
  currentStepFromPath,
} from '@/components/organisms/Stepper';
import styles from './StepNavBar.module.css';

export function StepNavBar() {
  const router   = useRouter();
  const pathname = usePathname();
  const current  = currentStepFromPath(pathname);
  const regime   = useScanStore((s) => s.regime);

  const [showConfirm, setShowConfirm] = useState(false);

  const prev = SCREENER_STEPS[current - 2];
  const next = SCREENER_STEPS[current];

  const goPrev = useCallback(() => {
    if (prev) router.push(`/screener/${prev.slug}`);
  }, [prev, router]);

  const goNext = useCallback(() => {
    if (next) router.push(`/screener/${next.slug}`);
  }, [next, router]);

  const handleNext = useCallback(() => {
    if (current === 3 && regime === 'REJECT') {
      setShowConfirm(true);
    } else {
      goNext();
    }
  }, [current, regime, goNext]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
      if (e.key === 'ArrowLeft')  { e.preventDefault(); goPrev(); }
      if (e.key === 'ArrowRight') { e.preventDefault(); handleNext(); }
      if (e.key === 'Escape' && showConfirm) setShowConfirm(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [goPrev, handleNext, showConfirm]);

  return (
    <>
      {showConfirm && (
        <div className={styles.overlay} role="dialog" aria-modal aria-labelledby="regime-dialog-title">
          <div className={styles.dialog}>
            <div className={styles.dialogIcon}>⚠</div>
            <p id="regime-dialog-title" className={styles.dialogTitle}>
              <Text size={14} weight={600}>Regime flagged as REJECT</Text>
            </p>
            <Text size={13} tone="secondary">
              Market conditions are unfavourable for new directional positions.
              Step 4 will still rank your candidates — but consider waiting for a better regime before trading.
            </Text>
            <div className={styles.dialogActions}>
              <button type="button" className={styles.btn} onClick={() => setShowConfirm(false)}>
                Cancel
              </button>
              <button
                type="button"
                className={`${styles.btn} ${styles.btnDanger}`}
                onClick={() => { setShowConfirm(false); goNext(); }}
              >
                Proceed anyway →
              </button>
            </div>
          </div>
        </div>
      )}

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
          onClick={handleNext}
          disabled={!next}
        >
          <Text size={13} weight={500}>{next ? `Next: ${next.label}` : 'Done'}</Text>
          <span aria-hidden="true">→</span>
        </button>
      </nav>
    </>
  );
}
