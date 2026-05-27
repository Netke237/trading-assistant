'use client';
import { useState } from 'react';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { WatchStar } from '@/components/atoms/WatchStar';
import { Text } from '@/components/primitives';
import styles from './ChartRightPanel.module.css';

type Tab = 'watchlist' | 'data';

export interface DataValues {
  time: string | null;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  indicators: Record<string, number>;
}

interface Props {
  crosshairData: DataValues;
}

export default function ChartRightPanel({ crosshairData }: Props) {
  const [tab, setTab] = useState<Tab>('watchlist');
  const added = useWatchlistStore(s => s.added);

  return (
    <div className={styles.panel}>
      <div className={styles.tabs}>
        {(['watchlist', 'data'] as Tab[]).map(t => (
          <button
            key={t}
            className={`${styles.tab} ${tab === t ? styles.tabActive : ''}`}
            onClick={() => setTab(t)}
          >
            {t === 'watchlist' ? 'Watchlist' : 'Data'}
          </button>
        ))}
      </div>

      {tab === 'watchlist' && (
        <div className={styles.list}>
          {added.length === 0 && (
            <div className={styles.empty}>
              <Text size={11} tone="dim">No symbols watched</Text>
            </div>
          )}
          {added.map(sym => (
            <div key={sym} className={styles.row}>
              <WatchStar symbol={sym} size="sm" />
              <Text size={12} tone="primary">{sym}</Text>
            </div>
          ))}
        </div>
      )}

      {tab === 'data' && (
        <div className={styles.dataPanel}>
          {crosshairData.time ? (
            <>
              <Text size={10} tone="dim" as="p">{crosshairData.time}</Text>
              {crosshairData.open !== undefined && (
                <div className={styles.ohlcv}>
                  <span>O <b>{crosshairData.open?.toFixed(2)}</b></span>
                  <span>H <b>{crosshairData.high?.toFixed(2)}</b></span>
                  <span>L <b>{crosshairData.low?.toFixed(2)}</b></span>
                  <span>C <b>{crosshairData.close?.toFixed(2)}</b></span>
                </div>
              )}
              {Object.entries(crosshairData.indicators).map(([id, val]) => (
                <div key={id} className={styles.indicatorVal}>
                  <Text size={10} tone="secondary">{id}</Text>
                  <Text size={10} tone="primary">{val.toFixed(4)}</Text>
                </div>
              ))}
            </>
          ) : (
            <Text size={11} tone="dim">Hover over chart</Text>
          )}
        </div>
      )}
    </div>
  );
}
