'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Title, Text, Data } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { ConfidenceBadge } from '@/components/atoms/ConfidenceBadge';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { ScanFunnel } from '@/components/organisms/ScanFunnel';
import { backtestGateTooltip, winRateTooltip } from '@/lib/statusTooltips';
import type { PositionCardData } from '@/types/stockDomain';
import styles from './page.module.css';

function BacktestRow({ c, selected, onClick }: { c: PositionCardData; selected: boolean; onClick: () => void }) {
  const bt = c.backtest;
  const pass = bt.passes_gate;
  const minTrades = useScanParamsStore((s) => s.btMinTrades);
  const minWinRate = useScanParamsStore((s) => s.btMinWinRate);
  return (
    <button className={`${styles.row} ${selected ? styles.rowSelected : ''} ${!pass ? styles.rowFail : ''}`}
      onClick={onClick}>
      <Data size={12} weight={500}>{c.symbol}</Data>
      <Text size={11}>{c.backtest.summary_text.split('·')[0]?.trim()}</Text>
      <Data
        size={12}
        tone={bt.win_rate >= 0.5 ? 'pass' : bt.win_rate >= 0.45 ? 'caution' : 'reject'}
        title={winRateTooltip(bt.win_rate, 0.5, 0.45)}
      >
        {(bt.win_rate * 100).toFixed(0)}%
      </Data>
      <Data size={12}>{bt.n_trades}</Data>
      <Data size={12} tone={bt.total_return_pct >= 0 ? 'pass' : 'reject'}>
        {bt.total_return_pct.toFixed(1)}%
      </Data>
      <Data size={12} tone="reject">{Math.abs(bt.max_drawdown_pct).toFixed(1)}%</Data>
      <Data
        size={12}
        tone={
          c.sector_rs_pct == null ? 'secondary'
          : c.sector_rs_pct > 1   ? 'pass'
          : c.sector_rs_pct < -1  ? 'reject'
          : 'secondary'
        }
      >
        {c.sector_rs_pct != null
          ? `${c.sector_rs_pct > 0 ? '+' : ''}${c.sector_rs_pct.toFixed(1)}%`
          : '—'}
      </Data>
      <Text
        size={11}
        tone={
          c.next_event_days == null   ? 'dim'
          : c.next_event_days <= 3    ? 'reject'
          : c.next_event_days <= 14   ? 'caution'
          : 'secondary'
        }
      >
        {c.next_event_days != null
          ? `${(c.next_event_label ?? 'E')[0].toUpperCase()} ${c.next_event_days}d`
          : '—'}
      </Text>
      <ConfidenceBadge confidence={c.confidence} title={c.confidence_text ?? undefined} />
      <StatusBadge
        status={pass ? 'PASS' : 'REJECT'}
        tooltip={backtestGateTooltip({ passes: pass, winRate: bt.win_rate, nTrades: bt.n_trades, expectancy: bt.expectancy, minWinRate, minTrades })}
      />
    </button>
  );
}

export default function Step6BacktestPage() {
  const result = useScanStore((s) => s.stockScanResult);
  const setSelectedSymbol = useScanStore((s) => s.setSelectedSymbol);
  const eventFilter = useScanParamsStore((s) => s.eventFilter);
  const [selected, setSelected] = useState<string | null>(result?.candidates[0]?.symbol ?? null);
  const router = useRouter();

  if (!result) {
    return (
      <div className={styles.main}>
        <Text size={13} tone="dim">No stock scan result. Go back to Step 5 and run a scan.</Text>
      </div>
    );
  }

  // No candidate can fail passes_gate — stock_scan.py rejects those with a
  // "backtest gate:" reason before they ever become candidates — so this is a
  // no-op kept only because the header reads "N failed" off it.
  const passing = result.candidates.filter((c) => c.backtest.passes_gate);
  const filteredPassing = passing.filter((c) => {
    const days = c.next_event_days;
    if (eventFilter === 'avoid')          return days == null || days > 7;
    if (eventFilter === 'only_pre_event') return days != null && days <= 21;
    return true;
  });
  const rejected = result.rejected;

  function proceedWith(symbol: string) {
    setSelected(symbol);
    setSelectedSymbol(symbol);   // carry the choice to Step 7
    router.push('/screener/step-7-position-card');
  }

  return (
    <div className={styles.main}>
      <div className={styles.header}>
        <Text size={11} tone="dim" weight={500}>STEP 6 OF 7</Text>
        <Title as="h1" size={24}>Backtest Gate</Title>
        <Text size={13} tone="secondary">
          {filteredPassing.length} candidates passed · {result.candidates.length - passing.length} failed ·
          {rejected.length} rejected before backtest
        </Text>
      </div>

      {result.pipeline && (
        <ScanFunnel mode="stock" pipeline={result.pipeline} />
      )}

      {/* The event filter hides rows AFTER everything the funnel counted, so
          without this the funnel's "Candidates N" sits above a shorter table
          with nothing accounting for the difference. */}
      {passing.length > filteredPassing.length && (
        <Text size={11} tone="caution">
          {passing.length - filteredPassing.length} of {passing.length} hidden by the event filter.
        </Text>
      )}

      <div className={styles.tableHeader}>
        <Text size={11} tone="dim">SYMBOL</Text>
        <Text size={11} tone="dim">SUMMARY</Text>
        <Text size={11} tone="dim">WIN %</Text>
        <Text size={11} tone="dim">TRADES</Text>
        <Text size={11} tone="dim">RETURN</Text>
        <Text size={11} tone="dim">MAX DD</Text>
        <Text size={11} tone="dim">VS SPX</Text>
        <Text size={11} tone="dim">EVENT</Text>
        <Text size={11} tone="dim">CONF</Text>
        <Text size={11} tone="dim">GATE</Text>
      </div>

      <div className={styles.tableBody}>
        {filteredPassing.map((c) => (
          <BacktestRow key={c.symbol} c={c}
            selected={selected === c.symbol}
            onClick={() => proceedWith(c.symbol)} />
        ))}
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
  );
}
