'use client';

/**
 * #583 (TC-REVIEW-08) — the destination-specific review of ONE direct send.
 *
 * It renders the captured broker request (`lib/brokerReview.ts`
 * `captureBrokerRequest`) and the server's resolution of the row the save will
 * store (#582 preview), and nothing it reconstructs: the readable rows and the
 * "Exact request" JSON are the same object the confirmation posts.
 *
 * What it keeps apart, deliberately:
 *   - the request (sent as shown) from estimates (market price, outlay) that
 *     execution decides;
 *   - the tracked entry (a save-time quote) from a fill, which no response
 *     reports;
 *   - in-app stop / target alerts from broker orders: only the one opening
 *     order is sent.
 *
 * #609 (TC-ALIGN-06) — destination-first: the destination and request, the
 * saved row's position settings (with the ≤3 DTE time-exit alert) and the
 * target-alert basis are visible groups; mode, time in force and the exact
 * request JSON sit in one closed disclosure. The warnings stay visible.
 */

import { Text } from '@/components/primitives';
import type { CapturedBrokerRequest } from '@/lib/brokerReview';
import { brokerModeOf, confirmLabelFor, orderTypeText } from '@/lib/brokerReview';
import type { ReviewLine } from '@/lib/trackingReview';
import { TIME_STOP_DTE } from '@/lib/alertEngine';
import styles from './BrokerOrderReview.module.css';

export interface BrokerOrderReviewData {
  /** The human contract label. */
  label: string;
  /** The contract's supplied expiry (YYYY-MM-DD), or null when it has none. */
  expiry: string | null;
  brokerLabel: string;
  /** The account id entered in Settings → Brokers, or null when none is. */
  account: string | null;
  /** The captured request: what the confirmation posts, unchanged. */
  request: Readonly<CapturedBrokerRequest>;
  /** The quantity the card asked for (the request carries the server's). */
  requestedQuantity: number;
  /** The writer's reason when the server resolved another quantity. */
  quantityNote: string | null;
  /** The live mid probed for this review, or null without a confirmed live quote. */
  marketMid: number | null;
  /** The entry the save will store (the server's save-time quote). */
  savedEntry: number;
  /** Requested vs server-resolved settings (#582 `reviewLines`). */
  lines: ReviewLine[];
  /** Set after a 412: the lines the new server resolution changed. */
  changedSinceReview: string[] | null;
}

interface Props {
  data: BrokerOrderReviewData;
  /** Material fields changed since the review; non-empty blocks the send. */
  stale: string[];
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  onRefresh: () => void;
}

const money = (x: number) => `$${x.toFixed(2)}`;
const contracts = (n: number) => `${n} contract${n === 1 ? '' : 's'}`;

/** The server-resolved rows, by group; contract and quantity are in the request rows. */
const REQUEST_LINES = new Set(['entry', 'value']);
const SETTING_LINES = new Set(['stop', 'structuralStop', 'premiumStop']);
const TARGET_LINES = new Set(['targets', 'targetAlert']);
const SETTING_LABEL: Record<string, string> = {
  entry: 'Tracked entry (quote estimate, not a fill)',
  value: 'Est. position value (estimate)',
};
const STALE_LABEL: Record<string, string> = {
  contract: 'contract', broker: 'broker', plan: 'plan', quantity: 'quantity', limitPrice: 'limit price',
  stockStop: 'stock stop', stockStopIsUserSet: 'stock stop', structuralStop: 'structural stop',
  premiumStopDollar: 'premium stop', premiumStopPct: 'premium stop', maxLossOverride: 'max-loss override',
  exitPlan: 'exit plan', targets: 'targets', pickedMethod: 'method pick', pickedRowStockPrice: 'method pick',
  pickedRowOptionPrice: 'method pick', pickedStopBasis: 'method pick', pickedAt: 'method pick',
  trackingEntryPrice: 'entry basis', directEntryPrice: 'entry basis', request: 'request',
};

export function BrokerOrderReview({ data, stale, busy, onConfirm, onCancel, onRefresh }: Props) {
  const req = data.request;
  const isLimit = req.order_type === 'LMT';
  const staleText = [...new Set(stale.map((s) => STALE_LABEL[s] ?? s))].join(', ');
  const outlay = isLimit
    ? `Up to ${money(req.quantity * (req.limit_price ?? 0) * 100)} — ${req.quantity} × limit × 100; a buy limit fills at or below it, if at all (estimate)`
    : `About ${money(req.quantity * data.savedEntry * 100)} at the tracked quote — the market fill is unknown until execution (estimate)`;
  const resolved = (keys: Set<string>) => data.lines.filter((l) => keys.has(l.key)).map((l) => (
    <div key={l.key} className={styles.row}>
      <dt className={styles.label}>{SETTING_LABEL[l.key] ?? l.label}</dt>
      <dd className={styles.value}>
        {l.effective}
        {l.adjusted ? ` (requested ${l.requested}${l.note ? ` — ${l.note}` : ''})` : ''}
      </dd>
    </div>
  ));
  return (
    <section role="region" aria-label="Broker order review" className={styles.review}>
      <Text size={13} weight={500}>{`Review before sending to ${data.brokerLabel}`}</Text>

      <div role="group" aria-label="Destination and request" className={styles.group} data-review-group="destination">
        <Text size={12} weight={500}>Destination &amp; request</Text>
        <dl className={styles.list}>
          <div className={styles.row}><dt className={styles.label}>Destination</dt><dd className={styles.value}>{data.brokerLabel}</dd></div>
          <div className={styles.row}>
            <dt className={styles.label}>Account</dt>
            <dd className={styles.value}>
              {data.account
                ? `${data.account} — as entered in Settings → Brokers; the server sends with its stored credentials and does not echo the account`
                : 'Not set in Settings → Brokers; the server sends with its stored credentials'}
            </dd>
          </div>
          <div className={styles.row}><dt className={styles.label}>Contract</dt><dd className={styles.value}>{`${data.label} · ${req.option_symbol}`}</dd></div>
          <div className={styles.row}><dt className={styles.label}>Expiry</dt><dd className={styles.value}>{data.expiry ?? 'Not supplied'}</dd></div>
          <div className={styles.row}><dt className={styles.label}>Action</dt><dd className={styles.value}>{`${req.action} to ${req.effect === 'OPEN' ? 'open' : 'close'}`}</dd></div>
          <div className={styles.row}>
            <dt className={styles.label}>Quantity</dt>
            <dd className={styles.value}>
              {req.quantity === data.requestedQuantity
                ? contracts(req.quantity)
                : `${contracts(req.quantity)} (requested ${data.requestedQuantity}${data.quantityNote ? ` — ${data.quantityNote}` : ''})`}
            </dd>
          </div>
          <div className={styles.row}><dt className={styles.label}>Order type</dt><dd className={styles.value}>{orderTypeText(req)}</dd></div>
          <div className={styles.row}>
            <dt className={styles.label}>Limit price</dt>
            <dd className={styles.value}>
              {isLimit && req.limit_price != null ? money(req.limit_price) : 'None — market order; fills at the market price, unknown until execution'}
            </dd>
          </div>
          <div className={styles.row}>
            <dt className={styles.label}>Market price (estimate)</dt>
            <dd className={styles.value}>{data.marketMid != null ? `Live mid ${money(data.marketMid)} at review time` : 'No confirmed live quote at review time'}</dd>
          </div>
          <div className={styles.row}><dt className={styles.label}>Premium outlay (estimate)</dt><dd className={styles.value}>{outlay}</dd></div>
          {resolved(REQUEST_LINES)}
        </dl>
      </div>

      <div role="group" aria-label="Position settings" className={styles.group} data-review-group="settings">
        <Text size={12} weight={500}>Position settings · saved row, as the server resolves it</Text>
        <dl className={styles.list}>
          {resolved(SETTING_LINES)}
          <div className={styles.row}>
            <dt className={styles.label}>Time-exit alert</dt>
            <dd className={styles.value}>{`≤${TIME_STOP_DTE} days to expiry — an alert, not a close`}</dd>
          </div>
        </dl>
        <Text size={11} tone="secondary">
          These stops and the target alert below are in-app alerts on the saved Portfolio row. No stop-loss or take-profit order is sent to the broker — only this one opening order.
        </Text>
      </div>

      <div role="group" aria-label="Target alert basis" className={styles.group} data-review-group="target">
        <Text size={12} weight={500}>Target alert basis</Text>
        <dl className={styles.list}>
          {resolved(TARGET_LINES)}
        </dl>
      </div>

      {data.changedSinceReview && (
        <Text size={12} tone="caution">
          {`The server values changed since your review — nothing was saved and no order was sent${data.changedSinceReview.length ? ` (${data.changedSinceReview.join(', ')})` : ''}. Check the values above and confirm again.`}
        </Text>
      )}
      {stale.length > 0 && (
        <Text size={12} tone="reject">
          {`Changed since this review: ${staleText}. Nothing will be sent until you refresh the review.`}
        </Text>
      )}

      <details className={styles.exact} data-review-details>
        <summary>Technical details · exact broker request</summary>
        <dl className={`${styles.list} ${styles.detailsList}`}>
          <div className={styles.row}><dt className={styles.label}>Mode</dt><dd className={styles.value}>{brokerModeOf(req.broker)}</dd></div>
          <div className={styles.row}><dt className={styles.label}>Time in force</dt><dd className={styles.value}>{req.tif}</dd></div>
        </dl>
        <pre data-testid="broker-request" className={styles.pre}>{JSON.stringify(req)}</pre>
      </details>

      <div className={styles.actions}>
        <button type="button" className={styles.confirm} onClick={onConfirm} disabled={busy || stale.length > 0}>
          {confirmLabelFor(data.brokerLabel, req)}
        </button>
        {stale.length > 0 && (
          <button type="button" className={styles.secondary} onClick={onRefresh} disabled={busy}>Refresh review</button>
        )}
        <button type="button" className={styles.secondary} onClick={onCancel} disabled={busy}>Cancel</button>
      </div>
    </section>
  );
}
