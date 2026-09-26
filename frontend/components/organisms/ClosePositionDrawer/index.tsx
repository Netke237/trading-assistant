// frontend/components/organisms/ClosePositionDrawer/index.tsx
'use client';

/*
 * ClosePositionDrawer — sell/close UI for one portfolio position.
 * - Partial sells: qty defaults to full, capped at contracts held.
 * - Exit price pre-filled with the live current price, fully editable.
 * - Realized P&L preview updates live.
 * - "Also send to broker" is intentionally DISABLED (coming soon), mirroring
 *   the Step 7 Send-basket-to-broker feature that is wired but not yet live.
 */

import { useEffect, useState } from 'react';
import { Text, Data } from '@/components/primitives';
import type { PortfolioPosition } from '@/types/domain';
import { positionMultiplier } from '@/lib/risk';
import styles from './ClosePositionDrawer.module.css';

interface Props {
  position: PortfolioPosition;
  onCancel: () => void;
  onConfirm: (opts: { qtyToClose: number; exitPrice: number; exitDate: string }) => void;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export function ClosePositionDrawer({ position, onCancel, onConfirm }: Props) {
  const held = position.contracts ?? 1;
  const [qty, setQty] = useState<number>(held);
  const [exitPrice, setExitPrice] = useState<number>(position.currentPrice || position.entryPrice);
  const [exitDate, setExitDate] = useState<string>(todayIso());
  // The row can change under an open dialog: a close that hit 'not found'
  // re-saves the position, and since STOCK-SENDS-SAVE-FIRST-THEN-REAL-SHARES
  // that re-save can be booked SMALLER (stock code round 3, C1). Re-seed the
  // quantity from the row, or the preview and the next confirm keep the old
  // size -- a close the user did not approve.
  useEffect(() => { setQty(held); }, [held, position.entryPrice]);

  // Short *stock* positions profit when price falls — flip the delta's sign for
  // those. Options are never flipped: 'Bearish' on an option position just labels
  // a bought put (this app never writes/sells options to open), which is still a
  // long position that profits when its premium rises, same as a bought call.
  const isShortStock = position.direction === 'Bearish' && position.contract.endsWith('|STOCK');
  // Deriving both dollar and pct from this one signed value keeps them from
  // drifting into a contradictory "+$500 (-3.2%)" display for a profitable short close.
  const priceDelta = isShortStock
    ? position.entryPrice - exitPrice
    : exitPrice - position.entryPrice;
  const realizedDollar = Math.round(priceDelta * positionMultiplier(position) * qty);
  const realizedPct = position.entryPrice ? (priceDelta / position.entryPrice) * 100 : 0;
  const tone = realizedDollar > 0 ? 'pass' : realizedDollar < 0 ? 'reject' : undefined;

  return (
    <div className={styles.drawer}>
      <div className={styles.header}>
        <Text size={12} weight={400}>Close {position.contract}</Text>
        <button type="button" className={styles.close} onClick={onCancel} aria-label="Cancel close">×</button>
      </div>

      <div className={styles.grid}>
        <label className={styles.field}>
          <Text size={11} tone="secondary">Contracts to sell (of {held})</Text>
          <input
            type="number" min={1} max={held} step={1} className={styles.input}
            value={qty}
            onChange={(e) => setQty(Math.max(1, Math.min(held, Math.round(Number(e.target.value) || 1))))}
            aria-label="Contracts to sell"
          />
        </label>

        <label className={styles.field}>
          <Text size={11} tone="secondary">Exit price (per contract)</Text>
          <input
            type="number" min={0} step={0.05} className={styles.input}
            value={exitPrice}
            onChange={(e) => setExitPrice(Math.max(0, Number(e.target.value) || 0))}
            aria-label="Exit price"
          />
          <Text size={10} tone="dim">Pre-filled with the live price — edit to match your broker fill.</Text>
        </label>

        <label className={styles.field}>
          <Text size={11} tone="secondary">Exit date</Text>
          <input
            type="date" className={styles.input}
            value={exitDate}
            onChange={(e) => setExitDate(e.target.value || todayIso())}
            aria-label="Exit date"
          />
        </label>

        <div className={styles.field}>
          <Text size={11} tone="secondary">Realized P&L</Text>
          <Data size={16} weight={500} tone={tone}>
            {realizedDollar > 0 ? '+' : ''}${realizedDollar}
            {'  '}({realizedPct > 0 ? '+' : ''}{realizedPct.toFixed(1)}%)
          </Data>
        </div>
      </div>

      <label className={styles.brokerStub} title="Coming soon — broker routing is not active yet">
        <input type="checkbox" disabled aria-label="Also send close to broker (coming soon)" />
        <Text size={11} tone="dim">Also send to broker (coming soon)</Text>
      </label>

      <div className={styles.footer}>
        <button type="button" className={styles.btn} onClick={onCancel}>Cancel</button>
        <button
          type="button"
          className={`${styles.btn} ${styles.btnPrimary}`}
          onClick={() => onConfirm({ qtyToClose: qty, exitPrice, exitDate })}
        >
          {qty >= held ? 'Close position' : `Sell ${qty} of ${held}`}
        </button>
      </div>
    </div>
  );
}
