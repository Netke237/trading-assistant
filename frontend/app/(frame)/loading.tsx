/*
 * Frame-level loading state. Shown while a route segment streams in.
 * Intentionally minimal — the persistent shell is already visible.
 */

import { Text } from '@/components/primitives';
import styles from './loading.module.css';

export default function Loading() {
  return (
    <div className={styles.wrap} role="status" aria-live="polite">
      <div className={styles.spinner} aria-hidden="true" />
      <Text size={12} tone="secondary">Loading…</Text>
    </div>
  );
}
