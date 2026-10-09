'use client';

import { useState, useEffect, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Title, Text } from '@/components/primitives';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore, type ScanParams } from '@/lib/scanParamsStore';
import { useStrategyProfilesStore, profileView } from '@/lib/strategyProfilesStore';
import { tunedParamsHorizon } from '@/lib/horizonPresets';
import { useShallow } from 'zustand/shallow';
import { StrategyParamsPanel, type StrategyParams } from '@/components/organisms/StrategyParamsPanel';
import { MeanReversionConfirmPanel } from '@/components/molecules/MeanReversionConfirmPanel';
import { runStockScanWithContinuation, isStockManualScanCurrent, stockScanFailureReason } from '@/lib/stockScan';
import { Tooltip } from '@/components/atoms/Tooltip';
import { regimeFitTooltip } from '@/lib/statusTooltips';
import { DirectSendNotesPanel } from '@/components/organisms/DirectSendNotesPanel';
import { HistoryPrefetchRow } from './HistoryPrefetchRow';
import styles from './page.module.css';

function _startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}
function _labelWithDate(iso: string): string {
  const scan = new Date(iso);
  const now  = new Date();
  const diffDays = Math.round((_startOfDay(now) - _startOfDay(scan)) / 86_400_000);
  const timeStr = scan.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  const mon = scan.toLocaleString(undefined, { month: 'short' });
  const day = scan.getDate();
  if (diffDays === 1) return `Yesterday · ${timeStr}`;
  const sameYear = scan.getFullYear() === now.getFullYear();
  return sameYear ? `${mon} ${day} · ${timeStr}` : `${mon} ${day} ${scan.getFullYear()} · ${timeStr}`;
}

// `stop:` and `exit:` describe what strategy_engine.py actually computes — these
// strings are the user's only explanation of where their money comes off the
// table, so they are kept in sync with the signal functions deliberately, not
// written as marketing. Exit rung 1 is `signal.targets[0]` (== target_price, the
// only rung the backtest and TP_HIT observe); the rest are the ladder's
// extensions. See docs/superpowers/plans/2026-08-22-stock-exit-targets-plan.md.
const STRATEGIES_BULLISH = [
  { key: 'pullback_ema',          label: 'Pullback to 20-EMA',        when: 'Steady uptrends',        entry: 'Dip to 20-EMA + reversal candle in uptrend',              stop: 'Below the pullback MA by 1.5 ATR', exit: 'Prior swing high, then 2R / 3R extensions' },
  { key: 'breakout_base',         label: 'Breakout from tight base',  when: 'Momentum stocks',        entry: 'Break above N-day high after narrow range + volume spike', stop: 'Just under the breakout level (base high)', exit: 'Measured move — base height projected off the breakout' },
  { key: 'ma_crossover',          label: 'MA Crossover 20/50',        when: 'Simple trend entry',     entry: '20-SMA crosses above 50-SMA',                             stop: 'Below 50-SMA',           exit: '3 / 4.5 / 6 ATR ladder (cross-back level shown)' },
  { key: 'mean_reversion_rsi',    label: 'Mean Reversion RSI',        when: 'Oversold in uptrend',    entry: 'RSI < 30 while above 200-SMA',                            stop: 'Below recent swing low', exit: 'Return to the 20-SMA, then 2.5 / 3.75 ATR' },
  { key: 'mean_reversion_bb',     label: 'Mean Reversion BB',         when: 'Choppy / range-bound',   entry: 'Price touches lower Bollinger Band + reversal signal',     stop: 'Below lower band',       exit: 'Mid-band, then upper band' },
  { key: 'mean_reversion_vwap',   label: 'Mean Reversion VWAP',       when: 'Intraday · 15m session', entry: 'Price deviates >1.5% below VWAP + reversal bar',           stop: '0.5 ATR below entry',    exit: 'VWAP, then 0.5 ATR past it' },
  { key: 'mean_reversion_multi',  label: 'Mean Reversion Multi-Signal', when: 'High-conviction oversold entries', entry: 'RSI + BB + VWAP daily all confirm simultaneously', stop: "Widest of the fired variants' stops", exit: "Tightest of the fired variants' targets" },
];

const STRATEGIES_BEARISH = [
  { key: 'pullback_ema',          label: 'Pullback to 20-EMA',        when: 'Steady downtrends',      entry: 'Bounce to 20-EMA + reversal candle in downtrend',          stop: 'Above the pullback MA by 1.5 ATR', exit: 'Prior swing low, then 2R / 3R extensions' },
  { key: 'breakout_base',         label: 'Breakdown from tight base', when: 'Momentum shorts',        entry: 'Break below N-day low after narrow range + volume spike',  stop: 'Just above the breakdown level (base low)', exit: 'Measured move — base height projected off the breakdown' },
  { key: 'ma_crossover',          label: 'MA Crossover 20/50',        when: 'Simple trend entry',     entry: '20-SMA crosses below 50-SMA',                             stop: 'Above 50-SMA',           exit: '3 / 4.5 / 6 ATR ladder (cross-back level shown)' },
  { key: 'mean_reversion_rsi',    label: 'Mean Reversion RSI',        when: 'Overbought in downtrend', entry: 'RSI > 70 while below 200-SMA',                           stop: 'Above recent swing high', exit: 'Return to the 20-SMA, then 2.5 / 3.75 ATR' },
  { key: 'mean_reversion_bb',     label: 'Mean Reversion BB',         when: 'Choppy / range-bound',   entry: 'Price touches upper Bollinger Band + reversal signal',     stop: 'Above upper band',       exit: 'Mid-band, then lower band' },
  { key: 'mean_reversion_vwap',   label: 'Mean Reversion VWAP',       when: 'Intraday · 15m session', entry: 'Price deviates >1.5% above VWAP + reversal bar',           stop: '0.5 ATR above entry',    exit: 'VWAP, then 0.5 ATR past it' },
  { key: 'mean_reversion_multi',  label: 'Mean Reversion Multi-Signal', when: 'High-conviction overbought entries', entry: 'RSI + BB + VWAP daily all confirm simultaneously', stop: "Widest of the fired variants' stops", exit: "Tightest of the fired variants' targets" },
];

type RegimeFit = 'PASS' | 'CAUTION' | 'REJECT';
const REGIME_FIT: Record<string, Partial<Record<string, RegimeFit>>> = {
  pullback_ema:         { PASS: 'PASS',    CAUTION: 'CAUTION', REJECT: 'REJECT'  },
  breakout_base:        { PASS: 'PASS',    CAUTION: 'REJECT',  REJECT: 'REJECT'  },
  ma_crossover:         { PASS: 'CAUTION', CAUTION: 'CAUTION', REJECT: 'REJECT'  },
  mean_reversion_rsi:   { PASS: 'CAUTION', CAUTION: 'PASS',    REJECT: 'CAUTION' },
  mean_reversion_bb:    { PASS: 'CAUTION', CAUTION: 'PASS',    REJECT: 'CAUTION' },
  mean_reversion_vwap:  { PASS: 'CAUTION', CAUTION: 'PASS',    REJECT: 'CAUTION' },
  mean_reversion_multi: { PASS: 'CAUTION', CAUTION: 'PASS',    REJECT: 'CAUTION' },
};
const REGIME_BADGE: Record<RegimeFit, { label: string }> = {
  PASS:    { label: 'Recommended' },
  CAUTION: { label: 'Neutral'     },
  REJECT:  { label: 'Avoid'       },
};
const BADGE_CLASS: Record<RegimeFit, string> = {
  PASS:    styles.regimeBadgePass,
  CAUTION: styles.regimeBadgeCaution,
  REJECT:  styles.regimeBadgeReject,
};

/** The panel's slice of the saved scan params. One list, used by the
 *  selector, Reset and the post-hydration sync, so they cannot drift. */
function panelParamsOf(s: ScanParams): StrategyParams {
  return {
    pullbackTolerancePct: s.pullbackTolerancePct, pullbackEmaPeriod: s.pullbackEmaPeriod,
    pullbackTrendEma: s.pullbackTrendEma, pullbackMaType: s.pullbackMaType,
    maCrossoverFast: s.maCrossoverFast, maCrossoverSlow: s.maCrossoverSlow,
    maCrossoverLookback: s.maCrossoverLookback, breakoutVolumeMult: s.breakoutVolumeMult,
    rsiPeriod: s.rsiPeriod, rsiOversold: s.rsiOversold, rsiOverbought: s.rsiOverbought,
    rsiTrendSma: s.rsiTrendSma, requireChoppyRegime: s.requireChoppyRegime,
    btMinTrades: s.btMinTrades, btMinWinRate: s.btMinWinRate,
    eventFilter: s.eventFilter, stockShortlistMax: s.stockShortlistMax,
  };
}

export default function Step4StocksPage() {
  const context        = useScanStore((s) => s.context);
  const direction      = context?.direction ?? 'Bullish';
  const bearish        = direction === 'Bearish';
  const STRATEGIES     = bearish ? STRATEGIES_BEARISH : STRATEGIES_BULLISH;
  const activeStrategy    = useScanStore((s) => s.activeStrategy);
  const setActiveStrategy = useScanStore((s) => s.setActiveStrategy);
  const combinedRegime = useScanStore((s) => s.combinedRegime);
  const result         = useScanStore((s) => s.stockScanResult);
  const scanState      = useScanStore((s) => s.scanState);

  const savedParams = useScanParamsStore(useShallow(panelParamsOf));
  const scanOverrides   = useScanStore((s) => s.scanOverrides);
  const requireReversal = (scanOverrides.pullback_require_reversal as boolean | undefined) ?? false;

  const meanReversionVariants      = useScanParamsStore((s) => s.meanReversionVariants);
  const meanReversionMinConfirm    = useScanParamsStore((s) => s.meanReversionMinConfirm);
  const vwapLookback                = useScanParamsStore((s) => s.vwapLookback);
  const vwapDeviationPct            = useScanParamsStore((s) => s.vwapDeviationPct);
  const setMeanReversionVariants    = useScanParamsStore((s) => s.setMeanReversionVariants);
  const setMeanReversionMinConfirm  = useScanParamsStore((s) => s.setMeanReversionMinConfirm);
  const setVwapLookback             = useScanParamsStore((s) => s.setVwapLookback);
  const setVwapDeviationPct         = useScanParamsStore((s) => s.setVwapDeviationPct);

  // STOCKS-HORIZON-T1 H5: the panel shows the backend horizon profile for
  // direction x params horizon; the store and the panel hold overrides only.
  const profiles       = useStrategyProfilesStore((s) => s.profiles);
  const profilesFailed = useStrategyProfilesStore((s) => s.status === 'failed');
  useEffect(() => { void useStrategyProfilesStore.getState().fetch(); }, []);
  const paramsHorizon = context ? tunedParamsHorizon(context.horizonPreset, context.holdMax) : null;
  const profile = useMemo(
    () => (profiles ? profileView(profiles, direction, paramsHorizon) : null),
    [profiles, direction, paramsHorizon],
  );
  const pv = profile?.values;

  const stockScanAt  = useScanStore((s) => s.stockScanAt);
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const [params, setParams] = useState<StrategyParams>(() => ({ ...savedParams }));
  // If this page mounts before useScanParamsStore finishes rehydrating from
  // localStorage (skipHydration: true — see StoreHydration), the useState
  // initializer captures the store's module defaults instead of the persisted
  // params. Sync once hydration actually finishes (moved from Step 5, which
  // fixed this as Critical finding #8, 2026-07-15 audit).
  useEffect(() => {
    const sync = () => setParams(panelParamsOf(useScanParamsStore.getState()));
    if (useScanParamsStore.persist.hasHydrated()) sync();
    return useScanParamsStore.persist.onFinishHydration(sync);
  }, []);
  const error = useScanStore(s => s.stockScanFeedback.error);
  const notice = useScanStore(s => s.stockScanFeedback.notice);
  const router = useRouter();

  const scanning = scanState === 'SCANNING';

  // What the scan will use: the override, else the profile value (undefined
  // when neither is in hand; the labels then fall back to generic text).
  const eff = {
    pullbackEmaPeriod:  params.pullbackEmaPeriod ?? pv?.pullbackEmaPeriod,
    pullbackMaType:     params.pullbackMaType ?? pv?.pullbackMaType ?? 'EMA',
    maCrossoverFast:    params.maCrossoverFast ?? pv?.maCrossoverFast,
    maCrossoverSlow:    params.maCrossoverSlow ?? pv?.maCrossoverSlow,
    rsiOversold:        params.rsiOversold ?? pv?.rsiOversold,
    // 70 is strategy_engine.mean_reversion_rsi_signal's own default, which
    // applies when neither an override nor the profile carries the key.
    rsiOverbought:      params.rsiOverbought ?? pv?.rsiOverbought ?? 70,
    rsiTrendSma:        params.rsiTrendSma ?? pv?.rsiTrendSma,
    breakoutVolumeMult: params.breakoutVolumeMult ?? pv?.breakoutVolumeMult,
  };
  const n = (v: number | undefined, fallback: string) => (v === undefined ? fallback : String(v));
  const multiVariants         = meanReversionVariants ?? pv?.meanReversionVariants ?? null;
  const multiMinConfirm       = meanReversionMinConfirm ?? pv?.meanReversionMinConfirm ?? null;
  const multiVwapLookback     = vwapLookback ?? pv?.vwapLookback ?? null;
  const multiVwapDeviationPct = vwapDeviationPct ?? pv?.vwapDeviationPct ?? null;
  const multiOverridden = meanReversionVariants !== null || meanReversionMinConfirm !== null
    || vwapLookback !== null || vwapDeviationPct !== null;

  const pullbackMa = eff.pullbackEmaPeriod === undefined
    ? eff.pullbackMaType : `${eff.pullbackEmaPeriod}-${eff.pullbackMaType}`;
  const fastSma  = `${n(eff.maCrossoverFast, 'fast')}-SMA`;
  const slowSma  = `${n(eff.maCrossoverSlow, 'slow')}-SMA`;
  const trendSma = eff.rsiTrendSma === undefined ? 'the trend SMA' : `${eff.rsiTrendSma}-SMA`;
  const volSpike = eff.breakoutVolumeMult === undefined ? 'volume spike' : `volume spike (${eff.breakoutVolumeMult}×)`;
  const strategyLabel: Record<string, string> = {
    pullback_ema:          `${bearish ? 'Bounce' : 'Pullback'} to ${pullbackMa}`,
    ma_crossover:          eff.maCrossoverFast === undefined || eff.maCrossoverSlow === undefined
      ? 'MA Crossover' : `MA Crossover ${eff.maCrossoverFast}/${eff.maCrossoverSlow}`,
    mean_reversion_rsi:    eff.rsiTrendSma === undefined ? 'Mean Reversion RSI' : `Mean Reversion RSI / ${eff.rsiTrendSma}-SMA`,
    mean_reversion_bb:     'Mean Reversion BB',
    mean_reversion_vwap:   'Mean Reversion VWAP (15m)',
    breakout_base:         bearish ? 'Breakdown from tight base' : 'Breakout from tight base',
  };
  const entryLabel: Record<string, string> = bearish
    ? {
        pullback_ema:          `Bounce to ${pullbackMa} in downtrend${requireReversal ? ' + reversal candle' : ''}`,
        ma_crossover:          `${fastSma} crosses below ${slowSma}`,
        mean_reversion_rsi:    `RSI > ${eff.rsiOverbought} while below ${trendSma}`,
        mean_reversion_bb:     'Price touches upper Bollinger Band + reversal signal',
        mean_reversion_vwap:   'Price deviates >1.5% above VWAP + reversal bar toward VWAP (15m bars)',
        breakout_base:         `Break below N-day low after narrow range + ${volSpike}`,
      }
    : {
        pullback_ema:          `Dip to ${pullbackMa} in uptrend${requireReversal ? ' + reversal candle' : ''}`,
        ma_crossover:          `${fastSma} crosses above ${slowSma}`,
        mean_reversion_rsi:    `RSI < ${n(eff.rsiOversold, 'the oversold level')} while above ${trendSma}`,
        mean_reversion_bb:     'Price touches lower Bollinger Band + reversal signal',
        mean_reversion_vwap:   'Price deviates >1.5% below VWAP + reversal bar toward VWAP (15m bars)',
        breakout_base:         `Break above N-day high after narrow range + ${volSpike}`,
      };

  async function onRun() {
    if (!activeStrategy) return;
    const pending = runStockScanWithContinuation(activeStrategy, params);
    const token = useScanStore.getState().stockManualRunToken;
    try {
      const outcome = await pending;
      if (outcome.kind !== 'success' || !isStockManualScanCurrent(outcome)) return;
      router.push('/screener/step-6-backtest');
    } catch (error) {
      if (useScanStore.getState().stockManualRunToken !== token) return;
      const reason = stockScanFailureReason(error, false);
      try { useScanStore.getState().setStockScanFeedback(token, { error: `Scan failed — ${reason}`, notice: null }); } catch { /* unavailable storage */ }
      try { useScanStore.getState().setStockScanError(reason); } catch { /* unavailable storage */ }
      if (useScanStore.getState().stockManualRunToken !== token) return;
      try { useScanStore.getState().setScanState('FAILED'); } catch { /* unavailable storage */ }
    }
  }


  return (
    <div className={styles.main}>
      <div className={styles.header}>
        <Text size={11} tone="dim" weight={500}>STEP 4 OF 6</Text>
        <Title as="h1" size={24}>Strategy</Title>
        <Text size={13} tone="secondary">
          Pick a strategy and run a scan. Review the results on Backtest.
        </Text>
        <Text size={12} tone="secondary">
          Scanning full {context?.universe ?? 'SP500'} universe for stock setups
        </Text>
      </div>

      <div className={styles.grid}>
        {STRATEGIES.map((s) => {
          const fit = REGIME_FIT[s.key]?.[combinedRegime];
          const badge = fit ? REGIME_BADGE[fit] : null;
          return (
            <button
              key={s.key}
              type="button"
              className={`${styles.card} ${activeStrategy === s.key ? styles.cardActive : ''}`}
              onClick={() => setActiveStrategy(s.key)}
            >
              <div className={styles.cardHeader}>
                <Text size={14} weight={500}>{strategyLabel[s.key] ?? s.label}</Text>
                <Text size={11} tone="secondary">{s.when}</Text>
                {badge && fit && (
                  <Tooltip text={regimeFitTooltip(strategyLabel[s.key] ?? s.label, fit, combinedRegime)}>
                    <span className={`${styles.regimeBadge} ${BADGE_CLASS[fit]}`}>{badge.label}</span>
                  </Tooltip>
                )}
              </div>
              <div className={styles.cardBody}>
                <Text size={11} tone="dim">Entry: {entryLabel[s.key] ?? s.entry}</Text>
                <Text size={11} tone="dim">Stop: {s.stop}</Text>
                <Text size={11} tone="dim">Exit: {s.exit}</Text>
              </div>
            </button>
          );
        })}
      </div>

      <StrategyParamsPanel
        params={params}
        setParams={setParams}
        onReset={() => setParams(panelParamsOf(useScanParamsStore.getState()))}
        profile={profile}
        profileUnavailable={profilesFailed}
        customHorizon={context?.horizonPreset === 'Custom' ? paramsHorizon : null}
      />

      {activeStrategy === 'mean_reversion_multi' && (
        multiVariants !== null && multiMinConfirm !== null && multiVwapLookback !== null && multiVwapDeviationPct !== null ? (
          <MeanReversionConfirmPanel
            variants={multiVariants}
            minConfirmations={multiMinConfirm}
            vwapLookback={multiVwapLookback}
            vwapDeviationPct={multiVwapDeviationPct}
            onChange={(update) => {
              if (update.variants !== undefined)         setMeanReversionVariants(update.variants);
              if (update.minConfirmations !== undefined) setMeanReversionMinConfirm(update.minConfirmations);
              if (update.vwapLookback !== undefined)     setVwapLookback(update.vwapLookback);
              if (update.vwapDeviationPct !== undefined) setVwapDeviationPct(update.vwapDeviationPct);
            }}
          />
        ) : (
          <Text size={11} tone="caution">
            {'Signal confirmation: profile unavailable — the scan uses the backend\'s values'}
          </Text>
        )
      )}
      {activeStrategy === 'mean_reversion_multi' && multiOverridden && (
        <button
          type="button"
          className={styles.resetProfileBtn}
          onClick={() => {
            setMeanReversionVariants(null);
            setMeanReversionMinConfirm(null);
            setVwapLookback(null);
            setVwapDeviationPct(null);
          }}
        >
          Reset signal confirmation to profile
        </button>
      )}

      <div className={styles.runRow}>
        <button
          type="button"
          className={styles.runBtn}
          onClick={onRun}
          disabled={!activeStrategy || scanning || (activeStrategy === 'mean_reversion_multi' && multiVariants !== null && multiVariants.length === 0)}
          title={
            !activeStrategy
              ? 'Select a strategy first'
              : activeStrategy === 'mean_reversion_multi' && multiVariants !== null && multiVariants.length === 0
              ? 'Select at least one confirmation signal'
              : undefined
          }
        >
          {scanning ? 'Running backtest scan…' : 'Run Stock Scan'}
        </button>
        {stockScanAt && mounted && (
          <Text size={11} tone="dim">Last stock scan: {_labelWithDate(stockScanAt)}</Text>
        )}

      </div>

      <HistoryPrefetchRow />

      {error && <Text size={12} tone="reject">{error}</Text>}
      {notice && <Text size={12} tone="caution">{notice}</Text>}
      {/* STOCK-SENDS (§A3): notes left by a stock send (StockPositionCard or
        * StockSendDialog) whose row may have no order, or whose order's status
        * is unknown. */}
      <DirectSendNotesPanel />

      {result && (
        <button type="button" className={styles.sendBtn} onClick={() => router.push('/screener/step-6-backtest')}>
          View Backtest results
        </button>
      )}
    </div>
  );
}
