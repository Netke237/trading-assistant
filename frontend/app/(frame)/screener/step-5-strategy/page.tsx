'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { Title, Text } from '@/components/primitives';
import { useScanStore, toLocalWallClock } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { useRiskStore } from '@/lib/riskStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { buildStockScanRequestBody } from '@/lib/resolveStockScanRequest';
import { stockScanFailureReason, STOCK_SCAN_SETTINGS_INVALID } from '@/lib/stockScan';
import { useShallow } from 'zustand/shallow';
import { api, getLastDataRefresh } from '@/lib/api';
import styles from './page.module.css';
import { StrategyParamsPanel } from '@/components/organisms/StrategyParamsPanel';
import { MeanReversionConfirmPanel } from '@/components/molecules/MeanReversionConfirmPanel';
import { Tooltip } from '@/components/atoms/Tooltip';
import { regimeFitTooltip } from '@/lib/statusTooltips';

const STRATEGIES = [
  {
    key: 'pullback_ema',
    label: 'Pullback to 20-EMA',
    when: 'Steady uptrends',
    entry: 'Dip to 20-EMA + reversal candle in uptrend',
    stop: 'Below the pullback MA by 1.5 ATR',
    exit: 'Prior swing high, then 2R / 3R extensions',
  },
  {
    key: 'breakout_base',
    label: 'Breakout from tight base',
    when: 'Momentum stocks',
    entry: 'Break above N-day high after narrow range + volume spike',
    stop: 'Just under the breakout level (base high)',
    exit: 'Measured move — base height projected off the breakout',
  },
  {
    key: 'ma_crossover',
    label: 'MA Crossover 20/50',
    when: 'Simple trend entry',
    entry: '20-SMA crosses above 50-SMA',
    stop: 'Below 50-SMA',
    exit: '3 / 4.5 / 6 ATR ladder (cross-back level shown)',
  },
  {
    key: 'mean_reversion_rsi',
    label: 'Mean Reversion RSI',
    when: 'Oversold in uptrend',
    entry: 'RSI < 30 while above 200-SMA',
    stop: 'Below recent swing low',
    exit: 'Return to the 20-SMA, then 2.5 / 3.75 ATR',
  },
  {
    key: 'mean_reversion_bb',
    label: 'Mean Reversion BB',
    when: 'Choppy / range-bound',
    entry: 'Price touches lower Bollinger Band + reversal signal',
    stop: 'Below lower band',
    exit: 'Return to mid-band / upper band',
  },
  {
    key: 'mean_reversion_vwap',
    label: 'Mean Reversion VWAP',
    when: 'Intraday · 15m session',
    entry: 'Price deviates >1.5% below VWAP + reversal bar toward VWAP (15m bars)',
    stop: '0.5 ATR below entry',
    exit: 'VWAP, then 0.5 ATR past it',
  },
  {
    key: 'mean_reversion_multi',
    label: 'Mean Reversion Multi-Signal',
    when: 'High-conviction oversold entries',
    entry: 'RSI + BB + VWAP daily all confirm simultaneously',
    stop: "Widest of the fired variants' stops",
    exit: "Tightest of the fired variants' targets",
  },
] as const;

type RegimeFit = 'PASS' | 'CAUTION' | 'REJECT';

// Maps each strategy to how well it fits each market regime.
const REGIME_FIT: Record<string, Partial<Record<string, RegimeFit>>> = {
  pullback_ema:           { PASS: 'PASS',    CAUTION: 'CAUTION', REJECT: 'REJECT'  },
  breakout_base:          { PASS: 'PASS',    CAUTION: 'REJECT',  REJECT: 'REJECT'  },
  ma_crossover:           { PASS: 'CAUTION', CAUTION: 'CAUTION', REJECT: 'REJECT'  },
  mean_reversion_rsi:     { PASS: 'CAUTION', CAUTION: 'PASS',    REJECT: 'CAUTION' },
  mean_reversion_bb:      { PASS: 'CAUTION', CAUTION: 'PASS',    REJECT: 'CAUTION' },
  mean_reversion_vwap:    { PASS: 'CAUTION', CAUTION: 'PASS',    REJECT: 'CAUTION' },
  mean_reversion_multi:   { PASS: 'CAUTION', CAUTION: 'PASS',    REJECT: 'CAUTION' },
};

const REGIME_BADGE: Record<RegimeFit, { label: string; cls: string }> = {
  PASS:    { label: 'Recommended', cls: 'regimeBadgePass'    },
  CAUTION: { label: 'Neutral',     cls: 'regimeBadgeCaution' },
  REJECT:  { label: 'Avoid',       cls: 'regimeBadgeReject'  },
};

export default function Step5StrategyPage() {
  const router = useRouter();
  const context = useScanStore((s) => s.context);
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
    requireChoppyRegime:  s.requireChoppyRegime ?? false,
    btMinTrades:          s.btMinTrades,
    btMinWinRate:         s.btMinWinRate,
    eventFilter:          s.eventFilter,
    stockShortlistMax:    s.stockShortlistMax,
  })));
  const scanOverrides = useScanStore((s) => s.scanOverrides);
  const requireReversal = (scanOverrides.pullback_require_reversal as boolean | undefined) ?? false;

  const meanReversionVariants   = useScanParamsStore((s) => s.meanReversionVariants);
  const meanReversionMinConfirm = useScanParamsStore((s) => s.meanReversionMinConfirm);
  const vwapLookback            = useScanParamsStore((s) => s.vwapLookback);
  const vwapDeviationPct        = useScanParamsStore((s) => s.vwapDeviationPct);
  const setMeanReversionVariants   = useScanParamsStore((s) => s.setMeanReversionVariants);
  const setMeanReversionMinConfirm = useScanParamsStore((s) => s.setMeanReversionMinConfirm);
  const setVwapLookback            = useScanParamsStore((s) => s.setVwapLookback);
  const setVwapDeviationPct        = useScanParamsStore((s) => s.setVwapDeviationPct);

  const [params, setParams] = useState(() => ({ ...savedParams }));

  function resetParams() { setParams({ ...savedParams }); }

  // If this page mounts before useScanParamsStore finishes rehydrating from
  // localStorage (skipHydration: true — see StoreHydration), the useState
  // initializer above captures the store's hardcoded module defaults instead
  // of the persisted savedParams. Sync local state once hydration actually
  // finishes, so a scan run shortly after a fresh load doesn't silently use
  // stale defaults instead of the user's saved strategy params (same class of
  // bug as a prior fix, Critical finding #8, 2026-07-15 audit).
  useEffect(() => {
    const syncFromHydratedStore = () => {
      const s = useScanParamsStore.getState();
      setParams({
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
        requireChoppyRegime:  s.requireChoppyRegime ?? false,
        btMinTrades:          s.btMinTrades,
        btMinWinRate:         s.btMinWinRate,
        eventFilter:          s.eventFilter,
        stockShortlistMax:    s.stockShortlistMax,
      });
    };
    if (useScanParamsStore.persist.hasHydrated()) syncFromHydratedStore();
    const unsub = useScanParamsStore.persist.onFinishHydration(syncFromHydratedStore);
    return unsub;
  }, []);

  // Dynamic card titles reflecting the current parameter values
  const strategyLabel: Record<string, string> = {
    pullback_ema:          `Pullback to ${params.pullbackEmaPeriod}-${params.pullbackMaType}`,
    ma_crossover:          `MA Crossover ${params.maCrossoverFast}/${params.maCrossoverSlow}`,
    mean_reversion_rsi:    `Mean Reversion RSI / ${params.rsiTrendSma}-SMA`,
    mean_reversion_vwap:   'Mean Reversion VWAP (15m)',
    breakout_base:         'Breakout from tight base',
  };

  const entryLabel: Record<string, string> = {
    pullback_ema:          `Dip to ${params.pullbackEmaPeriod}-${params.pullbackMaType} in uptrend${requireReversal ? ' + reversal candle' : ''}`,
    ma_crossover:          `${params.maCrossoverFast}-SMA crosses above ${params.maCrossoverSlow}-SMA`,
    mean_reversion_rsi:    `RSI < ${params.rsiOversold} while above ${params.rsiTrendSma}-SMA`,
    mean_reversion_bb:     'Price touches lower Bollinger Band + reversal signal',
    mean_reversion_vwap:   'Price deviates >1.5% below VWAP + reversal bar toward VWAP (15m bars)',
    breakout_base:         `Break above N-day high after narrow range + volume spike (${params.breakoutVolumeMult}×)`,
  };

  const portfolioValue = useRiskStore((s) => s.limits.portfolioValue);
  const [loadingStrategy, setLoadingStrategy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
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

  async function runScan(stratKey: string) {
    setActiveStrategy(stratKey);
    setStockScanResult(null);
    setLoadingStrategy(stratKey);
    setError(null);
    // A5d: same boundary as runStockScan — a throw before the post is our own
    // request building (most likely a malformed saved setting), not a failed scan.
    let reachedRequest = false;
    try {
      // A5: hoisted so the exact body travels with its result (Analysis replays it).
      // A5b: built by the same builder runStockScan (Steps 3/4) uses, so a
      // Step-5 scan carries every Step-3 setting — score overrides, confidence
      // gate, ATR pair, headwind and fundamentals thresholds. Stores are read
      // at click time, as runStockScan does.
      const scan = useScanStore.getState();
      const ctx = scan.context;
      const requestBody = buildStockScanRequestBody({
        universe: ctx?.universe ? [ctx.universe] : ['SP500'],
        direction: ctx?.direction ?? 'Bullish',
        horizon: (ctx?.horizon ?? 'Swing (5–15d)').split(' ')[0],
        strategy: stratKey,
        // Saved params (incl. the mean-reversion fields, which this page edits
        // straight into the store) overlaid with the panel's unsaved local
        // edits — the same `{ ...saved, ...overrides }` merge runStockScan does.
        params: { ...useScanParamsStore.getState(), ...params },
        requireReversal:
          (scan.scanOverrides.pullback_require_reversal as boolean | undefined) ?? false,
        scanOverrides: scan.scanOverrides,
        confidenceGate: useSettingsStore.getState().confidenceGate,
        // Deliberately the user's real account value, not runStockScan's
        // hardcoded 50_000 (a separate, pre-existing concern there).
        accountSize: portfolioValue,
        riskPct: 0.01,
      });
      reachedRequest = true;
      const result = await api.postStockScan(requestBody);
      setStockScanResult(result, requestBody);
      router.push('/screener/step-6-backtest');
    } catch (e) {
      // The raw error goes to the console so the detail survives for debugging.
      if (!reachedRequest) console.error('Step 5: building the stock-scan request failed', e);
      setError(reachedRequest ? stockScanFailureReason(e) : STOCK_SCAN_SETTINGS_INVALID);
    } finally {
      setLoadingStrategy(null);
      // Refresh last-run status/strategy from the backend so TopBar/Settings
      // reflect this scan immediately (success or failure), not just after
      // the next full page load.
      try {
        const s = await api.getLastStockScanStatus();
        useScanStore.getState().setLastStockScanMeta(
          s.status, s.updated_at ? toLocalWallClock(s.updated_at) : null, s.strategy ?? null,
        );
      } catch {
        // Backend unreachable — leave stale, StoreHydration will catch up on next load.
      }
    }
  }

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
    <div className={styles.main}>
      <div className={styles.header}>
        <Text size={11} tone="dim" weight={500}>STEP 5 OF 7</Text>
        <Title as="h1" size={24}>Strategy</Title>
        <Text size={13} tone="secondary">Pick an entry/exit rule — your historical backtest runs automatically.</Text>
        <Text size={12} tone="secondary">
          Scanning full {context?.universe ?? 'SP500'} universe for stock setups
        </Text>
      </div>

      <StrategyParamsPanel
        params={params}
        setParams={setParams}
        onReset={resetParams}
      />

      <MeanReversionConfirmPanel
        variants={meanReversionVariants}
        minConfirmations={meanReversionMinConfirm}
        vwapLookback={vwapLookback}
        vwapDeviationPct={vwapDeviationPct}
        onChange={(update) => {
          if (update.variants !== undefined)         setMeanReversionVariants(update.variants);
          if (update.minConfirmations !== undefined) setMeanReversionMinConfirm(update.minConfirmations);
          if (update.vwapLookback !== undefined)     setVwapLookback(update.vwapLookback);
          if (update.vwapDeviationPct !== undefined) setVwapDeviationPct(update.vwapDeviationPct);
        }}
      />

      {error && <Text size={12} tone="reject">{error}</Text>}

      <div className={styles.grid}>
        {STRATEGIES.map((s) => (
          <button
            key={s.key}
            className={`${styles.card} ${activeStrategy === s.key ? styles.cardActive : ''}`}
            onClick={() => runScan(s.key)}
            disabled={loadingStrategy !== null || (s.key === 'mean_reversion_multi' && meanReversionVariants.length === 0)}
          >
            <div className={styles.cardHeader}>
              <Text size={14} weight={600}>{strategyLabel[s.key] ?? s.label}</Text>
              <Text size={11} tone="secondary">{s.when}</Text>
              {(() => {
                const fit = REGIME_FIT[s.key]?.[combinedRegime] as RegimeFit | undefined;
                if (!fit) return null;
                const badge = REGIME_BADGE[fit];
                return (
                  <Tooltip text={regimeFitTooltip(strategyLabel[s.key] ?? s.label, fit, combinedRegime)}>
                    <span className={`${styles.regimeBadge} ${styles[badge.cls]}`}>
                      {badge.label}
                    </span>
                  </Tooltip>
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
