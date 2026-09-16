'use client';

import { useState, useEffect } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useShallow } from 'zustand/shallow';
import { ScanFunnel } from '@/components/organisms/ScanFunnel';
import { StrategyParamsPanel, type StrategyParams } from '@/components/organisms/StrategyParamsPanel';
import { MeanReversionConfirmPanel } from '@/components/molecules/MeanReversionConfirmPanel';
import { runStockScan, stockPositionCardKey, stockScanFailureReason } from '@/lib/stockScan';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { Tooltip } from '@/components/atoms/Tooltip';
import { WatchStar } from '@/components/atoms/WatchStar';
import { regimeFitTooltip, stockScanGateTooltip, fundamentalScoreTooltip, winRateTooltip } from '@/lib/statusTooltips';
import { toneForScore, FUNDAMENTAL_BAND } from '@/lib/status';
import { computeStockDeltas, type StockDelta } from '@/lib/stockDelta';
import { StockPositionCard } from '@/components/organisms/StockPositionCard';
import { StockSendDialog, type StockDraftOrder } from '@/components/organisms/StockSendDialog';
import { buildPaperStockPosition } from '@/lib/paperTrade';
import type { Direction } from '@/types/domain';
import type { StockScanResult } from '@/types/stockDomain';
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

export default function Step4StocksPage() {
  const context        = useScanStore((s) => s.context);
  const direction      = context?.direction ?? 'Bullish';
  const bearish        = direction === 'Bearish';
  const STRATEGIES     = bearish ? STRATEGIES_BEARISH : STRATEGIES_BULLISH;
  const activeStrategy = useScanStore((s) => s.activeStrategy);
  const combinedRegime = useScanStore((s) => s.combinedRegime);
  const result         = useScanStore((s) => s.stockScanResult);
  const previous       = useScanStore((s) => s.previousStockScanResult);
  const scanState      = useScanStore((s) => s.scanState);

  const savedParams = useScanParamsStore(useShallow((s) => ({
    pullbackTolerancePct: s.pullbackTolerancePct, pullbackEmaPeriod: s.pullbackEmaPeriod,
    pullbackTrendEma: s.pullbackTrendEma, pullbackMaType: s.pullbackMaType,
    maCrossoverFast: s.maCrossoverFast, maCrossoverSlow: s.maCrossoverSlow,
    maCrossoverLookback: s.maCrossoverLookback, breakoutVolumeMult: s.breakoutVolumeMult,
    rsiPeriod: s.rsiPeriod, rsiOversold: s.rsiOversold, rsiTrendSma: s.rsiTrendSma,
    requireChoppyRegime: s.requireChoppyRegime ?? false,
    btMinTrades: s.btMinTrades, btMinWinRate: s.btMinWinRate,
    eventFilter: s.eventFilter, stockShortlistMax: s.stockShortlistMax,
  })));
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
  const [selected, setSelected] = useState<string | null>(activeStrategy);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [openSymbol, setOpenSymbol] = useState<string | null>(null);
  const [afterScanArmedSymbols, setAfterScanArmedSymbols] = useState<Set<string>>(new Set());
  const [showSendDialog, setShowSendDialog] = useState(false);
  const [healthSort, setHealthSort] = useState<'asc' | 'desc' | null>(null);
  const deltas: Map<string, StockDelta> = result ? computeStockDeltas(result, previous) : new Map();

  // The table used to re-filter on `passes_gate || win_rate >= 0.40`. That was
  // dead: stock_scan.py returns a "backtest gate:" rejection for every symbol
  // failing passes_gate, so no candidate reaching here can fail it and the
  // predicate was always true. Dropped rather than kept for reassurance — the
  // funnel's count and this table are the same list.
  const shownCandidates = result?.candidates ?? [];

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
    setAfterScanArmedSymbols((prev) => {
      const next = new Set(prev);
      if (armed) next.add(symbol); else next.delete(symbol);
      return next;
    });
  }

  async function onRun() {
    if (!selected) return;
    setError(null);
    setNotice(null);
    // The catch is for a throw runStockScan could not convert into a null
    // return (setScanState itself failing) — without it that throw escapes
    // this handler as an unhandled rejection and the user is told nothing at
    // all. It resets scanState as well as showing the reason: the throw
    // happens with SCANNING already set, which leaves the Run button disabled
    // for the rest of the session.
    let res: StockScanResult | null;
    try {
      res = await runStockScan(selected, params);
    } catch (err) {
      useScanStore.getState().setScanState('FAILED');
      setError(`Scan failed — ${stockScanFailureReason(err, false)}`);
      return;
    }
    if (!res) {
      // The backend's own reason when it gave one (a 4xx/5xx detail), rather
      // than the unconditional "is the backend running?" guess this line used
      // to show even for a request the running backend had just rejected.
      setError(`Scan failed — ${useScanStore.getState().stockScanError ?? 'unknown error'}`);
      return;
    }
    // Auto-execute symbols armed for after_scan — add as paper positions locally
    const failures: string[] = [];
    const queued: string[] = [];
    const adjusted: string[] = [];
    for (const c of res.candidates) {
      if (afterScanArmedSymbols.has(c.symbol)) {
        // Auto-execute fires with no human in the loop, so there is no overlay to
        // prefer — send the pristine strategy levels. Note this path also did not
        // attach a snapshot before; it still does not, deliberately (the scan result
        // it came from is already persisted in scanStore).
        //
        // `?.length ?` not `??` — an empty targets array must fall back too.
        const addRes = await addPosition(buildPaperStockPosition(
          c.symbol, c.strategy.entry_price, c.shares, c.direction as Direction, undefined,
          {
            stop: c.strategy.stop_price,
            targets: (c.strategy.targets?.length ? c.strategy.targets : [c.strategy.target_price])
              .map((price) => ({ price })),
          },
        ));
        if (addRes.status === 'rejected') failures.push(`${c.symbol}: ${addRes.detail ?? 'not saved'}`);
        else if (addRes.status === 'pending') queued.push(c.symbol);
        else if (addRes.adjustedQty != null) adjusted.push(`${c.symbol} (${addRes.adjustedQty} sh)`);
      }
    }
    if (failures.length) {
      setError(`Some auto-executed positions were not saved — ${failures.join('; ')}`);
    }
    const noticeParts: string[] = [];
    if (queued.length) {
      noticeParts.push(`Queued — backend unreachable, will sync automatically: ${queued.join(', ')}`);
    }
    if (adjusted.length) {
      noticeParts.push(`Size reduced to fit exposure limits — ${adjusted.join(', ')}`);
    }
    if (noticeParts.length) setNotice(noticeParts.join(' · '));
  }

  return (
    <div className={styles.main}>
      <div className={styles.header}>
        <Text size={11} tone="dim" weight={500}>STEP 4 OF 7</Text>
        <Title as="h1" size={24}>Stocks</Title>
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
              className={`${styles.card} ${selected === s.key ? styles.cardActive : ''}`}
              onClick={() => setSelected(s.key)}
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
        onReset={() => setParams({ ...savedParams })}
      />

      {selected === 'mean_reversion_multi' && (
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
          disabled={!selected || scanning || (selected === 'mean_reversion_multi' && meanReversionVariants.length === 0)}
          title={
            !selected
              ? 'Select a strategy first'
              : selected === 'mean_reversion_multi' && meanReversionVariants.length === 0
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

      {error && <Text size={12} tone="reject">{error}</Text>}
      {notice && <Text size={12} tone="caution">{notice}</Text>}

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
                      strategyKey={selected ?? ''}
                      afterScanArmed={afterScanArmedSymbols.has(c.symbol)}
                      onAfterScanToggle={onAfterScanToggle}
                    />
                  )}
                </div>
              );
            })}
          </div>

          {result.rejected.length > 0 && (
            <details className={styles.rejectedSection}>
              <summary><Text size={12} tone="dim">{result.rejected.length} rejected</Text></summary>
              {result.rejected.map((r) => (
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

