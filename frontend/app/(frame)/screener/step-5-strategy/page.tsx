'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Title, Text } from '@/components/primitives';
import { useScanStore } from '@/lib/scanStore';
import { api } from '@/lib/api';
import styles from './page.module.css';

const STRATEGIES = [
  {
    key: 'pullback_ema',
    label: 'Pullback to 20-EMA',
    when: 'Steady uptrends',
    entry: 'Dip to 20-EMA + reversal candle in uptrend',
    stop: 'Below recent swing low',
    exit: 'Prior high / trailing stop under higher lows',
  },
  {
    key: 'breakout_base',
    label: 'Breakout from tight base',
    when: 'Momentum stocks',
    entry: 'Break above N-day high after narrow range + volume spike',
    stop: 'Below the base low',
    exit: 'Measured move / trailing stop',
  },
  {
    key: 'ma_crossover',
    label: 'MA Crossover 20/50',
    when: 'Simple trend entry',
    entry: '20-SMA crosses above 50-SMA',
    stop: 'Below 50-SMA',
    exit: 'Cross back down',
  },
  {
    key: 'mean_reversion_rsi',
    label: 'Mean Reversion RSI',
    when: 'Oversold in uptrend',
    entry: 'RSI < 30 while above 200-SMA',
    stop: 'Below recent swing low',
    exit: 'RSI returns to mid / take-profit target',
  },
] as const;

export default function Step5StrategyPage() {
  const router = useRouter();
  const context = useScanStore((s) => s.context);
  const activeStrategy = useScanStore((s) => s.activeStrategy);
  const setActiveStrategy = useScanStore((s) => s.setActiveStrategy);
  const setStockScanResult = useScanStore((s) => s.setStockScanResult);
  const [loadingStrategy, setLoadingStrategy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function runScan(stratKey: string) {
    setActiveStrategy(stratKey);
    setStockScanResult(null);   // clear any prior result so Step 6 can't show stale data
    setLoadingStrategy(stratKey);
    setError(null);
    try {
      const result = await api.postStockScan({
        universe: context?.universe ? [context.universe] : ['SP500'],
        direction: context?.direction ?? 'Bullish',
        horizon: (context?.horizon ?? 'Swing (5–15d)').split(' ')[0],
        strategy: stratKey,
        account_size: 50_000,
        risk_pct: 0.01,
      });
      setStockScanResult(result);
      router.push('/screener/step-6-backtest');
    } catch (e) {
      setError(String(e));
    } finally {
      setLoadingStrategy(null);
    }
  }

  return (
    <div className={styles.main}>
      <div className={styles.header}>
        <Text size={11} tone="dim" weight={500}>STEP 5 OF 7</Text>
        <Title as="h1" size={24}>Strategy</Title>
        <Text size={13} tone="secondary">Pick an entry/exit rule — your historical backtest runs automatically.</Text>
      </div>

      {error && <Text size={12} tone="reject">{error}</Text>}

      <div className={styles.grid}>
        {STRATEGIES.map((s) => (
          <button
            key={s.key}
            className={`${styles.card} ${activeStrategy === s.key ? styles.cardActive : ''}`}
            onClick={() => runScan(s.key)}
            disabled={loadingStrategy !== null}
          >
            <div className={styles.cardHeader}>
              <Text size={14} weight={600}>{s.label}</Text>
              <Text size={11} tone="secondary">{s.when}</Text>
            </div>
            <div className={styles.cardBody}>
              <Text size={11} tone="dim">Entry: {s.entry}</Text>
              <Text size={11} tone="dim">Stop: {s.stop}</Text>
              <Text size={11} tone="dim">Exit: {s.exit}</Text>
            </div>
            {loadingStrategy === s.key && (
              <Text size={11} tone="secondary">Running backtest scan…</Text>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
