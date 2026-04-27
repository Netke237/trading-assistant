'use client';

/*
 * SendToBrokerDialog — modal launched from Step 7 Send button.
 *
 * Lists every pinned basket item with per-row quantity + an "Auto-send"
 * checkbox. Checked rows are sent to the (mock) broker; unchecked rows go
 * straight into the portfolio with source='manual'.
 */

import { useMemo, useState } from 'react';
import { Text, Data } from '@/components/primitives';
import type { TradeCardData } from '@/types/domain';
import styles from './SendToBrokerDialog.module.css';

export interface DraftOrder {
  card:      TradeCardData;
  contracts: number;
  autoSend:  boolean;
}

interface Props {
  cards:    TradeCardData[];
  onClose:  () => void;
  onSubmit: (orders: DraftOrder[]) => void;
}

interface RowState {
  contracts: number;
  autoSend:  boolean;
}

export function SendToBrokerDialog({ cards, onClose, onSubmit }: Props) {
  const [rows, setRows] = useState<Record<string, RowState>>(() =>
    Object.fromEntries(cards.map((c) => [c.symbol, { contracts: 1, autoSend: true }])),
  );

  const { autoCount, manualCount, estTotal } = useMemo(() => {
    let a = 0, m = 0, t = 0;
    for (const c of cards) {
      const r = rows[c.symbol] ?? { contracts: 1, autoSend: true };
      if (r.autoSend) a++; else m++;
      const mid = c.contractDetails?.mid ?? 0;
      t += mid * 100 * r.contracts;
    }
    return { autoCount: a, manualCount: m, estTotal: t };
  }, [cards, rows]);

  const patch = (sym: string, p: Partial<RowState>) =>
    setRows((r) => ({ ...r, [sym]: { ...(r[sym] ?? { contracts: 1, autoSend: true }), ...p } }));

  const submit = () => {
    const orders: DraftOrder[] = cards.map((c) => {
      const r = rows[c.symbol] ?? { contracts: 1, autoSend: true };
      return { card: c, contracts: Math.max(1, Math.round(r.contracts)), autoSend: r.autoSend };
    });
    onSubmit(orders);
  };

  return (
    <div className={styles.backdrop} onClick={onClose} role="presentation">
      <div
        className={styles.dialog}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Send basket to broker"
      >
        <header className={styles.header}>
          <div>
            <Text size={14} weight={600}>Send basket to broker</Text>
            <Text size={11} tone="secondary">
              Uncheck Auto-send for any contract you&apos;d rather place manually. Unchecked orders
              are still added to the portfolio, tagged MANUAL.
            </Text>
          </div>
          <button
            type="button"
            className={styles.close}
            onClick={onClose}
            aria-label="Close dialog"
          >
            ×
          </button>
        </header>

        <div className={styles.tableHead}>
          <Text size={10} tone="dim">SYMBOL</Text>
          <Text size={10} tone="dim">CONTRACT</Text>
          <Text size={10} tone="dim" className={styles.right}>MID</Text>
          <Text size={10} tone="dim">QTY</Text>
          <Text size={10} tone="dim" className={styles.right}>EST $</Text>
          <Text size={10} tone="dim">AUTO-SEND</Text>
        </div>

        <div className={styles.tableBody}>
          {cards.map((c) => {
            const r   = rows[c.symbol] ?? { contracts: 1, autoSend: true };
            const mid = c.contractDetails?.mid ?? 0;
            const est = mid * 100 * r.contracts;
            return (
              <div key={c.symbol} className={styles.row}>
                <Data size={13} weight={500}>{c.symbol}</Data>
                <Text size={12}>{c.contract}</Text>
                <Data size={12} className={styles.right}>${mid.toFixed(2)}</Data>
                <input
                  type="number"
                  min={1}
                  step={1}
                  value={r.contracts}
                  className={styles.qtyInput}
                  onChange={(e) => patch(c.symbol, { contracts: Math.max(1, Number(e.target.value) || 1) })}
                  aria-label={`Contracts for ${c.symbol}`}
                />
                <Data size={12} className={styles.right}>${Math.round(est).toLocaleString()}</Data>
                <label className={styles.autoCell}>
                  <input
                    type="checkbox"
                    checked={r.autoSend}
                    onChange={(e) => patch(c.symbol, { autoSend: e.target.checked })}
                    aria-label={`Auto-send ${c.symbol} to broker`}
                  />
                  <Text size={11} tone={r.autoSend ? 'pass' : 'caution'}>
                    {r.autoSend ? 'Auto' : 'Manual'}
                  </Text>
                </label>
              </div>
            );
          })}
        </div>

        <footer className={styles.footer}>
          <Text size={12} tone="secondary">
            {autoCount} auto · {manualCount} manual · Est total ${Math.round(estTotal).toLocaleString()}
          </Text>
          <div className={styles.actions}>
            <button type="button" className={styles.btn} onClick={onClose}>Cancel</button>
            <button
              type="button"
              className={`${styles.btn} ${styles.btnPrimary}`}
              onClick={submit}
              disabled={cards.length === 0}
            >
              Submit {cards.length} order{cards.length === 1 ? '' : 's'}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
