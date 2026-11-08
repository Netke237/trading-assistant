'use client';

/**
 * #583 (TC-REVIEW-08) — what a direct send's broker response actually said.
 *
 * The broker endpoints answer an order id, a status, the broker and whether
 * the result was deduplicated. They report no fill price and no filled
 * quantity, so those rows say "Unavailable"; an acceptance is never shown as a
 * fill, and the saved row's entry is labelled the tracking quote it is. Lines
 * come from `lib/brokerReview.ts` `outcomeLines`.
 */

import { outcomeLines, type DirectOrderOutcome } from '@/lib/brokerReview';
import styles from './BrokerOrderOutcome.module.css';

export function BrokerOrderOutcome({ outcome }: { outcome: DirectOrderOutcome }) {
  return (
    <section role="region" aria-label="Broker order outcome" className={styles.outcome}>
      <dl className={styles.list}>
        {outcomeLines(outcome).map((l) => (
          <div key={l.key} className={styles.row}>
            <dt className={styles.label}>{l.label}</dt>
            <dd className={`${styles.value} ${styles[l.tone]}`}>{l.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
