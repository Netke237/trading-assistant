'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Title, Text } from '@/components/primitives';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { useShallow } from 'zustand/shallow';
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
  const scanResult = useScanStore((s) => s.scanResult);
  const activeStrategy = useScanStore((s) => s.activeStrategy);
  const setActiveStrategy = useScanStore((s) => s.setActiveStrategy);
  const setStockScanResult = useScanStore((s) => s.setStockScanResult);
  const savedParams = useScanParamsStore(useShallow((s) => ({
    pullbackTolerancePct: s.pullbackTolerancePct,
    pullbackEmaPeriod:    s.pullbackEmaPeriod,
    pullbackTrendEma:     s.pullbackTrendEma,
    pullbackMaType:       s.pullbackMaType,
    maCrossoverFast:      s.maCrossoverFast,
    maCrossoverSlow:      s.maCrossoverSlow,
    maCrossoverLookback:  s.maCrossoverLookback,
    breakoutVolumeMult:   s.breakoutVolumeMult,
    rsiPeriod:            s.rsiPeriod,
    rsiOversold:          s.rsiOversold,
    rsiTrendSma:          s.rsiTrendSma,
    btMinTrades:          s.btMinTrades,
    btMinWinRate:         s.btMinWinRate,
  })));
  const [params, setParams] = useState(() => ({ ...savedParams }));

  function resetParams() { setParams({ ...savedParams }); }

  // Dynamic card titles reflecting the current parameter values
  const strategyLabel: Record<string, string> = {
    pullback_ema:        `Pullback to ${params.pullbackEmaPeriod}-${params.pullbackMaType}`,
    ma_crossover:        `MA Crossover ${params.maCrossoverFast}/${params.maCrossoverSlow}`,
    mean_reversion_rsi:  `Mean Reversion RSI / ${params.rsiTrendSma}-SMA`,
    breakout_base:       'Breakout from tight base',
  };

  const entryLabel: Record<string, string> = {
    pullback_ema:       `Dip to ${params.pullbackEmaPeriod}-${params.pullbackMaType} + reversal candle in uptrend`,
    ma_crossover:       `${params.maCrossoverFast}-SMA crosses above ${params.maCrossoverSlow}-SMA`,
    mean_reversion_rsi: `RSI < ${params.rsiOversold} while above ${params.rsiTrendSma}-SMA`,
    breakout_base:      `Break above N-day high after narrow range + volume spike (${params.breakoutVolumeMult}×)`,
  };

  const [loadingStrategy, setLoadingStrategy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [prefetchStatus, setPrefetchStatus] = useState<
    'idle' | 'running' | 'completed' | 'error' | null
  >(null);
  const [prefetchProgress, setPrefetchProgress] = useState<{ done: number; total: number } | null>(null);

  async function runScan(stratKey: string) {
    setActiveStrategy(stratKey);
    setStockScanResult(null);
    setLoadingStrategy(stratKey);
    setError(null);
    try {
      const candidateSymbols = scanResult?.candidates.map((c) => c.symbol);
      const result = await api.postStockScan({
        universe: context?.universe ? [context.universe] : ['SP500'],
        symbols: candidateSymbols?.length ? candidateSymbols : undefined,
        direction: context?.direction ?? 'Bullish',
        horizon: (context?.horizon ?? 'Swing (5–15d)').split(' ')[0],
        strategy: stratKey,
        pullback_tolerance_pct: params.pullbackTolerancePct,
        pullback_ema_period:    params.pullbackEmaPeriod,
        pullback_trend_ema:     params.pullbackTrendEma,
        pullback_ma_type:       params.pullbackMaType,
        ma_crossover_fast:      params.maCrossoverFast,
        ma_crossover_slow:      params.maCrossoverSlow,
        ma_crossover_lookback:  params.maCrossoverLookback,
        breakout_volume_mult:   params.breakoutVolumeMult,
        rsi_period:             params.rsiPeriod,
        rsi_oversold:           params.rsiOversold,
        rsi_trend_sma:          params.rsiTrendSma,
        bt_min_trades:          params.btMinTrades,
        bt_min_win_rate:        params.btMinWinRate,
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

  async function startPrefetch() {
    try {
      const universe = context?.universe ? [context.universe] : ['SP500'];
      await api.startHistoryPrefetch({ universe });
      setPrefetchStatus('running');
      const poll = setInterval(async () => {
        try {
          const s = await api.getHistoryPrefetchStatus();
          setPrefetchProgress({ done: s.done, total: s.total });
          if (s.status === 'completed' || s.status === 'error') {
            setPrefetchStatus(s.status);
            clearInterval(poll);
          }
        } catch {
          clearInterval(poll);
        }
      }, 5_000);
    } catch {
      setPrefetchStatus('error');
    }
  }

  return (
    <div className={styles.main}>
      <div className={styles.header}>
        <Text size={11} tone="dim" weight={500}>STEP 5 OF 7</Text>
        <Title as="h1" size={24}>Strategy</Title>
        <Text size={13} tone="secondary">Pick an entry/exit rule — your historical backtest runs automatically.</Text>
        {scanResult?.candidates.length ? (
          <Text size={12} tone="secondary">
            Scanning {scanResult.candidates.length} candidates from Stock Ranking
          </Text>
        ) : (
          <Text size={12} tone="caution">
            No Stock Ranking results — scanning full universe
          </Text>
        )}
      </div>

      <details className={styles.paramsPanel}>
        <summary className={styles.paramsSummary}>
          <Text size={12} tone="secondary">Scan parameters</Text>
        </summary>

        <div className={styles.paramsGrid}>
          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">Pullback tolerance</Text>
            <div className={styles.paramInput}>
              <input
                type="number"
                value={Math.round(params.pullbackTolerancePct * 100 * 10) / 10}
                min={0.5} max={15} step={0.5}
                onChange={(e) =>
                  setParams((p) => ({ ...p, pullbackTolerancePct: Number(e.target.value) / 100 }))
                }
              />
              <Text size={11} tone="dim">%</Text>
            </div>
          </label>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">Pullback EMA period</Text>
            <div className={styles.paramInput}>
              <input
                type="number"
                value={params.pullbackEmaPeriod}
                min={5} max={200} step={5}
                onChange={(e) =>
                  setParams((p) => ({ ...p, pullbackEmaPeriod: Number(e.target.value) }))
                }
              />
            </div>
          </label>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">Pullback MA type</Text>
            <div className={styles.maToggle}>
              {(['EMA', 'SMA'] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  className={`${styles.maToggleBtn} ${params.pullbackMaType === t ? styles.maToggleBtnActive : ''}`}
                  onClick={() => setParams((p) => ({ ...p, pullbackMaType: t }))}
                >
                  <Text size={11} weight={500}>{t}</Text>
                </button>
              ))}
            </div>
          </label>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">Trend EMA period</Text>
            <div className={styles.paramInput}>
              <input
                type="number"
                value={params.pullbackTrendEma}
                min={10} max={500} step={10}
                onChange={(e) =>
                  setParams((p) => ({ ...p, pullbackTrendEma: Number(e.target.value) }))
                }
              />
            </div>
          </label>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">MA crossover fast</Text>
            <div className={styles.paramInput}>
              <input
                type="number"
                value={params.maCrossoverFast}
                min={2} max={100} step={1}
                onChange={(e) =>
                  setParams((p) => ({ ...p, maCrossoverFast: Number(e.target.value) }))
                }
              />
            </div>
          </label>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">MA crossover slow</Text>
            <div className={styles.paramInput}>
              <input
                type="number"
                value={params.maCrossoverSlow}
                min={5} max={300} step={5}
                onChange={(e) =>
                  setParams((p) => ({ ...p, maCrossoverSlow: Number(e.target.value) }))
                }
              />
            </div>
          </label>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">MA crossover lookback</Text>
            <div className={styles.paramInput}>
              <input
                type="number"
                value={params.maCrossoverLookback}
                min={1} max={30} step={1}
                onChange={(e) =>
                  setParams((p) => ({ ...p, maCrossoverLookback: Number(e.target.value) }))
                }
              />
              <Text size={11} tone="dim">bars</Text>
            </div>
          </label>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">RSI period</Text>
            <div className={styles.paramInput}>
              <input
                type="number"
                value={params.rsiPeriod}
                min={2} max={50} step={1}
                onChange={(e) =>
                  setParams((p) => ({ ...p, rsiPeriod: Number(e.target.value) }))
                }
              />
            </div>
          </label>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">RSI oversold level</Text>
            <div className={styles.paramInput}>
              <input
                type="number"
                value={params.rsiOversold}
                min={10} max={50} step={1}
                onChange={(e) =>
                  setParams((p) => ({ ...p, rsiOversold: Number(e.target.value) }))
                }
              />
            </div>
          </label>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">RSI trend SMA</Text>
            <div className={styles.paramInput}>
              <input
                type="number"
                value={params.rsiTrendSma}
                min={20} max={500} step={10}
                onChange={(e) =>
                  setParams((p) => ({ ...p, rsiTrendSma: Number(e.target.value) }))
                }
              />
            </div>
          </label>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">Breakout vol multiplier</Text>
            <div className={styles.paramInput}>
              <input
                type="number"
                value={params.breakoutVolumeMult}
                min={1.0} max={3.0} step={0.05}
                onChange={(e) =>
                  setParams((p) => ({ ...p, breakoutVolumeMult: Number(e.target.value) }))
                }
              />
              <Text size={11} tone="dim">×</Text>
            </div>
          </label>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">Min backtest trades</Text>
            <div className={styles.paramInput}>
              <input
                type="number"
                value={params.btMinTrades}
                min={1} max={50} step={1}
                onChange={(e) =>
                  setParams((p) => ({ ...p, btMinTrades: Number(e.target.value) }))
                }
              />
              <Text size={11} tone="dim">trades</Text>
            </div>
          </label>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">Min win rate</Text>
            <div className={styles.paramInput}>
              <input
                type="number"
                value={Math.round(params.btMinWinRate * 100)}
                min={10} max={80} step={5}
                onChange={(e) =>
                  setParams((p) => ({ ...p, btMinWinRate: Number(e.target.value) / 100 }))
                }
              />
              <Text size={11} tone="dim">%</Text>
            </div>
          </label>

          <button type="button" className={styles.resetBtn} onClick={resetParams}>
            Reset to saved
          </button>
        </div>
      </details>

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
              <Text size={14} weight={600}>{strategyLabel[s.key] ?? s.label}</Text>
              <Text size={11} tone="secondary">{s.when}</Text>
            </div>
            <div className={styles.cardBody}>
              <Text size={11} tone="dim">Entry: {entryLabel[s.key] ?? s.entry}</Text>
              <Text size={11} tone="dim">Stop: {s.stop}</Text>
              <Text size={11} tone="dim">Exit: {s.exit}</Text>
            </div>
            {loadingStrategy === s.key && (
              <Text size={11} tone="secondary">Running backtest scan…</Text>
            )}
          </button>
        ))}
      </div>

      <div className={styles.prefetchRow}>
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
        {prefetchStatus !== 'running' && (
          <button
            className={styles.prefetchBtn}
            onClick={startPrefetch}
          >
            {prefetchStatus === 'completed' ? 'Re-warm' : 'Pre-warm history'}
          </button>
        )}
      </div>
    </div>
  );
}
