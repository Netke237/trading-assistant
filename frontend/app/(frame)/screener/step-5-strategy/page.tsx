'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Title, Text } from '@/components/primitives';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { useShallow } from 'zustand/shallow';
import { api, getLastDataRefresh } from '@/lib/api';
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

type RegimeFit = 'PASS' | 'CAUTION' | 'REJECT';

// Maps each strategy to how well it fits each market regime.
const REGIME_FIT: Record<string, Partial<Record<string, RegimeFit>>> = {
  pullback_ema:       { PASS: 'PASS',    CAUTION: 'CAUTION', REJECT: 'REJECT'  },
  breakout_base:      { PASS: 'PASS',    CAUTION: 'REJECT',  REJECT: 'REJECT'  },
  ma_crossover:       { PASS: 'CAUTION', CAUTION: 'CAUTION', REJECT: 'REJECT'  },
  mean_reversion_rsi: { PASS: 'CAUTION', CAUTION: 'PASS',    REJECT: 'CAUTION' },
};

const REGIME_BADGE: Record<RegimeFit, { label: string; cls: string }> = {
  PASS:    { label: 'Recommended', cls: 'regimeBadgePass'    },
  CAUTION: { label: 'Neutral',     cls: 'regimeBadgeCaution' },
  REJECT:  { label: 'Avoid',       cls: 'regimeBadgeReject'  },
};

export default function Step5StrategyPage() {
  const router = useRouter();
  const context = useScanStore((s) => s.context);
  const scanResult = useScanStore((s) => s.scanResult);
  const activeStrategy = useScanStore((s) => s.activeStrategy);
  const setActiveStrategy = useScanStore((s) => s.setActiveStrategy);
  const setStockScanResult = useScanStore((s) => s.setStockScanResult);
  const combinedRegime = useScanStore((s) => s.combinedRegime);
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
    eventFilter:          s.eventFilter,
    stockShortlistMax:    s.stockShortlistMax,
  })));
  const scanOverrides = useScanStore((s) => s.scanOverrides);
  const requireReversal = (scanOverrides.pullback_require_reversal as boolean | undefined) ?? false;
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
    pullback_ema:       `Dip to ${params.pullbackEmaPeriod}-${params.pullbackMaType} in uptrend${requireReversal ? ' + reversal candle' : ''}`,
    ma_crossover:       `${params.maCrossoverFast}-SMA crosses above ${params.maCrossoverSlow}-SMA`,
    mean_reversion_rsi: `RSI < ${params.rsiOversold} while above ${params.rsiTrendSma}-SMA`,
    breakout_base:      `Break above N-day high after narrow range + volume spike (${params.breakoutVolumeMult}×)`,
  };

  const [loadingStrategy, setLoadingStrategy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshTs, setLastRefreshTs] = useState<string | null>(null);
  const [prefetchStatus, setPrefetchStatus] = useState<
    'idle' | 'running' | 'completed' | 'error' | null
  >(null);
  const [prefetchProgress, setPrefetchProgress] = useState<{ done: number; total: number } | null>(null);

  useEffect(() => {
    getLastDataRefresh()
      .then((r) => setLastRefreshTs(r.last_refresh))
      .catch(() => {});
  }, []);

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
        pullback_tolerance_pct:    params.pullbackTolerancePct,
        pullback_ema_period:       params.pullbackEmaPeriod,
        pullback_trend_ema:        params.pullbackTrendEma,
        pullback_ma_type:          params.pullbackMaType,
        pullback_require_reversal: requireReversal,
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
        shortlist_max_candidates: params.stockShortlistMax,
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

          {/* ── Pullback to EMA ── */}
          <div className={styles.paramSection}>
            <Text size={11} weight={500} tone="secondary">Pullback to EMA</Text>
            <Text size={10} tone="dim">Controls the &quot;Pullback to EMA&quot; strategy — how far a stock can be below the moving average and still qualify, and how the uptrend is confirmed.</Text>
          </div>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">Pullback tolerance</Text>
            <Text size={10} tone="dim">Max % below the EMA to still count as a pullback. ↑ Higher → deeper pullbacks qualify (more results) · ↓ Lower → only tight pullbacks pass (fewer)</Text>
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
            <Text size={10} tone="dim">The EMA the stock must pull back to. ↑ Higher → slower EMA used (e.g. 50), longer trend needed (fewer) · ↓ Lower → faster EMA, more setups (more)</Text>
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
            <Text size={10} tone="dim">Type of moving average. EMA reacts faster to recent price; SMA is smoother and less reactive.</Text>
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
            <Text size={10} tone="dim">Longer EMA that defines whether the stock is in an uptrend at all. ↑ Higher → more established trend required (fewer) · ↓ Lower → shorter uptrends qualify (more)</Text>
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

          {/* ── MA Crossover ── */}
          <div className={styles.paramSection}>
            <Text size={11} weight={500} tone="secondary">MA Crossover</Text>
            <Text size={10} tone="dim">Controls the &quot;MA Crossover&quot; strategy — defines the two moving averages and how recently the crossover must have occurred.</Text>
          </div>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">MA crossover fast</Text>
            <Text size={10} tone="dim">Short MA period. ↑ Higher → fewer, more deliberate crossover signals · ↓ Lower → more frequent but noisier crossovers</Text>
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
            <Text size={10} tone="dim">Long MA period. ↑ Higher → crossover requires a bigger trend reversal (fewer) · ↓ Lower → shorter moves trigger a signal (more)</Text>
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
            <Text size={10} tone="dim">How many bars back a crossover can still be counted as fresh. ↑ Higher → older crossovers qualify (more results) · ↓ Lower → only very recent crossovers (fewer)</Text>
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

          {/* ── Mean Reversion RSI ── */}
          <div className={styles.paramSection}>
            <Text size={11} weight={500} tone="secondary">Mean Reversion RSI</Text>
            <Text size={10} tone="dim">Controls the &quot;Mean Reversion RSI&quot; strategy — defines how oversold a stock must be and what uptrend baseline it must still sit above.</Text>
          </div>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">RSI period</Text>
            <Text size={10} tone="dim">Bars used to calculate RSI. ↑ Higher → smoother, slower RSI reading · ↓ Lower → more sensitive, triggers faster</Text>
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
            <Text size={10} tone="dim">RSI must be below this to qualify as oversold. ↑ Higher → easier to trigger (less oversold needed), more results · ↓ Lower → deep oversold required, fewer results</Text>
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
            <Text size={10} tone="dim">SMA the stock must be trading above to confirm it&apos;s still in an uptrend. ↑ Higher → only stocks in longer established uptrends qualify (fewer) · ↓ Lower → shorter uptrends allowed (more)</Text>
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

          {/* ── Breakout ── */}
          <div className={styles.paramSection}>
            <Text size={11} weight={500} tone="secondary">Breakout from Tight Base</Text>
            <Text size={10} tone="dim">Controls the &quot;Breakout&quot; strategy — how much volume surge is required to confirm a genuine breakout above the base high.</Text>
          </div>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">Breakout vol multiplier</Text>
            <Text size={10} tone="dim">Required volume as a multiple of average on the breakout day. ↑ Higher → only high-conviction volume spikes pass (fewer, stronger signals) · ↓ Lower → lower volume breakouts qualify (more)</Text>
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

          {/* ── Backtest quality gate ── */}
          <div className={styles.paramSection}>
            <Text size={11} weight={500} tone="secondary">Backtest quality gate</Text>
            <Text size={10} tone="dim">Minimum historical performance a stock&apos;s setup must have shown before it qualifies. Applied to all strategies — stocks that fail are excluded from results.</Text>
          </div>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">Min backtest trades</Text>
            <Text size={10} tone="dim">Minimum number of historical signals required for the backtest to be statistically meaningful. ↑ Higher → more data required (fewer qualify) · ↓ Lower → sparse history accepted (more)</Text>
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
            <Text size={10} tone="dim">Minimum % of historical trades that were winners. ↑ Higher → only well-performing past setups qualify (fewer, more accurate) · ↓ Lower → looser past performance accepted (more)</Text>
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

          {/* ── Shortlist cap ── */}
          <div className={styles.paramSection}>
            <Text size={11} weight={500} tone="secondary">Shortlist</Text>
            <Text size={10} tone="dim">Maximum number of stock candidates returned after all gates. Same cap applies to all strategies.</Text>
          </div>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">Max candidates</Text>
            <Text size={10} tone="dim">↑ Higher → more stocks pass to Position Card · ↓ Lower → only top-ranked setups shown</Text>
            <div className={styles.paramInput}>
              <input
                type="number"
                value={params.stockShortlistMax}
                min={1} max={50} step={1}
                onChange={(e) =>
                  setParams((p) => ({ ...p, stockShortlistMax: Math.max(1, Number(e.target.value)) }))
                }
              />
            </div>
          </label>

          {/* ── Event exposure ── */}
          <div className={styles.paramSection}>
            <Text size={11} weight={500} tone="secondary">Event exposure</Text>
            <Text size={10} tone="dim">Controls whether stocks with upcoming catalysts (earnings, FOMC, dividends) are included, excluded, or exclusively targeted.</Text>
          </div>

          <label className={styles.paramLabel}>
            <Text size={11} tone="dim">Event exposure</Text>
            <Text size={10} tone="dim">Include = all stocks regardless of events · Avoid = exclude stocks with near-term catalysts (safer, fewer) · Events only = only stocks with upcoming events</Text>
            <div className={styles.maToggle}>
              {(['include', 'avoid', 'only_pre_event'] as const).map((v) => (
                <button
                  key={v}
                  type="button"
                  className={`${styles.maToggleBtn} ${params.eventFilter === v ? styles.maToggleBtnActive : ''}`}
                  onClick={() => setParams((p) => ({ ...p, eventFilter: v }))}
                >
                  <Text size={11} weight={500}>
                    {v === 'include' ? 'Include' : v === 'avoid' ? 'Avoid' : 'Events only'}
                  </Text>
                </button>
              ))}
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
              {(() => {
                const fit = REGIME_FIT[s.key]?.[combinedRegime] as RegimeFit | undefined;
                if (!fit) return null;
                const badge = REGIME_BADGE[fit];
                return (
                  <span className={`${styles.regimeBadge} ${styles[badge.cls]}`}>
                    {badge.label}
                  </span>
                );
              })()}
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
    </div>
  );
}
