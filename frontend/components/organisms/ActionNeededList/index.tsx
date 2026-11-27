'use client';

/*
 * PORTFOLIO-ALERT-ACTION (#672, plan §4) — "Action needed" on the Portfolio
 * page. Replaces the stop-breach banners in their place: an item whose derived
 * breach is the stop or the structural stop keeps the banner's role="alert"
 * and its exact sentence. No dismiss button (as the banner). Renders nothing
 * when no position needs action. Items come from lib/actionNeeded.ts.
 *
 * "Close position…" only asks the page to open the existing manual
 * ClosePositionDrawer; nothing here places or prepares an order.
 */

import { useId } from 'react';
import { Text } from '@/components/primitives';
import type { ActionItem } from '@/lib/actionNeeded';
import styles from './ActionNeededList.module.css';

export interface ActionNeededListProps {
  items: readonly ActionItem[];
  onReview: (item: ActionItem) => void;
  onClose: (item: ActionItem) => void;
}

export function ActionNeededList({ items, onReview, onClose }: ActionNeededListProps) {
  const headingId = useId();
  if (items.length === 0) return null;
  return (
    <section className={styles.section} aria-labelledby={headingId}>
      <h2 id={headingId} className={styles.heading}>
        <Text size={13} weight={500}>{`Action needed (${items.length})`}</Text>
      </h2>
      <ul className={styles.list}>
        {items.map((item) => {
          const body = (
            <>
              <div className={styles.text}>
                {item.breachSentence !== null ? (
                  <Text size={13} tone="reject">{item.breachSentence}</Text>
                ) : (
                  <Text size={13}>{`${item.symbol} ${item.contractLabel}`}</Text>
                )}
                <ul className={styles.entries}>
                  {item.entries.map((e) => (
                    <li key={e.alertType} className={styles.entry}>
                      <Text size={12} tone="primary">{e.label}</Text>
                      <Text size={12} tone="secondary">{` — ${e.detail}`}</Text>
                    </li>
                  ))}
                </ul>
              </div>
              <div className={styles.actions}>
                <button type="button" className={styles.btn} onClick={() => onReview(item)}>
                  {`Review ${item.symbol}`}
                </button>
                <button type="button" className={styles.btn} onClick={() => onClose(item)}>
                  Close position…
                </button>
              </div>
            </>
          );
          const breach = item.breachSentence !== null;
          return (
            <li key={item.contract} className={breach ? styles.itemBreach : styles.item}>
              {breach ? <div role="alert" className={styles.row}>{body}</div> : <div className={styles.row}>{body}</div>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
