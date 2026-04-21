'use client';

/*
 * Frame-level error boundary. Next.js App Router hands us the thrown error and
 * a reset() to retry the segment.
 */

import { useEffect } from 'react';
import { Title, Text } from '@/components/primitives';
import styles from './error.module.css';

export default function FrameError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Hook a real reporter (Sentry etc.) in Phase 7.
    console.error('[frame] route error:', error);
  }, [error]);

  return (
    <div className={styles.wrap} role="alert">
      <Title as="h2" size={20}>Something broke in this view.</Title>
      <Text size={13} tone="secondary">
        {error.message || 'Unknown error.'}
        {error.digest && <> · <code>{error.digest}</code></>}
      </Text>
      <div className={styles.actions}>
        <button type="button" className={styles.btnPrimary} onClick={reset}>Retry</button>
        <a className={styles.btn} href="/dashboard">Back to dashboard</a>
      </div>
    </div>
  );
}
