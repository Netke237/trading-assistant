'use client';
import { useState, useEffect } from 'react';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { useChartAlertStore } from '@/lib/chartAlertStore';
import { WatchStar } from '@/components/atoms/WatchStar';
import { Text } from '@/components/primitives';
import styles from './ChartRightPanel.module.css';

type Tab = 'watchlist' | 'data' | 'alerts';

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
  symbol: string;
}

export default function ChartRightPanel({ crosshairData, symbol }: Props) {
  const [tab, setTab] = useState<Tab>('watchlist');
  const added = useWatchlistStore((s) => s.added);
  const history = useChartAlertStore((s) => s.history);
  const rules = useChartAlertStore((s) => s.rules);
  const dismissHistory = useChartAlertStore((s) => s.dismissHistory);
  const markViewed = useChartAlertStore((s) => s.markViewed);
  const newSinceView = useChartAlertStore((s) => s.newSinceView);

  useEffect(() => {
    if (tab === 'alerts') markViewed();
  }, [tab, markViewed]);

  const tabLabels: Record<Tab, string> = {
    watchlist: 'Watchlist',
    data: 'Data',
    alerts: 'Alerts',
  };

  const symbolHistory = history.filter((h) => h.symbol === symbol);

  function timeAgo(iso: string): string {
    const diff = Date.now() - new Date(iso).getTime();
    const m = Math.floor(diff / 60_000);
    if (m < 1) return 'just now';
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  }

  function ruleName(ruleId: string): string {
    return rules.find((r) => r.id === ruleId)?.name ?? ruleId;
  }

  return (
    <div className={styles.panel}>
      <div className={styles.tabs}>
        {(['watchlist', 'data', 'alerts'] as Tab[]).map((t) => (
          <button
            key={t}
            className={`${styles.tab} ${tab === t ? styles.tabActive : ''}`}
            onClick={() => setTab(t)}
          >
            {tabLabels[t]}
            {t === 'alerts' && newSinceView > 0 && (
              <span className={styles.badge}>{newSinceView}</span>
            )}
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
          {added.map((sym) => (
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

      {tab === 'alerts' && (
        <div className={styles.list}>
          {symbolHistory.length === 0 && (
            <div className={styles.empty}>
              <Text size={11} tone="dim">No alerts for {symbol}</Text>
            </div>
          )}
          {symbolHistory.map((h) => (
            <div key={h.id} className={styles.alertRow}>
              <div className={styles.alertHeader}>
                <Text size={10} tone="dim">{timeAgo(h.triggered_at)}</Text>
                <button
                  className={styles.alertDismiss}
                  onClick={() => dismissHistory(h.id)}
                  aria-label="Dismiss alert"
                >
                  &times;
                </button>
              </div>
              <Text size={11} tone="primary" weight={500}>{h.reason}</Text>
              <Text size={10} tone="secondary">{ruleName(h.rule_id)}</Text>
              {h.candle && (
                <div className={styles.alertOch}>
                  <Text size={10} tone="dim">
                    O:{h.candle.open.toFixed(2)} C:{h.candle.close.toFixed(2)} H:{h.candle.high.toFixed(2)} L:{h.candle.low.toFixed(2)}
                  </Text>
                </div>
              )}
              {Object.keys(h.trigger_values).length > 0 && (
                <div className={styles.alertVals}>
                  {Object.entries(h.trigger_values).map(([k, v]) => (
                    <span key={k} className={styles.alertVal}>
                      {k}: {v.toFixed(2)}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
