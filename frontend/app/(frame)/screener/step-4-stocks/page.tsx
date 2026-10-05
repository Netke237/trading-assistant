'use client';

import { useState, useEffect } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore, type ScanParams } from '@/lib/scanParamsStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useShallow } from 'zustand/shallow';
import { ScanFunnel } from '@/components/organisms/ScanFunnel';
import { StrategyParamsPanel, type StrategyParams } from '@/components/organisms/StrategyParamsPanel';
import { MeanReversionConfirmPanel } from '@/components/molecules/MeanReversionConfirmPanel';
import { runStockScanWithContinuation, isStockManualScanCurrent, stockPositionCardKey, stockScanFailureReason } from '@/lib/stockScan';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { Tooltip } from '@/components/atoms/Tooltip';
import { WatchStar } from '@/components/atoms/WatchStar';
import { regimeFitTooltip, stockScanGateTooltip, fundamentalScoreTooltip, winRateTooltip } from '@/lib/statusTooltips';
import { toneForScore, FUNDAMENTAL_BAND } from '@/lib/status';
import { computeStockDeltas, type StockDelta } from '@/lib/stockDelta';
import { splitStockRejected } from '@/lib/stockShortlist';
import { StockPositionCard } from '@/components/organisms/StockPositionCard';
import { StockSendDialog, type StockDraftOrder } from '@/components/organisms/StockSendDialog';
import { DirectSendNotesPanel } from '@/components/organisms/DirectSendNotesPanel';
import { buildPaperStockPosition } from '@/lib/paperTrade';
import type { Direction } from '@/types/domain';
import type { StockScanResult } from '@/types/stockDomain';
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
    rsiPeriod: s.rsiPeriod, rsiOversold: s.rsiOversold, rsiTrendSma: s.rsiTrendSma,
    requireChoppyRegime: s.requireChoppyRegime ?? false,
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
  // The request of the run whose rows are on screen (A5). With the row's own
  // strategy as fallback, this is StockPositionCard's strategyKey below.
  const scannedRequestStrategy = useScanStore((s) => s.stockScanRequest?.strategy ?? null);
  const combinedRegime = useScanStore((s) => s.combinedRegime);
  const result         = useScanStore((s) => s.stockScanResult);
  const previous       = useScanStore((s) => s.previousStockScanResult);
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

  const stockBasket  = useScanStore((s) => s.stockBasket);
  const stockScanAt  = useScanStore((s) => s.stockScanAt);
  const addPosition = usePortfolioStore((s) => s.addPosition);
  const portfolioPositions = usePortfolioStore((s) => s.positions);
  const portfolioSymbols = new Set(portfolioPositions.map((p) => p.symbol));

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
  const [openSymbol, setOpenSymbol] = useState<string | null>(null);
  const afterScanIntent = useScanStore(s => s.stockAfterScanIntent);
  const [showSendDialog, setShowSendDialog] = useState(false);
  const [healthSort, setHealthSort] = useState<'asc' | 'desc' | null>(null);
  const deltas: Map<string, StockDelta> = result ? computeStockDeltas(result, previous) : new Map();

  // The table used to re-filter on `passes_gate || win_rate >= 0.40`. That was
  // dead: stock_scan.py returns a "backtest gate:" rejection for every symbol
  // failing passes_gate, so no candidate reaching here can fail it and the
  // predicate was always true. Dropped rather than kept for reassurance — the
  // funnel's count and this table are the same list.
  const shownCandidates = result?.candidates ?? [];
  // Names ranked below the shortlist cap passed every gate; they ride in
  // `rejected` so they are visible, but are listed apart from real rejections.
  const { rejected: gateRejected, overCap } = splitStockRejected(result?.rejected);

  const scanning = scanState === 'SCANNING';

  const strategyLabel: Record<string, string> = {
    pullback_ema:          `${bearish ? 'Bounce' : 'Pullback'} to ${params.pullbackEmaPeriod}-${params.pullbackMaType}`,
    ma_crossover:          `MA Crossover ${params.maCrossoverFast}/${params.maCrossoverSlow}`,
    mean_reversion_rsi:    `Mean Reversion RSI / ${params.rsiTrendSma}-SMA`,
    mean_reversion_bb:     'Mean Reversion BB',
    mean_reversion_vwap:   'Mean Reversion VWAP (15m)',
    breakout_base:         bearish ? 'Breakdown from tight base' : 'Breakout from tight base',
  };
  const entryLabel: Record<string, string> = bearish
    ? {
        pullback_ema:          `Bounce to ${params.pullbackEmaPeriod}-${params.pullbackMaType} in downtrend${requireReversal ? ' + reversal candle' : ''}`,
        ma_crossover:          `${params.maCrossoverFast}-SMA crosses below ${params.maCrossoverSlow}-SMA`,
        mean_reversion_rsi:    `RSI > 70 while below ${params.rsiTrendSma}-SMA`,
        mean_reversion_bb:     'Price touches upper Bollinger Band + reversal signal',
        mean_reversion_vwap:   'Price deviates >1.5% above VWAP + reversal bar toward VWAP (15m bars)',
        breakout_base:         `Break below N-day low after narrow range + volume spike (${params.breakoutVolumeMult}×)`,
      }
    : {
        pullback_ema:          `Dip to ${params.pullbackEmaPeriod}-${params.pullbackMaType} in uptrend${requireReversal ? ' + reversal candle' : ''}`,
        ma_crossover:          `${params.maCrossoverFast}-SMA crosses above ${params.maCrossoverSlow}-SMA`,
        mean_reversion_rsi:    `RSI < ${params.rsiOversold} while above ${params.rsiTrendSma}-SMA`,
        mean_reversion_bb:     'Price touches lower Bollinger Band + reversal signal',
        mean_reversion_vwap:   'Price deviates >1.5% below VWAP + reversal bar toward VWAP (15m bars)',
        breakout_base:         `Break above N-day high after narrow range + volume spike (${params.breakoutVolumeMult}×)`,
      };

  function onAfterScanToggle(symbol: string, armed: boolean) {
    useScanStore.getState().setStockAfterScanIntent(symbol, armed);
  }

  async function onRun() {
    if (!activeStrategy) return;
    const pending = runStockScanWithContinuation(activeStrategy, params);
    const token = useScanStore.getState().stockManualRunToken;
    try {
      const outcome = await pending;
      if (!isStockManualScanCurrent(outcome)) return;
      // W2 consumes this successful continuation to navigate to Backtest.
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
          Pick a strategy, run the scan, and act on the results — all on this page.
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
      />

      {activeStrategy === 'mean_reversion_multi' && (
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
      )}

      <div className={styles.runRow}>
        <button
          type="button"
          className={styles.runBtn}
          onClick={onRun}
          disabled={!activeStrategy || scanning || (activeStrategy === 'mean_reversion_multi' && meanReversionVariants.length === 0)}
          title={
            !activeStrategy
              ? 'Select a strategy first'
              : activeStrategy === 'mean_reversion_multi' && meanReversionVariants.length === 0
              ? 'Select at least one confirmation signal'
              : undefined
          }
        >
          {scanning ? 'Running backtest scan…' : 'Run Stock Scan'}
        </button>
        {stockScanAt && mounted && (
          <Text size={11} tone="dim">Last stock scan: {_labelWithDate(stockScanAt)}</Text>
        )}
        {stockBasket.length > 0 && (
          <button
            type="button"
            className={styles.sendBtn}
            onClick={() => setShowSendDialog(true)}
          >
            Send basket ({stockBasket.length})
          </button>
        )}
      </div>

      <HistoryPrefetchRow />

      {error && <Text size={12} tone="reject">{error}</Text>}
      {notice && <Text size={12} tone="caution">{notice}</Text>}
      {/* STOCK-SENDS (§A3): notes left by a stock send (StockPositionCard or
        * StockSendDialog) whose row may have no order, or whose order's status
        * is unknown. */}
      <DirectSendNotesPanel />

      {result?.pipeline && (
        <details className={styles.logPanel}>
          <summary><Text size={12} tone="secondary">Pipeline log</Text></summary>
          <ScanFunnel mode="stock" pipeline={result.pipeline} />
        </details>
      )}

      {result?.direction_banner && (
        <div className={styles.directionBanner}>
          <Text size={12} tone="caution">{result.direction_banner}</Text>
        </div>
      )}

      {result && (
        <div className={styles.results}>
          <div className={styles.tableHeader}>
            <span aria-hidden />
            <Text size={11} tone="dim">SYMBOL</Text>
            <Text size={11} tone="dim">SCORE</Text>
            <Text size={11} tone="dim">Δ</Text>
            <Text size={11} tone="dim">WIN %</Text>
            <Text size={11} tone="dim">TRADES</Text>
            <Text size={11} tone="dim">RETURN</Text>
            <Text size={11} tone="dim">MAX DD</Text>
            <button
              type="button"
              className={styles.sortableHeader}
              onClick={() => setHealthSort((s) => s === null ? 'desc' : s === 'desc' ? 'asc' : null)}
              title="Sort by fundamental health score"
            >
              <Text size={11} tone="dim">HEALTH</Text>
              <Text size={10} tone="dim">{healthSort === 'desc' ? '↓' : healthSort === 'asc' ? '↑' : '↕'}</Text>
            </button>
            <Text size={11} tone="dim">GATE</Text>
          </div>

          <div className={styles.tableBody}>
            {[...shownCandidates].sort((a, b) => {
              if (healthSort === null) return 0;
              const aScore = a.fundamentals?.score ?? -1;
              const bScore = b.fundamentals?.score ?? -1;
              return healthSort === 'desc' ? bScore - aScore : aScore - bScore;
            }).map((c) => {
              const d = deltas.get(c.symbol);
              const bt = c.backtest;
              const open = openSymbol === c.symbol;
              // Always PASS: a symbol failing the gate is rejected before it
              // becomes a candidate, so the CAUTION branch was unreachable.
              const gateStatus = 'PASS';
              return (
                <div key={c.symbol}>
                  <button
                    type="button"
                    className={`${styles.row} ${open ? styles.rowOpen : ''}`}
                    onClick={() => setOpenSymbol(open ? null : c.symbol)}
                  >
                    <span onClick={(e) => e.stopPropagation()}>
                      <WatchStar symbol={c.symbol} size="sm" />
                    </span>
                    <span className={styles.symbolCell}>
                      <Data size={12} weight={500}>{c.symbol}</Data>
                      {portfolioSymbols.has(c.symbol) && (
                        <span className={styles.inPortfolioDot} title="Already in portfolio" />
                      )}
                    </span>
                    <Data size={12}>{c.stock_score}</Data>
                    <Data size={11} tone={!d ? 'dim' : d.scoreDelta > 0 ? 'pass' : d.scoreDelta < 0 ? 'reject' : 'secondary'}>
                      {!d ? '—' : `${d.scoreDelta > 0 ? '+' : ''}${d.scoreDelta}${d.rankDelta !== 0 ? ` (${d.rankDelta > 0 ? '↑' : '↓'}${Math.abs(d.rankDelta)})` : ''}`}
                    </Data>
                    <Data
                      size={12}
                      tone={bt.win_rate >= 0.5 ? 'pass' : bt.win_rate >= 0.40 ? 'caution' : 'reject'}
                      title={winRateTooltip(bt.win_rate, 0.5, 0.40)}
                    >
                      {(bt.win_rate * 100).toFixed(0)}%
                    </Data>
                    <Data size={12}>{bt.n_trades}</Data>
                    <Data size={12} tone={bt.total_return_pct >= 0 ? 'pass' : 'reject'}>{bt.total_return_pct.toFixed(1)}%</Data>
                    <Data size={12} tone="reject">{Math.abs(bt.max_drawdown_pct).toFixed(1)}%</Data>
                    {c.fundamentals ? (
                      <Tooltip text={fundamentalScoreTooltip('overall', c.fundamentals.score)}>
                        <Data size={12} tone={toneForScore(c.fundamentals.score, FUNDAMENTAL_BAND)}>
                          {c.fundamentals.score}
                        </Data>
                      </Tooltip>
                    ) : (
                      <Data size={12} tone="dim">—</Data>
                    )}
                    <StatusBadge
                      status={gateStatus}
                      tooltip={stockScanGateTooltip({
                        passes: bt.passes_gate,
                        winRate: bt.win_rate,
                        nTrades: bt.n_trades,
                        expectancy: bt.expectancy,
                        minWinRate: params.btMinWinRate,
                        minTrades: params.btMinTrades,
                      })}
                    />
                  </button>
                  {open && (
                    <StockPositionCard
                      // See stockPositionCardKey's doc comment: an adversarial audit
                      // round caught a stale entry/stop/target overlay from a
                      // PREVIOUS scan silently surviving a same-symbol Run Scan and
                      // reaching order placement / Add to Portfolio, because
                      // `openSymbol` isn't reset by onRun() and StockPositionCard's
                      // own overlay-reset effect only fires on a symbol change.
                      key={stockPositionCardKey(c)}
                      card={c}
                      // The strategy this row was scanned with: NOT the current selection, which
                      // can change after the scan, and NOT lastStockScanStrategy, which can name
                      // another tab's or device's scan (plan audit P1-F1). StockAutoTradeArm
                      // persists a strategy watch with this key.
                      strategyKey={scannedRequestStrategy ?? c.strategy.strategy}
                      afterScanArmed={!!afterScanIntent[c.symbol]}
                      onAfterScanToggle={onAfterScanToggle}
                    />
                  )}
                </div>
              );
            })}
          </div>

          {overCap.length > 0 && (
            <details className={styles.rejectedSection}>
              <summary><Text size={12} tone="caution">{overCap.length} over cap</Text></summary>
              {overCap.map((r) => (
                <Text key={r.symbol} size={11} tone="dim">{r.symbol}: {r.reason}</Text>
              ))}
            </details>
          )}
          {gateRejected.length > 0 && (
            <details className={styles.rejectedSection}>
              <summary><Text size={12} tone="dim">{gateRejected.length} rejected</Text></summary>
              {gateRejected.map((r) => (
                <Text key={r.symbol} size={11} tone="dim">{r.symbol}: {r.reason}</Text>
              ))}
            </details>
          )}
        </div>
      )}
      {showSendDialog && (
        <StockSendDialog
          cards={stockBasket}
          onClose={() => setShowSendDialog(false)}
          onSubmit={(_orders: StockDraftOrder[]) => {
            setShowSendDialog(false);
          }}
        />
      )}
    </div>
  );
}

