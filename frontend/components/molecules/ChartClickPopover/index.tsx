'use client';
import { Text } from '@/components/primitives';
import styles from './ChartClickPopover.module.css';

interface Props {
  kind: 'alert' | 'buy';
  price: number;
  qty: number;
  onQty?: (n: number) => void;
  onConfirm: () => void;
  onCancel: () => void;
}
export default function ChartClickPopover({ kind, price, qty, onQty, onConfirm, onCancel }: Props) {
  return (
    <div className={styles.pop} role="dialog" aria-label={kind === 'alert' ? 'Set alert' : 'Paper buy'}>
      <Text size={12} weight={500}>{kind === 'alert' ? 'Set alert' : 'Paper buy'} @ ${price.toFixed(2)}</Text>
      {kind === 'buy' && (
        <label className={styles.qty}>
          <Text size={11} tone="dim">Shares</Text>
          <input type="number" min={1} value={qty} onChange={(e) => onQty?.(Math.max(1, Number(e.target.value) || 1))} />
        </label>
      )}
      <div className={styles.actions}>
        <button type="button" onClick={onCancel}>Cancel</button>
        <button type="button" onClick={onConfirm}>{kind === 'alert' ? 'Configure' : 'Buy'}</button>
      </div>
    </div>
  );
}
