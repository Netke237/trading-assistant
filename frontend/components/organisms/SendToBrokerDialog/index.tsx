'use client';

/*
 * SendToBrokerDialog — modal launched from Step 7 Send button.
 *
 * Lists every pinned basket item with a per-row quantity. Fix #5 (review, D6):
 * the basket places NO broker order. Every row is saved to the Portfolio as a
 * tracked position with source='manual'; to trade one, send it from its own
 * card. It used to offer an "Auto-send" checkbox and store 'broker' rows, which
 * made phantom positions that looked like fills.
 *
 * #582 (TC-REVIEW-07) — every row is REVIEWED BY THE SERVER before it can be
 * confirmed. The page's draft builder makes the exact tracking request at the
 * row's one-off quantity; `previewPosition` asks the server what it would
 * store for exactly that request (the writer's own resolution; nothing is
 * written), and the row shows requested against server-resolved values. A
 * quantity edit, a new live quote or any other change to the request makes a
 * new draft and a new review; a late answer for an older request is dropped.
 * Confirming hands the page the reviewed request and its fingerprint; a row
 * whose current resolution differs comes back review-required with the new
 * values, and must be confirmed again. Pinning only selected the candidates.
 */

import { contractKeyFor } from '@/lib/tradeCardOverride';
import { quoteWarning } from '@/lib/quoteWarning';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Text, Data } from '@/components/primitives';
import { useRiskStore } from '@/lib/riskStore';
import { previewPosition, usePortfolioStore } from '@/lib/portfolioStore';
import {
  checkTradeRisk,
  MISSING_INVALIDATION_MESSAGE, MISSING_INVALIDATION_TITLE,
  MISSING_METHOD_PICK_MESSAGE, MISSING_METHOD_PICK_TITLE,
} from '@/lib/risk';
import { stampPosition, type SubmissionDraft, type SubmissionStamps } from '@/lib/submissionDraft';
import { TIME_STOP_DTE } from '@/lib/alertEngine';
import {
  changedSince, resolvedValue, reviewLines,
  type ReviewedTrackingOrder, type TrackingPreview, type TrackingSubmitResult,
} from '@/lib/trackingReview';
import type { TradeCardData, RiskCheckResult, MaxLossOverride, MethodPick, PortfolioPosition } from '@/types/domain';
import styles from './SendToBrokerDialog.module.css';

export interface DraftOrder {
  card:      TradeCardData;
  contracts: number;
}

/** One row's server review, keyed by the draft fingerprint it covers. */
type RowReview =
  | { status: 'loading'; key: string }
  | { status: 'ready'; key: string; request: PortfolioPosition; preview: TrackingPreview; changed: string[] | null }
  | { status: 'error'; key: string; detail: string };

interface Props {
  cards:    TradeCardData[];
  quoteWarningsByContract?: Record<string, string | null>;
  /** Feature 7 — the page-level shared per-symbol contracts map (same one fed
   *  into TradeCard's `contracts` prop and read by the quick-order/auto-trade
   *  paths), used only to SEED this dialog's row state. Editing the quantity
   *  inside this dialog is a one-off override for that submission only — it
   *  deliberately does NOT write back to the shared map; the dialog reviews/
   *  finalizes a snapshot right before sending, not a place for live pre-trade
   *  state the rest of the page also reads from. */
  contractsBySymbol: Record<string, number>;
  /** Feature 5 — the page-level shared per-symbol max-loss override cache,
   *  sourced from the same `maxLossOverrideBySymbol` state TradeCard's
   *  Arithmetic card writes to. Read directly into `checkTradeRisk` below so
   *  this dialog's own risk check knows about an active override and doesn't
   *  force a spurious extra confirmation click for a trade the user already
   *  explicitly sized up under a raised budget. */
  overridesBySymbol: Record<string, MaxLossOverride | null>;
  /** PIECE 3 — the stop each card is actually SHOWING, resolved by the page
   *  through `invalidationFor` (the user's typed value when the Invalidation
   *  field is touched, else the card's own). Fed straight into
   *  `checkTradeRisk` so `missing_invalidation` judges the level that would be
   *  stored as `PortfolioPosition.stop`, not the card's stale one — which on a
   *  candidate restored from a pre-piece-3 scan session is null, and which the
   *  user can fix by typing. A symbol absent from the map falls back to the
   *  card. */
  invalidationBySymbol: Record<string, number | null>;
  /** Phase G piece 5, build step 4 (§7.1) — the trader's explicit method pick
   *  for each basket card, sourced from step 7's `methodPickFor` (keyed by
   *  contract through `editKeyFor`, looked up here per symbol since one
   *  basket card is one contract). Fed into `checkTradeRisk` so `.some(...)`
   *  below applies the same rule §7.1 states in words: one unpicked card
   *  blocks the whole basket, the same rule `missing_invalidation` already
   *  applies. A symbol absent from the map means no pick, same as `null`. */
  methodPickBySymbol: Record<string, MethodPick | null | undefined>;
  /** #582 — the page's submission-draft builder for one row at this dialog's
   *  one-off quantity: the SAME builder the review and the submission use.
   *  Without it no row can be server-reviewed, so none can be confirmed. */
  trackingDraftFor?: (card: TradeCardData, contracts: number) => SubmissionDraft;
  /** #582 — the stamps a reviewed request carries; the recId is the page's
   *  stable per-symbol id, so a retry is recognisable by recId. */
  stampsFor?: (symbol: string) => SubmissionStamps;
  /** Settings' global premium stop, for the requested column only. */
  globalPremiumStopPct?: number;
  onClose:  () => void;
  /** Receives the REVIEWED rows. May answer which rows came back
   *  review-required (nothing saved for them) with their new previews. */
  onSubmit: (orders: ReviewedTrackingOrder[], riskOverridden: boolean) => Promise<TrackingSubmitResult | void> | void;
}

interface RowState {
  contracts: number;
}

export function SendToBrokerDialog({ cards, quoteWarningsByContract, contractsBySymbol, overridesBySymbol, invalidationBySymbol, methodPickBySymbol, trackingDraftFor, stampsFor, globalPremiumStopPct, onClose, onSubmit }: Props) {
  const [rows, setRows] = useState<Record<string, RowState>>(() =>
    Object.fromEntries(cards.map((c) => [c.symbol, { contracts: contractsBySymbol[c.symbol] ?? 1 }])),
  );
  const [overrideReady, setOverrideReady] = useState(false);
  const [reviews, setReviews] = useState<Record<string, RowReview>>({});
  /** Per-symbol retry counter for a failed review. */
  const [retries, setRetries] = useState<Record<string, number>>({});
  const [submitting, setSubmitting] = useState(false);
  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const qtyOf = (c: TradeCardData) => Math.max(1, Math.round((rows[c.symbol] ?? { contracts: 1 }).contracts));

  /* #582 — the exact request each row would submit NOW, at its one-off
   * quantity. Rebuilt every render from the page's current inputs, so a new
   * live quote or edit changes the fingerprint and invalidates the review. */
  const drafts: Record<string, SubmissionDraft> = {};
  if (trackingDraftFor) for (const c of cards) drafts[c.symbol] = trackingDraftFor(c, qtyOf(c));
  const draftsRef = useRef(drafts);
  draftsRef.current = drafts;
  const stampsRef = useRef(stampsFor);
  stampsRef.current = stampsFor;
  /** The request tag each symbol's latest preview was issued for. A response
   *  whose tag is no longer the latest is dropped. */
  const issuedRef = useRef<Record<string, string>>({});
  const retriesRef = useRef(retries);
  retriesRef.current = retries;
  const retrySignature = JSON.stringify(retries);
  const draftSignature = cards.map((c) => `${c.symbol}=${drafts[c.symbol]?.fingerprint ?? ''}`).join('|');

  useEffect(() => {
    const stamp = stampsRef.current;
    if (!stamp) return;
    for (const [symbol, draft] of Object.entries(draftsRef.current)) {
      const tag = `${draft.fingerprint}#${retriesRef.current[symbol] ?? 0}`;
      // A row already reviewed for this exact draft keeps its review (and its
      // stamped request, so the confirmation sends exactly what was reviewed).
      if (issuedRef.current[symbol] === tag) continue;
      issuedRef.current[symbol] = tag;
      const request = stampPosition(draft.tracking, stamp(symbol));
      setReviews((prev) => ({ ...prev, [symbol]: { status: 'loading', key: draft.fingerprint } }));
      void previewPosition(request).then((out) => {
        if (!mountedRef.current || issuedRef.current[symbol] !== tag) return;   // superseded
        setReviews((prev) => ({
          ...prev,
          [symbol]: out.kind === 'ok'
            ? { status: 'ready', key: draft.fingerprint, request, preview: out.preview, changed: null }
            : {
              status: 'error', key: draft.fingerprint,
              detail: out.kind === 'network' ? 'The server could not be reached.' : out.detail,
            },
        }));
      });
    }
  }, [draftSignature, retrySignature]);

  const reviewFor = (c: TradeCardData): RowReview | null => {
    const r = reviews[c.symbol];
    const d = drafts[c.symbol];
    return r && d && r.key === d.fingerprint ? r : null;
  };
  const allReviewed = cards.length > 0 && cards.every((c) => reviewFor(c)?.status === 'ready');
  const resolvedTotal = allReviewed
    ? cards.reduce((t, c) => t + resolvedValue((reviewFor(c) as Extract<RowReview, { status: 'ready' }>).preview), 0)
    : null;

  const limits = useRiskStore((s) => s.limits);
  const dailyRecommendations = useRiskStore((s) => s.dailyRecommendations);
  const positions = usePortfolioStore((s) => s.positions);

  const estTotal = useMemo(() => {
    let t = 0;
    for (const c of cards) {
      const r = rows[c.symbol] ?? { contracts: 1 };
      const mid = c.contractDetails?.mid ?? 0;
      t += mid * 100 * r.contracts;
    }
    return t;
  }, [cards, rows]);

  const riskChecks = useMemo(() => {
    const checks: Record<string, RiskCheckResult> = {};
    for (const c of cards) {
      const r = rows[c.symbol] ?? { contracts: 1 };
      checks[c.symbol] = checkTradeRisk(
        c, Math.max(1, Math.round(r.contracts)), limits, positions, dailyRecommendations,
        overridesBySymbol[c.symbol] ?? null,
        invalidationBySymbol[c.symbol] ?? c.exit.invalidation,
        methodPickBySymbol[c.symbol] ?? null,
      );
    }
    return checks;
  }, [cards, rows, limits, positions, dailyRecommendations, overridesBySymbol, invalidationBySymbol, methodPickBySymbol]);

  const hasMissingInvalidation = useMemo(
    () => Object.values(riskChecks).some((rc) => rc.reasons.includes('missing_invalidation')),
    [riskChecks],
  );

  const hasMissingMethodPick = useMemo(
    () => Object.values(riskChecks).some((rc) => rc.reasons.includes('missing_method_pick')),
    [riskChecks],
  );

  const hasWarnings = useMemo(
    () => Object.values(riskChecks).some((rc) =>
      !rc.approved
      && !rc.reasons.includes('missing_invalidation')
      && !rc.reasons.includes('missing_method_pick'),
    ),
    [riskChecks],
  );

  const allClean = useMemo(
    () => Object.values(riskChecks).every((rc) => rc.approved),
    [riskChecks],
  );

  const patch = (sym: string, p: Partial<RowState>) => {
    setOverrideReady(false);
    setRows((r) => ({ ...r, [sym]: { ...(r[sym] ?? { contracts: 1 }), ...p } }));
  };

  const submit = async () => {
    if (hasMissingInvalidation) return;
    if (hasMissingMethodPick) return;
    if (hasWarnings && !overrideReady) {
      setOverrideReady(true);
      return;
    }
    // #582 — only reviewed rows can be confirmed, and each confirms the exact
    // request the server reviewed (never a rebuilt, unreviewed one).
    if (!allReviewed || submitting) return;
    const orders: ReviewedTrackingOrder[] = cards.map((c) => {
      const r = reviewFor(c) as Extract<RowReview, { status: 'ready' }>;
      return { card: c, contracts: qtyOf(c), draftFingerprint: r.key, request: r.request, preview: r.preview };
    });
    setSubmitting(true);
    try {
      const result = await onSubmit(orders, overrideReady);
      if (!mountedRef.current || !result) return;
      const changed = Object.entries(result.reviewRequired);
      if (changed.length === 0) return;
      // Nothing was saved for these rows: show the new server values and
      // require another confirmation. Successful rows have left the basket.
      setReviews((prev) => {
        const next = { ...prev };
        for (const [symbol, preview] of changed) {
          const old = prev[symbol];
          if (old?.status !== 'ready') continue;
          next[symbol] = {
            ...old, preview,
            changed: changedSince(old.preview, preview, old.request, globalPremiumStopPct ?? null),
          };
        }
        return next;
      });
      setOverrideReady(false);
    } finally {
      if (mountedRef.current) setSubmitting(false);
    }
  };

  const reviewBlock = (c: TradeCardData) => (
    <TrackingReviewBlock
      symbol={c.symbol}
      review={trackingDraftFor ? reviewFor(c) : null}
      draft={drafts[c.symbol] ?? null}
      available={!!trackingDraftFor && !!stampsFor}
      globalPremiumStopPct={globalPremiumStopPct ?? null}
      onRetry={() => setRetries((r) => ({ ...r, [c.symbol]: (r[c.symbol] ?? 0) + 1 }))}
    />
  );
  const confirmTitle =
    hasMissingInvalidation ? MISSING_INVALIDATION_TITLE
    : hasMissingMethodPick ? MISSING_METHOD_PICK_TITLE
    : !allReviewed ? 'Waiting for the server review of every row'
    : undefined;

  return (
    <div className={styles.backdrop} onClick={onClose} role="presentation">
      <div
        className={styles.dialog}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Track basket in Portfolio"
      >
        <header className={styles.header}>
          <div>
            <Text size={14} weight={600}>Track basket in Portfolio</Text>
            <Text size={11} tone="secondary">
              Adds these to Portfolio as tracked rows — no broker order is placed. A tracked row reserves
              its contract and symbol: to trade it instead, send from the card.
            </Text>
            <Text size={11} tone="secondary">
              Pinning only selected these candidates; it froze nothing. Each row below shows what you request
              beside what the server resolves for it now (live quote, re-anchored levels, exposure, premium stop,
              target alert). Confirming saves exactly the reviewed values — if they change first, you review again.
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
        </div>

        <div className={styles.tableBody}>
          {cards.map((c) => {
            const r      = rows[c.symbol] ?? { contracts: 1 };
            const isSpread = c.spreadType && c.spreadType !== 'single' && c.legs && c.legs.length > 0;
            const mid    = c.contractDetails?.mid ?? 0;
            const est    = mid * 100 * r.contracts;

            if (isSpread) {
              // Spread: one row per leg, all sharing the same qty control in the first leg row.
              return (
                <div key={c.symbol}>
                  {c.legs!.map((leg, i) => {
                    const legMid = (leg.bid + leg.ask) / 2;
                    return (
                      <div key={i} className={`${styles.row} ${i > 0 ? styles.legSubRow : ''}`}>
                        {i === 0 ? (
                          <Data size={13} weight={500}>{c.symbol}</Data>
                        ) : (
                          <span />
                        )}
                        <Text size={12}>
                          {leg.action} {leg.qty}× {c.symbol} ${leg.strike}{leg.right} {leg.expiry}
                        </Text>
                        <Data size={12} className={styles.right}>
                          {legMid > 0 ? `$${legMid.toFixed(2)}` : '—'}
                        </Data>
                        {i === 0 ? (
                          <>
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
                          </>
                        ) : (
                          <>
                            <span />
                            <span />
                          </>
                        )}
                      </div>
                    );
                  })}
                  {reviewBlock(c)}
                </div>
              );
            }

            // Single-leg (original path)
            return (
              <div key={c.symbol}>
              <div className={styles.row}>
                <Data size={13} weight={500}>{c.symbol}</Data>
                <div><Text size={12}>{c.contract}</Text><Text size={11} tone="caution">{quoteWarningsByContract?.[contractKeyFor(c) ?? c.contract] ?? (quoteWarningsByContract && (contractKeyFor(c) ?? c.contract) in quoteWarningsByContract ? null : quoteWarning(null))}</Text></div>
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
              </div>
              {reviewBlock(c)}
              </div>
            );
          })}
        </div>

        <div className={styles.riskSummaryWrap}>
          <RiskSummary
            hasMissingInvalidation={hasMissingInvalidation}
            hasMissingMethodPick={hasMissingMethodPick}
            hasWarnings={hasWarnings}
            allClean={allClean}
            overrideReady={overrideReady}
            riskChecks={riskChecks}
          />
        </div>

        <footer className={styles.footer}>
          <Text size={12} tone="secondary">
            {cards.length} to track · Est total ${Math.round(estTotal).toLocaleString()}
            {resolvedTotal != null && <> · Server-resolved ${Math.round(resolvedTotal).toLocaleString()}</>}
          </Text>
          <div className={styles.actions}>
            <button type="button" className={styles.btn} onClick={onClose}>Cancel</button>
            <button
              type="button"
              className={`${styles.btn} ${styles.btnPrimary}`}
              onClick={submit}
              disabled={cards.length === 0 || hasMissingInvalidation || hasMissingMethodPick || !allReviewed || submitting}
              title={confirmTitle}
            >
              {overrideReady && hasWarnings
                ? 'Override & Submit'
                : `Add ${cards.length} to Portfolio`}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}

/** #609 — the row's review lines, grouped destination-first. */
const REVIEW_GROUPS: { id: string; name: string; title: string; keys: string[] }[] = [
  { id: 'destination', name: 'Destination and request', title: 'Destination & request', keys: ['contract', 'qty', 'entry', 'value'] },
  { id: 'settings', name: 'Position settings', title: 'Position settings · in-app alerts', keys: ['stop', 'structuralStop', 'premiumStop'] },
  { id: 'target', name: 'Target alert basis', title: 'Target alert basis', keys: ['targets', 'targetAlert'] },
];

/** #582 — one row's requested-vs-server-resolved review. #609 — grouped
 *  destination-first (destination and request; the actual position settings
 *  with the ≤3 DTE time-exit alert; the target-alert basis), with the review
 *  fingerprint and saved-row id in one closed disclosure. */
function TrackingReviewBlock({
  symbol, review, draft, available, globalPremiumStopPct, onRetry,
}: {
  symbol: string;
  review: RowReview | null;
  /** The row's current draft, for its supplied expiry and the time-exit rule. */
  draft: SubmissionDraft | null;
  available: boolean;
  globalPremiumStopPct: number | null;
  onRetry: () => void;
}) {
  const label = `Server review ${symbol}`;
  if (!available) {
    return (
      <div className={styles.review} role="region" aria-label={label}>
        <Text size={11} tone="caution">Server review unavailable — this row cannot be confirmed.</Text>
      </div>
    );
  }
  if (!review || review.status === 'loading') {
    return (
      <div className={styles.review} role="region" aria-label={label} aria-busy="true">
        <Text size={11} tone="dim">Resolving the tracked values with the server…</Text>
      </div>
    );
  }
  if (review.status === 'error') {
    return (
      <div className={styles.review} role="region" aria-label={label}>
        <Text size={11} tone="reject">Server review failed: {review.detail}</Text>
        <button type="button" className={styles.btn} onClick={onRetry}>Review again</button>
      </div>
    );
  }
  const lines = reviewLines(review.request, review.preview, globalPremiumStopPct);
  const expiry = draft?.identity.expiry && draft.identity.expiry.trim() !== '' ? draft.identity.expiry : null;
  const dte = draft?.identity.dte ?? null;
  const expiryText = expiry
    ? `${expiry}${dte != null ? ` · ${dte} DTE` : ''}`
    : `Not supplied${review.request.expiry ? ` — tracked as ${review.request.expiry}, derived from the DTE` : ''}`;
  const lineRow = (l: ReturnType<typeof reviewLines>[number]) => (
    <div key={l.key} className={styles.reviewLine} data-field={l.key} data-adjusted={l.adjusted ? 'true' : 'false'}>
      <Text size={11} tone="secondary">{l.label}</Text>
      <Data size={11}>{l.requested}</Data>
      <div>
        <Data size={11} tone={l.adjusted ? 'caution' : 'primary'}>{l.effective}</Data>
        {l.note && <Text size={10} tone="caution">Adjusted — {l.note}</Text>}
      </div>
    </div>
  );
  const fixedRow = (label: string, value: string) => (
    <div className={styles.reviewLine}>
      <Text size={11} tone="secondary">{label}</Text>
      <div className={styles.reviewSpan}><Data size={11}>{value}</Data></div>
    </div>
  );
  return (
    <div className={styles.review} role="region" aria-label={label}>
      {review.changed && (
        <Text size={11} tone="caution">
          Changed since your review — nothing was saved. Check the new values and confirm again
          {review.changed.length > 0 ? ` (${review.changed.join(', ')})` : ''}.
        </Text>
      )}
      <div className={styles.reviewGrid}>
        <Text size={10} tone="dim">FIELD</Text>
        <Text size={10} tone="dim">REQUESTED</Text>
        <Text size={10} tone="dim">SERVER-RESOLVED</Text>
      </div>
      {REVIEW_GROUPS.map((g) => (
        <div key={g.name} role="group" aria-label={g.name} className={styles.reviewGroup} data-review-group={g.id}>
          {g.id === 'destination'
            ? <Text size={11} tone="secondary">Portfolio tracking · no broker order · values resolved by the server now</Text>
            : <Text size={10} tone="dim">{g.title}</Text>}
          <div className={styles.reviewGrid}>
            {lines.filter((l) => g.keys.includes(l.key)).map(lineRow)}
            {g.id === 'destination' && fixedRow('Expiry', expiryText)}
            {g.id === 'settings' && fixedRow('Time-exit alert', `≤${draft?.stops.timeExitDte ?? TIME_STOP_DTE} days to expiry — an alert, not a close`)}
          </div>
          {g.id === 'settings' && (
            <Text size={11} tone="secondary">No protective stop-loss or take-profit order is sent to a broker.</Text>
          )}
        </div>
      ))}
      {review.preview.premiumStopUnapplied && (
        <Text size={10} tone="caution">{review.preview.premiumStopUnapplied}</Text>
      )}
      <details className={styles.reviewDetails} data-review-details>
        <summary>Technical details</summary>
        <div className={styles.reviewGrid}>
          <div className={styles.reviewLine}>
            <Text size={10} tone="secondary">Review fingerprint</Text>
            <div className={styles.reviewSpan}><Data size={10}>{review.preview.fingerprint}</Data></div>
          </div>
          <div className={styles.reviewLine}>
            <Text size={10} tone="secondary">Saved-row id</Text>
            <div className={styles.reviewSpan}><Data size={10}>{review.request.recId}</Data></div>
          </div>
        </div>
      </details>
    </div>
  );
}

function RiskSummary({
  hasMissingInvalidation,
  hasMissingMethodPick,
  hasWarnings,
  allClean,
  overrideReady,
  riskChecks,
}: {
  hasMissingInvalidation: boolean;
  hasMissingMethodPick: boolean;
  hasWarnings: boolean;
  allClean: boolean;
  overrideReady: boolean;
  riskChecks: Record<string, RiskCheckResult>;
}) {
  if (hasMissingInvalidation) {
    return (
      <Text size={12} tone="reject">
        {MISSING_INVALIDATION_MESSAGE}
      </Text>
    );
  }

  if (hasMissingMethodPick) {
    return (
      <Text size={12} tone="reject">
        {MISSING_METHOD_PICK_MESSAGE}
      </Text>
    );
  }

  if (allClean) {
    return (
      <Text size={12} tone="pass">
        Within risk limits.
      </Text>
    );
  }

  const reasons = new Set<string>();
  for (const rc of Object.values(riskChecks)) {
    for (const r of rc.reasons) {
      reasons.add(r);
    }
  }

  const reasonLabels: Record<string, string> = {
    single_trade_exposure_too_high: 'Single trade exposure too high',
    total_exposure_limit_reached: 'Total exposure limit reached',
    max_concurrent_positions_reached: 'Max concurrent positions reached',
    duplicate_symbol: 'Duplicate symbol in portfolio',
    max_daily_recommendations_reached: 'Max daily recommendations reached',
    max_loss_per_trade_exceeded: 'Max loss at stop exceeds per-trade limit',
  };

  return (
    <div className={styles.riskReasonsStack}>
      {Array.from(reasons).map((r) => (
        <Text key={r} size={12} tone="caution">
          {reasonLabels[r] ?? r}
        </Text>
      ))}
      {reasons.has('max_loss_per_trade_exceeded') && (() => {
        // The actual worst offender, not just the first match in basket order —
        // a symbol pinned first with a barely-over loss must never mask a
        // later symbol whose loss is wildly over the same limit.
        let worst: { symbol: string; rc: RiskCheckResult } | null = null;
        for (const [symbol, rc] of Object.entries(riskChecks)) {
          if (!rc.reasons.includes('max_loss_per_trade_exceeded') || rc.maxLossAtStop == null) continue;
          if (!worst || rc.maxLossAtStop > worst.rc.maxLossAtStop!) worst = { symbol, rc };
        }
        if (!worst || worst.rc.maxLossLimitDollar == null) return null;
        return (
          <Text size={11} tone="dim">
            Max loss at stop ({worst.symbol}) ≈ ${Math.round(worst.rc.maxLossAtStop!).toLocaleString('en-US')}
            {' '}(limit ${Math.round(worst.rc.maxLossLimitDollar).toLocaleString('en-US')})
          </Text>
        );
      })()}
      {!overrideReady && (
        <Text size={12} tone="secondary">
          Click Submit again to override.
        </Text>
      )}
    </div>
  );
}
