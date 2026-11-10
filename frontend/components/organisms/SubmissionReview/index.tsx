'use client';

/**
 * #581 (TC-REVIEW-06) — the submission review.
 *
 * Renders ONE `SubmissionDraft` and nothing else: no reconstruction, no second
 * resolution of any field. The draft is built by `lib/submissionDraft.ts`, the
 * same builder Track basket and the direct sends stamp and submit, so what this
 * shows is the request that goes out.
 *
 * Four separations it keeps, deliberately:
 *   - execution inputs (sent) versus the recorded selection (sent as a record,
 *     never applied to the settings);
 *   - requested values versus server-resolved ones — the saved entry, the
 *     quantity after the exposure check, the premium-stop fraction against the
 *     saved entry and the effective target alert are labelled unresolved until
 *     the server review (#582) supplies them;
 *   - the existing fallback rule for the selection, stated from the request
 *     (`services/picked_method.py` `seed_tp_from_pick`), never a promise of an
 *     option-price take-profit order;
 *   - calculation results (probabilities, times, estimated values) stay in the
 *     selected-target review above and are not submitted.
 *
 * #609 (TC-ALIGN-06) — destination-first: three visible groups (destination
 * and request; the actual position settings; the recorded decision and target
 * alert), then ONE native closed disclosure for the draft generation, the
 * attached-plan provenance and the long resolution explanations. Every
 * warning, refusal and provisional / unresolved label stays visible.
 */

import type { ReactNode } from 'react';
import { Text } from '@/components/primitives';
import type { LadderFallbackReason, SubmissionDraft, TargetBasis } from '@/lib/submissionDraft';
import styles from './SubmissionReview.module.css';
import disclosure from '@/styles/disclosure.module.css';

const METHOD_LABEL: Record<string, string> = {
  ladder: 'Ladder', arithmetic: 'Arithmetic', monte_carlo: 'Monte Carlo', barrier_race: 'Barrier Race',
};

const usd = (x: number) => `$${x.toFixed(2)}`;
const pct = (x: number) => `${Number((x * 100).toFixed(2))}%`;

const LADDER_RULE = 'Under the existing server rule the target alert starts on the live first Ladder target.';
const NO_TP_ORDER = 'The option premium is recorded only; no option-price take-profit order is placed.';

const FALLBACK_TEXT: Record<LadderFallbackReason, string> = {
  no_row: `No target row is recorded, so no stock-price target is sent. ${LADDER_RULE}`,
  mc_unreachable: `This Monte Carlo target has no stock-price equivalent (not reachable), so no stock-price target is sent. ${LADDER_RULE} ${NO_TP_ORDER}`,
  barrier_race: `Barrier Race rows carry an option premium and no stock level, so no stock-price target is sent. ${LADDER_RULE} ${NO_TP_ORDER}`,
  arithmetic_no_plan: `No Arithmetic plan is attached to this submission, so the recorded target cannot be mapped to an R row. ${LADDER_RULE}`,
  arithmetic_unmatched: `No row of the attached Arithmetic plan is within a cent of the recorded target, so it cannot be mapped to an R row. ${LADDER_RULE}`,
  arithmetic_ambiguous: `Rows of the attached Arithmetic plan with different R multiples match the recorded target equally, so it cannot be mapped to one R row. ${LADDER_RULE}`,
  arithmetic_beyond: `Only the first two Arithmetic rows have target-alert slots and this row is beyond them. ${LADDER_RULE}`,
};

function intendedBasis(b: TargetBasis): string {
  switch (b.kind) {
    case 'no_pick': return 'No method recorded';
    case 'ladder_live': return 'Live Ladder — follows the first Ladder target; no fixed price is stored';
    case 'requested_stock_level':
      return b.method === 'arithmetic'
        ? `Arithmetic ${b.rrRatio}:1 row at ${usd(b.stockPrice)} stock (requested)`
        : `Monte Carlo stock level ${usd(b.stockPrice)} (requested)`;
    case 'ladder_fallback': return 'Live Ladder fallback';
  }
}

function basisNote(b: TargetBasis): string | null {
  if (b.kind === 'ladder_fallback') return FALLBACK_TEXT[b.reason];
  if (b.kind === 'requested_stock_level') {
    return 'The server decides the effective alert price when it saves the position; until then it is not confirmed. '
      + 'An Arithmetic row the server cannot map falls back to the live first Ladder target.';
  }
  if (b.kind === 'no_pick') return 'Sending stays blocked until a method is chosen.';
  return null;
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className={styles.row}>
      <dt className={styles.label}>{label}</dt>
      <dd className={styles.value}>{children}</dd>
    </div>
  );
}

export interface SubmissionReviewProps {
  draft: SubmissionDraft;
  /** The page's generation for this draft (a new one per distinct fingerprint). */
  generation: number;
}

export function SubmissionReview({ draft, generation }: SubmissionReviewProps) {
  const { identity, quantity, entry, stops, selection, direct } = draft;
  const pick = selection.pick;
  const premium = stops.premiumStop;
  const premiumText = premium.kind === 'global'
    ? `Global ${pct(premium.globalPct)} of the saved entry — no dollar amount sent; the server resolves it against the fill`
    : premium.trackingFraction != null
      ? `${usd(premium.dollar)}/share pinned · ${pct(premium.trackingFraction)} of the ${usd(entry.trackingEntryPrice)}/share entry basis`
        + (premium.directFraction != null && premium.directFraction !== premium.trackingFraction
          ? ` (direct send: ${pct(premium.directFraction)} of ${usd(entry.directEntryPrice)}/share)` : '')
      : `${usd(premium.dollar)}/share pinned · no fraction sent (the premium is too small to carry one)`;
  const entryBasis = `${usd(entry.trackingEntryPrice)}/share · ${entry.entryPriceSource}`
    + (entry.directEntryPrice !== entry.trackingEntryPrice ? ` (direct send: ${usd(entry.directEntryPrice)}/share)` : '')
    + ' — provisional; the server re-quotes at save (not a fill)';
  const route = (r: NonNullable<typeof direct>['limit']) => r.blocked
    ? `${direct!.brokerLabel} · refused before sending: ${r.blocked}`
    : `${direct!.brokerLabel} · BUY to open ${r.order.quantity} × ${r.order.option_symbol} · ${r.order.order_type}`
      + `${r.order.limit_price != null ? ` ${usd(r.order.limit_price)}` : ''} · ${r.order.tif}`;
  const note = basisNote(selection.targetBasis);

  const expiry = identity.expiry && identity.expiry.trim() !== '' ? identity.expiry : null;
  const expiryText = expiry
    ? `${expiry}${identity.dte != null ? ` · ${identity.dte} DTE` : ''}`
    : `Not supplied${draft.tracking.expiry ? ` — Track basket stores ${draft.tracking.expiry}, derived from the DTE` : ''}`;
  const fallbackNote = note && selection.targetBasis.kind !== 'requested_stock_level';

  return (
    <section
      aria-label="Submission review"
      className={styles.review}
      data-generation={generation}
      data-fingerprint={draft.fingerprint}
    >
      <div className={styles.header}>
        <Text size={13} weight={500}>Submission review</Text>
        <Text size={11} tone="secondary">What Track basket and the direct sends submit for this card</Text>
      </div>
      {identity.spread && (
        <Text size={12} tone="caution">
          {identity.spread.name}: only the selected contract is submitted; the other legs are not part of this request.
        </Text>
      )}

      <div role="group" aria-label="Destination and request" className={styles.group} data-review-group="destination">
        <Text size={11} weight={500}>Destination &amp; request</Text>
        <dl className={styles.list}>
          <Row label="Track basket">{`Portfolio row only — no broker order · stored as ${identity.trackedContract}`}</Row>
          <Row label="Place Limit">{direct ? route(direct.limit) : 'Select a paper broker'}</Row>
          <Row label="Right Now — Market">{direct ? route(direct.market) : 'Select a paper broker'}</Row>
          <Row label="Contract">{`${identity.contractLabel} · ${identity.optionSymbol}`}</Row>
          <Row label="Expiry">{expiryText}</Row>
          <Row label="Quantity">{`${quantity.contracts} contracts × 100 = ${quantity.shares} shares`}</Row>
          <Row label="Entry limit">{`${usd(entry.limitPrice)}/share · plan order type ${entry.planOrderType} · Place Limit posts it; Right Now — Market posts no limit`}</Row>
          <Row label="Entry basis sent">{entryBasis}</Row>
          <Row label="Saved entry, quantity and premium-stop fraction">Unresolved until server review — the server re-quotes, applies the exposure check and derives the fraction at save</Row>
        </dl>
      </div>

      <div role="group" aria-label="Position settings" className={styles.group} data-review-group="settings">
        <Text size={11} weight={500}>Position settings · actual, submitted, distinct from model results</Text>
        <dl className={styles.list}>
          <Row label="Stock stop">{stops.stockStop != null
            ? `${usd(stops.stockStop)} stock · ${stops.stockStopIsUserSet ? 'typed (absolute; not re-anchored)' : 'plan-derived (the server re-anchors it to the live price)'}`
            : 'Missing — sending is blocked until a stock stop is set'}</Row>
          <Row label="Premium stop">{premiumText}</Row>
          <Row label="Time-exit alert">{`≤${stops.timeExitDte} days to expiry — an alert, not a close; app-wide rule, not a per-position field`}</Row>
          <Row label="Structural stop">{stops.structuralStop != null ? `${usd(stops.structuralStop)} stock (record)` : 'None attached'}</Row>
          <Row label="Max-loss override">{stops.maxLossOverride
            ? stops.maxLossOverride.mode === 'dollar' ? usd(stops.maxLossOverride.value) : pct(stops.maxLossOverride.value)
            : 'None'}</Row>
        </dl>
        <Text size={11} tone="secondary">
          These are in-app alert settings on the Portfolio row. No protective stop-loss or take-profit order is sent to a broker.
        </Text>
      </div>

      <div role="group" aria-label="Target alert basis" className={styles.group} data-review-group="target">
        <Text size={11} weight={500}>Recorded decision &amp; target alert (the selection is not applied to the settings)</Text>
        <dl className={styles.list}>
          <Row label="Method">{pick ? METHOD_LABEL[pick.method] ?? pick.method : 'Not selected — sending is blocked until one is chosen'}</Row>
          <Row label="Recorded stock target">{pick?.rowStockPrice != null ? `${usd(pick.rowStockPrice)} stock` : 'None sent'}</Row>
          <Row label="Recorded option target">{pick?.rowOptionPrice != null
            ? `${usd(pick.rowOptionPrice)}/share (record only — never a take-profit order)` : 'None'}</Row>
          <Row label="Judged on">{pick
            ? `${pick.stopBasis === 'premium' ? 'Premium stop' : 'Stock stop'} — a recorded basis; the stock-stop and premium-stop alerts both stay armed`
            : 'Not recorded'}</Row>
          <Row label="Intended basis">{intendedBasis(selection.targetBasis)}</Row>
          <Row label="Effective target alert">Unresolved until server review</Row>
        </dl>
        {fallbackNote && <Text size={12} tone={selection.targetBasis.kind === 'ladder_fallback' ? 'caution' : 'secondary'}>{note}</Text>}
      </div>

      <details className={`${styles.details} ${disclosure.disclosureRow}`} data-review-details>
        <summary>Technical details and provenance</summary>
        <div className={styles.detailsBody}>
          <Text size={12} tone="secondary">{`Draft generation ${generation}`}</Text>
          <Text size={12} tone="secondary">
            The values Track basket and the direct sends submit for this card, from the same request they send.
            Changing the contract, quantity, entry, an exit setting or the selection replaces this draft.
          </Text>
          <dl className={styles.list}>
            <Row label="Arithmetic plan attached">{selection.exitPlanAttached
              ? `Yes — computed ${selection.exitPlanComputedAt ?? 'at an unknown time'}; its stop is a calculation result and is not applied`
              : 'No'}</Row>
          </dl>
          {note && !fallbackNote && <Text size={12} tone="secondary">{note}</Text>}
          <Text size={12} tone="secondary">
            A direct send re-fetches the option quote when clicked; its entry basis and premium-stop fraction then use
            that quote, and this review refreshes to it. If the server reduces the quantity to fit exposure limits, the
            order is sent at the saved quantity.
          </Text>
          <Text size={12} tone="secondary">
            Probabilities, times and estimated values in “Your selected target” above are calculation results; they are not submitted.
          </Text>
        </div>
      </details>
    </section>
  );
}

/** Concise material notices remain visible when the inline request detail is closed.
 * Destination reviews still render their complete authoritative review separately. */
export function SubmissionReviewWarnings({ draft }: { draft: SubmissionDraft }) {
  const { identity, selection, stops, direct } = draft;
  const note = basisNote(selection.targetBasis);
  return <div className={styles.notices} data-submission-notices>
    <Text size={12}>Entry basis is provisional — the server re-quotes at save; saved entry, quantity, premium-stop fraction and effective target alert remain unresolved until server review. Not a fill.</Text>
    <Text size={12}>Exit settings are in-app alerts; no protective stop-loss or take-profit order is sent to a broker.</Text>
    {identity.spread && <Text size={12} tone="caution">{identity.spread.name}: only the selected contract is submitted; the other legs are not part of this request.</Text>}
    {stops.stockStop == null && <Text size={12} tone="reject">Missing — sending is blocked until a stock stop is set</Text>}
    {note && selection.targetBasis.kind !== 'requested_stock_level' && <Text size={12} tone={selection.targetBasis.kind === 'ladder_fallback' ? 'caution' : 'reject'}>{note}</Text>}
    {direct?.limit.blocked && <Text size={12} tone="reject">{direct.brokerLabel} · Place Limit refused before sending: {direct.limit.blocked}</Text>}
    {direct?.market.blocked && <Text size={12} tone="reject">{direct.brokerLabel} · Right Now — Market refused before sending: {direct.market.blocked}</Text>}
  </div>;
}
