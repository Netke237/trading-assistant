'use client';
import { Text, Data } from '@/components/primitives';
import { formatRegimeAverage } from '@/lib/regimeDuration';
import type { SentimentData } from '@/types/domain';
import styles from './MarketSentiment.module.css';

const tone = (pct: number): 'pass' | 'caution' | 'reject' =>
  pct >= 15 ? 'pass' : pct <= -15 ? 'reject' : 'caution';

export function MarketSentiment({ s, compact = false }: {
  s: SentimentData | null | undefined;
  compact?: boolean;
}) {
  if (!s || s.insufficient_data) {
    return (
      <div className={styles.empty}>
        <Text size={12} tone="caution">Regime: Unmeasured</Text>{' '}
        <Text size={12} tone="caution">Insufficient history or unavailable data.</Text>
      </div>
    );
  }
  return (
    <div className={compact ? `${styles.card} ${styles.compact}` : styles.card}>
      <div className={styles.head}>
        <Text size={12} weight={500}>Market Sentiment</Text>
        <Text size={11} tone="dim">{s.horizon} · {s.timeframe}</Text>
      </div>
      <div className={styles.row}>
        <Text size={12} tone="dim">Conviction</Text>
        <Data size={16} tone={tone(s.conviction_pct)}>
          {s.conviction_pct > 0 ? '+' : ''}{s.conviction_pct}%
        </Data>
      </div>
      <Text size={12}>{s.conviction_label} — {s.interpretation}</Text>
      <div className={styles.row}>
        <Text size={11} tone="dim">
          State {s.state} · sticky {Math.round(s.p_stay * 100)}% · {formatRegimeAverage(s.avg_regime_duration, s.duration_stride_bars)}
        </Text>
        <div className={styles.alignment}>
          <Text size={11} tone="dim">Alignment</Text>
          <span className={
            s.alignment === 'Aligned' ? styles.aligned :
            s.alignment === 'Diverging' ? styles.diverging :
            styles.unavail
          }>
            {s.alignment === 'Unavailable' ? 'OMM only' : `OMM/HMM ${s.alignment}`}
          </span>
        </div>
      </div>
    </div>
  );
}
