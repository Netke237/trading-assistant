import { Text, Data } from '@/components/primitives';
import type { PositionCardData } from '@/types/stockDomain';
import { useScanStore } from '@/lib/scanStore';
import styles from './StockPositionCard.module.css';

const number = (value: number | null | undefined, digits = 2, scale = 1, suffix = '') =>
  value != null && Number.isFinite(value) ? `${(value * scale).toFixed(digits)}${suffix}` : 'Unavailable';

export function PositionEvidence({ card, pickMissing, earningsVeto, ownership, checklistOnly = false }: {
  card: PositionCardData; pickMissing: boolean; earningsVeto: boolean; ownership?: string; checklistOnly?: boolean;
}) {
  const request = useScanStore(s => s.stockScanRequest);
  const bt = card.backtest;
  return <div className={checklistOnly ? undefined : styles.qualification} id={checklistOnly ? undefined : "qualification"}>
    {!checklistOnly && <><section className={styles.workspaceCard} aria-label="Stock Scorecard">
      <h3>Stock Scorecard</h3>
      <Text size={12}>Final verdict: {card.stock_status}</Text>
      <Data size={18}>{number(card.stock_score, 0)} / 100</Data>
      <Text size={11} tone="secondary">Stock score is a filter, not a probability of profit.</Text>
      {card.stock_explanation ? <>
        <Text size={11} tone="secondary">Scorer evidence before final caps: {card.stock_explanation.status}</Text>
        {Object.entries(card.stock_explanation.components).map(([key, c]) => <div key={key} className={styles.evidenceRow}>
          <Text size={12}>{c.name}</Text><Data size={12}>{c.measured ? number(c.raw_score, 0) : 'Unavailable'}</Data>
          <Text size={11} tone="secondary">weight {number(c.weight, 0, 100, '%')} · contribution {number(c.contribution)}</Text>
          <Text size={11} tone="secondary">{c.measured ? 'Measured' : 'Unmeasured'} · {c.status ?? 'Status unavailable'}</Text>
          {c.detail && Object.keys(c.detail).length > 0 && <details className={styles.factorDetails}><summary>Observations</summary>{Object.entries(c.detail).map(([name, value]) => <Text key={name} size={11} tone="secondary">{name}: {value == null ? 'Unavailable' : typeof value === 'object' ? JSON.stringify(value) : String(value)}</Text>)}</details>}
        </div>)}
      </> : <Text size={12} tone="dim">Scorer factors unavailable</Text>}
    </section>
    <section className={styles.workspaceCard} aria-label="Backtest evidence">
      <h3>Backtest evidence</h3>
      <div className={styles.evidenceGrid}>{[
        ['Win rate', number(bt.win_rate, 0, 100, '%')], ['Trades', number(bt.n_trades, 0)],
        ['Expectancy', number(bt.expectancy)], ['Return', number(bt.total_return_pct, 1, 1, '%')],
        ['Max DD', number(Math.abs(bt.max_drawdown_pct), 1, 1, '%')], ['Sharpe', number(bt.sharpe)],
        ['Confidence', number(card.confidence, 0, 1, '%')],
      ].map(([label, value]) => <div key={label}><Text size={11} tone="dim">{label}</Text><Data size={14}>{label === 'Win rate' ? `${value} win rate` : value}</Data></div>)}</div>
      <Text size={12}>{card.confidence_text ?? 'Confidence explanation unavailable'}</Text>
      <Text size={11} tone="secondary">{bt.summary_text}</Text>
      <Text size={11} tone="secondary">{request?.bt_min_trades != null && request.bt_min_win_rate != null
        ? `Scan thresholds: ≥ ${request.bt_min_trades} trades · ≥ ${number(request.bt_min_win_rate, 0, 100, '%')} win rate`
        : 'Scan thresholds unavailable'}</Text>
    </section>
    </>}
    {checklistOnly && <section className={styles.workspaceCard} aria-label="Pre-trade checklist">
      <h3>Pre-trade checklist</h3>
      {(card.gate_flags ?? []).map((flag, i) => <Text key={i} size={12}>{flag.gate}: {flag.status} · {flag.detail}</Text>)}
      {!card.gate_flags?.length && <Text size={12} tone="dim">Recorded gates unavailable</Text>}
      <Text size={12}>Recorded backtest: {bt.passes_gate ? 'PASS' : 'REJECT'}</Text>
      <Text size={12}>Final stock verdict: {card.stock_status}</Text>
      <Text size={12}>Earnings: {earningsVeto ? 'VETO' : card.earnings_days == null ? 'Unknown' : 'No current veto'}</Text>
      <Text size={12}>Fundamentals: {card.fundamentals ? `score ${card.fundamentals.score}` : 'Unavailable'}</Text>
      <Text size={12}>Method: {pickMissing ? 'Pick required' : 'Selected'}</Text>
      <Text size={12}>Execution: Unvalidated — broker execution blocked</Text>
      <Text size={12}>Save/send ownership: {ownership ?? 'Not claimed'}</Text>
      <Text size={11} tone="dim">Risk, exposure and daily limits</Text>
      <Text size={12} tone="caution">Pending server validation</Text>
    </section>}
  </div>;
}
