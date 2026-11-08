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
 *     Final Recommendation above and are not submitted.
 */

import type { ReactNode } from 'react';
import { Text } from '@/components/primitives';
import type { LadderFallbackReason, SubmissionDraft, TargetBasis } from '@/lib/submissionDraft';
import styles from './SubmissionReview.module.css';

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

  return (
    <section
      aria-label="Submission review"
      className={styles.review}
      data-generation={generation}
      data-fingerprint={draft.fingerprint}
    >
      <div className={styles.header}>
        <Text size={13} weight={500}>Submission review</Text>
        <Text size={10} tone="dim">Draft generation {generation}</Text>
      </div>
      <Text size={11} tone="secondary">
        The values Track basket and the direct sends submit for this card, from the same request they send.
        Changing the contract, quantity, entry, an exit setting or the selection replaces this draft.
      </Text>
      {identity.spread && (
        <Text size={10} tone="caution">
          {identity.spread.name}: only the selected contract is submitted; the other legs are not part of this request.
        </Text>
      )}

      <Text size={11} weight={500}>Order and contract (execution inputs)</Text>
      <dl className={styles.list}>
        <Row label="Contract">{`${identity.contractLabel} · ${identity.optionSymbol}`}</Row>
        <Row label="Quantity">{`${quantity.contracts} contracts × 100 = ${quantity.shares} shares`}</Row>
        <Row label="Entry limit">{`${usd(entry.limitPrice)}/share · plan order type ${entry.planOrderType} · Place Limit posts it; Right Now — Market posts no limit`}</Row>
        <Row label="Entry basis sent">{entryBasis}</Row>
      </dl>

      <Text size={11} weight={500}>Actual exit settings (submitted)</Text>
      <dl className={styles.list}>
        <Row label="Stock stop">{stops.stockStop != null
          ? `${usd(stops.stockStop)} stock · ${stops.stockStopIsUserSet ? 'typed (absolute; not re-anchored)' : 'plan-derived (the server re-anchors it to the live price)'}`
          : 'Missing — sending is blocked until a stock stop is set'}</Row>
        <Row label="Premium stop">{premiumText}</Row>
        <Row label="Structural stop">{stops.structuralStop != null ? `${usd(stops.structuralStop)} stock (record)` : 'None attached'}</Row>
        <Row label="Max-loss override">{stops.maxLossOverride
          ? stops.maxLossOverride.mode === 'dollar' ? usd(stops.maxLossOverride.value) : pct(stops.maxLossOverride.value)
          : 'None'}</Row>
        <Row label="Time exit">{`${stops.timeExitDte} DTE — app-wide rule, not a per-position field`}</Row>
        <Row label="Arithmetic plan attached">{selection.exitPlanAttached
          ? `Yes — computed ${selection.exitPlanComputedAt ?? 'at an unknown time'}; its stop is a calculation result and is not applied`
          : 'No'}</Row>
      </dl>

      <Text size={11} weight={500}>Recorded selection (not applied to the settings)</Text>
      <dl className={styles.list}>
        <Row label="Method">{pick ? METHOD_LABEL[pick.method] ?? pick.method : 'Not selected — sending is blocked until one is chosen'}</Row>
        <Row label="Recorded stock target">{pick?.rowStockPrice != null ? `${usd(pick.rowStockPrice)} stock` : 'None sent'}</Row>
        <Row label="Recorded option target">{pick?.rowOptionPrice != null
          ? `${usd(pick.rowOptionPrice)}/share (record only — never a take-profit order)` : 'None'}</Row>
        <Row label="Judged on">{pick
          ? `${pick.stopBasis === 'premium' ? 'Premium stop' : 'Stock stop'} — a recorded basis; the stock-stop and premium-stop alerts both stay armed`
          : 'Not recorded'}</Row>
      </dl>

      <Text size={11} weight={500}>Target alert</Text>
      <dl className={styles.list}>
        <Row label="Intended basis">{intendedBasis(selection.targetBasis)}</Row>
        <Row label="Effective target alert">Unresolved until server review</Row>
        <Row label="Saved entry, quantity and premium-stop fraction">Unresolved until server review — the server re-quotes, applies the exposure check and derives the fraction at save</Row>
      </dl>
      {note && <Text size={10} tone={selection.targetBasis.kind === 'ladder_fallback' ? 'caution' : 'dim'}>{note}</Text>}

      <Text size={11} weight={500}>Destinations</Text>
      <dl className={styles.list}>
        <Row label="Track basket">{`Portfolio row only — no broker order · stored as ${identity.trackedContract}`}</Row>
        <Row label="Place Limit">{direct ? route(direct.limit) : 'Select a paper broker'}</Row>
        <Row label="Right Now — Market">{direct ? route(direct.market) : 'Select a paper broker'}</Row>
      </dl>
      <Text size={10} tone="dim">
        A direct send re-fetches the option quote when clicked; its entry basis and premium-stop fraction then use
        that quote, and this review refreshes to it. If the server reduces the quantity to fit exposure limits, the
        order is sent at the saved quantity.
      </Text>
      <Text size={10} tone="dim">
        Probabilities, times and estimated values in the Final Recommendation are calculation results; they are not submitted.
      </Text>
    </section>
  );
}
