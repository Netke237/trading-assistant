import { Text, Data } from '@/components/primitives';
import type { PositionCardData } from '@/types/stockDomain';
import styles from './StockPositionCard.module.css';

const finite = (value: number | null | undefined): value is number =>
  value != null && Number.isFinite(value);
const display = (value: number | null | undefined, prefix = '', suffix = '') =>
  finite(value) ? `${prefix}${value.toFixed(2)}${suffix}` : 'Unavailable';

/** The scan's strategy ladder, never the generated or edited order rungs.
 * Original strategy data has no allocation field; the editable order's
 * sharesT1–3 must not be presented as original strategy allocations. */
export function InitialStrategyTargets({ card, shares }: { card: PositionCardData; shares: number }) {
  const { entry_price: entry, stop_price: stop } = card.strategy;
  const sign = card.direction === 'Bullish' ? 1 : card.direction === 'Bearish' ? -1 : null;
  const risk = sign != null && finite(entry) && finite(stop) ? sign * (entry - stop) : null;
  const targets = card.strategy.targets?.length ? card.strategy.targets : [card.strategy.target_price];
  return <section className={styles.workspaceCard} aria-label="Initial strategy targets" id="initial-targets">
    <h3>Initial strategy targets</h3>
    <Text size={12} tone="secondary">Source: scanned strategy · entry {display(entry, '$')} · stop {display(stop, '$')}</Text>
    <Text size={11} tone="secondary">Full exit scenarios before costs use the original strategy entry and {finite(shares) && shares >= 0 ? shares : 'unavailable'} entered shares. Each row exits the entire position; outcomes are alternatives and must not be added together.</Text>
    <div className={styles.initialTableWrap}>
      <table className={styles.initialTable}>
        <thead><tr>{['Target', 'Stock price', 'Reward / share', 'Return', 'R:R', 'Full position outcome'].map(label => <th key={label} scope="col"><Text size={11} tone="dim">{label}</Text></th>)}</tr></thead>
        <tbody>{targets.map((target, i) => {
          const reward = sign != null && finite(entry) && finite(target) ? sign * (target - entry) : null;
          const returnPct = reward != null && finite(entry) && entry > 0 ? reward / entry * 100 : null;
          const rr = reward != null && risk != null && risk > 0 ? reward / risk : null;
          const outcome = reward != null && finite(shares) && shares >= 0 ? reward * shares : null;
          return <tr key={i}>
            <th scope="row"><Text size={12}>T{i + 1}</Text></th>
            <td><Data size={14}>{display(target, '$')}</Data></td>
            <td><Data size={12}>{display(reward, '$')}</Data></td>
            <td><Data size={12}>{display(returnPct, '', '%')}</Data></td>
            <td><Data size={12}>{display(rr, '', '×')}</Data></td>
            <td><Data size={14}>{display(outcome, '$')}</Data></td>
          </tr>;
        })}</tbody>
      </table>
    </div>
    <Text size={11} tone="dim">Original target allocations unavailable</Text>
    {Object.keys(card.strategy.detail ?? {}).length > 0 && <details className={styles.factorDetails}>
      <summary>Strategy observations</summary>
      {Object.entries(card.strategy.detail).map(([key, value]) => <Text key={key} size={11} tone="secondary">{key}: {value == null ? 'Unavailable' : typeof value === 'object' ? JSON.stringify(value) : String(value)}</Text>)}
    </details>}
  </section>;
}
