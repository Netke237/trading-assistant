'use client';

import { useState } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useShallow } from 'zustand/shallow';
import { ScanFunnel } from '@/components/organisms/ScanFunnel';
import { StrategyParamsPanel, type StrategyParams } from '@/components/organisms/StrategyParamsPanel';
import { runStockScan } from '@/lib/stockScan';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { computeStockDeltas, type StockDelta } from '@/lib/stockDelta';
import { StockPositionCard } from '@/components/organisms/StockPositionCard';
import { StockSendDialog, type StockDraftOrder } from '@/components/organisms/StockSendDialog';
import { buildPaperStockPosition } from '@/lib/paperTrade';
import { api } from '@/lib/api';
import styles from './page.module.css';

const STRATEGIES = [
  { key: 'pullback_ema',       label: 'Pullback to 20-EMA',        when: 'Steady uptrends',     entry: 'Dip to 20-EMA + reversal candle in uptrend',              stop: 'Below recent swing low', exit: 'Prior high / trailing stop under higher lows' },
  { key: 'breakout_base',      label: 'Breakout from tight base',  when: 'Momentum stocks',     entry: 'Break above N-day high after narrow range + volume spike', stop: 'Below the base low',     exit: 'Measured move / trailing stop' },
  { key: 'ma_crossover',       label: 'MA Crossover 20/50',        when: 'Simple trend entry',  entry: '20-SMA crosses above 50-SMA',                             stop: 'Below 50-SMA',           exit: 'Cross back down' },
  { key: 'mean_reversion_rsi', label: 'Mean Reversion RSI',        when: 'Oversold in uptrend', entry: 'RSI < 30 while above 200-SMA',                            stop: 'Below recent swing low', exit: 'RSI returns to mid / take-profit target' },
] as const;

type RegimeFit = 'PASS' | 'CAUTION' | 'REJECT';
const REGIME_FIT: Record<string, Partial<Record<string, RegimeFit>>> = {
  pullback_ema:       { PASS: 'PASS',    CAUTION: 'CAUTION', REJECT: 'REJECT'  },
  breakout_base:      { PASS: 'PASS',    CAUTION: 'REJECT',  REJECT: 'REJECT'  },
  ma_crossover:       { PASS: 'CAUTION', CAUTION: 'CAUTION', REJECT: 'REJECT'  },
  mean_reversion_rsi: { PASS: 'CAUTION', CAUTION: 'PASS',    REJECT: 'CAUTION' },
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
    btMinTrades: s.btMinTrades, btMinWinRate: s.btMinWinRate,
    eventFilter: s.eventFilter, stockShortlistMax: s.stockShortlistMax,
  })));
  const scanOverrides   = useScanStore((s) => s.scanOverrides);
  const requireReversal = (scanOverrides.pullback_require_reversal as boolean | undefined) ?? false;

  const stockBasket = useScanStore((s) => s.stockBasket);
  const addPosition = usePortfolioStore((s) => s.addPosition);

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
    pullback_ema:       `Pullback to ${params.pullbackEmaPeriod}-${params.pullbackMaType}`,
    ma_crossover:       `MA Crossover ${params.maCrossoverFast}/${params.maCrossoverSlow}`,
    mean_reversion_rsi: `Mean Reversion RSI / ${params.rsiTrendSma}-SMA`,
    breakout_base:      'Breakout from tight base',
  };
  const entryLabel: Record<string, string> = {
    pullback_ema:       `Dip to ${params.pullbackEmaPeriod}-${params.pullbackMaType} in uptrend${requireReversal ? ' + reversal candle' : ''}`,
    ma_crossover:       `${params.maCrossoverFast}-SMA crosses above ${params.maCrossoverSlow}-SMA`,
    mean_reversion_rsi: `RSI < ${params.rsiOversold} while above ${params.rsiTrendSma}-SMA`,
    breakout_base:      `Break above N-day high after narrow range + volume spike (${params.breakoutVolumeMult}×)`,
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
    // Auto-execute symbols armed for after_scan
    for (const c of res.candidates) {
      if (afterScanArmedSymbols.has(c.symbol)) {
        try {
          await api.postStockOrder({
            broker: 'recommendation',
            symbol: c.symbol,
            action: c.direction === 'Bullish' ? 'BUY' : 'SELL',
            quantity: c.shares,
            order_type: 'LMT',
            limit_price: c.strategy.entry_price,
            tif: 'DAY',
          });
          addPosition(buildPaperStockPosition(c.symbol, c.strategy.entry_price, c.shares));
        } catch {
          // silent — user can retry via dialog
        }
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

      {result && (
        <div className={styles.results}>
          <div className={styles.tableHeader}>
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
              onClick={() => setHealthSort((s) => s === 'desc' ? 'asc' : 'desc')}
              title="Sort by fundamental health score"
            >
              <Text size={11} tone="dim">HEALTH</Text>
              <Text size={10} tone="dim">{healthSort === 'desc' ? '↓' : healthSort === 'asc' ? '↑' : '↕'}</Text>
            </button>
            <Text size={11} tone="dim">GATE</Text>
          </div>

          <div className={styles.tableBody}>
            {[...result.candidates.filter((c) => c.backtest.passes_gate)].sort((a, b) => {
              if (healthSort === null) return 0;
              const aScore = a.fundamentals?.score ?? -1;
              const bScore = b.fundamentals?.score ?? -1;
              return healthSort === 'desc' ? bScore - aScore : aScore - bScore;
            }).map((c) => {
              const d = deltas.get(c.symbol);
              const bt = c.backtest;
              const open = openSymbol === c.symbol;
              return (
                <div key={c.symbol}>
                  <button
                    type="button"
                    className={`${styles.row} ${open ? styles.rowOpen : ''}`}
                    onClick={() => setOpenSymbol(open ? null : c.symbol)}
                  >
                    <Data size={12} weight={500}>{c.symbol}</Data>
                    <Data size={12}>{c.stock_score}</Data>
                    <Data size={11} tone={!d ? 'dim' : d.scoreDelta > 0 ? 'pass' : d.scoreDelta < 0 ? 'reject' : 'secondary'}>
                      {!d ? '—' : `${d.scoreDelta > 0 ? '+' : ''}${d.scoreDelta}${d.rankDelta !== 0 ? ` (${d.rankDelta > 0 ? '↑' : '↓'}${Math.abs(d.rankDelta)})` : ''}`}
                    </Data>
                    <Data size={12} tone={bt.win_rate >= 0.5 ? 'pass' : bt.win_rate >= 0.45 ? 'caution' : 'reject'}>
                      {(bt.win_rate * 100).toFixed(0)}%
                    </Data>
                    <Data size={12}>{bt.n_trades}</Data>
                    <Data size={12} tone={bt.total_return_pct >= 0 ? 'pass' : 'reject'}>{bt.total_return_pct.toFixed(1)}%</Data>
                    <Data size={12} tone="reject">{Math.abs(bt.max_drawdown_pct).toFixed(1)}%</Data>
                    <Data size={12} tone={c.fundamentals ? (c.fundamentals.score >= 65 ? 'pass' : c.fundamentals.score >= 40 ? 'caution' : 'reject') : 'dim'}>
                      {c.fundamentals?.score ?? '—'}
                    </Data>
                    <StatusBadge status={bt.passes_gate ? 'PASS' : 'REJECT'} />
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

