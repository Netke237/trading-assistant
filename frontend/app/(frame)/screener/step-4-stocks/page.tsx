'use client';

import { useState, useEffect } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useShallow } from 'zustand/shallow';
import { ScanFunnel } from '@/components/organisms/ScanFunnel';
import { StrategyParamsPanel, type StrategyParams } from '@/components/organisms/StrategyParamsPanel';
import { runStockScan } from '@/lib/stockScan';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { WatchStar } from '@/components/atoms/WatchStar';
import { computeStockDeltas, type StockDelta } from '@/lib/stockDelta';
import { StockPositionCard } from '@/components/organisms/StockPositionCard';
import { StockSendDialog, type StockDraftOrder } from '@/components/organisms/StockSendDialog';
import { buildPaperStockPosition } from '@/lib/paperTrade';
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

const STRATEGIES_BULLISH = [
  { key: 'pullback_ema',          label: 'Pullback to 20-EMA',        when: 'Steady uptrends',        entry: 'Dip to 20-EMA + reversal candle in uptrend',              stop: 'Below recent swing low', exit: 'Prior high / trailing stop under higher lows' },
  { key: 'breakout_base',         label: 'Breakout from tight base',  when: 'Momentum stocks',        entry: 'Break above N-day high after narrow range + volume spike', stop: 'Below the base low',     exit: 'Measured move / trailing stop' },
  { key: 'ma_crossover',          label: 'MA Crossover 20/50',        when: 'Simple trend entry',     entry: '20-SMA crosses above 50-SMA',                             stop: 'Below 50-SMA',           exit: 'Cross back down' },
  { key: 'mean_reversion_rsi',    label: 'Mean Reversion RSI',        when: 'Oversold in uptrend',    entry: 'RSI < 30 while above 200-SMA',                            stop: 'Below recent swing low', exit: 'RSI returns to mid / take-profit target' },
  { key: 'mean_reversion_bb',     label: 'Mean Reversion BB',         when: 'Choppy / range-bound',   entry: 'Price touches lower Bollinger Band + reversal signal',     stop: 'Below lower band',       exit: 'Return to mid-band / upper band' },
  { key: 'mean_reversion_vwap',   label: 'Mean Reversion VWAP',       when: 'Intraday · 15m session', entry: 'Price deviates >1.5% below VWAP + reversal bar',           stop: '0.5 ATR below entry',    exit: '2× risk above VWAP' },
];

const STRATEGIES_BEARISH = [
  { key: 'pullback_ema',          label: 'Pullback to 20-EMA',        when: 'Steady downtrends',      entry: 'Bounce to 20-EMA + reversal candle in downtrend',          stop: 'Above recent swing high', exit: 'Prior low / trailing stop above lower highs' },
  { key: 'breakout_base',         label: 'Breakdown from tight base', when: 'Momentum shorts',        entry: 'Break below N-day low after narrow range + volume spike',  stop: 'Above the base high',    exit: 'Measured move / trailing stop' },
  { key: 'ma_crossover',          label: 'MA Crossover 20/50',        when: 'Simple trend entry',     entry: '20-SMA crosses below 50-SMA',                             stop: 'Above 50-SMA',           exit: 'Cross back up' },
  { key: 'mean_reversion_rsi',    label: 'Mean Reversion RSI',        when: 'Overbought in downtrend', entry: 'RSI > 70 while below 200-SMA',                           stop: 'Above recent swing high', exit: 'RSI returns to mid / take-profit target' },
  { key: 'mean_reversion_bb',     label: 'Mean Reversion BB',         when: 'Choppy / range-bound',   entry: 'Price touches upper Bollinger Band + reversal signal',     stop: 'Above upper band',       exit: 'Return to mid-band / lower band' },
  { key: 'mean_reversion_vwap',   label: 'Mean Reversion VWAP',       when: 'Intraday · 15m session', entry: 'Price deviates >1.5% above VWAP + reversal bar',           stop: '0.5 ATR above entry',    exit: '2× risk below VWAP' },
];

type RegimeFit = 'PASS' | 'CAUTION' | 'REJECT';
const REGIME_FIT: Record<string, Partial<Record<string, RegimeFit>>> = {
  pullback_ema:         { PASS: 'PASS',    CAUTION: 'CAUTION', REJECT: 'REJECT'  },
  breakout_base:        { PASS: 'PASS',    CAUTION: 'REJECT',  REJECT: 'REJECT'  },
  ma_crossover:         { PASS: 'CAUTION', CAUTION: 'CAUTION', REJECT: 'REJECT'  },
  mean_reversion_rsi:   { PASS: 'CAUTION', CAUTION: 'PASS',    REJECT: 'CAUTION' },
  mean_reversion_bb:    { PASS: 'CAUTION', CAUTION: 'PASS',    REJECT: 'CAUTION' },
  mean_reversion_vwap:  { PASS: 'CAUTION', CAUTION: 'PASS',    REJECT: 'CAUTION' },
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
  const [openSymbol, setOpenSymbol] = useState<string | null>(null);
  const [afterScanArmedSymbols, setAfterScanArmedSymbols] = useState<Set<string>>(new Set());
  const [showSendDialog, setShowSendDialog] = useState(false);
  const [healthSort, setHealthSort] = useState<'asc' | 'desc' | null>(null);
  const deltas: Map<string, StockDelta> = result ? computeStockDeltas(result, previous) : new Map();

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
    const res = await runStockScan(selected, params);
    if (!res) {
      setError('Scan failed — is the backend running on port 8000?');
      return;
    }
    // Auto-execute symbols armed for after_scan — add as paper positions locally
    for (const c of res.candidates) {
      if (afterScanArmedSymbols.has(c.symbol)) {
        addPosition(buildPaperStockPosition(c.symbol, c.strategy.entry_price, c.shares));
      }
    }
  }

  return (
    <div className={styles.main}>
      <div className={styles.header}>
        <Text size={11} tone="dim" weight={500}>STEP 4 OF 4</Text>
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
                {badge && fit && <span className={`${styles.regimeBadge} ${BADGE_CLASS[fit]}`}>{badge.label}</span>}
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

      <div className={styles.runRow}>
        <button
          type="button"
          className={styles.runBtn}
          onClick={onRun}
          disabled={!selected || scanning}
          title={!selected ? 'Select a strategy first' : undefined}
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
            {[...result.candidates.filter((c) => c.backtest.passes_gate || c.backtest.win_rate >= 0.40)].sort((a, b) => {
              if (healthSort === null) return 0;
              const aScore = a.fundamentals?.score ?? -1;
              const bScore = b.fundamentals?.score ?? -1;
              return healthSort === 'desc' ? bScore - aScore : aScore - bScore;
            }).map((c) => {
              const d = deltas.get(c.symbol);
              const bt = c.backtest;
              const open = openSymbol === c.symbol;
              const gateStatus = bt.passes_gate ? 'PASS' : 'CAUTION';
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
                    <Data size={12} tone={bt.win_rate >= 0.5 ? 'pass' : bt.win_rate >= 0.40 ? 'caution' : 'reject'}>
                      {(bt.win_rate * 100).toFixed(0)}%
                    </Data>
                    <Data size={12}>{bt.n_trades}</Data>
                    <Data size={12} tone={bt.total_return_pct >= 0 ? 'pass' : 'reject'}>{bt.total_return_pct.toFixed(1)}%</Data>
                    <Data size={12} tone="reject">{Math.abs(bt.max_drawdown_pct).toFixed(1)}%</Data>
                    <Data size={12} tone={c.fundamentals ? (c.fundamentals.score >= 65 ? 'pass' : c.fundamentals.score >= 40 ? 'caution' : 'reject') : 'dim'}>
                      {c.fundamentals?.score ?? '—'}
                    </Data>
                    <StatusBadge status={gateStatus} />
                  </button>
                  {open && (
                    <StockPositionCard
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

