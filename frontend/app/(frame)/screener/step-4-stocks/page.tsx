'use client';

import { useState, useEffect } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { useShallow } from 'zustand/shallow';
import { ScanFunnel } from '@/components/organisms/ScanFunnel';
import { StrategyParamsPanel, type StrategyParams } from '@/components/organisms/StrategyParamsPanel';
import { runStockScan } from '@/lib/stockScan';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { computeStockDeltas, type StockDelta } from '@/lib/stockDelta';
import type { PositionCardData } from '@/types/stockDomain';
import Link from 'next/link';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
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

  const [params, setParams] = useState<StrategyParams>(() => ({ ...savedParams }));
  const [selected, setSelected] = useState<string | null>(activeStrategy);
  const [error, setError] = useState<string | null>(null);
  const [openSymbol, setOpenSymbol] = useState<string | null>(null);
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

  async function onRun() {
    if (!selected) return;
    setError(null);
    const res = await runStockScan(selected, params);
    if (!res) setError('Scan failed — is the backend running on port 8000?');
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
            <Text size={11} tone="dim">GATE</Text>
          </div>

          <div className={styles.tableBody}>
            {result.candidates.filter((c) => c.backtest.passes_gate).map((c) => {
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
                    <StatusBadge status={bt.passes_gate ? 'PASS' : 'REJECT'} />
                  </button>
                  {open && <PositionCardAccordion card={c} />}
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
    </div>
  );
}

type ExecutionMode = 'recommendation' | 'ibkr_paper' | 'tradier_paper' | 'alpaca_paper';

function PositionCardAccordion({ card }: { card: PositionCardData }) {
  const stockBasket   = useScanStore((s) => s.stockBasket);
  const addToBasket   = useScanStore((s) => s.addToStockBasket);
  const removeBasket  = useScanStore((s) => s.removeFromStockBasket);
  const addPosition   = usePortfolioStore((s) => s.addPosition);
  const ibkrPaper     = useSettingsStore((s) => s.ibkrPaper);
  const tradierPaper  = useSettingsStore((s) => s.tradierPaper);

  const [execMode, setExecMode] = useState<ExecutionMode>('recommendation');
  const [placingType, setPlacingType] = useState<'LMT' | 'MKT' | null>(null);
  const [orderId, setOrderId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [added, setAdded] = useState(false);
  const [alpacaConfigured, setAlpacaConfigured] = useState(false);

  const pinned = stockBasket.some((c) => c.symbol === card.symbol);
  const ibkrConfigured    = !!ibkrPaper.accountId && !!ibkrPaper.baseUrl;
  const tradierConfigured = !!tradierPaper.token && !!tradierPaper.accountId;

  useEffect(() => {
    api.getBrokerStatus()
      .then((s) => setAlpacaConfigured(s.alpaca_paper?.configured ?? false))
      .catch(() => {});
  }, []);

  async function submit(orderType: 'LMT' | 'MKT') {
    if (execMode === 'recommendation') return;
    setPlacingType(orderType);
    setErr(null);
    try {
      const res = await api.postStockOrder({
        broker: execMode,
        symbol: card.symbol,
        action: card.direction === 'Bullish' ? 'BUY' : 'SELL',
        quantity: card.shares,
        order_type: orderType,
        limit_price: orderType === 'LMT' ? card.strategy.entry_price : null,
        tif: 'DAY',
      });
      setOrderId(res.order_id);
    } catch (e) {
      setErr(String(e));
    } finally {
      setPlacingType(null);
    }
  }

  function onAddToPortfolio() {
    addPosition(buildPaperStockPosition(card.symbol, card.price, card.shares));
    setAdded(true);
  }

  return (
    <div className={styles.accordion}>
      <div className={styles.grid4}>
        <div><Text size={10} tone="dim">ENTRY</Text><Data size={16} weight={500}>${card.strategy.entry_price}</Data></div>
        <div><Text size={10} tone="dim">STOP</Text><Data size={16} weight={500} tone="reject">${card.strategy.stop_price}</Data></div>
        <div><Text size={10} tone="dim">TARGET</Text><Data size={16} weight={500} tone="pass">${card.strategy.target_price}</Data></div>
        <div><Text size={10} tone="dim">R:R</Text><Data size={16} weight={500}>{card.strategy.rr_ratio.toFixed(1)}</Data></div>
      </div>
      <div className={styles.grid4}>
        <div><Text size={10} tone="dim">SHARES</Text><Data size={16} weight={500}>{card.shares}</Data></div>
        <div><Text size={10} tone="dim">RISK $</Text><Data size={16} weight={500}>{card.dollar_risk.toFixed(0)}</Data></div>
        <div><Text size={10} tone="dim">SIZE $</Text><Data size={16} weight={500}>{card.dollar_size.toFixed(0)}</Data></div>
        <div><Text size={10} tone="dim">WIN %</Text><Data size={16} weight={500} tone={card.backtest.win_rate >= 0.5 ? 'pass' : 'caution'}>{(card.backtest.win_rate * 100).toFixed(0)}%</Data></div>
      </div>

      <div className={styles.actionRow}>
        <Link href={`/chart?symbol=${encodeURIComponent(card.symbol)}`} className={styles.actionBtn}>View Chart</Link>
        <button type="button" className={styles.actionBtn}
          onClick={() => (pinned ? removeBasket(card.symbol) : addToBasket(card))}>
          {pinned ? 'Unpin from Basket' : 'Pin to Basket'}
        </button>
        <button type="button" className={styles.actionBtn} onClick={onAddToPortfolio} disabled={added}>
          {added ? 'Added to Portfolio' : 'Add to Portfolio'}
        </button>
      </div>

      <div className={styles.modeRow}>
        {([
          ['recommendation', 'Recommendation', true],
          ['ibkr_paper', 'IBKR Paper', ibkrConfigured],
          ['tradier_paper', 'Tradier Paper', tradierConfigured],
          ['alpaca_paper', 'Alpaca Paper', alpacaConfigured],
        ] as Array<[ExecutionMode, string, boolean]>).map(([mode, label, ok]) => (
          <button key={mode} type="button"
            className={`${styles.modeBtn} ${execMode === mode ? styles.modeBtnActive : ''}`}
            disabled={!ok}
            title={!ok ? 'Not configured — Settings → Brokers' : undefined}
            onClick={() => setExecMode(mode)}>
            <Text size={12} weight={500}>{label}</Text>
          </button>
        ))}
      </div>

      {execMode !== 'recommendation' && (
        <div className={styles.actionRow}>
          <button type="button" className={styles.actionBtn} onClick={() => submit('LMT')} disabled={placingType !== null}>
            {placingType === 'LMT' ? 'Placing…' : `Limit @ $${card.strategy.entry_price}`}
          </button>
          <button type="button" className={styles.actionBtn} onClick={() => submit('MKT')} disabled={placingType !== null}>
            {placingType === 'MKT' ? 'Placing…' : 'Market Order'}
          </button>
        </div>
      )}

      {orderId && <Text size={12} tone="pass">Order placed — ID: {orderId}</Text>}
      {err && <Text size={12} tone="reject">{err}</Text>}
    </div>
  );
}
