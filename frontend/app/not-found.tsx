/*
 * Global 404. Rendered outside the persistent frame so it also covers the
 * `/` index and any unknown top-level routes.
 */

import Link from 'next/link';
import { Title, Text } from '@/components/primitives';
import styles from './not-found.module.css';

export default function NotFound() {
  return (
    <div className={styles.wrap}>
      <div className={styles.card}>
        <Text size={11} tone="dim">404</Text>
        <Title as="h1" size={24}>Page not found</Title>
        <Text size={13} tone="secondary">
          That URL isn&rsquo;t part of the app. Try the dashboard or your watchlist.
        </Text>
        <div className={styles.actions}>
          <Link href="/dashboard" className={styles.btnPrimary}>Dashboard</Link>
          <Link href="/watchlist" className={styles.btn}>Watchlist</Link>
        </div>
      </div>
    </div>
  );
}
