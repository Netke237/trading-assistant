/**
 * #582 (TC-REVIEW-07) — THE SERVER REVIEW OF A PORTFOLIO TRACKING ROW.
 *
 * `position_writer.create_position` re-quotes the entry, re-anchors generated
 * levels to the live underlying, applies the exposure check and its resize,
 * derives the premium-stop fraction against the saved entry and seeds the
 * effective target alert. A summary built in the browser cannot predict that
 * row, so Track basket asks the server: `POST /api/portfolio/preview` runs the
 * writer's own resolution and writes nothing (see `portfolioStore`'s
 * `previewPosition`). Confirming sends the preview's `fingerprint` back; the
 * server re-resolves under its booking lock and answers 412 review-required,
 * writing nothing, when the current values differ.
 *
 * This module holds the parsed review and pure helpers over it. It prices
 * nothing: every effective value here is the SERVER's, shown beside the
 * request it came from.
 */

import type { PortfolioPosition, TradeCardData, TpMethod } from '@/types/domain';

/** One field the server resolved differently from the request, with the
 *  writer's own reason (`position_writer._differences`). */
export interface PreviewDifference {
  field: string;
  requested: unknown;
  effective: unknown;
  reason: string;
}

/** The server's resolution of one tracking request. `position` is what the
 *  create WOULD store, mapped like a GET row. */
export interface TrackingPreview {
  fingerprint: string;
  position: PortfolioPosition;
  adjustedQty: number | null;
  premiumStopUnapplied: string | null;
  entryFromLiveQuote: boolean;
  entryStockPrice: number | null;
  /** The global a null `position.premiumStopPct` inherits. */
  inheritedPremiumStopPct: number | null;
  differences: PreviewDifference[];
}

/** One basket row, reviewed: the exact stamped request the server previewed,
 *  the draft generation it came from, and the server's preview. Confirming
 *  POSTs `request` unchanged with `preview.fingerprint`. */
export interface ReviewedTrackingOrder {
  card: TradeCardData;
  /** The one-off basket quantity (never written back to the card). */
  contracts: number;
  /** `SubmissionDraft.fingerprint` of the draft `request` was stamped from. */
  draftFingerprint: string;
  request: PortfolioPosition;
  preview: TrackingPreview;
}

/** What the page tells the dialog after a confirm: rows whose current server
 *  resolution differed (nothing was saved for them) and must be re-reviewed. */
export interface TrackingSubmitResult {
  reviewRequired: Record<string, TrackingPreview>;
}

const REASON_TEXT: Record<string, string> = {
  live_quote: 'save-time live quote',
  request: 'no live quote — request value kept',
  exposure_resize: 'resized to fit exposure limits',
  reanchored: 're-anchored to the live underlying',
  normalized: 'normalised by the server',
  unset: 'stored as unset',
  rung_rescaled: 'rung shares follow the resize',
  derived_from_dollar: 'derived from your $ stop against the saved entry',
  premium_stop_unapplied: 'your $ stop could not be applied at the saved entry',
  inherits_global: 'inherits the global premium stop',
  ladder_fallback: 'falls back to the live Ladder',
};

export function reasonText(reason: string): string {
  return REASON_TEXT[reason] ?? reason.replace(/_/g, ' ');
}

export function differenceFor(preview: TrackingPreview, field: string): PreviewDifference | undefined {
  return preview.differences.find((d) => d.field === field);
}

const usd = (x: number | null | undefined, digits = 2): string =>
  x == null || !Number.isFinite(x) ? '—' : `$${x.toFixed(digits)}`;
const pct = (x: number) => `${(x * 100).toFixed(1)}%`;

const TP_LABEL: Record<TpMethod, string> = {
  ladder: 'Live Ladder',
  monte_carlo: 'Monte Carlo stock level',
  exit_plan_2r: 'Arithmetic first R row',
  exit_plan_3r: 'Arithmetic second R row',
};

function targetsText(targets: PortfolioPosition['targets'] | undefined): string {
  if (!targets || targets.length === 0) return 'None';
  return targets
    .map((t) => `${usd(t.targetPrice ?? t.stockPrice)}${t.contractsToSell != null ? ` ×${t.contractsToSell}` : ''}`)
    .join(' · ');
}

function requestedPremiumStop(r: PortfolioPosition, globalPct: number | null): string {
  const dollar = (r.premiumStopDollar ?? 0) > 0 ? r.premiumStopDollar! : null;
  if (dollar != null) return `${usd(dollar)}/share`;
  const fraction = (r.premiumStopPct ?? 0) > 0 && r.premiumStopPct! < 1 ? r.premiumStopPct! : null;
  if (fraction != null) return `${pct(fraction)} of the premium`;
  return globalPct != null ? `Global ${pct(globalPct)}` : 'Global';
}

function effectivePremiumStop(p: PortfolioPosition, inherited: number | null): string {
  const fraction = p.premiumStopPct;
  if (fraction != null) {
    return `${pct(fraction)} of the ${usd(p.entryPrice)} entry · fires at ${usd(p.entryPrice * (1 - fraction))}/share`;
  }
  return inherited != null
    ? `Inherits global ${pct(inherited)} · fires at ${usd(p.entryPrice * (1 - inherited))}/share`
    : 'Inherits the global premium stop';
}

function requestedTarget(r: PortfolioPosition): string {
  if (!r.pickedMethod) return 'No method recorded';
  const row = r.pickedRowStockPrice != null ? ` · stock ${usd(r.pickedRowStockPrice)}` : ' · no stock row';
  return `${r.pickedMethod.replace('_', ' ')}${row}`;
}

function effectiveTarget(p: PortfolioPosition): string {
  const method = (p.activeTpMethod ?? 'ladder') as TpMethod;
  if (method === 'ladder' || p.resolvedTpPrice == null) return TP_LABEL.ladder;
  return `${TP_LABEL[method]} · stock ${usd(p.resolvedTpPrice)}`;
}

function stopText(stop: number | null | undefined, userSet?: boolean): string {
  if (stop == null || !(stop > 0)) return 'Unset';
  return userSet == null ? usd(stop) : `${usd(stop)} · ${userSet ? 'typed (absolute)' : 'plan level'}`;
}

/** One line of the requested-vs-effective review. */
export interface ReviewLine {
  key: string;
  label: string;
  requested: string;
  effective: string;
  /** The server changed it; `note` says why (the writer's reason). */
  adjusted: boolean;
  note: string | null;
}

/** Requested (the exact request) against effective (the server's row), in
 *  the order the dialog shows them. */
export function reviewLines(request: PortfolioPosition, preview: TrackingPreview, globalPremiumStopPct: number | null): ReviewLine[] {
  const p = preview.position;
  const line = (key: string, label: string, requested: string, effective: string, field?: string): ReviewLine => {
    const diff = field ? differenceFor(preview, field) : undefined;
    return { key, label, requested, effective, adjusted: diff != null, note: diff ? reasonText(diff.reason) : null };
  };
  const qty = request.contracts ?? 1;
  return [
    line('contract', 'Contract', request.contract, p.contract),
    line('qty', 'Quantity', `${qty}`, `${p.contracts ?? 1}`, 'qty'),
    line('entry', 'Tracked entry price', `${usd(request.entryPrice)}/share`,
      `${usd(p.entryPrice)}/share · ${preview.entryFromLiveQuote ? 'save-time live quote' : 'no live quote — request value'}`,
      'entryPrice'),
    line('stop', 'Stock stop', stopText(request.stop, request.stopIsUserSet ?? false), stopText(p.stop), 'stop'),
    line('structuralStop', 'Structural stop', stopText(request.structuralStop), stopText(p.structuralStop), 'structuralStop'),
    line('premiumStop', 'Premium stop', requestedPremiumStop(request, globalPremiumStopPct),
      effectivePremiumStop(p, preview.inheritedPremiumStopPct), 'premiumStop'),
    line('targets', 'Ladder targets', targetsText(request.targets), targetsText(p.targets), 'targets'),
    line('targetAlert', 'Target alert', requestedTarget(request), effectiveTarget(p), 'targetAlert'),
    line('value', 'Est. position value', usd(request.entryPrice * 100 * qty, 0), usd(p.entryPrice * 100 * (p.contracts ?? 1), 0)),
  ];
}

/** The server-resolved premium outlay of a reviewed row ($, options ×100). */
export function resolvedValue(preview: TrackingPreview): number {
  return preview.position.entryPrice * 100 * (preview.position.contracts ?? 1);
}

/** Material fields of a saved row compared against the reviewed preview — the
 *  "matching confirmed request identity" check when a save is resolved by recId
 *  after an ambiguous answer. Empty means the saved row is the reviewed row. */
export function savedDifferences(saved: PortfolioPosition, preview: TrackingPreview): string[] {
  const p = preview.position;
  const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
  const fields: [string, unknown, unknown][] = [
    ['contract', saved.contract, p.contract],
    ['entryPrice', saved.entryPrice, p.entryPrice],
    ['quantity', saved.contracts, p.contracts],
    ['stop', saved.stop, p.stop],
    ['structuralStop', saved.structuralStop, p.structuralStop],
    ['premiumStopPct', saved.premiumStopPct, p.premiumStopPct],
    ['targets', saved.targets, p.targets],
    ['activeTpMethod', saved.activeTpMethod, p.activeTpMethod],
    ['resolvedTpPrice', saved.resolvedTpPrice, p.resolvedTpPrice],
  ];
  return fields.filter(([, a, b]) => !same(a, b)).map(([k]) => k);
}

/** Which reviewed lines a re-review changed (for the "changed since your
 *  review" marker). */
export function changedSince(previous: TrackingPreview, next: TrackingPreview, request: PortfolioPosition, globalPremiumStopPct: number | null): string[] {
  const a = reviewLines(request, previous, globalPremiumStopPct);
  const b = reviewLines(request, next, globalPremiumStopPct);
  return b.filter((l, i) => l.effective !== a[i]?.effective).map((l) => l.label);
}
