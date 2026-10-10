'use client';

import { useState, useEffect, useRef } from 'react';
import { Text } from '@/components/primitives';
import { useScanStore } from '@/lib/scanStore';
import { api, getLastDataRefresh } from '@/lib/api';
import styles from './page.module.css';

/** The Pre-warm history row, moved verbatim from Step 5 (step-5-strategy). */
export function HistoryPrefetchRow() {
  const context = useScanStore((s) => s.context);

  const [lastRefreshTs, setLastRefreshTs] = useState<string | null>(null);
  const [prefetchStatus, setPrefetchStatus] = useState<
    'idle' | 'running' | 'completed' | 'error' | null
  >(null);
  const [prefetchProgress, setPrefetchProgress] = useState<{ done: number; total: number } | null>(null);
  const prefetchPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (prefetchPollRef.current) clearInterval(prefetchPollRef.current);
    };
  }, []);

  useEffect(() => {
    getLastDataRefresh()
      .then((r) => setLastRefreshTs(r.last_refresh))
      .catch(() => {});
  }, []);

  async function startPrefetch() {
    try {
      const universe = context?.universe ? [context.universe] : ['SP500'];
      await api.startHistoryPrefetch({ universe });
      setPrefetchStatus('running');
      prefetchPollRef.current = setInterval(async () => {
        try {
          const s = await api.getHistoryPrefetchStatus();
          setPrefetchProgress({ done: s.done, total: s.total });
          if (s.status === 'completed' || s.status === 'error') {
            setPrefetchStatus(s.status);
            if (prefetchPollRef.current) { clearInterval(prefetchPollRef.current); prefetchPollRef.current = null; }
          }
        } catch {
          if (prefetchPollRef.current) { clearInterval(prefetchPollRef.current); prefetchPollRef.current = null; }
        }
      }, 5_000);
    } catch {
      setPrefetchStatus('error');
    }
  }

  return (
      <div className={styles.prefetchRow}>
        <div className={styles.prefetchLeft}>
          <Text size={12} tone="secondary">
            Historical data:{' '}
            {prefetchStatus === 'running' && prefetchProgress
              ? `warming up ${prefetchProgress.done}/${prefetchProgress.total}`
              : prefetchStatus === 'completed'
              ? 'ready'
              : prefetchStatus === 'error'
              ? 'error — retry below'
              : 'not pre-warmed'}
          </Text>
          {lastRefreshTs && (
            <Text size={11} tone="dim">
              Last refresh: {new Date(lastRefreshTs).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}
            </Text>
          )}
        </div>
        {prefetchStatus !== 'running' && (
          <button
            className={styles.prefetchBtn}
            onClick={startPrefetch}
          >
            {prefetchStatus === 'completed' ? 'Re-warm' : 'Pre-warm history'}
          </button>
        )}
      </div>
  );
}
