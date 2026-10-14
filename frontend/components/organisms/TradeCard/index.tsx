'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Text, Data } from '@/components/primitives';
import { SymbolHeader } from '@/components/molecules/SymbolHeader';
import { CollapsibleSection } from '@/components/molecules/CollapsibleSection';
import { ScoreCardPanel } from '@/components/molecules/ScoreCardPanel';
import { AlternativeContractRow } from '@/components/molecules/AlternativeContractRow';
import { MethodPickSelector } from '@/components/molecules/MethodPickSelector';
import type { MethodPickOption } from '@/components/molecules/MethodPickSelector';
import { MarketSentiment } from '@/components/molecules/MarketSentiment';
import { FundamentalHealthCard } from '@/components/molecules/FundamentalHealthCard';
import { InlineChartPanel } from '@/components/organisms/InlineChartPanel';
import BarrierRaceCard from '@/components/organisms/BarrierRaceCard';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { Tooltip } from '@/components/atoms/Tooltip';
import { LabeledStatusBadge } from '@/components/molecules/LabeledStatusBadge';
import { stopJustification, targetCompareState, targetCompareLabel } from '@/lib/exitPlanLabels';
import { capitalAtRisk, maxLossAtStop, resolveMaxLossLimitDollar, recommendedContractSize, formatRecommendedContractSizeRaw, stopPremiumRisk, formatStopPremiumRisk, formatStopLossHeadline, formatStopLossBadge, stopLossIsTotalOnPrintedFigures } from '@/lib/risk';
import { resolveIv, formatIv } from '@/lib/ivBasis';
import { useRiskStore } from '@/lib/riskStore';
import { api } from '@/lib/api';
import { useSettingsStore } from '@/lib/settingsStore';
import { useScanStore } from '@/lib/scanStore';
import { rrOverridesForPlan } from '@/lib/tradeCardOverride';
import { resolveParamsHorizon, presetByKey } from '@/lib/horizonPresets';
import { premiumStopPctFromDollars, money, weightPercents, days } from '@/lib/barrierRace';
import { premiumStopDollarBounds } from '@/lib/premiumStop';
import { TIME_STOP_DTE } from '@/lib/alertEngine';
import { horizonFieldsFrom } from '@/lib/tradeCardOverride';
import {
  type EditOverlay,
  type EditedFields,
  DEFAULT_CONTRACTS,
  FIELD_LABELS,
  editedFields as editedFieldsAgainstPlan,
  markEdited,
  planOverlay,
  restoredEdits,
} from '@/lib/tradeCardEdits';
import type { TradeCardData, TargetLevel, StructuralStop, FirstPassageEstimate, FirstPassageContext, FirstPassageTarget, ExitPlan, ExitPlanTargetRow, MaxLossOverride, MethodPick, StopCostOut } from '@/types/domain';
import {
  triggerDetailText,
  pullbackDetailText,
  trendDetailText,
  eventDetailText,
  volDetailText,
  dteDetailText,
  deltaDetailText,
  ivDetailText,
  liquidityDetailText,
  spreadDetailText,
} from '@/lib/scoreDetailText';
import styles from './TradeCard.module.css';

// `EditOverlay` now lives in lib/tradeCardEdits.ts alongside the card-level
// "edited" comparison that has to agree with it field-for-field
// (EDITED-FLAG-2026-09-04). Re-exported here because the type is part of this
// component's public surface — `onEditsChange` hands one to the parent, and
// the re-export at the bottom of this file keeps that import path working.

/** Which overlay fields the user has actually EDITED, as opposed to fields
 *  still carrying the seed `defaultOverlay` put there.
 *
 *  `patch` reports the whole overlay on every call, so the parent cannot tell
 *  the two apart by looking at values: the seed moves under an untouched field
 *  whenever `mergePlan` lands, and a user is free to type the seed's own value
 *  deliberately. Only this card knows which happened, so it says.
 *
 *  Covers exactly the three fields a send path reads. `maxFill` and
 *  `timeStopDays` are deliberately absent: nothing anywhere consumes either one
 *  -- TIME_STOP fires on a hardcoded `dteRemaining <= 3` (alertEngine.ts) and
 *  `maxFill` has no reader outside its own input -- so there is nothing to
 *  report touched-ness TO. Threading those two is a build (a new persisted
 *  field, a backend column and an alert change), not a wiring fix. */
interface TouchedFields {
  entryLimit: boolean;
  invalidation: boolean;
  premiumStop: boolean;
}

function defaultOverlay(data: TradeCardData): EditOverlay {
  return {
    entryLimit: data.entry.limit,
    maxFill: data.entry.maxFill,
    invalidation: data.exit.invalidation,
    premiumStop: data.exit.premiumStop,
    timeStopDays: data.exit.timeStopDays,
    targets: data.exit.targets.map((t) => t.targetPrice ?? t.stockPrice),
    contracts: DEFAULT_CONTRACTS,
  };
}

// isDirty() and computeEditedRR() were deleted here with the "Projected R/R
// (+8% stock move)" readout in the Final Recommendation's Ladder-default
// branch, which was the only thing that called either. computeEditedRR's
// delta approximation (0.5 in the money / 0.3 out, applied to the typed
// target) is not worth preserving for a future caller: it was a display
// estimate for one line of copy, and anything that needs a repriced option
// value now goes through the backend's reprice_horizon path like the rest of
// the card. recomputeTargetEstOption below is a DIFFERENT function with a live
// caller and stays.

function recomputeTargetEstOption(
  targetStockPrice: number,
  entryLimit: number,
  data: TradeCardData,
): number {
  const cd = data.contractDetails;
  if (!cd) return 0;
  const isCall = cd.right === 'C';
  const strike = cd.strike;
  const currentStockPrice = data.price;
  const delta =
    (isCall && targetStockPrice > strike) || (!isCall && targetStockPrice < strike)
      ? 0.5
      : 0.3;
  const priceMove = Math.abs(targetStockPrice - currentStockPrice);
  return Math.max(0.01, entryLimit + delta * priceMove);
}

function rrContribution(
  estOptionPrice: number,
  entryLimit: number,
  riskBasis: number,
): number {
  // Risk basis is the FULL premium at the overlay's own entry
  // (TRADING-REVIEW-PHASE-C-RR, decision D5): no protective stop order is ever
  // placed, so neither the premium stop (an alert level) nor the captured
  // stock-stop loss bounds what the trade can lose.
  // Mirrors the backend's reward_risk.py M2 fix: a negative reward's sign/
  // magnitude is preserved, not flattened to 0 — a target priced below entry
  // is a real loss the trader should see, not an indistinguishable "no data".
  // Guards both operands, not just riskBasis, even though today's UI already
  // clamps entryLimit to a positive minimum before it can reach here. (The
  // symmetry this used to cite was with computeEditedRR's equivalent guard;
  // that function is gone, the guard's own reason is not.)
  if (riskBasis <= 0 || entryLimit <= 0) return 0;
  const reward = estOptionPrice - entryLimit;
  return Math.round((reward / riskBasis) * 10) / 10;
}

function normalizeStructuralStopResponse(res: {
  available: boolean;
  price: number | null;
  source: 'order_block' | 'swing_low' | 'swing_high' | null;
  confidence: number | null;
  distancePct: number | null;
  stopCost?: StopCostOut | null;
}): StructuralStop | null {
  return res.available && res.price != null && res.source != null
    && res.confidence != null && res.distancePct != null
    // `stopCost` rides along with the level it was priced against, deliberately
    // rather than being held in its own state: the gate is only ever valid FOR
    // a particular stop, and a separate slot is a slot that can hold last
    // request's verdict beside this request's level.
    // `?? null` normalises an absent block to the same "not computed" the
    // endpoint sends when it declines to price one, so the card has one state
    // to render rather than two that mean the same thing.
    ? { price: res.price, source: res.source, confidence: res.confidence,
        distancePct: res.distancePct, stopCost: res.stopCost ?? null }
    : null;
}

/** Feature 3 (Arithmetic Profit Target card) — stopJustification,
 *  targetCompareState and targetCompareLabel moved to lib/exitPlanLabels when
 *  the stocks arithmetic plan arrived: it reports the same fields under the
 *  same names, and two copies of this prose would eventually explain one card's
 *  stop differently from the other's for identical numbers. `targetCompareState`
 *  is called here with a full `ExitPlanTargetRow`, which structurally satisfies
 *  the narrower parameter type. */

/** Feature 8 — "computed via: <method>, HH:MM" timestamp label. */
function formatHHMM(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function structuralStopSourceLabel(source: 'order_block' | 'swing_low' | 'swing_high' | null | undefined): string {
  if (source === 'order_block') return 'Structural stop — Order Block';
  if (source === 'swing_low') return 'Structural stop — Swing Low';
  if (source === 'swing_high') return 'Structural stop — Swing High';
  return 'Structural stop';
}

interface TradeCardProps {
  data: TradeCardData;
  /** Step 7 renders this context once above candidate navigation. */
  showMarketSentiment?: boolean;
  /** Controlled selector may render in the page execution panel. Undefined
   *  retains standalone placement; null waits for the page DOM anchor. All
   *  method state and effects remain owned by this single TradeCard. */
  decisionTarget?: HTMLElement | null;
  recId?: string;
  onSendToBroker?: () => void;
  sendLabel?: string;
  sendDisabled?: boolean;
  contracts?: number;
  /** A flag in `meta.touched` is TRUE only once the user has actually edited
   *  that field on this card. The parent must cache a value only when its flag
   *  is set, because "untouched" cannot be recovered later by comparing the
   *  cached value against the card's seed: the seed moves under an untouched
   *  field whenever `mergePlan` lands, and a user is free to type the seed's own
   *  value deliberately. See `premiumStopDollarToSend` and `TouchedFields`. */
  onEditsChange?: (overlay: EditOverlay, meta: { touched: TouchedFields }) => void;
  onRrStaleChange?: (stale: boolean) => void;
  /** Fired whenever the "Check structure" result changes for the current contract
   *  (including being reset to `undefined` on a contract switch, or `null` when no
   *  structural level was found) — lets the parent capture the level so it can be
   *  attached to the position if/when this trade is sent to the broker, AND cache it
   *  per symbol so re-navigating to this candidate restores it instead of wiping it.
   *  `stockPrice` is the fresh underlying price the level was measured against
   *  (`null` whenever `stop` is `undefined`); the parent must cache it alongside the
   *  level or a restored stop cannot produce an R:R-vs-structural-stop figure. */
  onStructuralStopChange?: (stop: StructuralStop | null | undefined, stockPrice: number | null) => void;
  /** Fired whenever the "Estimate" (first-passage) result changes for the current
   *  contract, including the reset to `undefined` on a contract switch/start of a
   *  re-estimate, and the explicit `null` a FAILED re-estimate writes once it
   *  actually completes. The parent caches the pair per CONTRACT (not per symbol —
   *  the estimate is priced off this contract's premium) and must ignore only the
   *  `undefined` sentinel (still in flight — don't touch the cache), while treating
   *  `null` as a real answer to write through, the same distinction
   *  `onStructuralStopChange`'s `stop` parameter above already makes: an in-flight
   *  re-estimate must never destroy the value already on screen, but a FAILED one
   *  must actually overwrite a stale cached entry, or it silently reappears on the
   *  next navigate-away-and-back next to whatever the OTHER cache resolved to. */
  onFirstPassageChange?: (
    estimate: FirstPassageEstimate | null | undefined,
    context: FirstPassageContext | null,
  ) => void;
  /** Fired whenever the "Compute Exit Plan" result changes for the current
   *  contract, including the reset to `undefined` on a contract switch/start
   *  of a re-compute, and the explicit `null` a FAILED re-compute writes once
   *  it actually completes — same `undefined` (in-flight, don't touch the
   *  cache) vs `null` (a real answer, overwrite the cache) distinction as
   *  `onStructuralStopChange`/`onFirstPassageChange` above. Unlike those two,
   *  this is a single self-contained server computation (no cross-fetch
   *  pairing/freshness to track), so the parent can cache it per contract
   *  on its own. */
  onExitPlanChange?: (plan: ExitPlan | null | undefined) => void;
  /** Feature 5 — the active pre-trade max-loss override, seeded from the
   *  page-level `maxLossOverrideBySymbol` cache (keyed by SYMBOL — a risk
   *  decision about the underlying, same keying as `structuralBySymbol`, not
   *  `exitPlanByContract`). `null`/absent means "inherit the global
   *  `maxLossPerTradePct` default". */
  initialMaxLossOverride?: MaxLossOverride | null;
  /** Piece 4 — the card's editable "Premium stop" DOLLAR field, seeded from
   *  the page-level `premiumStopByContract` cache (keyed by CONTRACT, since a
   *  dollar stop is meaningful only against the premium it was typed on).
   *  `null`/absent means "this contract has never been edited", and the field
   *  falls back to `data.exit.premiumStop`.
   *
   *  It has to round-trip, exactly as `contracts` does. Without it the reset
   *  on a contract change (which deliberately does NOT call `onEditsChange`)
   *  put the SEED back in the field while the parent's cache kept the user's
   *  edit: Prev to another candidate and back and the card displayed $3.12
   *  while both send paths posted the $2.00 still sitting in the cache. */
  initialPremiumStop?: number | null;
  /** The page-level caches for the two fields threaded on 2026-09-05, restored
   *  the same way `initialPremiumStop` is and for exactly the reason its doc
   *  above describes: the reset on a contract change deliberately does NOT call
   *  `onEditsChange`, so without a round trip the card puts the SEED back in the
   *  field while the parent's cache keeps the edit -- Prev to another candidate
   *  and back, and the card showed $2.50 / $140.00 while the button promised
   *  $2.71, the order posted 2.71 and the position stored a stop of 132.
   *
   *  `initialEntryLimit` comes from `entryLimitByContract` (keyed by CONTRACT --
   *  a premium for one contract); `initialInvalidation` from
   *  `invalidationBySymbol` (keyed by SYMBOL -- a level on the underlying).
   *  `null`/absent means "never edited", and the field falls back to the card's
   *  own value, which is what lets an untouched field keep following `mergePlan`. */
  initialEntryLimit?: number | null;
  initialInvalidation?: number | null;
  /** The page's freshly-fetched underlying price and contract mid, used ONLY
   *  to anchor the three fields' bounds.
   *
   *  Round 8: the bounds were anchored to `data.price` / `contractDetails.mid`,
   *  which come off `scanResult` -- and `scanStore` persists that to
   *  localStorage, so on a reload they can be days old. AAPL scanned Bullish at
   *  $145, reopened with the stock at $200: the bounds were [72.50, 143.55] and
   *  a perfectly sane $180 stop was rejected as out of range while the page
   *  displayed "Live stock: $200.00" three rows away. The live values are
   *  already fetched; they were simply never handed down.
   *
   *  Null falls back to the scan-time figures, which is the pre-fetch state and
   *  the offline one -- bounds off a stale anchor still beat no bounds. */
  liveStockPrice?: number | null;
  liveMid?: number | null;
  /** Bumped by the page whenever it clears its per-card edit caches (a new
   *  scan result). Forces the same full reset a candidate change does.
   *
   *  Round 8: the page cleared `entryLimitByContract` and friends without any
   *  way to tell the card, and the card's reset is gated on symbol/contract
   *  identity -- which a new scan of the SAME contract does not change. So the
   *  card kept `touchedRef.entryLimit` and displayed the user's $2.71 while
   *  `entryLimitFor` fell back to the new plan's $6.00: card, button and order
   *  disagreeing, which is the whole defect class this branch exists to close.
   *  Clearing the parent's cache without this prop landed in the WORSE of the
   *  two states, not the safer one. */
  resetKey?: number;
  /** Fired whenever the override changes (Apply/Clear inside the Arithmetic
   *  card's max-loss override editor) — direct call inside the setter, the
   *  same pattern `onEditsChange` already uses. Not the ref-synced-effect
   *  pattern `onStructuralStopChange`/`onFirstPassageChange` use: those exist
   *  to protect against an ASYNC callback (a `.then()` body) closing over a
   *  stale, pre-navigation `onXChange` prop after the user has already
   *  switched candidates mid-flight. The override has no such async gap —
   *  Apply/Clear are synchronous, user-triggered state updates, so the
   *  direct-call pattern (call the current prop value inline, same render) is
   *  sufficient and simpler; there is no in-flight request whose resolution
   *  could race a candidate switch. */
  onMaxLossOverrideChange?: (v: MaxLossOverride | null) => void;
  /** Phase G piece 5 (D4/D5), spec §6.2 — the fifth `initial*`/`on*Change`
   *  pair, and it is wired exactly like `initialMaxLossOverride` above: the
   *  page holds the value in `scanStore`'s scan-stamped `picks` map (read
   *  through `selectCardEdits`, never off the slice directly) and hands it back
   *  down, so the round trip that `initialPremiumStop`'s note describes works
   *  for the pick too — the reset on a contract change deliberately does NOT
   *  call back, so without the trip the card would put "no pick" on screen
   *  while the store still held one and the send gate still saw it.
   *
   *  `null`/absent means NO PICK HAS BEEN MADE, which is a real and required
   *  state (§6.1: no default is pre-selected, because a pre-selected radio is
   *  a default nobody looked at wearing a radio's clothes).
   *
   *  DIRECT-CALL, NOT REF-SYNCED, for the reason `onMaxLossOverrideChange`
   *  gives above: a pick is a synchronous user click with no in-flight request
   *  whose resolution could race a candidate switch, so the two-effect ref
   *  pattern `onFirstPassageChange` needs buys nothing here. */
  initialMethodPick?: MethodPick | null;
  onMethodPickChange?: (pick: MethodPick | null) => void;
}

function targetStatusTooltip(statusVal: TargetLevel['status']): string {
  if (statusVal === 'HIT') return 'This profit target has been reached.';
  if (statusVal === 'MISSED') return 'Price moved past this target level without filling — treated as missed.';
  return 'Target not yet reached.';
}

function generateRecId(): string {
  return 'REC-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6).toUpperCase();
}

/**
 * Abort `controller` if nothing has settled within REQUEST_TIMEOUT_MS, and
 * report that it was a TIMEOUT rather than a supersede.
 *
 * WHY THE FLAG. Every handler here distinguishes "this request was cancelled
 * because a newer one replaced it" from "this request failed", by checking
 * `controller.signal.aborted` in its catch and its finally. A bare
 * `setTimeout(() => controller.abort())` is indistinguishable from the former,
 * so on a timeout the catch returned early without setting an error AND the
 * finally skipped clearing the loading flag — the request was cancelled and the
 * spinner became permanent and silent. That is the exact failure the timeout
 * was added to fix, reintroduced by the fix.
 *
 * WHY IT EXISTS AT ALL. `lib/api.ts` sets no timeout on `fetch`. That was
 * survivable while each request only drove its own spinner; it stopped being
 * survivable once the Estimate button was disabled on `structuralLoading ||
 * exitPlanLoading`, because a request that never settles then disables a button
 * the user has no other way to re-enable. Bounding this component's own calls is
 * the narrow fix; a timeout inside `api.ts` would also bound scans and
 * backtests, which legitimately run for minutes.
 */
const REQUEST_TIMEOUT_MS = 20_000;

interface RequestDeadline {
  timer: ReturnType<typeof setTimeout>;
  /** True once the deadline fired. Read it in `catch` and `finally` to tell a
   *  timeout apart from a supersede — `controller.signal.aborted` is true for
   *  both. */
  timedOut: boolean;
}

function abortAfterTimeout(controller: AbortController): RequestDeadline {
  const deadline: Partial<RequestDeadline> = { timedOut: false };
  deadline.timer = setTimeout(() => {
    deadline.timedOut = true;
    controller.abort();
  }, REQUEST_TIMEOUT_MS);
  return deadline as RequestDeadline;
}

/** True when the request is over and nothing more should be done with it —
 *  either a newer request superseded it (stay silent) or our deadline killed it
 *  (the caller must surface it). Callers pair this with `isRealFailure`. */
function isFinished(controller: AbortController): boolean {
  return controller.signal.aborted;
}

/** True when this request should be treated as a real failure — it either threw
 *  on its own, or our own deadline killed it. False only when a newer request
 *  superseded it, which is the one case that must stay silent. */
function isRealFailure(controller: AbortController, deadline: RequestDeadline): boolean {
  return !controller.signal.aborted || deadline.timedOut;
}

export function TradeCard({
  data,
  showMarketSentiment = true,
  decisionTarget,
  recId: propRecId,
  onSendToBroker,
  sendLabel,
  sendDisabled,
  contracts: initialContracts = 1,
  onEditsChange,
  onRrStaleChange,
  onStructuralStopChange,
  onFirstPassageChange,
  onExitPlanChange,
  initialMaxLossOverride = null,
  initialPremiumStop = null,
  initialEntryLimit = null,
  initialInvalidation = null,
  liveStockPrice = null,
  liveMid = null,
  resetKey = 0,
  onMaxLossOverrideChange,
  initialMethodPick = null,
  onMethodPickChange,
}: TradeCardProps) {
  const [chartOpen, setChartOpen] = useState(false);
  const [altOpen, setAltOpen] = useState(false);
  const [overlay, setOverlay] = useState<EditOverlay>(() => ({
    ...defaultOverlay(data),
    contracts: initialContracts,
    premiumStop: initialPremiumStop ?? data.exit.premiumStop,
    entryLimit: initialEntryLimit ?? data.entry.limit,
    invalidation: initialInvalidation ?? data.exit.invalidation,
  }));
  /** Has the user typed in the "Premium stop" field for the contract currently
   *  on screen? Distinguishes "$3.12 because that is what I chose" from "$3.12
   *  because that is `round(mid x global, 2)` and nobody has touched it",
   *  which `overlay.premiumStop` alone cannot: the two are the same number
   *  until the seed moves underneath it.
   *
   *  And it does move. A Step 6 contract override changes `data.contract`
   *  immediately (`applyPickedContract`) but leaves `exit` as the AUTO-PICK's,
   *  so the reset below re-seeds the old $3.12; `mergePlan` then replaces
   *  `exit` wholesale a network round-trip later, WITHOUT touching
   *  `data.contract`, so nothing re-ran and the field kept $3.12 against a
   *  recomputed seed of $2.40. One unrelated `patch()` after that (clicking
   *  Apply on the recommended contract size is enough) cached $3.12 under the
   *  NEW contract's key, `premiumStopDollarToSend` saw 3.12 !== 2.40 and let
   *  it through, and the router derived 3.12 / 4.00 = a 78% premium stop
   *  nobody chose. That is verbatim the failure `premiumStop.ts` documents,
   *  reached by a second route. The re-seed effect below closes it.
   *
   *  ROUND 6 CORRECTION -- that scenario appears FORECLOSED upstream, so this
   *  is belt-and-braces rather than the only thing between the user and a 78%
   *  stop. Step 7's page renders "Preparing the plan for your selected
   *  contract..." in place of the card while `isOverride && !planReady`, so the
   *  card is UNMOUNTED across the whole pre-merge window and remounts with
   *  `exit` already merged; and the recompute is claimed once per contract key
   *  (`requestedPlanKeysRef`), so it cannot re-fire while the card is visible.
   *  Both the flag and the effect are still worth keeping -- neither guarantee
   *  is local to this file, and the cost of being wrong is a silently
   *  mis-anchored stop -- but do not build on the claim that the window is
   *  live. On every path found so far, it is not. */
  // A cached value arriving from the parent IS a previous edit on this card,
  // restored -- see the props' own docs. Marking it touched is what keeps it
  // from being overwritten by the follow-the-seed effects below, and what makes
  // the card report it back on the next patch.
  const touchedRef = useRef<TouchedFields>({
    entryLimit: initialEntryLimit != null,
    invalidation: initialInvalidation != null,
    premiumStop: initialPremiumStop != null,
  });
  /** The card-level "edited" indicator's half of the same question
   *  (EDITED-FLAG-2026-09-04): which overlay fields has the user changed?
   *
   *  Kept SEPARATE from `touchedRef` rather than replacing it, on purpose.
   *  `touchedRef` covers only the three fields a send path reads, is reported
   *  to the parent, and is read SYNCHRONOUSLY inside effects and send handlers
   *  that do not depend on it — turning it into state would hand those reads a
   *  stale closure, which is precisely the failure mode this file has been
   *  bitten by before. This one is display-only, so it must be state (a ref
   *  would not re-render the badge) and it covers every overlay field. The
   *  three they share are written in the same statements below, so they cannot
   *  drift apart. */
  const [edited, setEdited] = useState<EditedFields>(() => restoredEdits({
    entryLimit: initialEntryLimit,
    invalidation: initialInvalidation,
    premiumStop: initialPremiumStop,
    contracts: initialContracts,
  }));
  // Feature 5 — pre-trade max-loss override, seeded from the page-level cache
  // (keyed by symbol there; this local state just mirrors whatever the parent
  // resolved for the CURRENT candidate). Reset alongside overlay/structuralStop/
  // etc. in the contract-change effect below — see that effect's own comment
  // for why a per-candidate reset is required.
  const [maxLossOverride, setMaxLossOverride] = useState<MaxLossOverride | null>(initialMaxLossOverride);
  /** Phase G piece 5 (§6.1) — the trader's explicit exit-method pick for THIS
   *  contract, seeded from the page's scan-stamped `picks` map and re-synced on
   *  every identity change in the reset effect below, exactly as
   *  `maxLossOverride` above is. Local state rather than the prop read directly
   *  so a click paints immediately instead of waiting for a store round trip. */
  const [methodPick, setMethodPick] = useState<MethodPick | null>(initialMethodPick);
  // Display-only memory prevents an invalidated pick from showing another
  // method's latest results. Reset with the candidate/scan, or a new choice.
  const [recommendationInvalidated, setRecommendationInvalidated] = useState(false);
  const [structuralStop, setStructuralStop] = useState<StructuralStop | null | undefined>(
    data.exit.structuralStop,
  );
  const [structuralLoading, setStructuralLoading] = useState(false);
  const [structuralError, setStructuralError] = useState(false);
  // The fresh stock price checkStructure fetched to derive structuralStop —
  // persisted (not just used transiently) so a later R:R-vs-structural-stop
  // calc can reuse the SAME fresh price the backend actually used, instead of
  // falling back to data.price (the scan-time snapshot checkStructure was
  // specifically written to avoid). Seeded from data.exit alongside
  // structuralStop above, so a cached structure check the parent splices back
  // in on re-navigation restores BOTH halves — restoring the stop alone would
  // leave structuralPairing null and every row showing the defensive '—'.
  const [structuralStopStockPrice, setStructuralStopStockPrice] = useState<number | null>(
    data.exit.structuralStopStockPrice ?? null,
  );
  // Adversarial-audit finding 2 — the live stock price most recently fetched
  // by EITHER "Check Structure" or "Compute Arithmetic Plan" on the
  // Arithmetic card, so its "Stock entry price" header shows the SAME number
  // the stop/target math directly below it was computed against, instead of
  // the scan-time `data.price` snapshot silently drifting from the live
  // quote once either button has actually run. null until either has been
  // run this mount (reset alongside structuralStop/exitPlan/etc. on a
  // contract switch). Deliberately NOT cleared on a failed refetch — the
  // header keeps showing the last successfully fetched price rather than
  // reverting to the stale snapshot, same spirit as structuralStop's own
  // "a restored value stays on screen" behavior.
  const [arithmeticLiveStockPrice, setArithmeticLiveStockPrice] = useState<number | null>(null);
  // Tracks the in-flight "Check structure" request (if any) so a stale response
  // for a contract the user has since navigated away from (via CandidateNav
  // Prev/Next) can never overwrite the display for the new one — same class of
  // race step-7-trade-card/page.tsx's recomputePlan effects guard against.
  const structuralRequestRef = useRef<AbortController | null>(null);
  // Whether the CURRENT structuralStop value was obtained by a fetch performed
  // during THIS mount, as opposed to a cache-restored (or never-fetched) value.
  // A restored value can be arbitrarily old — it was measured against whatever
  // stock price was current the last time this exact contract/symbol was
  // viewed, which may be minutes, hours, or days ago. Gates
  // estimateFirstPassage's auto-fetch below: without this, restoring a cached
  // structuralStop makes `structuralStop === undefined` false, so the
  // auto-fetch never fires again for this candidate, and structuralPairing then
  // permanently combines that stale check-time price with the FRESH
  // premium/delta the estimate just fetched — silently overstating or
  // understating risk by however much the stock has moved since the cache was
  // written. Not state: it never needs to trigger a render on its own, only
  // to gate a callback's branch the next time it runs.
  const structuralIsFreshRef = useRef(false);
  // The mirror image of structuralIsFreshRef, tracking the OTHER side of
  // structuralPairing: whether the current firstPassageContext was
  // obtained by a fetch performed this mount, as opposed to a cache restore.
  // estimateFirstPassage already auto-refreshes a not-yet-fresh
  // structuralStop when Estimate is clicked, so that direction is covered —
  // but a MANUAL "Check structure" click can independently refresh
  // structuralStop while a restored (possibly stale) estimate is still on
  // screen, which is exactly the same mixed-vintage hazard structuralPairing
  // exists to avoid, just from the other side. Rather than also auto-firing
  // a full Estimate computation from "Check structure" (tried, reverted — it
  // adds two unwanted network calls for a user who only asked to check
  // structure, and duplicates a fetch on the very next real Estimate click
  // regardless), this ref instead feeds structuralPairing's own gate below:
  // computing an R:R requires BOTH sides confirmed fresh THIS mount. A fresh
  // Check-structure against a stale estimate simply shows no R:R until the
  // user's own next Estimate click brings both sides current — conservative,
  // but never wrong.
  //
  // An earlier version of this gate also accepted a "restored pair" — both
  // halves still holding whatever a single cache restore last wrote together
  // — on the reasoning that a restore writes both atomically, so they're
  // mutually consistent even if old. A fifth independent audit round found
  // that reasoning doesn't survive a SECOND restore: structuralBySymbol
  // (symbol-keyed) and estimatesByContract (contract-keyed) in
  // step-7-trade-card/page.tsx are two independent parent caches, each
  // writable on its own schedule. A fresh Check-structure-only click (this
  // ref's whole reason to exist) updates the PARENT's structural cache
  // without touching its estimate cache; the NEXT restore then pairs that
  // newly-fresh stop with whatever stale estimate the parent still has
  // cached for this contract — "restored together" describes the local
  // component's own two setState calls, not the two independent caches
  // upstream of them, and there is no cheap way to make it describe that
  // without threading pairing metadata through both caches (tried in
  // sketch form; it requires widening both cache entry shapes and both
  // write-back callback signatures across page.tsx and this file, for a
  // MEDIUM-severity, multi-navigation-only scenario). Removed rather than
  // patched again: correctness over convenience. The Estimate rows
  // themselves (targets, probabilities, option prices) still restore
  // instantly from cache exactly as before — only the DERIVED
  // R:R-vs-structural-stop figure now waits for both halves to be
  // independently reconfirmed fresh, same as it always required after a
  // genuine (non-cached) first visit.
  const firstPassageIsFreshRef = useRef(false);

  const defaultTargetPct = useSettingsStore((s) => s.targetProfitPct);
  // R3-7 -- the browser's copy of the GLOBAL premium stop. Residual: it can
  // differ from the server's yaml until the Settings page has mounted once.
  const globalPremiumStopPct = useSettingsStore((s) => s.premiumStopPct);
  // Seeded from the restored estimate's own context when the parent splices a
  // cached estimate back in — otherwise the % inputs would show the settings
  // default while the restored rows show the percentages the estimate was
  // actually run at, and a follow-up Estimate click would silently re-run at
  // different percentages than the numbers on screen.
  const [targetPct, setTargetPct] = useState(data.exit.firstPassageContext?.targetPct ?? defaultTargetPct);
  const [firstPassage, setFirstPassage] = useState<FirstPassageEstimate | null | undefined>(
    data.exit.firstPassage,
  );
  const [firstPassageLoading, setFirstPassageLoading] = useState(false);
  const [firstPassageError, setFirstPassageError] = useState(false);
  // The inputs estimateFirstPassage actually used — optionPrice in each
  // firstPassage.targets entry is premium*(1+pct) computed off THIS premium
  // (see first_passage.py), not data.contractDetails.mid, which can differ
  // once a fresh quote has been fetched. Persisted so a later R:R calc
  // subtracts the matching baseline instead of a stale one, and seeded from
  // data.exit so a restored estimate carries its baseline with it.
  const [firstPassageContext, setFirstPassageContext] = useState<FirstPassageContext | null>(
    data.exit.firstPassageContext ?? null,
  );
  // Same stale-response guard as structuralRequestRef above.
  // The barrier levels the currently-rendered race was computed against. Not
  // persisted to the parent cache: it exists only to detect that a barrier has
  // MOVED since this mount's estimate, and a restored estimate is refused by
  // firstPassageIsFreshRef anyway.
  // `contract` rides along so freshness can be derived from STATE rather than
  // from a ref cleared in an effect: on the first render after a contract
  // switch, `firstPassage`/`raceBarriers` still hold the previous contract's
  // values while `firstPassageIsFreshRef` has not been cleared yet, so a
  // ref-only gate rendered the PREVIOUS contract's armed stop and dollar edge
  // under the new symbol for one committed frame. `fromField` records whether
  // the editable premium-stop field actually set the barrier, decided at
  // request time against the premium the request used.
  const [raceBarriers, setRaceBarriers] = useState<
    { contract: string; stockStop: number; premiumStop: number; fromField: boolean } | null
  >(null);
  const firstPassageRequestRef = useRef<AbortController | null>(null);

  const [exitPlan, setExitPlan] = useState<ExitPlan | null | undefined>(data.exit.exitPlan);
  const [exitPlanLoading, setExitPlanLoading] = useState(false);
  const [exitPlanError, setExitPlanError] = useState(false);
  // Same stale-response guard as structuralRequestRef/firstPassageRequestRef above.
  const exitPlanRequestRef = useRef<AbortController | null>(null);

  const prevSymbolRef = useRef(data.symbol);
  const prevContractRef = useRef(data.contract);
  // Third identity the reset watches — see the `resetKey` prop's own note.
  const prevResetKeyRef = useRef(resetKey);
  // Single effect resetting BOTH structuralStop and firstPassage state on a
  // contract change — deliberately not two separate effects each comparing
  // against prevSymbolRef/prevContractRef: effects run in declaration order
  // within the same commit, so a first effect that updates those refs would
  // make a second effect's own "did it change" comparison always see "no
  // change" (the first effect already advanced the ref). Caught by the
  // first-passage stale-response regression test below.
  useEffect(() => {
    if (
      data.symbol !== prevSymbolRef.current
      || data.contract !== prevContractRef.current
      || resetKey !== prevResetKeyRef.current
    ) {
      structuralRequestRef.current?.abort();
      firstPassageRequestRef.current?.abort();
      exitPlanRequestRef.current?.abort();
      touchedRef.current = {
        entryLimit: initialEntryLimit != null,
        invalidation: initialInvalidation != null,
        premiumStop: initialPremiumStop != null,
      };
      // Same reset, same basis — a new candidate inherits the incoming card's
      // plan everywhere except the fields the parent restored an edit for.
      setEdited(restoredEdits({
        entryLimit: initialEntryLimit,
        invalidation: initialInvalidation,
        premiumStop: initialPremiumStop,
        contracts: initialContracts,
      }));
      setOverlay({
        ...defaultOverlay(data),
        contracts: initialContracts,
        premiumStop: initialPremiumStop ?? data.exit.premiumStop,
        entryLimit: initialEntryLimit ?? data.entry.limit,
        invalidation: initialInvalidation ?? data.exit.invalidation,
      });
      // Every one of these five reads data.exit — for a candidate nothing has
      // been run on they are all absent and this is still a full reset (the
      // pre-existing behaviour). When the parent has a cached result for the
      // incoming contract it splices all of them in together, so the estimate,
      // its baseline premium/delta, its % inputs, the structural stop and the
      // price that stop was measured against are restored as ONE consistent
      // set — never a half-restore that would leave structuralPairing null.
      setStructuralStop(data.exit.structuralStop);
      setStructuralStopStockPrice(data.exit.structuralStopStockPrice ?? null);
      setStructuralError(false);
      setStructuralLoading(false);
      // A restored value (or the genuine absence of one) is never "fresh this
      // mount" — see structuralIsFreshRef's declaration.
      structuralIsFreshRef.current = false;
      firstPassageIsFreshRef.current = false;
      setTargetPct(data.exit.firstPassageContext?.targetPct ?? defaultTargetPct);
      setFirstPassage(data.exit.firstPassage);
      setFirstPassageContext(data.exit.firstPassageContext ?? null);
      setRaceBarriers(null);
      setFirstPassageError(false);
      setFirstPassageLoading(false);
      setExitPlan(data.exit.exitPlan);
      setExitPlanError(false);
      setExitPlanLoading(false);
      // Adversarial-audit finding 2 — reset the Arithmetic header's live-quote
      // tracker too, or the new candidate would briefly show the PREVIOUS
      // candidate's live price above its own (freshly-reset) stop/target math.
      setArithmeticLiveStockPrice(null);
      // Feature 5 — re-sync to whatever the parent resolved for the incoming
      // candidate (its symbol-keyed cache), so the newly active card never
      // briefly shows the PREVIOUS candidate's override.
      setMaxLossOverride(initialMaxLossOverride);
      // Phase G piece 5 — same re-sync, same reason: the page's `picks` map is
      // keyed per contract, so the incoming candidate has its own entry and the
      // card must show THAT one, not the outgoing candidate's.
      //
      // DELIBERATELY DOES NOT CALL `onMethodPickChange`. §6.1 says a contract
      // change clears the pick, and it is already cleared -- by
      // `scanStore.setPickedContract`, which drops every other pick under the
      // symbol (`clearPicksForSymbol`), and by the per-contract keying, which
      // means the new key simply has no entry. Emitting null from here would
      // instead write null under the INCOMING key and wipe a pick the user
      // legitimately made on this contract a moment ago -- the same hazard
      // `initialPremiumStop`'s note describes for the typed fields.
      setMethodPick(initialMethodPick);
      setRecommendationInvalidated(false);
      prevSymbolRef.current = data.symbol;
      prevContractRef.current = data.contract;
      prevResetKeyRef.current = resetKey;
    }
  }, [data.symbol, data.contract, resetKey, initialContracts, defaultTargetPct, initialMaxLossOverride,
      initialPremiumStop, initialEntryLimit, initialInvalidation, initialMethodPick]);

  // Cancel any outstanding requests on unmount.
  useEffect(() => () => structuralRequestRef.current?.abort(), []);
  useEffect(() => () => firstPassageRequestRef.current?.abort(), []);
  useEffect(() => () => exitPlanRequestRef.current?.abort(), []);

  // Surface every structuralStop change (including the reset to `undefined`/`null`
  // above) to the parent, so it can attach the level to the position if/when this
  // trade is sent to the broker — TradeCard itself never writes back to `data`.
  //
  // Deliberately split into two effects (a ref sync + a ref-reading effect)
  // instead of one effect depending on both `structuralStop` and
  // `onStructuralStopChange`: the parent (step-7-trade-card/page.tsx) passes a
  // fresh inline closure on every render, bound to whatever symbol is active
  // AT THAT RENDER. On a Prev/Next contract switch, `data`/`onStructuralStopChange`
  // update in one commit, but `structuralStop` itself doesn't reset until the
  // contract-change effect ABOVE schedules it — a full render later. A single
  // effect keyed on both would fire in that in-between commit using THIS
  // render's (new-symbol) callback together with the STALE (old-symbol)
  // structuralStop value still sitting in state, silently attaching the old
  // candidate's structural stop price to the new one. Keying the
  // value-surfacing effect on the VALUES ALONE — reading the callback out of a
  // ref that a separate, harmless effect keeps current — means it only ever
  // fires when the state itself genuinely changes, by which point the ref has
  // already caught up to the current symbol's callback.
  //
  // `structuralStopStockPrice` is a dependency as well as `structuralStop`
  // because the parent caches the pair: the two are always set in the same
  // batch, so this normally fires once with a matched pair, and if they ever
  // landed in separate commits the second fire would correct the first rather
  // than leaving a half-written cache entry.
  const onStructuralStopChangeRef = useRef(onStructuralStopChange);
  useEffect(() => {
    onStructuralStopChangeRef.current = onStructuralStopChange;
  }, [onStructuralStopChange]);
  useEffect(() => {
    onStructuralStopChangeRef.current?.(structuralStop, structuralStopStockPrice);
  }, [structuralStop, structuralStopStockPrice]);

  // Same two-effect discipline, same reasoning, for the first-passage estimate —
  // the parent caches it per contract so re-navigating to this candidate restores
  // the Profit Targets rows instead of forcing another Monte Carlo round-trip.
  // `firstPassage` and `firstPassageContext` are BOTH dependencies because the
  // pair is what the cache stores; `targetPct` deliberately is NOT, because it
  // already travels inside `firstPassageContext` (snapshotted at request time),
  // so editing a % input after an estimate can never rewrite that estimate's
  // cached percentages.
  const onFirstPassageChangeRef = useRef(onFirstPassageChange);
  useEffect(() => {
    onFirstPassageChangeRef.current = onFirstPassageChange;
  }, [onFirstPassageChange]);
  useEffect(() => {
    onFirstPassageChangeRef.current?.(firstPassage, firstPassageContext);
  }, [firstPassage, firstPassageContext]);

  // Same two-effect discipline as above, for the exit-plan pipeline result.
  const onExitPlanChangeRef = useRef(onExitPlanChange);
  useEffect(() => {
    onExitPlanChangeRef.current = onExitPlanChange;
  }, [onExitPlanChange]);
  useEffect(() => {
    onExitPlanChangeRef.current?.(exitPlan);
  }, [exitPlan]);

  // The barrier race's repricing horizon falls back to a per-PRESET table when
  // the simulation itself produced no median days to a barrier, and the
  // stop-vs-premium gate picks its pass line per horizon. Both key on the
  // holding preset, not `scanHorizon` (a display string derived from the
  // collapsed scoring horizon) — Quarterly, SemiAnnual and Annual all collapse
  // to "Position", and repricing a 200-day hold like a 20-day one is exactly
  // the error the preset table exists to avoid. The backend collapses the seven
  // presets to the three scoring horizons itself (`horizon_key` in
  // app/scoring/stop_cost.py), so sending the preset is what keeps the gate and
  // the race on one horizon for one contract.
  //
  // DECLARED HERE, above the handlers, rather than beside the barrier-race code
  // that used to be its only reader: `computeExitPlan` below now sends it too,
  // and a `const` read from a closure declared further down the component reads
  // as an accident even where it is safe.
  const horizonPreset = useScanStore((s) => s.context?.horizonPreset ?? null);
  const holdMin = useScanStore((s) => s.context?.holdMin ?? null);
  const holdMax = useScanStore((s) => s.context?.holdMax ?? null);

  // THE GATE'S horizon, which is NOT always the holding preset — the paragraph
  // above is about the barrier race, and the two diverge on exactly one key.
  //
  // `Custom` carries no scoring horizon of its own; the app derives one from
  // the hold range (`scoringHorizonForHold`: <=4 Intraday, <=20 Swing, else
  // Position), and every other surface on the card is already reading that
  // resolved value — `context.horizon`, the display string Step 3 writes, is
  // built from it. The gate's pass line is per SCORING horizon, and the
  // backend's `_PRESET_TO_HORIZON` has to map a bare `custom` to something:
  // it picks `swing`, because the request carries no hold range to resolve
  // with. So a Custom 60-185d scan — labelled "Position (60-185d)" on this
  // very card, graded on Position's parameter row in Step 3 — was having its
  // stop cost graded against Swing's 0.70 instead of Position's 0.60, and the
  // badge echoed `passMaxFraction 0.70` beside it. Pre-B2 the card resolved
  // this itself (`scoringHorizonFromLabel(context.horizon)`) and got it right;
  // sending the raw key was the regression.
  //
  // `resolveParamsHorizon` collapses Custom and passes every other key through
  // UNCHANGED, so Quarterly/SemiAnnual/Annual keep their own keys and the
  // backend still maps all three to `position` — the reasoning above about not
  // repricing a 200-day hold like a 20-day one is untouched. An absent
  // `holdMax` falls back to the preset row's own bound rather than to 0, which
  // `scoringHorizonForHold` would read as Intraday.
  const gateHorizon = horizonPreset
    ? resolveParamsHorizon(horizonPreset, holdMax ?? presetByKey(horizonPreset).holdMax)
    : null;

  const computeExitPlan = useCallback(async () => {
    exitPlanRequestRef.current?.abort();
    const controller = new AbortController();
    exitPlanRequestRef.current = controller;
    const deadline = abortAfterTimeout(controller);
    // Same shape as estimateFirstPassage's: `null`, not `undefined`, so a real
    // failure overwrites the parent's cached plan rather than leaving it to
    // reappear on the next navigate-away-and-back.
    const failExitPlan = () => {
      setExitPlanError(true);
      setExitPlan(null);
    };
    setExitPlanLoading(true);
    setExitPlanError(false);
    setExitPlan(undefined);
    try {
      const cd = data.contractDetails;
      if (!cd) throw new Error('no contract selected');
      // Fresh stock + contract quotes, same reasoning as checkStructure/
      // estimateFirstPassage above — never data.price/cd.mid, which are
      // scan-time snapshots.
      const [stockQuote, contractQuote] = await Promise.all([
        api.getStockQuote(data.symbol, controller.signal).catch(() => null),
        api.getContractQuote(data.symbol, cd.strike, cd.expiry, cd.right, controller.signal).catch(() => null),
      ]);
      // NOT a bare `if (aborted) return`. Both sub-fetches swallow their own
      // rejection, so a deadline that fires while they hang never throws — it
      // arrives here instead, where a bare return would skip the error state
      // AND leave `firstPassage` at `undefined`, which the parent's cache reads
      // as "don't touch": the previous estimate for this contract would survive
      // and silently reappear on the next navigate-away-and-back. That is
      // exactly what the catch block below exists to prevent.
      if (isFinished(controller)) {
        if (deadline.timedOut) failExitPlan();
        return;
      }
      const entryPrice = stockQuote?.price ?? data.price;
      const premium = contractQuote?.price ?? cd.mid;
      const res = await api.getExitPlan({
        symbol: data.symbol,
        direction: data.direction,
        entry_price: entryPrice,
        strike: cd.strike,
        dte: cd.dte,
        premium,
        trend_score: data.stockBreakdown.trend,
        target_r_multiple: rrOverridesForPlan(useScanStore.getState().scanResult, useScanStore.getState().scanOverrides).rr_target_r_multiple,
        horizon_preset: gateHorizon ?? undefined,
      }, controller.signal);
      if (isFinished(controller)) {
        if (deadline.timedOut) failExitPlan();
        return;
      }
      setExitPlan({ ...res, computedAt: new Date().toISOString() });
      setArithmeticLiveStockPrice(entryPrice);
    } catch {
      if (!isRealFailure(controller, deadline)) return;
      failExitPlan();
      // Same reasoning as estimateFirstPassage's `.catch`: this was cleared to
      // `undefined` above (in-flight, which the parent's cache treats as
      // "don't touch") — an explicit `null` here forces the overwrite on a
      // genuine failure instead of leaving a stale cached plan to silently
      // reappear on the next navigate-away-and-back.
    } finally {
      clearTimeout(deadline.timer);
      if (isRealFailure(controller, deadline)) setExitPlanLoading(false);
    }
  }, [data.symbol, data.direction, data.price, data.contractDetails, data.stockBreakdown.trend, gateHorizon]);

  // Piece 2 (stop-model unification) — the stop level shared by the
  // stop-vs-premium gate, structuralPairing, and (below) the Monte Carlo request's
  // invalidation_price, so none of the three ever quotes a different number
  // for "the stop" on the same card. Prefers the exit plan's structural+ATR
  // final stop (compute_final_stop: max(structural, 2x ATR)) over the raw
  // order-block/swing level once an Arithmetic Plan has been computed for
  // this contract. `arithmeticLiveStockPrice` gates the exit-plan branch
  // (rather than falling back to data.price) because it doubles as a
  // freshness signal: it is set only when computeExitPlan actually ran THIS
  // mount (reset to null on every contract switch), so a cache-restored
  // exitPlan with no matching live price falls through to the raw
  // structural branch below instead of pairing a possibly-stale final stop
  // with a placeholder stock price.
  //
  // Declared here, ahead of estimateFirstPassage, specifically so the Monte
  // Carlo request below can read it instead of `exitPlan` directly — piece 1
  // originally read `exitPlan?.stop.price` unconditionally, which (unlike
  // this memo) accepts a cache-restored plan with no fresh stock price to
  // pair it with. That let Next/Prev in CandidateNav land on a card where
  // Monte Carlo measured against the exit-plan stop while the gate and
  // structuralPairing — both already reading `sharedStop` — measured against the
  // raw structural level: two different stops on one card. Routing the MC
  // request through `sharedStop` too closes that gap; keep it that way
  // rather than reverting to `exitPlan?.stop.price` for "simplicity".
  const sharedStop = useMemo(() => {
    if (exitPlan && arithmeticLiveStockPrice != null) {
      return { price: exitPlan.stop.price, stockPrice: arithmeticLiveStockPrice, source: 'exit_plan' as const };
    }
    if (structuralStop) {
      return { price: structuralStop.price, stockPrice: structuralStopStockPrice ?? data.price, source: 'structural' as const };
    }
    return null;
  }, [exitPlan, arithmeticLiveStockPrice, structuralStop, structuralStopStockPrice, data.price]);

  const estimateFirstPassage = useCallback(async () => {
    firstPassageRequestRef.current?.abort();
    const controller = new AbortController();
    firstPassageRequestRef.current = controller;
    // The one call that actually runs the 2000-path simulation, and the only
    // one that was left unbounded: firstPassageLoading gates the Estimate
    // button, so a hung /contracts/first-passage left "Estimating…" disabled
    // with no way out but navigating to another contract.
    const deadline = abortAfterTimeout(controller);
    // What "this estimate failed" means, in one place. `null` rather than
    // `undefined` on both pieces of state: the parent's cache treats `undefined`
    // as "in flight, don't touch", so only an explicit `null` overwrites a
    // stale cached entry instead of letting it reappear later.
    const failFirstPassage = () => {
      setFirstPassageError(true);
      setFirstPassage(null);
      setFirstPassageContext(null);
    };
    setFirstPassageLoading(true);
    setFirstPassageError(false);
    setFirstPassage(undefined);
    setFirstPassageContext(null);
    setRaceBarriers(null);
    firstPassageIsFreshRef.current = false;
    try {
      const cd = data.contractDetails;
      if (!cd) throw new Error('no contract selected');
      // Fetch fresh stock + contract quotes rather than reusing data.price /
      // data.contractDetails (scan-time snapshots) — same reasoning as
      // checkStructure above, and the same fix applied to the pre-existing
      // recompute-plan flow in step-7-trade-card/page.tsx.
      const [stockQuote, contractQuote] = await Promise.all([
        api.getStockQuote(data.symbol, controller.signal).catch(() => null),
        api.getContractQuote(data.symbol, cd.strike, cd.expiry, cd.right, controller.signal).catch(() => null),
      ]);
      // NOT a bare `if (aborted) return`. Both sub-fetches swallow their own
      // rejection, so a deadline that fires while they hang never throws — it
      // arrives here instead, where a bare return would skip the error state
      // AND leave `firstPassage` at `undefined`, which the parent's cache reads
      // as "don't touch": the previous estimate for this contract would survive
      // and silently reappear on the next navigate-away-and-back. That is
      // exactly what the catch block below exists to prevent.
      if (isFinished(controller)) {
        if (deadline.timedOut) failFirstPassage();
        return;
      }
      const referenceStockPrice = stockQuote?.price ?? data.price;
      const premium = contractQuote?.price ?? cd.mid;
      const delta = contractQuote?.delta ?? cd.delta;

      // The Profit Targets card always shows R:R-vs-structural-stop alongside
      // the estimate now. If a FRESH structural stop hasn't been obtained yet
      // THIS mount — never fetched, or the current value is a cache-restored
      // one from a possibly much earlier navigation (structuralIsFreshRef,
      // see its declaration) — fetch it here too, reusing referenceStockPrice
      // (just obtained above) instead of an independent getStockQuote call,
      // so this adds exactly one extra network call, not two. Fired once per
      // Estimate click, not on every render/navigation — same click-gated
      // model as before, just triggered from one button instead of two. A
      // restored value stays on screen (no flash to blank) while this runs
      // and is only replaced once the fresh pair actually lands — and if the
      // refresh fails instead, its `.catch` below clears structuralStop
      // rather than leaving the old one in place. Either way structuralPairing
      // never combines a stop it can't vouch for as fresh with THIS click's
      // premium/delta: it either gets a same-vintage pair or nothing to
      // compute from, never a silent mismatch.
      //
      // AWAITED, and it did not used to be. Firing it in the background and
      // sending the estimate immediately meant the first Estimate click of a
      // mount raced against its own stop: the request went out carrying the
      // flat scan-time invalidation (structuralStop still null), the race
      // snapshotted that same level, this fetch then landed, and
      // `raceBarriersMoved` flipped true — so the very first click rendered
      // "Barriers changed - re-run the estimate" and no bars at all, with
      // nothing on screen explaining why. The message was even honest: the
      // estimate really had been computed against the flat stop rather than
      // the structural one. The fix is not to click twice, it is not to
      // dispatch before the level the simulation depends on has resolved.
      // It still manages its own loading/error state via structuralRequestRef,
      // same as a manual "Check structure" click would, and that ref-swap means
      // the existing contract-change cleanup effect still aborts it correctly
      // if the user navigates away.
      let resolvedStructural = structuralStop ?? null;
      if (!structuralIsFreshRef.current && !structuralLoading) {
        structuralRequestRef.current?.abort();
        const structuralController = new AbortController();
        structuralRequestRef.current = structuralController;
        const structuralDeadline = abortAfterTimeout(structuralController);
        setStructuralLoading(true);
        setStructuralError(false);
        await api.getStructuralStop({
          symbol: data.symbol,
          direction: data.direction,
          stock_price: referenceStockPrice,
          // The contract, so the response carries the stop-vs-premium gate
          // priced at THIS level. All three or none — a partial set is a 422.
          strike: cd.strike,
          dte: cd.dte,
          // `premium`, the LIVE mid resolved above — not `cd.mid`. Both are in
          // scope here and they are different numbers: cd.mid is the scan-time
          // snapshot. B2 made this request price the gate, so the premium sent
          // is the one the badge prints AND the one the server inverts the IV
          // out of; sending the stale one against the fresh spot resolved two
          // lines above is what let the same contract read "100% of premium,
          // total loss" on this click and "64% of premium" after Compute
          // Arithmetic Plan, which sends the live mid.
          premium,
          horizon_preset: gateHorizon ?? undefined,
        }, structuralController.signal)
          .then((res) => {
            if (isFinished(structuralController)) return;
            const normalized = normalizeStructuralStopResponse(res);
            resolvedStructural = normalized;
            setStructuralStop(normalized);
            setStructuralStopStockPrice(referenceStockPrice);
            structuralIsFreshRef.current = true;
          })
          .catch(() => {
            if (!isRealFailure(structuralController, structuralDeadline)) return;
            setStructuralError(true);
            // This refresh only ever runs because structuralIsFreshRef was
            // false — i.e. whatever structuralStop currently holds (a cache
            // restore, or nothing) was never confirmed fresh this mount. On
            // failure, don't leave that unconfirmed pair sitting next to
            // firstPassageContext, which below may already hold THIS click's
            // fresh premium/delta by the time this rejection lands —
            // structuralPairing would otherwise silently render a mixed-vintage
            // number with no staleness cue, the exact failure mode this
            // whole mechanism exists to prevent.
            //
            // Deliberately `null`, not `undefined`. The parent's cache
            // reducer (cacheStructural) treats `undefined` as "ignore, don't
            // touch the cache" BY DESIGN — that's what lets an in-flight or
            // failed re-run leave an existing good value alone elsewhere.
            // Here that same protection backfires: it would leave the STALE
            // restored entry sitting in the parent's cache forever, so the
            // very next navigate-away-and-back would restore it again — the
            // one moment the local component clears itself would be
            // invisible outside this render. `null` is not a "nothing
            // happened" sentinel to this cache, it's the same shape a
            // genuine "checked, found nothing" result already produces
            // (see checkStructure's success path below), so writing it here
            // forces the parent to actually overwrite the stale entry. The
            // cost is a slightly imprecise placeholder next time ("No order
            // block or swing level found nearby" rather than "check
            // failed") — an acceptable trade for never re-serving a value
            // this refresh specifically determined it could no longer vouch
            // for.
            resolvedStructural = null;
            setStructuralStop(null);
            setStructuralStopStockPrice(null);
          })
          .finally(() => {
            clearTimeout(structuralDeadline.timer);
            if (isRealFailure(structuralController, structuralDeadline)) setStructuralLoading(false);
          });
        // The chain above is .then().catch().finally(), so awaiting it can
        // never reject — which is exactly the condition that makes a bare
        // `if (aborted) return` wrong here. This runs on the first Estimate
        // click of every mount, so a hung structural fetch killed the estimate
        // silently: no error copy, and firstPassage left at `undefined`, which
        // the parent's cache reads as "in flight, don't touch".
        if (isFinished(controller)) {
          if (deadline.timedOut) failFirstPassage();
          return;
        }
      }

      // `sharedStop`'s own precedence, re-derived from what THIS click actually
      // resolved. The memo cannot be read here: it is computed from state React
      // has not re-rendered yet, so it still holds the pre-refresh level. Both
      // the request below and the race's barrier snapshot must use this one, or
      // they disagree with each other the moment the render lands.
      // Computed once, so the value SENT and the value the card later reports
      // as "from the editable field above" are the same decision, taken against
      // the same premium.
      //
      // GATED ON TOUCHED-NESS, like every other consumer of this overlay.
      // `overlay.premiumStop` is SEEDED with `round(scan_mid x global, 2)`, so
      // on an untouched card it is the global wearing a dollar sign -- and
      // dividing that scan-time dollar by the freshly fetched `premium` gives a
      // third number that is neither. With a $5.20 scan mid, a 0.60 global and
      // a live premium of $4.00 the race was simulated at 78% and the row read
      // "stops out after losing ~78% of premium, from the editable field
      // above", for a field nobody had edited and a position that will be
      // armed at the 60% global. Untouched now yields undefined, which is what
      // makes the documented fallback to risk_rules.yaml reachable at all --
      // before this it was dead except on a degenerate seed.
      const sentPremiumStopPct = touchedRef.current.premiumStop
        ? premiumStopPctFromDollars(overlay.premiumStop, premium)
        : undefined;

      // Last-resort fallback is `overlay.invalidation`, NOT
      // `data.exit.invalidation`. Once the Invalidation field became
      // load-bearing (it is what `buildPaperPosition` stores as
      // `PortfolioPosition.stop`, which STOP_REACHED compares against the live
      // underlying), sending the seed here made the card quote the odds of a
      // stop the trade will not use: with no structural stop and no Arithmetic
      // plan — the DEFAULT state, since both are user-triggered buttons — an
      // edit from $140 to $132 left the invalidation probability, the stock-
      // stop risk leg and the dollar edge all measured at $140 while Place
      // Limit stored 132.
      const resolvedStockStop = (exitPlan && arithmeticLiveStockPrice != null)
        ? exitPlan.stop.price
        : (resolvedStructural?.price ?? overlay.invalidation);

      // NO STOP, NO SIMULATION. `overlay.invalidation` is null only on a card
      // restored from a scan session persisted before piece 3, whose stored
      // stop the v15 migration stripped as a flat percentage wearing the
      // resolved stop's name. Every other branch above is a real level.
      //
      // The engine would accept a 0 here and quietly answer a different
      // question: `estimate_stock_first_passage` gates the stop leg on
      // `invalidation_price > 0`, so a card with no stop would come back with
      // a probability of invalidation of zero and a barrier race missing one
      // of its barriers -- read on screen as "this trade cannot be stopped
      // out". Fail the estimate instead; the card already renders that state.
      //
      // The BUTTON stays enabled, deliberately. This branch is reached only
      // after the structural sub-fetch above has run, and a structural level
      // is a perfectly good stop for a card whose stored one was stripped --
      // so "Check structure, then Estimate" still works on a restored card.
      // Disabling on `overlay.invalidation == null` would refuse it before
      // finding out.
      if (resolvedStockStop == null) {
        failFirstPassage();
        return;
      }

      const res = await api.getFirstPassageEstimate({
        symbol: data.symbol,
        direction: data.direction,
        stock_price: referenceStockPrice,
        strike: cd.strike,
        dte: cd.dte,
        premium,
        delta,
        trend_score: data.stockBreakdown.trend,
        // Per D1 (stop-model-unification plan), Monte Carlo owns the same
        // structural+ATR stop as the Arithmetic card, not the flat scan-time
        // -3% (`data.exit.invalidation`). Sending the flat stop here was a
        // real discrepancy, not a display nit: the "probability of
        // invalidation" was being measured against a level up to 3x tighter
        // than the structural+ATR stop shown a few inches above on the same
        // card. Uses `resolvedStockStop` (above), which applies `sharedStop`'s
        // OWN precedence to the values this click resolved rather than reading
        // the memo, which React has not recomputed yet. That precedence is what
        // refuses a cache-restored exit plan with no fresh stock price to pair
        // it with and falls back to the raw structural level — something
        // `exitPlan?.stop.price` alone would not do. Both are frequently
        // absent (Compute Arithmetic Plan is user-triggered, and
        // `structuralStop` only populates after a Check-structure/Estimate
        // click), so it falls back to the flat stop when neither exists.
        //
        // Known limitation, deliberately not fixed here (tracked separately,
        // plan's Phase 2.4 "Freshness"): if the user re-runs Compute
        // Arithmetic Plan AFTER already running this estimate, the
        // already-rendered Monte Carlo probability does NOT retroactively
        // update to the new exit plan stop — it silently goes stale until
        // the user re-runs the estimate.
        invalidation_price: resolvedStockStop,
        t1_pct: targetPct.t1,
        t2_pct: targetPct.t2,
        t3_pct: targetPct.t3,
        // The barrier race's THIRD barrier, read from the card's own editable
        // "Premium stop" field (Q10 — piece 4's per-position stop stays
        // deferred). That field holds a DOLLAR amount; the barrier is defined
        // as a fraction of premium, so convert. `undefined` falls back to
        // risk_rules.yaml's premium_stop_pct rather than sending a value the
        // backend would reject.
        premium_stop_pct: sentPremiumStopPct,
        // Same three fields, same helper, as the recomputePlan calls behind the
        // Fixed % Ladder (step-7-trade-card/page.tsx). The two cards must
        // reprice at the same horizon and the backend cannot tell you when they
        // don't — resolve_reprice_days falls through to Swing on a dict miss
        // without complaining.
        ...horizonFieldsFrom({
          horizonPreset: horizonPreset ?? undefined,
          holdMin: holdMin ?? undefined,
          holdMax: holdMax ?? undefined,
        }),
      }, controller.signal);
      if (isFinished(controller)) {
        if (deadline.timedOut) failFirstPassage();
        return;
      }
      // Feature 8 (Final Recommendation) — computedAt stamped here, the same
      // client-set-on-receipt pattern as ExitPlan.computedAt (this endpoint
      // is stateless/fresh on every call, so it isn't returned by the API).
      setFirstPassage({
        targets: res.targets,
        invalidation: res.invalidation,
        // `null` when the backend refused to simulate (dte < 1). Carried
        // through as-is: the card distinguishes "refused" from "not run yet".
        race: res.race ?? null,
        computedAt: new Date().toISOString(),
      });
      // optionPrice in each target is premium*(1+pct) built from THIS
      // premium (first_passage.py) — persist it so a later R:R calc
      // subtracts the matching baseline, not data.contractDetails.mid.
      // targetPct is snapshotted here (not read back later) so the trio
      // stored alongside the estimate is exactly the trio the request above
      // carried, even if the user edited an input while it was in flight.
      setFirstPassageContext({ premium, delta, targetPct: { ...targetPct } });
      // The two barriers the race was actually run against, snapshotted at
      // request time. Both are live and user-movable, so the card compares
      // them against their current values and CLEARS the race when either has
      // moved — never silently re-sorts bars that were measured against a stop
      // the user has since changed.
      setRaceBarriers({
        contract: data.contract,
        stockStop: resolvedStockStop,
        premiumStop: overlay.premiumStop,
        fromField: sentPremiumStopPct != null,
      });
      firstPassageIsFreshRef.current = true;
    } catch {
      if (!isRealFailure(controller, deadline)) return;
      failFirstPassage();
      // Same reasoning, same fix, as the structural sub-fetch's `.catch`
      // above — and it applies here even more directly, since this IS the
      // primary fetch, not a sub-fetch. `firstPassage`/`firstPassageContext`
      // were already cleared to `undefined`/`null` at the top of this
      // function (the in-flight state), which `cacheFirstPassage` treats as
      // "don't touch" — so without this, a failure here leaves the PARENT's
      // cache holding whatever this contract's last successful estimate was,
      // unchanged, and it silently reappears (possibly next to a genuinely
      // fresh structuralStop from this very click's auto-trigger above) on
      // the next navigate-away-and-back. `null` forces the overwrite instead,
      // the same way it does for structuralStop.
    } finally {
      clearTimeout(deadline.timer);
      if (isRealFailure(controller, deadline)) setFirstPassageLoading(false);
    }
    // `structuralStop`, `exitPlan` and `arithmeticLiveStockPrice` are read
    // directly (to re-derive sharedStop's precedence from what THIS click
    // resolved), so they are listed. They were correct while omitted only
    // because sharedStop's own memo depends on exactly those three, so its
    // identity moved with them — an unstated coincidence that would break
    // silently the moment that memo is narrowed. `data.contract` is stamped
    // into raceBarriers for the freshness check.
  }, [data.symbol, data.direction, data.price, data.contract, data.contractDetails, data.stockBreakdown.trend, overlay.invalidation, structuralStop, exitPlan, arithmeticLiveStockPrice, targetPct, structuralLoading, overlay.premiumStop, horizonPreset, gateHorizon, holdMin, holdMax]);

  // R:R using the structural stop (order block / swing level) as the risk
  // basis instead of the original fixed "premium * 60%" assumption — only
  // computable once BOTH Check structure and Estimate have been run, and
  // using each other's FRESH persisted values (structuralStopStockPrice,
  // firstPassageContext), never data.price/data.contractDetails, for the
  // same staleness reasons documented on those two handlers above. NOTE:
  // "fresh" does not mean "identical" — Check structure and Estimate are
  // independent, user-triggered fetches, so if they're clicked minutes
  // apart the two stock prices they captured can legitimately differ; this
  // R:R is only as consistent as how close together the user ran both.
  // Whether the "Max loss if the stop is hit" readout is actually ON SCREEN.
  // Named because the Barrier Race card cross-references that readout by name,
  // and the race can render when this cannot: the race falls back to
  // `data.exit.invalidation` for its stock stop, while the gate needs a
  // resolved `sharedStop` and a structural fetch that neither failed nor is in
  // flight. An Estimate whose structural sub-fetch failed therefore printed
  // "see 'Max loss if the stop is hit' on the Arithmetic Profit Target card"
  // pointing at nothing on the page.
  //
  // A stop sitting exactly at the current price is not a stop, and the
  // structural row above already says so ("N/A (stop = price)"). The gate stays
  // off rather than printing a truthful-but-vacuous "PASS · 0% of premium"
  // beside it: the server WILL price that stop — value at the stop is value
  // now, so nothing is lost — and a PASS on a level that controls nothing reads
  // as a verdict on the trade. Pre-B2 this fell out of the arithmetic
  // (`stockMove === 0` returned null); stated here now that the arithmetic
  // lives on the server. Folded into `stopCostShown` rather than into the memo
  // so the "not computed" line hides with the badge — "no priced contract" is
  // the wrong explanation for "no stop".
  const stopIsAtPrice = sharedStop != null && sharedStop.price === sharedStop.stockPrice;
  const stopCostShown = !structuralError && !structuralLoading && !stopIsAtPrice;

  // Stop-vs-premium gate (B2, spec §3). The card RENDERS this; it does not
  // compute it. The block was priced by whichever endpoint produced the stop
  // `sharedStop` is currently reporting, which is why it is read back through
  // the SAME branch that memo picked rather than from a slot of its own: the
  // gate is only ever valid for one particular stop, so a verdict and a level
  // that came from different requests must not be able to meet on screen.
  //
  // The two endpoints disagreeing is the model working, not a bug — the
  // exit-plan stop is the wider of the structural level and the ATR floor, and
  // a wider stop costs more of the premium (spec §2.2).
  //
  // `?? null` covers the honest "not computed" cases in one place: no contract
  // was sent, no level was found, the IV would not invert, or — for the
  // exit-plan branch, which IS persisted — a plan restored from a blob written
  // before B2 shipped, which carries no block at all. `stopPremiumRisk` returns
  // null for each, and the badge below reads "not computed". Never a silent
  // PASS: the whole point of the third state is that a contract with no verdict
  // must not read like an unremarkable one.
  const stopRisk = useMemo(() => {
    if (!sharedStop) return null;
    const block = sharedStop.source === 'exit_plan'
      ? exitPlan?.stop.stopCost
      : structuralStop?.stopCost;
    return stopPremiumRisk(block ?? null);
  }, [sharedStop, exitPlan, structuralStop]);

  // The freshness pairing behind the "Structural level found" row.
  //
  // This used to also produce an R:R per target. That readout is gone
  // (barrier-race spec section 3.4): its risk leg was a delta approximation of the
  // stop distance CLAMPED TO PREMIUM, and once that clamp bound — routinely,
  // for a distant structural stop or a low-delta contract — the ratio reduced
  // to exactly the typed target percentage, the same number on every contract.
  // The Barrier Race card's stock-stop R:R replaces it with one whose risk leg
  // is `premium - BS(stop, ...)`, which does not collapse that way. The ratio
  // arithmetic is deleted rather than left computing into nothing; the PAIRING
  // it was wrapped in is what five audit rounds actually built, and it survives
  // unchanged below.
  //
  // Each side must be independently confirmed fresh this mount before being
  // combined — a stale restore sitting next to a fresh value is exactly the
  // mixed-vintage state this exists to prevent (see firstPassageIsFreshRef's
  // declaration above). firstPassage always needs its own check; sharedStop's
  // depends on where it came from: the raw-structural branch is only as fresh
  // as the last checkStructure/auto-fetch (structuralIsFreshRef), while the
  // exit-plan branch is only ever populated (see sharedStop's own memo) when
  // arithmeticLiveStockPrice was set THIS mount, which already IS its freshness
  // guarantee — no separate ref needed for that branch.
  //
  // NOTE: "fresh" does not mean "identical". Check structure / Compute
  // Arithmetic Plan and Estimate are independent, user-triggered fetches, so if
  // they are clicked minutes apart the two stock prices they captured can
  // legitimately differ.
  const structuralPairing = useMemo<'ok' | 'zero_risk' | null>(() => {
    if (!sharedStop || !firstPassage || !firstPassageContext) return null;
    if (!firstPassageIsFreshRef.current) return null;
    if (sharedStop.source === 'structural' && !structuralIsFreshRef.current) return null;
    // A stop sitting exactly on the price it was measured against is a
    // COMPLETED check with nothing to measure, not a check that has not run.
    // The row must distinguish the two.
    if (Math.abs(sharedStop.price - sharedStop.stockPrice) <= 0) return 'zero_risk';
    return 'ok';
  }, [sharedStop, firstPassage, firstPassageContext]);

  // Re-derives the SAME eligibility structuralPairing checks internally, for
  // the render below: "N/A (stop = price)" specifically means "this pair WAS
  // eligible and there was still nothing to measure" — without this, a pair
  // blocked purely for staleness would wrongly claim the stop sits at the
  // current price. Plain read, not memoized: cheap boolean, and it only needs
  // to be current as of this render anyway.
  const structuralPairEligible = firstPassageIsFreshRef.current
    && (sharedStop?.source === 'exit_plan' || structuralIsFreshRef.current);

  const checkStructure = useCallback(async () => {
    structuralRequestRef.current?.abort();
    const controller = new AbortController();
    structuralRequestRef.current = controller;
    const deadline = abortAfterTimeout(controller);
    const failStructural = () => {
      setStructuralError(true);
      setStructuralStop(null);
      setStructuralStopStockPrice(null);
    };
    setStructuralLoading(true);
    setStructuralError(false);
    setStructuralStop(undefined);
    setStructuralStopStockPrice(null);
    structuralIsFreshRef.current = false;
    try {
      // Fetch a fresh stock price rather than reusing data.price (a scan-time
      // snapshot that may be stale, especially for a contract the user never
      // overrode in Step 6, which has nothing else refreshing it). Falls back
      // to data.price only if the live quote fetch itself fails.
      //
      // The CONTRACT quote is fetched alongside it, on the same click and for
      // the same reason: `cd.mid` is a scan-time snapshot too. Before B2 that
      // did not matter here, because this request carried no contract at all;
      // now it prices the gate, so the premium sent is the one the badge
      // prints and the one the server inverts the IV out of. Pairing a fresh
      // spot with a stale mid is what made the same contract read one verdict
      // after "Check structure" and another after "Compute Arithmetic Plan"
      // (which has always sent the live mid), and could refuse to price an
      // ordinary ITM contract outright once the spot rallied past the stale
      // mid's intrinsic. Same `.catch(() => null)` fallback to `cd.mid` as
      // computeExitPlan and estimateFirstPassage use.
      const cd = data.contractDetails;
      const [stockQuote, contractQuote] = await Promise.all([
        api.getStockQuote(data.symbol, controller.signal).catch(() => null),
        cd
          ? api.getContractQuote(data.symbol, cd.strike, cd.expiry, cd.right, controller.signal).catch(() => null)
          : Promise.resolve(null),
      ]);
      // `.catch(() => null)` swallows the rejection, so our own deadline would
      // otherwise arrive at a bare early return and neither report nor clear.
      if (isFinished(controller)) {
        if (deadline.timedOut) failStructural();
        return;
      }
      const referenceStockPrice = stockQuote?.price ?? data.price;
      const res = await api.getStructuralStop({
        symbol: data.symbol,
        direction: data.direction,
        stock_price: referenceStockPrice,
        // The contract, so the response carries the stop-vs-premium gate priced
        // at THIS level. Spread all-or-nothing: the endpoint 422s a partial set,
        // and a card with no `contractDetails` (nothing picked yet) legitimately
        // sends none and gets no gate.
        ...(cd ? {
          strike: cd.strike,
          dte: cd.dte,
          premium: contractQuote?.price ?? cd.mid,
          horizon_preset: gateHorizon ?? undefined,
        } : {}),
      }, controller.signal);
      if (controller.signal.aborted) return;
      setStructuralStop(normalizeStructuralStopResponse(res));
      setStructuralStopStockPrice(referenceStockPrice);
      setArithmeticLiveStockPrice(referenceStockPrice);
      structuralIsFreshRef.current = true;
    } catch {
      if (!isRealFailure(controller, deadline)) return;
      setStructuralError(true);
      // Same fix as estimateFirstPassage's structural sub-fetch `.catch`:
      // this function cleared to `undefined` above (in-flight state, which
      // cacheStructural treats as "don't touch"), so without an explicit
      // `null` here on actual failure, a stale cached level would survive in
      // the PARENT untouched and silently reappear on the next
      // navigate-away-and-back.
      setStructuralStop(null);
      setStructuralStopStockPrice(null);
    } finally {
      clearTimeout(deadline.timer);
      if (isRealFailure(controller, deadline)) setStructuralLoading(false);
    }
  }, [data.symbol, data.direction, data.price, data.contractDetails, gateHorizon]);

  useEffect(() => {
    setOverlay((prev) => ({ ...prev, contracts: initialContracts }));
  }, [initialContracts]);

  // Follow the seed while the field is untouched. Declared AFTER the reset
  // effect above so it runs after it within the same commit — on a contract
  // change the reset has already decided `touchedRef.premiumStop`, and this is
  // then a no-op. Its real job is the case with no contract change at all:
  // `mergePlan` swapping `data.exit` under an overridden card (see
  // touchedRef.premiumStop's own note). Identity-guarded, so a seed that did
  // not move costs nothing.
  //
  // Deliberately does NOT call `onEditsChange`: while the field is untouched
  // the parent's cache holds `null` (it caches the dollar amount only when
  // `meta.touched.premiumStop`), which already means "inherit the global" --
  // the same thing following the seed means. Reporting the moved seed would
  // put a number nobody chose back into the send path, which is the defect
  // this early return exists to avoid.
  useEffect(() => {
    if (touchedRef.current.premiumStop) return;
    setOverlay((prev) =>
      prev.premiumStop === data.exit.premiumStop
        ? prev
        : { ...prev, premiumStop: data.exit.premiumStop },
    );
  }, [data.exit.premiumStop]);

  // The same rule for the other two threaded fields, and it matters in the
  // opposite direction: an untouched field caches `null` at the page level, so
  // `invalidationFor`/`entryLimitFor` already resolve to the card's CURRENT
  // value. If the overlay kept a stale seed after `mergePlan` swapped
  // `data.exit`, the card would DISPLAY the old level while the order used the
  // new one -- the same display-vs-send disagreement as the round-trip defect,
  // just with the two sides swapped.
  useEffect(() => {
    if (touchedRef.current.entryLimit) return;
    setOverlay((prev) =>
      prev.entryLimit === data.entry.limit ? prev : { ...prev, entryLimit: data.entry.limit },
    );
  }, [data.entry.limit]);

  useEffect(() => {
    if (touchedRef.current.invalidation) return;
    setOverlay((prev) =>
      prev.invalidation === data.exit.invalidation
        ? prev
        : { ...prev, invalidation: data.exit.invalidation },
    );
  }, [data.exit.invalidation]);


  // Direct-call pattern (see `onEditsChange`'s own doc comment) — same shape
  // as `applyMaxLossOverride` below: setOverlay and onEditsChange are two
  // sibling statements, not one nested inside the other's updater. An
  // earlier version called `onEditsChange` from INSIDE the setOverlay
  // functional updater; React updater functions must be pure, and it can
  // invoke them during another component's render pass, so that nested call
  // was actually updating Step7Page's state while React was rendering
  // TradeCard — "Cannot update a component while rendering a different
  // component". Depending on `overlay` here (instead of using the updater
  // form) is safe: every call site is a single discrete user event (a click
  // or an input's onChange), never several patch() calls batched in the same
  // tick against a stale closure.
  const patch = useCallback(
    (partial: Partial<EditOverlay>) => {
      // Only a CHANGE counts, not merely a key being present. `patch` carries
      // the whole overlay to the parent on every call, so an untouched field
      // rides along with a Contracts bump, and any caller may re-send an
      // unchanged value (EditableKV's save-on-blur did); recording either as
      // "the user chose this" is how the seeded default came to be posted as a
      // deliberate premium stop. Belt-and-braces with the no-op guard in
      // EditableKV.save -- either alone fixes the blur, and neither depends on
      // the other's caller behaving.
      for (const k of ['entryLimit', 'invalidation', 'premiumStop'] as const) {
        if (partial[k] !== undefined && partial[k] !== overlay[k]) {
          touchedRef.current = { ...touchedRef.current, [k]: true };
        }
      }
      // The card-level indicator's record, folded from the SAME partial under
      // the same "only a CHANGE counts" rule (markEdited), just across every
      // overlay field instead of the three above. Written here, next to the
      // `touchedRef` loop, so the two cannot be updated apart.
      setEdited((prev) => markEdited(prev, partial, overlay));
      const next = { ...overlay, ...partial };
      setOverlay(next);
      onEditsChange?.(next, { touched: touchedRef.current });
    },
    [overlay, onEditsChange],
  );

  /** Put a threaded field back to INHERITING its seed — the counterpart to
   *  `patch`, and the only way out of "touched" short of leaving the page.
   *
   *  Without this, `touchedRef` was a one-way latch: `patch` sets it true and
   *  nothing ever set it false, so the moment the user typed, that field was
   *  pinned for the life of Step 7 and `mergePlan` swapping `data.exit`
   *  underneath it changed nothing. Round 6's own note names "a card with no
   *  way back to inheriting" as the bad outcome it was fixing for the premium
   *  stop; it was then the permanent state for all three fields.
   *
   *  Reached by CLEARING the input (the same gesture the portfolio
   *  EditDrawer's premium-stop editor already uses to mean "inherit the
   *  global"), so it adds no new control to a card whose layout is governed by
   *  the schematic — and specifically does not pre-empt the still-unbuilt
   *  card-level edited indicator (decision EDITED-FLAG-2026-09-04).
   *
   *  Reports to the parent, which is the point: `onEditsChange` re-derives its
   *  caches from `meta.touched`, so an untouched field caches `null` and
   *  `invalidationFor`/`entryLimitFor`/`premiumStopDollarFor` fall back to the
   *  card's current value again. */
  const revert = useCallback(
    (key: 'entryLimit' | 'invalidation' | 'premiumStop') => {
      const seed =
        key === 'entryLimit' ? data.entry.limit
        : key === 'invalidation' ? data.exit.invalidation
        : data.exit.premiumStop;
      if (!touchedRef.current[key] && overlay[key] === seed) return;
      touchedRef.current = { ...touchedRef.current, [key]: false };
      // Clearing the input means "inherit the plan again", so it clears the
      // card-level flag too — this is the gesture EDITED-FLAG's indicator
      // exists to make discoverable (CLEAR-TO-INHERIT-2026-09-05).
      setEdited((prev) => (prev[key] ? { ...prev, [key]: false } : prev));
      const next = { ...overlay, [key]: seed };
      setOverlay(next);
      onEditsChange?.(next, { touched: touchedRef.current });
    },
    [overlay, onEditsChange, data.entry.limit, data.exit.invalidation, data.exit.premiumStop],
  );

  /** Card-level "edited" indicator (EDITED-FLAG-2026-09-04). Names the fields
   *  the user has changed AND left differing from the plan's CURRENT value —
   *  see lib/tradeCardEdits.ts for why both halves are required. Empty means
   *  the card is inheriting everywhere and the badge does not render. */
  const editedLabels = useMemo(
    () => editedFieldsAgainstPlan(overlay, planOverlay(data), edited)
      .map((f) => FIELD_LABELS[f]),
    [overlay, data, edited],
  );

  const displayRecId = useMemo(() => propRecId ?? generateRecId(), [propRecId]);
  const car = useMemo(
    () => capitalAtRisk(data.contractDetails?.mid ?? 0, overlay.contracts),
    [data.contractDetails?.mid, overlay.contracts],
  );

  // Risk-derived contract size: how many contracts the account's max-loss
  // budget affords at this exit plan's final stop. Feature 5 — now uses the
  // 3-arg resolveMaxLossLimitDollar form so an active pre-trade override
  // feeds this calculation immediately, the same shared resolution function
  // (not a reimplementation) the Portfolio EditDrawer's post-trade override
  // already calls. entryPremium intentionally mirrors checkTradeRisk's basis
  // (cd.mid, a scan-time snapshot) for consistency, not a fresh quote — see
  // risk.ts's comment on that same tradeoff.
  const limits = useRiskStore((s) => s.limits);
  const recommendedSize = useMemo(() => {
    if (!exitPlan) return null;
    const entryPremium = data.contractDetails?.mid ?? 0;
    const riskPerContract = maxLossAtStop(entryPremium, exitPlan.stop.contractPrice, 1);
    const riskBudget = resolveMaxLossLimitDollar(limits.portfolioValue, limits.maxLossPerTradePct, maxLossOverride);
    return recommendedContractSize(riskBudget, riskPerContract);
  }, [exitPlan, data.contractDetails?.mid, limits.portfolioValue, limits.maxLossPerTradePct, maxLossOverride]);

  /** PIECE 3 — the stop the SCAN resolved, with its provenance.
   *
   *  Read only while no Arithmetic Plan exists for this card: once one does,
   *  `exitPlan.stop` is the same levels recomputed against a fresh price and
   *  a chosen contract, and showing both would put two "final stop" rows on
   *  one screen. Absent means not computed — a card restored from a scan
   *  session persisted before piece 3, a bar feed too thin to form one true
   *  range, or a resolution that failed. */
  const scanFinalStop = data.exit.finalStop ?? null;

  const round2 = (n: number) => Math.round(n * 100) / 100;

  /** LIVE first, scan-time second. Both anchors below used to read straight off
   *  `data`, which comes from `scanResult` -- and scanStore persists that to
   *  localStorage, so after a reload they can be days stale while the page
   *  shows "Live stock:" and "Live mid:" a few rows up. See the props' notes. */
  //
  //  P2-23 (R1-11, R2-13) -- each step must be POSITIVE to win: a literal 0
  //  (a dead quote) falls through to the next anchor instead of disabling the
  //  bounds. The mid falls back to the plan's own entry limit, so a card with
  //  no live and no contract mid still bounds Entry limit and Premium stop;
  //  only a card with none of the three degrades to `{min: 0.01}`.
  const firstPositive = (...xs: (number | null | undefined)[]) =>
    xs.find((x): x is number => x != null && Number.isFinite(x) && x > 0) ?? 0;
  const anchorStockPrice = firstPositive(liveStockPrice, arithmeticLiveStockPrice, data.price);
  const anchorMid = firstPositive(liveMid, data.contractDetails?.mid, data.entry.limit);

  /** Bounds for the Invalidation field, which is now load-bearing: it is what
   *  `buildPaperPosition` stores as `PortfolioPosition.stop`, and
   *  `alertEngine` compares that directly against the live UNDERLYING price.
   *  Round 5 bounded the Premium stop field for exactly this reason and the
   *  field that became the position's stop was left at `min={0.01}` with no
   *  `max` and no directional check at all.
   *
   *  Two failures, both a single mistyped digit away on a $145 stock:
   *
   *    "1400" instead of "140" — `referencePrice <= stop` is true on the very
   *    first 30s scan, so the position raises a Critical STOP_REACHED the
   *    moment it is created, with Gmail and Telegram behind it.
   *
   *    "14" instead of "140" — worse, because it is SILENT: the send gate
   *    (`checkInvalidation`) only requires a positive number, so the trade
   *    goes out with a stop the underlying will never reach and the user
   *    believes they are protected.
   *
   *  DIRECTIONAL, because "outside the bounds" is not symmetric: a bullish
   *  stop sits below the price and a bearish stop above it, and a stop on the
   *  wrong SIDE is the same silent failure as "14" — it can never fire. The
   *  window is deliberately wide (a 50% adverse move) so it rejects mistyped
   *  digits, not merely wide stops.
   *
   *  REJECTS rather than clamps, matching the Premium stop field and the
   *  Portfolio drawer. Round 8 reversed round 5's clamp choice for both: a
   *  clamp does not refuse a fat-finger, it renames it -- "1400" became
   *  $143.55, 1% below spot, stored as the position's stop and firing Critical
   *  on the first ordinary wiggle while the user believed the stop was 7%
   *  away. Out of range, the field shows the previous value back.
   *
   *  ROUND 9 -- this doc block and the premium-stop one below it were both
   *  ORPHANED, stacked above each other and attached to `round2`, which is why
   *  both drifted into asserting the opposite of their code without anything
   *  pointing at them. Reattached; keep them on the const they describe. */
  const invalidationBounds = useMemo(() => {
    // NO ANCHOR, NO DIRECTIONAL CHECK -- and that residual is stated rather
    // than hidden. With no usable stock price there is nothing to compare a
    // stop against, so this degrades to the old "must be positive". Round 8
    // flagged the same fallback on `premiumStopBounds`; there the reject-rather-
    // than-clamp policy closes the dangerous half of it (typing 0 to mean "no
    // override" no longer commits $0.01 as a deliberate 0.19% stop), but a
    // wrong-SIDE stop on an anchorless card is still accepted. A card with no
    // price is not one an order should be placed from in the first place.
    if (!(anchorStockPrice > 0)) return { min: 0.01, max: undefined as number | undefined };
    return data.direction === 'Bearish'
      ? { min: Math.max(0.01, round2(anchorStockPrice * 1.01)), max: round2(anchorStockPrice * 1.50) }
      : { min: Math.max(0.01, round2(anchorStockPrice * 0.50)), max: Math.max(0.01, round2(anchorStockPrice * 0.99)) };
  }, [anchorStockPrice, data.direction]);

  /** Bounds for the per-position premium-stop DOLLAR field.
   *
   *  The field used to be `min={0.01}` with no max, and 0.01 is not a bound so
   *  much as an invitation: `parseFloat("0")` is 0, not NaN, so typing 0 -- the
   *  natural way to say "no override, use the global" -- clamped to $0.01,
   *  differed from the seed, and therefore counted as a deliberate edit. On a
   *  $5.20 mid the server stored 0.01/5.20 = 0.19%, putting the PREMIUM_STOP
   *  threshold at $5.19 and raising a Critical alert on the first cent of
   *  adverse move. (It also used to shrink the auto-trader's daily-loss count
   *  ~3000x; since A6 that gate counts the full premium and ignores the
   *  declared stop.)
   *
   *  10%-99% OF THE MID, because that is the range the app already considers a
   *  stop: the GLOBAL premium stop is bounded `ge=0.10, le=0.99` (le=1.0 before P2-02)
   *  (routers/risk_settings.py), and the server rejects a per-position ratio at
   *  or above 1. Deriving the dollar bounds from the mid keeps the card and
   *  those two rules from disagreeing, instead of hard-coding a second opinion.
   *  The two numbers themselves now live in `premiumStop.ts`, because the
   *  Portfolio drawer edits the same quantity as a PERCENT and used to accept
   *  a band this field refuses (round 12 finding 13) -- and so does the
   *  mid-to-dollar conversion, which has to round INWARD or this field's own
   *  boundary values fall outside the band the drawer enforces. See
   *  `premiumStopDollarBounds`.
   *
   *  There IS a way back to inheriting: round 7 added `revert()`, reached by
   *  clearing the input, with a tooltip on the field saying so -- the same
   *  gesture the Portfolio drawer uses. This block used to deny that ("the
   *  card has no equivalent"), which was true when it was written and false
   *  from round 7 on. A card-level indicator of WHICH fields are pinned is
   *  still the separate approved EDITED-FLAG build. */
  const premiumStopBounds = useMemo(() => {
    if (!(anchorMid > 0)) return { min: 0.01, max: undefined as number | undefined };
    return premiumStopDollarBounds(anchorMid);
  }, [anchorMid]);

  /** P2-24 (R1-12, R2-12) -- at a mid of $0.01 the band collapses to one
   *  penny, which is 100% of the mid and produces no stop. The row is then
   *  read-only. Only for a POSITIVE anchor whose band yields no stop: with no
   *  anchor at all the field stays editable as before. */
  const premiumStopReadOnly = anchorMid > 0
    && premiumStopBounds.max != null
    && premiumStopPctFromDollars(premiumStopBounds.max, anchorMid) === undefined;

  /** P2-19 (R1-14, R2-11) -- what the untouched Premium stop row SHOWS.
   *
   *  The seed is `round(scan_mid x global, 2)` from the scan, which after a
   *  reload can be days old: a $5.20 scan mid showed a $3.12 stop against a
   *  live $1.00 mid. Untouched and with a live mid, the row shows the global
   *  applied to the live mid, labelled "(global N%)". A touched field, or no
   *  live mid, shows the overlay as before.
   *
   *  DISPLAY ONLY -- it feeds the Premium stop row and nothing else. The send
   *  paths read the tracked touched flag and are unchanged (untouched sends
   *  null). The ladder's R:R (EditableTargetRow) stays on
   *  `overlay.premiumStop`, because its reward leg is on the scan basis (code
   *  round 1, C1-1). The barrier race's snapshot and `raceBarriersMoved` stay
   *  on `overlay.premiumStop` too, so a live mid arriving does not clear a
   *  finished race -- the residual being that the race's premium barrier is
   *  the scan-seeded dollar until the field is touched.
   *
   *  A bare focus-and-blur writes nothing even when this value CHANGES while
   *  the field is open (the one-shot live quote landing mid-edit): EditableKV
   *  commits only after a keystroke (its `typedRef`), not by comparing the
   *  draft with the current value (code round 1, C1-2). */
  const premiumStopTouched = touchedRef.current.premiumStop;
  const showsGlobalOnLiveMid = !premiumStopTouched && liveMid != null && liveMid > 0;
  const effectivePremiumStop = showsGlobalOnLiveMid
    ? Math.round((liveMid as number) * globalPremiumStopPct * 100) / 100
    : overlay.premiumStop;

  /** Bounds for the Entry limit — the field this branch made into the order's
   *  `limit_price`.
   *
   *  Round 8 called this the one CRITICAL of its round, and correctly: of the
   *  three fields threaded here it is the only one whose fat-finger is an
   *  EXECUTION error rather than an alerting one. Invalidation was bounded in
   *  round 7 and Premium stop in round 5; this one shipped with `min={0.01}`
   *  and no max. On a $2.50 mid, "25.0" typed for "2.50" put
   *  `limit_price: 25.0` on a BUY/OPEN order with nothing between it and the
   *  broker: `checkTradeRisk` and the capital-at-risk row both size off
   *  `contractDetails.mid`, not off the limit. On a wide options book a
   *  marketable buy limit an order of magnitude above the ask is a real fill.
   *  (Round 8 also noted the backend's `limit_price` was an unvalidated
   *  `Optional[float]`; round 9 bounded it `gt=0` on all three order schemas,
   *  so a non-positive limit is now refused server-side too. Magnitude is
   *  still only checked here, where the live mid is known.)
   *
   *  Wider than the other two, deliberately: paying up through the ask is a
   *  legitimate thing to do with a limit order, so this has to admit real
   *  intent while rejecting a misplaced decimal point. 3x catches the missing
   *  decimal (10x) with room to spare; 0.25x catches it in the other
   *  direction. */
  const entryLimitBounds = useMemo(() => {
    if (!(anchorMid > 0)) return { min: 0.01, max: undefined as number | undefined };
    return {
      min: Math.max(0.01, round2(anchorMid * 0.25)),
      max: Math.max(0.02, round2(anchorMid * 3)),
    };
  }, [anchorMid]);

  // Feature 5 — the $ figure the override editor displays as the "basis",
  // always shown (not silently used) whether or not an override is active.
  const maxLossLimitDollar = useMemo(
    () => resolveMaxLossLimitDollar(limits.portfolioValue, limits.maxLossPerTradePct, maxLossOverride),
    [limits.portfolioValue, limits.maxLossPerTradePct, maxLossOverride],
  );

  // Direct-call pattern (see the prop's own doc comment for why this doesn't
  // need the ref-synced-effect pattern onStructuralStopChange/onFirstPassageChange use).
  const applyMaxLossOverride = useCallback(
    (next: MaxLossOverride | null) => {
      setMaxLossOverride(next);
      onMaxLossOverrideChange?.(next);
    },
    [onMaxLossOverrideChange],
  );

  // `dirty` / `editedRR` and their helpers (isDirty, computeEditedRR) were
  // deleted with the "Projected R/R (+8% stock move)" readout below: it was
  // their only consumer, and an edit-tracking memo that feeds nothing is a
  // recomputation on every overlay keystroke for no rendered output. The
  // per-target R:R on the Sell-to-Close rows is a different function
  // (rrContribution) and is unaffected.

  // Has either barrier the race was run against moved since? The race is then
  // CLEARED, not recomputed: its bars, medians and both risk legs were all
  // measured against that stop, and re-running the simulation is the only way
  // to get honest ones. Editing the premium stop and watching the bars re-sort
  // must require a click; it must never appear to update on its own.
  // WHICH barrier moved, not just whether one did. The card prints "the
  // stock-stop probability is unaffected by the premium stop" in its
  // barriers-changed state, and that sentence is only true when the STOCK stop
  // is the one that stayed put. With a single boolean it was rendered after a
  // Check-structure or Arithmetic-Plan click too, quoting a probability
  // measured against a level that is no longer on screen anywhere.
  const capturedStockRisk = data.exit.stockStopLoss;
  const capturedStop = data.exit.stockStopLossAt;
  const currentRrStop = sharedStop?.price ?? overlay.invalidation;
  const hasCapturedStockRisk = typeof capturedStockRisk === 'number' && Number.isFinite(capturedStockRisk) && capturedStockRisk > 0;
  const rrStale = hasCapturedStockRisk && (typeof capturedStop !== 'number' || !Number.isFinite(capturedStop)
    || typeof currentRrStop !== 'number' || !Number.isFinite(currentRrStop) || Math.abs(currentRrStop - capturedStop) >= 0.005);
  // The full premium at the overlay's own entry (Phase C RR, D5). Neither the
  // premium stop nor the captured stock-stop loss is an R/R risk leg any more,
  // so rrStale no longer changes the ladder; it is still reported for the rail.
  const ladderRisk = overlay.entryLimit;
  useEffect(() => { onRrStaleChange?.(rrStale); }, [onRrStaleChange, rrStale]);

  const stockStopMoved = useMemo(() => {
    if (raceBarriers == null || firstPassage?.race == null) return false;
    // `overlay.invalidation` for the same reason `resolvedStockStop` uses it:
    // this is the guard that CLEARS a race whose barrier has moved, and it has
    // to watch the same value the race was actually run against. Reading the
    // seed here left one asymmetry with no defensible reason for it — editing
    // the Premium stop cleared the race (via the `overlay.premiumStop`
    // comparison in `raceBarriersMoved` below), editing the Invalidation did
    // not, so the card went on printing bars, medians and both risk legs
    // measured at a level no longer shown anywhere on it.
    return (sharedStop?.price ?? overlay.invalidation) !== raceBarriers.stockStop;
  }, [raceBarriers, firstPassage, sharedStop, overlay.invalidation]);

  const raceBarriersMoved = useMemo(() => {
    if (raceBarriers == null || firstPassage?.race == null) return false;
    return stockStopMoved || overlay.premiumStop !== raceBarriers.premiumStop;
  }, [raceBarriers, firstPassage, stockStopMoved, overlay.premiumStop]);

  // THE single gate on showing race numbers anywhere. It was previously spelled
  // out inline for BarrierRaceCard and simply omitted from the Final
  // Recommendation, so a restored estimate — `firstPassage` is seeded from the
  // parent's per-contract cache at mount, and `raceBarriers` is null then, so
  // nothing looked "moved" — refused to render the card and yet printed that
  // same arbitrarily-old race's armed stop and dollar edge in the decision
  // summary, while suppressing the un-stale invalidation fallback underneath
  // it. That is the mixed-vintage hazard section 3.3 exists to prevent, landing
  // in the one place on the card a number is most likely to be acted on.
  // Hoisted and named so the two sites cannot drift apart again.
  // Derived from STATE alone, deliberately, and not from firstPassageIsFreshRef.
  // `raceBarriers` is set only on a successful estimate and cleared in exactly
  // the places the ref is (the handler's entry, the contract-change effect), so
  // `raceBarriers.contract === data.contract` carries everything the ref
  // carried AND survives the frame between commit and that effect, which a ref
  // cleared inside it cannot.
  //
  // Keeping both read well but made neither load-bearing: with the ref in the
  // expression, deleting the contract term left all TradeCard tests green,
  // because the ref still hid the restored-estimate case that was the only
  // observable one. A guard no test can fail is not a guard. The ref remains
  // for its other consumers.
  //
  // TWO SEPARATE THINGS, deliberately. `estimateIsFresh` means "the estimate on
  // screen was fetched this mount, for the contract on screen"; `raceIsShowable`
  // adds "and neither barrier has moved since". The card needs the first,
  // because it renders the "barriers changed — re-run" copy itself and would
  // otherwise be handed a prop it can never act on. Everything that prints race
  // NUMBERS needs the second.
  //
  // RENAMED from `raceIsFresh` when TARGET-VINTAGE-2026-09-04 put the Final
  // Recommendation's `firstPassage.targets` rows behind it too. The value is
  // unchanged and the new name is the accurate one: `setRaceBarriers` fires on
  // EVERY successful estimate, including one the backend refused to run a race
  // for (`race: null` at dte < 1), and is cleared at the estimate handler's
  // entry and in the contract-change effect. So it never meant "a race came
  // back" — it means "an estimate did", which is precisely the vintage question
  // the target rows needed answered.
  // ONE term, not two. `firstPassageContext` was listed beside this and was
  // implied by it: setRaceBarriers is called on the line after
  // setFirstPassageContext, and both are cleared together at the handler's
  // entry and in the contract-change effect, so deleting it changed no test —
  // verbatim the criticism this comment levels at the ref it replaced. A guard
  // no test can fail is not a guard, and two of them are not better than one.
  // Display-only basis: prefer this result's server-rounded cents. The raw
  // captured request can differ at a half-cent due to Python's rounding.
  // A larger mismatch is not a matched basis for a dollar outcome.
  const capturedMcPremium = firstPassageContext?.premium;
  const echoedMcPremium = firstPassage?.race?.premiumUsed;
  const hasMcEcho = firstPassage?.race != null;
  const capturedMcValid = capturedMcPremium != null && Number.isFinite(capturedMcPremium) && capturedMcPremium > 0;
  const echoedMcValid = echoedMcPremium != null && Number.isFinite(echoedMcPremium) && echoedMcPremium > 0;
  const mcPremium = firstPassage == null ? null
    : hasMcEcho
      ? echoedMcValid && (firstPassageContext == null || (capturedMcValid && Math.abs(capturedMcPremium! - echoedMcPremium!) <= 0.005 + 1e-9))
        ? echoedMcPremium! : null
      : capturedMcValid ? Number(capturedMcPremium!.toFixed(2)) : null;
  const estimateIsFresh = raceBarriers?.contract === data.contract;

  const raceIsShowable = estimateIsFresh && !raceBarriersMoved;

  // Phase G piece 5 — PICK-ONLY variants of the two flags above, compared
  // against `prevContractRef.current` instead of the `data.contract` PROP.
  // Round-1 audit finding (2026-09-14), CONFIRMED BY REPRODUCTION, then a
  // round-2 finding against that fix's own hand-off-ref mechanism: on the
  // commit that switches contract, `data.contract` is already the incoming
  // candidate's while `raceBarriers` state is still the outgoing candidate's
  // for one transitional render, before the reset effect (below) has run.
  // `estimateIsFresh` above reads false in that one render purely from the
  // prop/state mismatch — correct for its own consumers (Final
  // Recommendation, BarrierRaceCard — TARGET-VINTAGE-2026-09-04, audited
  // separately and untouched here), but wrong for the method-pick gate,
  // where it can make a genuinely-fresh OUTGOING pick look gone and clear
  // the WRONG candidate's entry (see `pickedMethodGone` below).
  // `prevContractRef.current` is state, not a prop: it lags `data.contract`
  // by exactly the same one render `raceBarriers` does, and the reset effect
  // updates both together at its end — so on the transitional render they
  // are BOTH still the outgoing candidate's (no spurious mismatch), and on
  // every settled render (which is all of them, transitional or not, once
  // effects have run) `prevContractRef.current === data.contract` exactly,
  // so this behaves identically to `estimateIsFresh`/`raceIsShowable` there.
  // A hand-off ref between two effects was tried first and rejected: it
  // depends on `useEffect([pickedMethodGone])` re-firing only on a VALUE
  // CHANGE, which a round-2 audit found leaves the ref stuck `true` when a
  // reset doesn't change `pickedMethodGone` (swallowing a later, unrelated,
  // genuinely-real clear) and skips the clearing effect entirely when the
  // mixed and settled renders happen to agree (dropping a genuinely-stale
  // restored pick instead of merely delaying it). Comparing against state
  // instead of a prop removes the transitional render's bad reading at the
  // source, so nothing needs to be handed off between effects at all.
  const pickEstimateIsFresh = raceBarriers?.contract === prevContractRef.current;
  const pickRaceIsShowable = pickEstimateIsFresh && !raceBarriersMoved;

  // Before a choice, preserve the latest-run display, including the race
  // summary accompanying Monte Carlo. Explicit picks use their own results.
  const lastRunMethod = useMemo<'arithmetic' | 'monte_carlo' | null>(() => {
    const exitAt = exitPlan?.computedAt ? Date.parse(exitPlan.computedAt) : null;
    const fpAt = firstPassage?.computedAt ? Date.parse(firstPassage.computedAt) : null;
    if (exitAt == null && fpAt == null) return null;
    if (exitAt == null) return 'monte_carlo';
    if (fpAt == null) return 'arithmetic';
    return exitAt >= fpAt ? 'arithmetic' : 'monte_carlo';
  }, [exitPlan?.computedAt, firstPassage?.computedAt]);

  // ─── Phase G piece 5 (D4/D5) — the per-trade method pick ───────────────────
  //
  // ROWS ARE BUILT UNCONDITIONALLY; `unavailable` IS THE ONLY GATE. An earlier
  // version also re-tested `estimateIsFresh` / `raceIsShowable` inside each
  // `rows:` expression, which read as caution and was in fact a second copy of
  // a rule stated one line above it — no mutation of the duplicate could fail a
  // test, because `MethodPickSelector` refuses to offer rows for a method it is
  // rendering as disabled. That refusal is where the rule lives now, and it is
  // pinned there.
  //
  // Spec §6.1. FOUR OPTIONS, and an option whose numbers do not exist is
  // DISABLED WITH A REASON rather than hidden, so that a missing Monte Carlo
  // reads as "Estimate hasn't been run" and not as a method this card lacks.
  //
  // THE TWO PRICE SLOTS PER ROW ARE FIXED BY §6.1's TABLE AND ARE NOT A CHOICE
  // MADE HERE. `rowStockPrice` is underlying space and is the ONLY field that
  // may ever seed `resolved_tp_price`; `rowOptionPrice` is premium space and is
  // record-only. Ladder and Arithmetic quote stock levels and have no premium;
  // Barrier Race carries `targetOptionPrice` and NO stock level at all
  // (`BarrierRaceOutcome` simply has no such field), which is why §4.3 maps
  // every race pick to `('ladder', NULL)`. Monte Carlo is the trap: the card
  // RENDERS `optionPrice` (the Final Recommendation's rows below, and
  // BarrierRaceCard), so `displayPrice` is the premium the trader is reading
  // while `rowStockPrice` is the underlying level beside it. Collapsing the two
  // would put a $6.24 premium in a stock-price column, making `price >= 6.24`
  // true on the first tick and firing TP_HIT instantly on every bullish
  // position (alertEngine.ts:152, alert_generator.py:181).
  const methodPickOptions = useMemo<MethodPickOption[]>(() => [
    {
      // ALWAYS SELECTABLE (§6.1) — the ladder needs no run; its rows are the
      // card's own live T1/T2/T3. `targetPrice ?? stockPrice` is the same
      // fallback the Final Recommendation's ladder branch prints, so the pick
      // records the number that is on screen.
      method: 'ladder' as const,
      label: 'Ladder',
      unavailable: null,
      rows: data.exit.targets.map((t, i) => {
        const price = t.targetPrice ?? t.stockPrice;
        return {
          key: t.id ?? `ladder-${i}`,
          label: t.id ? t.id.toUpperCase() : `T${i + 1}`,
          displayPrice: price,
          rowStockPrice: price,
          rowOptionPrice: null,
        };
      }),
    },
    {
      method: 'arithmetic' as const,
      label: 'Arithmetic',
      unavailable: exitPlan ? null : 'Compute Arithmetic Plan first',
      rows: (exitPlan?.targets ?? []).map((t) => ({
        key: `arith-${t.rrRatio}`,
        label: `${t.rrRatio}:1`,
        displayPrice: t.price,
        rowStockPrice: t.price,
        rowOptionPrice: null,
      })),
    },
    {
      // GATED ON `pickEstimateIsFresh`, the PICK-ONLY sibling of the flag the
      // Final Recommendation's Monte Carlo rows are gated on
      // (TARGET-VINTAGE-2026-09-04's `estimateIsFresh`) — see its declaration
      // for why the pick gate needs its own copy, compared against
      // `prevContractRef.current` rather than the `data.contract` prop. When
      // it is false those rows are (for the DISPLAY flag) replaced by "Not
      // re-run this session", so there is nothing on screen to pick and the
      // method must not be selectable. This flag being per-mount AND
      // per-contract is what makes a Monte Carlo pick unable to outlive a
      // navigation or a reload — the clear effect below turns that into an
      // actual clear rather than a merely-disabled button.
      method: 'monte_carlo' as const,
      label: 'Monte Carlo',
      unavailable: firstPassage
        ? (pickEstimateIsFresh ? null : 'Estimate not re-run this session')
        : 'Run Monte Carlo Estimate first',
      rows: (firstPassage?.targets ?? []).map((t, i) => ({
        key: `mc-${t.pct}-${i}`,
        label: `T${Math.round(t.pct * 100)}%`,
        displayPrice: t.optionPrice,
        rowStockPrice: t.stockPrice,
        rowOptionPrice: t.optionPrice,
      })),
    },
    {
      // GATED ON `pickRaceIsShowable`, the PICK-ONLY sibling of
      // `raceIsShowable` — the STRICTER flag: it additionally requires that
      // neither barrier has MOVED since the estimate. `raceBarriersMoved`
      // itself never reads `data.contract`, only `sharedStop`/`overlay`
      // against `raceBarriers`, so it needs no pick-only copy of its own;
      // only the `estimateIsFresh` term inside it did.
      method: 'barrier_race' as const,
      label: 'Barrier Race',
      unavailable: firstPassage?.race
        // Phrased differently from BarrierRaceCard's own "Barriers changed —
        // re-run the estimate" on purpose: the two say the same thing in two
        // places on one screen, and identical strings make every `getByText`
        // in the suite ambiguous the moment this control is on the card.
        ? (pickRaceIsShowable ? null : 'Barriers moved since the estimate')
        : 'Run Monte Carlo Estimate first',
      rows: (firstPassage?.race?.outcomes ?? []).map((o) => ({
        key: `race-${o.targetPct}`,
        label: `T${Math.round(o.targetPct * 100)}%`,
        displayPrice: o.targetOptionPrice,
        // NULL, ALWAYS. Not `o.targetOptionPrice` — see the block comment above.
        rowStockPrice: null,
        rowOptionPrice: o.targetOptionPrice,
      })),
    },
  ], [data.exit.targets, exitPlan, firstPassage, pickEstimateIsFresh, pickRaceIsShowable]);

  // Direct-call pattern, per the prop's doc comment: a pick is a synchronous
  // click, like the max-loss override and unlike the exit plan.
  const applyMethodPick = useCallback((next: MethodPick | null) => {
    setMethodPick(next);
    setRecommendationInvalidated(false);
    onMethodPickChange?.(next);
  }, [onMethodPickChange]);

  // Same authoritative rows and stricter availability gate as the selector.
  // A race premium is NEVER promoted into a stock price, and the existing stop
  // basis survives this shortcut just as it survives a selector method change.
  const racePickOption = methodPickOptions.find((o) => o.method === 'barrier_race');
  const selectRaceTarget = (targetPct: number) => {
    if (!racePickOption || racePickOption.unavailable != null) return;
    const row = racePickOption.rows.find((r) => r.key === `race-${targetPct}`);
    if (!row) return;
    applyMethodPick({
      method: 'barrier_race',
      rowStockPrice: row.rowStockPrice,
      rowOptionPrice: row.rowOptionPrice,
      stopBasis: methodPick?.stopBasis ?? 'stock',
      pickedAt: new Date().toISOString(),
    });
  };
  const selectedRaceTarget = methodPick?.method === 'barrier_race'
    ? firstPassage?.race?.outcomes.find((o) =>
      methodPick.rowStockPrice === null && methodPick.rowOptionPrice === o.targetOptionPrice)?.targetPct ?? null
    : null;

  /** §6.1 — "picking a method whose numbers then go stale clears the pick".
   *
   *  STATED AS "THE PICKED METHOD IS NO LONGER SELECTABLE", which is wider than
   *  the spec's two named triggers (`estimateIsFresh` false, contract changed)
   *  and deliberately so: those two are the reasons a method goes away TODAY,
   *  and reusing `methodPickOptions`' own `unavailable` means a fifth reason
   *  added there cannot be forgotten here. It also covers a method that is not
   *  in the list at all, which is what a corrupted persisted pick looks like.
   *
   *  NOT `(find(...)?.unavailable ?? 'gone') != null`. `??` fires on null as
   *  well as undefined, and `unavailable: null` is precisely what an AVAILABLE
   *  method looks like — so that spelling collapses "found and selectable" into
   *  "gone" and clears every restored pick on mount. The two cases have to be
   *  separated explicitly.
   *
   *  NO "HAS THE RESET SETTLED YET" GUARD, and — after two rounds of getting
   *  this wrong — the reason is now the right one. `pickedOption`/
   *  `pickedMethodGone` are computed from `methodPickOptions`, which in turn
   *  is built from `pickEstimateIsFresh`/`pickRaceIsShowable`, NOT from
   *  `estimateIsFresh`/`raceIsShowable`. Those pick-only flags (declared
   *  above, beside `estimateIsFresh`) compare `raceBarriers.contract` against
   *  `prevContractRef.current` — STATE, not the `data.contract` PROP — so on
   *  the one transitional render where `data` has already switched but
   *  `raceBarriers`/`prevContractRef` haven't been reset yet, both sides of
   *  that comparison are still the OUTGOING candidate's, and nothing looks
   *  spuriously gone. `pickedMethodGone` can therefore only become `true` on
   *  a SETTLED render, where `methodPick` and the flags it is judged against
   *  are always from the same commit, transitional or not.
   *
   *  Two earlier guards were tried and rejected here, in order: an identity-
   *  ref `pickSettled` guard (42e6c6c3) that no mutation could be made to
   *  fail, and a boolean hand-off ref between this effect and the reset
   *  effect (round-1 audit fix, 2026-09-14) that a round-2 audit found could
   *  get stuck `true` and swallow a later, unrelated, genuinely-real clear —
   *  or, when the mixed and settled renders happened to agree, never fire at
   *  all and drop a genuinely-stale restored pick instead of merely delaying
   *  it. Both failed because they tried to suppress this effect for one
   *  render rather than removing the bad reading at its source. Comparing
   *  against `prevContractRef.current` fixes the SOURCE, so this effect
   *  needs no guard, no ref, and no memory between renders at all — it is
   *  the same effect `estimateIsFresh`'s own comments already describe:
   *  "a guard no test can fail is not a guard."
   *
   *  A boolean, not the option object, so the effect does not re-fire on every
   *  render just because `methodPickOptions` is a fresh array. */
  const pickedOption = methodPick
    ? methodPickOptions.find((o) => o.method === methodPick.method) ?? null
    : null;
  const pickedMethodGone = methodPick != null
    && (pickedOption == null || pickedOption.unavailable != null);

  const applyMethodPickRef = useRef(applyMethodPick);
  useEffect(() => { applyMethodPickRef.current = applyMethodPick; }, [applyMethodPick]);
  useEffect(() => {
    // Clearing sets `methodPick` to null, which makes `pickedMethodGone` false
    // on the next render, so this cannot loop.
    if (pickedMethodGone) {
      applyMethodPickRef.current(null);
      setRecommendationInvalidated(true);
    }
  }, [pickedMethodGone]);

  const recommendationMethod = methodPick?.method ?? lastRunMethod;
  const recommendationUnavailable = recommendationInvalidated || pickedMethodGone;

  const stockBars = [
    { label: 'Trend',     value: data.stockBreakdown.trend,     detailText: trendDetailText(data.stockBreakdown.trendDetail) },
    { label: 'Pullback',  value: data.stockBreakdown.pullback,  detailText: pullbackDetailText(data.stockBreakdown.pullbackDetail) },
    { label: 'Trigger',   value: data.stockBreakdown.trigger,   detailText: triggerDetailText(data.stockBreakdown.triggerDetail) },
    { label: 'Event',     value: data.stockBreakdown.event,     detailText: eventDetailText(data.stockBreakdown.eventDetail) },
    { label: 'Volatility',value: data.stockBreakdown.volatility,detailText: volDetailText(data.stockBreakdown.volDetail) },
  ];

  const contractBars = [
    { label: 'DTE fit', value: data.contractBreakdown.dteFit, detailText: dteDetailText(data.contractBreakdown.dteDetail) },
    { label: 'Delta', value: data.contractBreakdown.delta, detailText: deltaDetailText(data.contractBreakdown.deltaDetail) },
    { label: 'IV', value: data.contractBreakdown.ivAttractiveness, detailText: ivDetailText(data.contractBreakdown.ivDetail) },
    { label: 'Liquidity', value: data.contractBreakdown.liquidity, detailText: liquidityDetailText(data.contractBreakdown.liquidityDetail) },
    { label: 'Spread', value: data.contractBreakdown.spread, detailText: spreadDetailText(data.contractBreakdown.spreadDetail) },
  ];

  const methodSelector = (
    <MethodPickSelector
      options={methodPickOptions}
      pick={methodPick}
      onChange={applyMethodPick}
    />
  );

  // contracts.exit_plan prices both targets and StopCost with req.premium.
  // Use that echoed, cent-rounded calculation basis only; current quotes and
  // order edits are different vintages. A legacy/mismatched cost cannot supply it.
  const arithmeticCost = stopPremiumRisk(exitPlan?.stop.stopCost ?? null);
  const arithmeticPremium = arithmeticCost?.basis === 'bs_today'
    && arithmeticCost.stopPrice === exitPlan?.stop.price
    ? arithmeticCost.premium : null;

  // Recover result evidence with the selector's price pair. A changed row
  // cannot lend new probability/model data to a recorded older target.
  const chosenMatches = !recommendationUnavailable && pickedOption?.unavailable == null && methodPick
    && (methodPick.rowStockPrice != null || methodPick.rowOptionPrice != null)
    ? pickedOption?.rows.filter((r) => Object.is(r.rowStockPrice, methodPick.rowStockPrice)
      && Object.is(r.rowOptionPrice, methodPick.rowOptionPrice)) ?? [] : [];
  // The persisted schema has no row identity: equal price pairs cannot tell
  // which result's probability/time/model was chosen. Preserve that ambiguity.
  const chosenRow = chosenMatches.length === 1 ? chosenMatches[0] : null;
  const chosenIndex = chosenRow ? pickedOption!.rows.indexOf(chosenRow) : -1;
  const chosenArithmetic = methodPick?.method === 'arithmetic' && chosenIndex >= 0 ? exitPlan?.targets[chosenIndex] : null;
  const chosenMc = methodPick?.method === 'monte_carlo' && estimateIsFresh && chosenIndex >= 0 ? firstPassage?.targets[chosenIndex] : null;
  const chosenRace = methodPick?.method === 'barrier_race' && raceIsShowable && chosenIndex >= 0 ? firstPassage?.race?.outcomes[chosenIndex] : null;
  const chosenLadder = methodPick?.method === 'ladder' && chosenIndex >= 0 ? data.exit.targets[chosenIndex] : null;
  const chosenPremium = chosenArithmetic?.contractPrice ?? chosenMc?.optionPrice ?? chosenRace?.targetOptionPrice ?? chosenLadder?.estimatedOptionPrice;
  const chosenDays = chosenArithmetic?.expectedDays ?? chosenMc?.expectedDays ?? chosenRace?.daysTarget;
  const chosenProbability = chosenArithmetic?.probability ?? chosenMc?.probability;
  const chosenModel = chosenArithmetic?.rrModel ?? chosenLadder?.pricingMethod
    ?? ((chosenMc || chosenRace) && firstPassage?.race?.ivSolved === true ? 'BS repriced (IV-derived)' : null);
  const summaryPrice = (value: number | null | undefined, unit: string) => value != null && Number.isFinite(value) && value >= 0
    ? `$${value.toFixed(2)} ${unit}` : 'Unavailable';

  return (
    <div data-presentation="options-v2" className={styles.wrap}>
      {showMarketSentiment && <MarketSentiment s={data.sentiment} compact />}
      {/* 1. Header */}
      <section className={styles.headerCard} aria-label="Selected stock and contract">
        <div className={styles.headerRow}>
          <SymbolHeader
            ticker={data.symbol}
            company={data.company}
            price={data.price}
            direction={data.direction}
            status={data.status}
            size={24}
            showChartButton
          />
          {/* Card-level "edited" indicator (EDITED-FLAG-2026-09-04). A
              READOUT, not a control: the schematic governs this card's
              layout, and nothing here is clickable. It states only THAT the
              card departs from the plan and WHICH fields — deliberately no
              before/after numbers, which would be a second place for the
              card's figures to disagree with the rest of it. */}
          {editedLabels.length > 0 && (
            <Tooltip
              text={`Edited on this card, so it no longer matches the scan's plan: ${editedLabels.join(', ')}. Clearing a field's input restores the planned value.`}
              align="right"
              position="bottom"
            >
              <span className={styles.editedBadge}>
                <Text size={11} weight={500} tone="caution">Edited</Text>
              </span>
            </Tooltip>
          )}
        </div>
        <Text size={11} tone="secondary" className={styles.snapshotNote}>Stock and contract snapshots · live quotes, calculation results and order inputs are shown separately.</Text>
        <div className={styles.identityFacts}>
          <div>
            <Text size={12}>Stock score {data.stockScore}/100 · {data.stockConfidence}</Text>
            <Text size={11} tone="secondary">Backtested confidence: {data.confidence == null ? 'not supplied' : `${data.confidence}%`}</Text>
          </div>
          <div className={styles.contractIdentity}>
            <Text size={11} tone="dim">Selected contract</Text>
            <Text size={16} weight={500}>{data.contractDetails
              ? `$${data.contractDetails.strike} ${data.contractDetails.right === 'C' ? 'Call' : 'Put'} · ${data.contractDetails.expiry}`
              : data.contract}</Text>
            <Data size={11}>{data.contract}</Data>
            <Text size={12}>Contract score {data.contractScore}/100 · {data.contractConfidence}</Text>
            {data.contractDetails && <Text size={11} tone="secondary">${data.contractDetails.mid.toFixed(2)} mid / share · {data.contractDetails.dte}d DTE · ${car.toFixed(0)} CaR</Text>}
          </div>
        </div>
        {/* 5. Contract Details */}
        {data.contractDetails && (
          <section className={styles.contextDetails}>
            <Text size={14} weight={600}>Contract Details</Text>
            <Text size={11} tone="secondary">Contract snapshot</Text>
            <div className={styles.detailsGrid}>
              <DetailCell label="Strike" value={`$${data.contractDetails.strike}`} />
              <DetailCell label="Expiry" value={data.contractDetails.expiry} />
              <DetailCell label="Right" value={data.contractDetails.right === 'C' ? 'Call' : 'Put'} />
              <DetailCell label="Mid" value={`$${data.contractDetails.mid.toFixed(2)}`} />
              <DetailCell label="Δ" value={data.contractDetails.delta.toFixed(2)} mono />
              <DetailCell label="Θ / day" value={`$${data.contractDetails.theta.toFixed(2)}`} mono />
              {/* A percentile when a rank source answered, otherwise the
                  ABSOLUTE implied volatility — the label follows the figure,
                  because printing 45% IV as "IV rank 45" is the misreading
                  Phase A exists to end (PHASE-A-NULL-IVRANK-2026-09-06). */}
              <DetailCell
                label={resolveIv(data.contractDetails).basis === 'rank' ? 'IV rank' : 'IV'}
                value={formatIv(resolveIv(data.contractDetails), data.symbol).text}
                mono
              />
              <DetailCell label="DTE" value={`${data.contractDetails.dte}d`} mono />
              <DetailCell label="CaR" value={`$${car.toFixed(0)}`} mono />
            </div>
          </section>
        )}

        {/* 5b. Spread legs panel — shown only for multi-leg spreads */}
        {data.spreadType && data.spreadType !== 'single' && data.legs && data.legs.length > 0 && (
          <section className={styles.contextDetails}>
            <Text size={14} weight={600}>
              Spread Legs —{' '}
              {data.spreadType === 'bear_put' ? 'Bear Put Spread' : 'Bear Call Spread'}
            </Text>
            <div className={styles.legsTableHead}>
              <Text size={10} tone="dim">ACTION</Text>
              <Text size={10} tone="dim">QTY</Text>
              <Text size={10} tone="dim">STRIKE</Text>
              <Text size={10} tone="dim">RIGHT</Text>
              <Text size={10} tone="dim">EXPIRY</Text>
            </div>
            {data.legs.map((leg, i) => (
              <div key={i} className={styles.legRow}>
                <Data size={12} weight={500} tone={leg.action === 'BUY' ? 'pass' : 'caution'}>
                  {leg.action}
                </Data>
                <Data size={12}>{leg.qty}</Data>
                <Data size={12}>${leg.strike}</Data>
                <Data size={12}>{leg.right === 'C' ? 'Call' : 'Put'}</Data>
                <Data size={12}>{leg.expiry}</Data>
              </div>
            ))}
            <div className={styles.spreadSummary}>
              <KV
                label="Net debit / credit"
                value={
                  data.netDebitCredit != null
                    ? `${data.netDebitCredit >= 0 ? '+' : '−'}$${Math.abs(data.netDebitCredit).toFixed(2)}`
                    : '—'
                }
                mono
              />
              <KV label="Max profit" value={data.maxProfit != null ? `$${data.maxProfit.toFixed(2)}` : '—'} mono />
              <KV label="Max loss"   value={data.maxLoss   != null ? `$${data.maxLoss.toFixed(2)}`   : '—'} mono />
              <KV label="Breakeven"  value={data.breakeven  != null ? `$${data.breakeven.toFixed(2)}`  : '—'} mono />
            </div>
          </section>
        )}

        {data.alternatives && data.alternatives.length > 0 && (
          <div className={styles.altSection}>
            <button
              type="button"
              className={styles.altToggle}
              onClick={() => setAltOpen((v) => !v)}
              aria-expanded={altOpen}
            >
              <Text size={11} tone="dim">ALTERNATIVES ({data.alternatives.length})</Text>
              <Text size={11} tone="dim">{altOpen ? '▲' : '▼'}</Text>
            </button>
            {altOpen && (
              <div className={styles.altList}>
                {data.alternatives.map((alt, i) => (
                  <AlternativeContractRow key={`${alt.strike}|${alt.expiry}|${alt.right ?? ''}`} alt={alt} rank={i + 1} />
                ))}
              </div>
            )}
          </div>
        )}

      </section>
      <CollapsibleSection
        title="Stock & contract scores"
        storageKey="bamendjou:tradecard-scores-collapsed"
        defaultCollapsed
        keepMounted
      >
        <div className={styles.scorePanelsGrid}>
          {/* 3. Stock Scorecard | Contract — side by side */}
          <ScoreCardPanel
            title="Stock Scorecard"
            qualification={{ card: data, kind: 'stock' }}
            bars={stockBars}
            total={data.stockScore}
            confidence={data.stockConfidence}
            confidenceScore={data.confidence ?? null}
            confidenceText={data.confidenceText ?? null}
            statusTooltip="Backtested confidence tier for the stock signal. CAUTION means the pattern's historical win rate is marginal — consider reducing position size or waiting for a higher-conviction entry."
          />

          <ScoreCardPanel
            title={`Contract — ${data.contract}`}
            qualification={{ card: data, kind: 'contract' }}
            bars={contractBars}
            total={data.contractScore}
            confidence={data.contractConfidence}
            statusTooltip="Overall contract quality verdict. Combines DTE fit, delta, IV attractiveness, liquidity, and spread. CAUTION means at least one component is borderline — try a different strike or expiry for a cleaner contract."
            statusTooltipAlignRight
          />
        </div>
      </CollapsibleSection>
      <FundamentalHealthCard f={data.fundamentals} compact />

      <div className={styles.grid}>

        <CollapsibleSection
          title="Fixed % Ladder Plan"
          storageKey="bamendjou:tradecard-ladder-collapsed"
          className={styles.fullWidth}
        >
          <section aria-label="Fixed ladder targets" className={`${styles.planCard} ${styles.targetsCard}`}>
            <Text size={14} weight={600}>Sell-to-Close Plan</Text>
            <Text size={10} tone="dim">Scan-plan targets and stored option estimates. Edited stock targets use the existing local approximation; editing does not run a pricing model. Restored method choices and calculation results are shown separately below.</Text>
            <Text size={10} tone="dim">Dollar outcomes compare each alternative exit with the editable entry limit, using displayed premiums rounded to cents. Full-position exits and rung allocations are separate; do not add alternative outcomes.</Text>
            <Text size={10} tone="dim">R/R risk: full premium (no protective stop order).</Text>
            {data.exit.targetSource === 'capped' && <Text size={10} tone="caution">Bearish target capped to keep stock targets above the price floor.</Text>}
            <Text size={10} tone="dim">Fixed-formula ladder — independent of the other profit-target methods on this page; they can disagree.</Text>
            <div className={styles.targetsTable}>
              {data.exit.targets.map((t, i) => (
                <EditableTargetRow
                  key={t.id ?? i}
                  target={t}
                  index={i}
                  editedStockPrice={overlay.targets[i] ?? t.targetPrice ?? t.stockPrice}
                  entryLimit={overlay.entryLimit}
                  // The R:R risk leg: overlay.entryLimit, the full premium
                  // (Phase C RR, D5). Both legs stay on the SCAN basis -- its
                  // reward leg is estimatedOptionPrice - entryLimit -- so a
                  // live mid is never divided into a scan-mid reward.
                  premiumStop={ladderRisk}
                  // The backend's ratio only when it was computed on the same
                  // basis at the same entry. A saved pre-RR candidate
                  // ('premium_stop' / 'stock_stop' / absent) is recomputed,
                  // which is exact: estimatedOptionPrice does not depend on
                  // the risk basis.
                  authoritativeRr={data.exit.rrRiskBasis === 'full_premium' && overlay.entryLimit === data.entry.limit ? t.rrContribution : undefined}
                  data={data}
                  onStockPriceChange={(v) => {
                    const next = [...overlay.targets];
                    next[i] = v;
                    patch({ targets: next });
                  }}
                  totalContracts={overlay.contracts}
                />
              ))}
            </div>
          </section>

          {/* The "Risk / Reward" readout that stood here is gone: its risk leg
               was premium x a fixed percentage, so premium cancelled and the
               ratio reduced to the typed target % over the typed stop % — the
               same number on every contract. The Barrier Race card's
               stock-stop R:R replaces it with one that actually discriminates.
               overlay.premiumStop itself is UNTOUCHED: it is the premium-stop
               alert level and the race's third barrier. It is no longer the
               rrContribution risk denominator — that is the full premium
               (Phase C RR, D5). (computeEditedRR and isDirty were named
               here too until the Ladder-default copy of the "Projected R/R"
               readout went as well — that readout was their only caller, so
               both are gone. The field's remaining reasons stand on their
               own.) */}
        </CollapsibleSection>

        <section className={styles.handling} aria-label="Order inputs &amp; risk budget">
          <Text size={16} weight={600}>Order inputs &amp; risk budget</Text>
          <Text size={11} tone="secondary">
            Execution fields are separate from calculated and simulated results.
            Premium stop is a loss amount per share; a simulated option stop is an exit-price threshold.
          </Text>
          <div className={styles.handlingGrid}>
            {/* 4. Order Entry strip — thin, always-visible, non-collapsible. Pulled
                 out of the old Entry Plan card; sits above the three profit-target
                 method cards (Arithmetic / Monte Carlo / Fixed % Ladder) below.
                 Rendered exactly once per TradeCard (this component itself is
                 rendered once per active/basket candidate on Step 7). Max fill
                 comes from a global YAML formula (mid * (1 + slippage%)) and is
                 DISPLAY ONLY — see the row's own note below. This comment used to
                 end "the resulting dollar value has always been, and remains,
                 freely per-trade editable"; that stopped being true six lines
                 lower down and the sentence outlived it by a commit. */}
            <section className={styles.orderStrip} aria-label="Order Entry">
              <Text size={14} weight={600}>Order Entry</Text>
              <div className={styles.orderStripItem}>
                <KV label="Order type" value={data.entry.orderType} mono />
              </div>
              <div className={styles.orderStripItem}>
                <EditableKV
                  label="Limit"
                  value={overlay.entryLimit}
                  onChange={(v) => patch({ entryLimit: v })}
                  onRevert={() => revert('entryLimit')}
                  prefix="$"
                  min={entryLimitBounds.min}
                  max={entryLimitBounds.max}
                  mono
                />
              </div>
              <div className={styles.orderStripItem}>
                {/* READ-ONLY, deliberately. `maxFill` has exactly two readers in the
                    codebase — this row and `defaultOverlay` — so nothing downstream
                    has ever consumed it. That was internally consistent while all
                    five order/exit fields were inert; it stopped being consistent
                    the moment Limit, Invalidation and Premium stop became
                    load-bearing, because the five were rendered with an IDENTICAL
                    click-to-edit affordance and no way to tell which three reach
                    the broker. Threading it is a build, not a wiring fix (decision
                    MAXFILL-TIMESTOP-2026-09-05 defers it), so until then the card
                    shows the planned figure instead of inviting an edit it will
                    silently discard. */}
                <KV label="Max fill" value={`$${data.entry.maxFill.toFixed(2)}`} mono />
              </div>
              <div className={styles.orderStripItem}>
                <EditableKV
                  label="Contracts"
                  value={overlay.contracts}
                  onChange={(v) => patch({ contracts: v })}
                  min={1}
                  mono
                  decimals={0}
                />
              </div>
            </section>

          {/* P2-21 -- the Exit Plan (Invalidation, Premium stop, Time exit) is
               ALWAYS VISIBLE in the handling section: two of
               its three rows are what the order stores as the position's stops,
               and they were hidden behind a collapsed-by-default section. */}
            <section className={styles.planCard} aria-label="Exit Plan">
              <Text size={14} weight={600}>Exit Plan</Text>
              <dl className={styles.kvList}>
                <EditableKV
                  label="Invalidation"
                  value={overlay.invalidation}
                  onChange={(v) => patch({ invalidation: v })}
                  onRevert={() => revert('invalidation')}
                  prefix="$"
                  min={invalidationBounds.min}
                  max={invalidationBounds.max}
                  mono
                  // NULL only after the scanStore v15 migration stripped a
                  // pre-piece-3 flat percentage from a restored card. Says
                  // exactly what to do about it, because "—" beside an editable
                  // dollar field reads as zero, and because the card is
                  // unorderable until it is filled (checkInvalidation ->
                  // missing_invalidation).
                  nullLabel="not computed — re-run the scan"
                />
                {premiumStopReadOnly ? (
                  // P2-24 / R3-2 / decision Q-P2-2: a stop the user already typed
                  // is KEPT and shown as pinned (and still sent); an untouched
                  // field says the global applies.
                  <>
                    <KV
                      label="Premium stop"
                      value={premiumStopTouched && overlay.premiumStop != null
                        ? `$${overlay.premiumStop.toFixed(2)} (pinned)`
                        : `global (${Number((globalPremiumStopPct * 100).toFixed(2))}%)`}
                      mono
                    />
                    <div>
                      <Text size={10} tone="dim">
                        {premiumStopTouched
                          ? 'The mid is too small to edit a per-contract stop here. Your pinned stop is kept and sent; the server derives it against the fill, and drops it (with a notice) if it is at or above the fill.'
                          : 'The mid is too small for a per-contract premium stop — the global stop applies.'}
                      </Text>
                    </div>
                  </>
                ) : (
                  <>
                    <EditableKV
                      label="Premium stop"
                      value={effectivePremiumStop}
                      onChange={(v) => patch({ premiumStop: v })}
                      onRevert={() => revert('premiumStop')}
                      prefix="$"
                      min={premiumStopBounds.min}
                      max={premiumStopBounds.max}
                      mono
                    />
                    {showsGlobalOnLiveMid && (
                      <div>
                        <Text size={10} tone="dim">
                          {`(global ${Number((globalPremiumStopPct * 100).toFixed(2))}%)`}
                        </Text>
                      </div>
                    )}
                  </>
                )}
                {/* P2-03 (decision Q8) -- the exit the alerts actually make: an
                    option position raises TIME_STOP at TIME_STOP_DTE days to
                    expiry (alertEngine.ts, alert_generator.py). The plan's own
                    `timeStopDays` fires nothing and is no longer shown. */}
                <KV label="Time exit" value={`${TIME_STOP_DTE} DTE`} mono />
              </dl>
              <Text size={10} tone="dim">
                Invalidation is the editable execution stock stop. The scan supplies a structural/ATR stop
                (or legacy fallback); an Arithmetic calculation does not automatically replace this field.
                It also remains functionally load-bearing, not just a display figure: Send to broker stays disabled
                (&quot;Invalidation stop required&quot;) whenever this field is missing, regardless of what the
                Arithmetic card&apos;s stop shows — the two are not just independently-displayed numbers, one of them
                is a hard submit gate the other has no relationship to.
              </Text>
            </section>

            <section className={`${styles.planCard} ${styles.fullWidth}`} aria-label="Max loss budget">
              {/* Feature 5 — pre-trade max-loss override. Feeds recommendedSize
                   (and therefore Risk-derived size / Apply below) immediately.
                   `key` is tied to the candidate identity so the editor fully
                   remounts (clearing its own local editing/draftMode/draftValue
                   state) on every candidate switch — TradeCard itself is never
                   remounted on Prev/Next (no key at ITS call site), and the
                   existing contract-switch effect only resets the RESOLVED
                   `maxLossOverride` value, not this child's in-progress draft.
                   Without this, opening the editor on symbol A, typing a value,
                   and hitting Next before clicking Apply would leave that draft
                   sitting in the (still-mounted) editor instance; if the user
                   then clicked Apply while looking at symbol B, A's typed value
                   would silently become B's override. Remounting via key is
                   simpler and more robust here than lifting the draft state up
                   (nothing else needs it) or wiring a reset callback/ref through
                   TradeCard's own contract-switch effect. */}
              <Text size={14} weight={600}>Trade loss budget &amp; sizing</Text>
              <MaxLossOverrideEditor
                key={`${data.symbol}|${data.contract}`}
                override={maxLossOverride}
                limitDollar={maxLossLimitDollar}
                onApply={applyMaxLossOverride}
              />
              <div className={styles.budgetSummary}>
                <KV label="Entered quantity" value={`${overlay.contracts} contract${overlay.contracts === 1 ? '' : 's'}`} mono />
                <KV
                  label={data.spreadType && data.spreadType !== 'single' ? 'Selected-contract premium exposure' : 'Full-premium exposure'}
                  value={data.contractDetails && Number.isFinite(data.contractDetails.mid) ? `$${car.toFixed(0)}` : '—'}
                  mono
                />
                <Text size={10} tone="dim">Scan mid × entered contracts × 100; this snapshot exposure does not use the editable limit or live quote.</Text>
                {data.spreadType && data.spreadType !== 'single' ? (
                  <>
                    <Text size={10} tone="dim">Whole-spread debit/credit and max loss remain in Spread details above. Recommended size retains the selected-contract Arithmetic basis; it is not whole-spread sizing.</Text>
                    <Text size={10} tone="dim">Arithmetic stop-loss estimate unavailable for spreads; the selected-contract estimate is not whole-spread risk.</Text>
                  </>
                ) : exitPlan && data.contractDetails && Number.isFinite(data.contractDetails.mid) && Number.isFinite(exitPlan.stop.contractPrice) ? (
                  <>
                    <KV label="Arithmetic stop-loss estimate" value={`$${maxLossAtStop(data.contractDetails.mid, exitPlan.stop.contractPrice, overlay.contracts).toFixed(2)}`} mono />
                    <Text size={10} tone="dim">For entered quantity, using scan mid and the returned Arithmetic contract value at its calculation stop. Same basis as recommended size; separate from execution stops, today&apos;s stop-cost check and race median-day loss.</Text>
                  </>
                ) : (
                  <Text size={10} tone="dim">Arithmetic stop-loss estimate unavailable — compute an Arithmetic plan with a selected contract.</Text>
                )}
                <Text size={10} tone="dim">The loss budget affects recommended size, not target probability. Apply size explicitly; estimated stop loss does not bound full-premium risk.</Text>
              </div>
              {recommendedSize && (
                <div className={styles.structuralStop}>
                  <Text size={10} tone="dim">
                    Risk-derived size: {recommendedSize.recommended} contract{recommendedSize.recommended === 1 ? '' : 's'}{' '}
                    ({formatRecommendedContractSizeRaw(recommendedSize)} exact)
                  </Text>
                  <button
                    type="button"
                    className={styles.btn}
                    // recommendedContractSize() only returns null when riskBudget<=0 —
                    // whenever 0 < riskBudget/riskPerContract < 1 (a modest override, or
                    // just a portfolio-default budget smaller than one contract's risk on
                    // an expensive/wide-stop name), `recommended` is legitimately 0. The
                    // shared per-symbol Contracts map (Feature 7) is read with `?? 1` at
                    // its two order-placement sites, which does NOT catch 0 (only null/
                    // undefined) — writing 0 here would silently corrupt the shared field
                    // and the backend would then reject quantity:0 with an opaque 422 that
                    // gives the user no clue Apply is what broke it. Clamped at the write
                    // site AND disabled below for defense in depth: disabling communicates
                    // the actual budget constraint instead of silently flooring to 1, which
                    // could otherwise mislead the user about position size.
                    onClick={() => patch({ contracts: Math.max(1, recommendedSize.recommended) })}
                    disabled={recommendedSize.recommended < 1}
                    aria-label="Apply recommended contract size"
                  >
                    <Text size={12} weight={500}>Apply</Text>
                  </button>
                </div>
              )}
            </section>
          </div>
        </section>
        <section aria-label="Structure & Stops" className={styles.structureSection}>
          <div className={styles.scoreCardHeader}>
            <Text size={14} weight={600}>Structure &amp; Stops</Text>
            <Text size={11} tone="secondary">Calculation geometry</Text>
          </div>
          <dl className={styles.kvList}>
            <KV label="Execution stock invalidation" value={overlay.invalidation != null ? `$${overlay.invalidation.toFixed(2)}` : 'Not computed — re-run the scan'} mono />
          </dl>
          <Text size={11} tone="dim">Calculation does not replace your execution stock invalidation. Edit it in Order inputs &amp; risk budget.</Text>
          <Text size={10} tone="dim">ATR floor is backend-configured; the returned floor price and ATR(14) below describe this calculation.</Text>
          {!exitPlan && (
            <div className={styles.targetsTable}>
                <div className={styles.targetRow}>
                  <div className={styles.targetMain}>
                    {scanFinalStop ? (
                      <>
                        <div className={styles.targetId}>
                          <Text size={12} weight={600}>Bottom (final stop)</Text>
                        </div>
                        <div className={styles.targetValues}>
                          <KV label="Price" value={`$${scanFinalStop.price.toFixed(2)}`} mono />
                          <KV
                            label={structuralStopSourceLabel(scanFinalStop.structuralSource ?? null)}
                            value={scanFinalStop.structuralPrice != null
                              ? `$${scanFinalStop.structuralPrice.toFixed(2)}`
                              : 'No structural stop found'}
                            mono
                          />
                          <KV
                            label="ATR-floor price"
                            value={scanFinalStop.atrFloorPrice != null
                              ? `$${scanFinalStop.atrFloorPrice.toFixed(2)}` : '—'}
                            mono
                          />
                          <KV label="ATR(14)" value={`$${scanFinalStop.atr.toFixed(2)}`} mono />
                          <KV
                            label="Structural ↔ ATR-floor distance"
                            value={scanFinalStop.distanceDollar != null
                              ? `$${scanFinalStop.distanceDollar.toFixed(2)}` : '—'}
                            mono
                          />
                          {/* The two the scan cannot answer, said rather than
                              omitted — an absent row reads as "there is no
                              such thing", not "not computed yet". */}
                          <KV label="Contract value at stop" value="—" mono />
                          <KV label="Max loss if stopped" value="—" mono />
                        </div>
                        {scanFinalStop.stopSource != null && scanFinalStop.atrFloorPrice != null && (
                          <Text size={10} tone="dim">
                            {stopJustification({
                              source: scanFinalStop.stopSource,
                              structuralPrice: scanFinalStop.structuralPrice ?? null,
                              atrFloorPrice: scanFinalStop.atrFloorPrice,
                              distanceDollar: scanFinalStop.distanceDollar ?? null,
                            })}
                          </Text>
                        )}
                        <Text size={10} tone="dim">
                          From the scan. Compute an Arithmetic Plan to price this stop
                          against the contract and size the position. {scanFinalStop.computedAt ? `As of ${formatHHMM(scanFinalStop.computedAt)}.` : ''}
                        </Text>
                      </>
                    ) : (
                      <Text size={12} tone="dim">
                        Bottom (final stop) — not computed — re-run the scan
                      </Text>
                    )}
                  </div>
                </div>
            </div>
          )}
          {exitPlan && (
            <div className={styles.targetsTable}>
                <div className={styles.targetRow}>
                  <div className={styles.targetMain}>
                    <div className={styles.targetId}>
                      <Text size={12} weight={600}>Bottom (final stop)</Text>
                    </div>
                    <div className={styles.targetValues}>
                      <KV label="Price" value={`$${exitPlan.stop.price.toFixed(2)}`} mono />
                      <KV
                        label={structuralStopSourceLabel(exitPlan.stop.structuralSource)}
                        value={exitPlan.stop.structuralPrice != null ? `$${exitPlan.stop.structuralPrice.toFixed(2)}` : 'No structural stop found'}
                        mono
                      />
                      <KV label="ATR-floor price" value={`$${exitPlan.stop.atrFloorPrice.toFixed(2)}`} mono />
                      <KV label="ATR(14)" value={`$${exitPlan.atr.toFixed(2)}`} mono />
                      <KV
                        label="Structural ↔ ATR-floor distance"
                        value={exitPlan.stop.distanceDollar != null ? `$${exitPlan.stop.distanceDollar.toFixed(2)}` : '—'}
                        mono
                      />
                    </div>
                    <Text size={10} tone="dim">{stopJustification(exitPlan.stop)}</Text>
                    <Text size={10} tone="dim">{arithmeticLiveStockPrice != null ? 'Calculated this session' : 'Restored Arithmetic calculation'}{exitPlan.computedAt ? ` · ${formatHHMM(exitPlan.computedAt)}` : ''}; reference stock price {arithmeticLiveStockPrice != null ? `$${arithmeticLiveStockPrice.toFixed(2)}` : 'unavailable for restored calculation'}.</Text>
                    <dl className={styles.kvList}>
                      <KV label="Arithmetic contract value at stop" value={`$${exitPlan.stop.contractPrice.toFixed(2)}/share`} mono />
                      <KV label="Arithmetic stop pricing" value={exitPlan.stop.rrModel} />
                      <KV label="Arithmetic structural confidence" value={exitPlan.stop.structuralConfidence != null ? `${exitPlan.stop.structuralConfidence}%` : '—'} mono />
                    </dl>
                    <Text size={10} tone="dim">Arithmetic contract estimate; separate pricing basis from the stop-cost check below.</Text>

                  </div>
                </div>
            </div>
          )}
          {/* Standalone Check Structure — runs independently of the full
               compute below; its result shows on its own. Reuses the same
               checkStructure handler / structuralStop state as before. */}
          <div className={styles.structuralStop}>
            <button
              type="button"
              className={styles.btn}
              onClick={checkStructure}
              disabled={structuralLoading}
            >
              <Text size={12} weight={500}>
                {structuralLoading ? 'Checking structure…' : 'Check structure'}
              </Text>
            </button>
            {structuralError && (
              <Text size={11} tone="reject">Couldn&apos;t check structure — try again.</Text>
            )}
            {!structuralError && structuralLoading && (
              <Text size={11} tone="dim">Checking…</Text>
            )}
            {!structuralError && !structuralLoading && structuralStop === undefined && (
              <Text size={11} tone="dim">—</Text>
            )}
            {!structuralError && !structuralLoading && structuralStop === null && (
              <Text size={11} tone="dim">No structural stop found</Text>
            )}
            {!structuralError && !structuralLoading && structuralStop != null && structuralStop.distancePct === 0 && (
              <Text size={11} tone="dim">N/A (stop = price)</Text>
            )}
            {!structuralError && !structuralLoading && structuralStop != null && structuralStop.distancePct !== 0 && (
              <div className={styles.structuralSnapshot}>
                <Text size={10} tone="dim">{structuralIsFreshRef.current ? 'Standalone structural check refreshed this session' : 'Restored standalone structural check'}; independent of the final structural/ATR stop above.</Text>
                <dl className={styles.kvList}>
                <KV label="Structural check stock reference" value={`$${(structuralStopStockPrice ?? data.price).toFixed(2)}`} mono />
                <KV label="Structural confidence" value={`${structuralStop.confidence}%`} mono />
                <KV
                  label={structuralStopSourceLabel(structuralStop.source)}
                  value={`$${structuralStop.price.toFixed(2)} (${structuralStop.distancePct.toFixed(1)}% away)`}
                  mono
                />
                </dl>
              </div>
            )}
            {/* "Not computed", never a silent PASS. The gate has a third state
                by design (spec §3): no contract on the card, an IV that would
                not invert, an expiring contract, or an exit plan restored from
                a blob written before the gate moved server-side. A missing
                badge would read as an unremarkable contract, which is the one
                thing this readout must never do. Gated on `stopCostShown` like
                the badge itself, so a failed or in-flight structural fetch
                shows its own state rather than two contradicting ones. */}
            {stopCostShown && !stopRisk && sharedStop && (
              <div className={styles.stopRiskGate}>
                <Text size={10} tone="dim">MAX LOSS IF THE STOP IS HIT</Text>
                <Text size={11} tone="dim">
                  Not computed — no priced contract for this stop.
                </Text>
              </div>
            )}
            {stopCostShown && stopRisk && (
              <div className={styles.stopRiskGate}>
                <div className={styles.stopRiskHead}>
                  <Text size={10} tone="dim">MAX LOSS IF THE STOP IS HIT</Text>
                  <StatusBadge
                    status={stopRisk.status}
                    label={formatStopLossBadge(stopRisk)}
                    tooltip={
                      stopRisk.status === 'PASS'
                        ? 'The contract still holds meaningful value if this stop is hit — the cheaper candidate to be wrong on.'
                        : stopLossIsTotalOnPrintedFigures(stopRisk)
                          ? 'At this stop the contract is a total loss, so the stop is not a risk control on it. A closer stop, or a higher-delta strike, would make it one. Not a reason to skip the trade — a reason to size it knowing that.'
                          : 'This stop costs most of the premium. Little is left to salvage if it is hit.'
                    }
                  />
                </div>
                {/* Every input, so the verdict is auditable at a glance — the
                    whole complaint that produced this gate was a ratio whose
                    inputs were invisible. */}
                {/* Headline first, in per-contract dollars: that is the sum
                    actually at risk, and the percentage on the badge is a
                    summary of it. The arithmetic line stays per-share so it
                    reconciles against the premium it prints. Every figure on
                    both lines is the server's, already quantized to cents, so
                    the subtraction holds exactly under the hand check this
                    card's whole premise rests on. */}
                <dl className={styles.stopLossFigures}>
                  <KV label="Estimated premium remaining per share" value={`$${stopRisk.valueAtStop.toFixed(2)}/share`} mono />
                  <KV label="Premium loss per share" value={`$${stopRisk.loss.toFixed(2)}/share`} mono />
                  <KV label="Estimated loss per contract" value={formatStopLossHeadline(stopRisk)} mono />
                  <KV label={`Estimated loss for ${overlay.contracts} entered contract${overlay.contracts === 1 ? '' : 's'}`} value={`$${(Math.round(stopRisk.loss * 100) * overlay.contracts).toLocaleString('en-US')}`} mono />
                </dl>
                <Text size={10} tone="dim">Selected contract only ({data.contract}), using entered quantity × 100 shares per contract, before costs. This is not whole-spread risk.</Text>
                <Text size={10} tone="dim">Stop-cost source: {sharedStop?.source === 'exit_plan' ? 'Arithmetic calculation stop' : 'standalone structural check'}.</Text>
                <Data size={11} tone="secondary">{formatStopPremiumRisk(stopRisk)}</Data>
              </div>
            )}
          </div>

        </section>

        <div className={styles.methodGrid}>
        {/* Arithmetic Profit Target (Feature 3) — the primary method, expanded
             by default, alongside Monte Carlo when the card has enough width. */}
        <section className={`${styles.planCard} ${styles.arithmeticSection}`} aria-label="Arithmetic Profit Target">
          <div className={styles.scoreCardHeader}>
            <Text size={14} weight={600}>Arithmetic Profit Target</Text>
            <Text size={11} tone="secondary">{data.direction}</Text>
          </div>
          <div className={styles.arithmeticBasis}>
            <KV label="Selected strike / right" value={data.contractDetails ? `$${data.contractDetails.strike.toFixed(2)} ${data.contractDetails.right === 'C' ? 'Call' : 'Put'}` : 'Unavailable'} mono />
            <KV label={arithmeticLiveStockPrice != null ? 'Latest calculation-input stock reference' : 'Scan stock reference'} value={`$${(arithmeticLiveStockPrice ?? data.price).toFixed(2)}`} mono />
            <KV label="Calculation premium used" value={arithmeticPremium != null ? `$${arithmeticPremium.toFixed(2)}/share` : 'Unavailable — calculation premium basis missing'} mono />
            <KV label="Shared computed stock stop" value={exitPlan ? `$${exitPlan.stop.price.toFixed(2)} · ${exitPlan.stop.source}` : 'Not yet computed'} mono />
          </div>
          <Text size={10} tone="dim">Stored calculation stock entry: unavailable in the returned plan. The reference above is the scan or latest calculation input; Check structure can also refresh it.</Text>
          <Text size={10} tone="dim">{`${overlay.contracts} entered contracts × 100 shares · selected-contract full exit. Estimated dollar outcome = (returned option premium − calculation's echoed premium) × quantity × 100, from displayed cent-rounded prices, before commissions; not a fill or guaranteed profit.`}</Text>
          {data.spreadType && data.spreadType !== 'single' && <Text size={10} tone="caution">Selected-contract basis only; this is not a whole-spread outcome.</Text>}
          <Text size={10} tone="dim">Risk reference: selected-contract full premium; stop-loss sizing remains separately shown with its scan-mid basis in Order inputs & risk budget. Ratios describe stock geometry, not guaranteed option R:R. Independent of the other profit-target methods on this page; they can disagree. The computed stock stop is shared by every returned target and does not replace execution invalidation.</Text>
          <div className={styles.structuralStop}>
            <button type="button" className={styles.btn} onClick={computeExitPlan} disabled={exitPlanLoading || !data.contractDetails}>
              <Text size={12} weight={500}>{exitPlanLoading ? 'Computing arithmetic plan…' : 'Compute Arithmetic Plan'}</Text>
            </button>
            {exitPlanError && <Text size={11} tone="reject">Couldn&apos;t compute an arithmetic plan — try again.</Text>}
            {!exitPlan && <Text size={12} tone="dim">Target estimates — not yet computed —</Text>}
            {exitPlan && exitPlan.targets.length === 0 && <Text size={12} tone="dim">No target estimates returned.</Text>}
            {exitPlan && exitPlan.targets.length > 0 && (
              <div className={styles.arithmeticTableScroll}>
                <table className={styles.arithmeticTable} aria-label="Arithmetic target comparison">
                  <thead><tr>
                    {['Stock ratio / geometry', 'Arithmetic stock target', 'Effective stock target', 'Option premium', 'Estimated dollar outcome', 'Probability before expiry', 'Conditional median time', 'Pricing model'].map((label) => <th key={label} scope="col"><Text size={10} tone="secondary" weight={400}>{label}</Text></th>)}
                  </tr></thead>
                  <tbody>{exitPlan.targets.map((t, i) => {
                    const compareState = targetCompareState(t);
                    const priceAvailable = Number.isFinite(t.contractPrice) && t.contractPrice >= 0;
                    const outcome = arithmeticPremium != null && priceAvailable && Number.isFinite(overlay.contracts) && overlay.contracts >= 0
                      ? (t.contractPrice - arithmeticPremium) * overlay.contracts * 100 : null;
                    return <tr key={`${t.rrRatio}-${i}`}>
                      <th scope="row">
                        <Text size={12} weight={500}>{t.rrRatio}:1 target {compareState === 'beyond' ? '⚠' : ''}</Text>
                        <Text size={10} tone={compareState === 'beyond' ? 'caution' : 'dim'}>
                          {t.qualityReasons.includes('target_capped') ? 'Bearish target capped at the price floor. ' : ''}{targetCompareLabel(compareState)}
                        </Text>
                        <details className={styles.methodDetails}>
                          <summary>Target geometry</summary>
                          <KV label="Target source" value={t.tpSource} />
                          <KV label="Quality" value={t.qualityGood ? 'Good' : 'Caution'} />
                          <Text size={10} tone="dim">{t.qualityReasons.length ? t.qualityReasons.join(' · ') : 'No quality warnings'}</Text>
                          <KV label="Nearest structural level" value={t.structuralPrice != null ? `$${t.structuralPrice.toFixed(2)}` : 'No structural stop found'} mono />
                          <KV label="Distance" value={t.distanceDollar != null ? `$${t.distanceDollar.toFixed(2)}` : '—'} mono />
                          <KV label="Tolerance" value={`$${t.toleranceDollar.toFixed(2)}`} mono />
                        </details>
                      </th>
                      <td><Data size={12}>{Number.isFinite(t.arithmeticPrice) ? `$${t.arithmeticPrice.toFixed(2)}` : 'Unavailable'}</Data></td>
                      <td><Data size={12}>{Number.isFinite(t.price) ? `$${t.price.toFixed(2)}` : 'Unavailable'}</Data><Text size={10} tone="dim">{t.tpSource}</Text></td>
                      <td><Data size={12}>{priceAvailable ? `$${t.contractPrice.toFixed(2)}` : 'Unavailable'}</Data></td>
                      <td><Data size={12}>{outcome != null ? `$${outcome.toFixed(2)}` : arithmeticPremium == null ? 'Unavailable — calculation premium basis missing' : 'Unavailable'}</Data></td>
                      <td><Data size={12}>{Number.isFinite(t.probability) && t.probability >= 0 && t.probability <= 1 ? `${(t.probability * 100).toFixed(0)}%` : 'Unavailable'}</Data></td>
                      <td><Data size={12}>{t.expectedDays != null && Number.isFinite(t.expectedDays) && t.expectedDays >= 0 ? `~${Math.round(t.expectedDays)} calendar days` : 'Unavailable — no conditional median'}</Data></td>
                      <td><Text size={11}>{t.rrModel || 'Unavailable'}</Text></td>
                    </tr>;
                  })}</tbody>
                </table>
              </div>
            )}
          </div>
        </section>

        {/* Monte Carlo Profit Target (Feature 2 — renamed from "Profit Targets") */}
        <section className={`${styles.planCard} ${styles.monteCarloSection}`} aria-label="Monte Carlo Profit Target">
          <Text size={14} weight={600}>Monte Carlo Profit Target</Text>
          <Text size={10} tone="dim">Monte Carlo estimate — independent of the other profit-target methods on this page; they can disagree.</Text>
          <div className={styles.arithmeticBasis}>
            <KV label="Selected strike / right" value={data.contractDetails ? `$${data.contractDetails.strike.toFixed(2)} ${data.contractDetails.right === 'C' ? 'Call' : 'Put'}` : 'Unavailable'} mono />
            <KV label="Scan stock reference" value={`$${data.price.toFixed(2)}`} mono />
            <KV label={hasMcEcho ? 'Same-estimate echoed premium' : 'Captured request premium (rounded to cents)'} value={mcPremium != null && mcPremium > 0 ? `$${mcPremium.toFixed(2)}/share` : firstPassage ? 'Unavailable — estimate premium basis missing' : 'Not yet estimated'} mono />
            <KV label="Editable order entry (separate basis)" value={`$${overlay.entryLimit.toFixed(2)}/share`} mono />
          </div>
          <Text size={10} tone="dim">Stored Monte Carlo run stock entry: unavailable in the saved context. The scan reference above is not the run&apos;s stock-entry snapshot.</Text>
          {hasMcEcho && capturedMcValid && <Text size={10} tone="dim">Captured request premium: ${capturedMcPremium}/share; dollar outcomes use the same-estimate echoed cent basis when matched.</Text>}
          <Text size={10} tone="dim">{`${overlay.contracts} entered contracts × 100 shares · selected-contract full exit. Estimated dollar outcome = (returned option premium − estimate premium basis) × quantity × 100, using displayed cent-rounded prices, before costs; not a fill or guaranteed profit.`}</Text>
          {data.spreadType && data.spreadType !== 'single' && <Text size={10} tone="caution">Selected-contract basis only; this is not a whole-spread outcome.</Text>}
          <Text size={11} tone="secondary">GBM simulated stock paths · Black-Scholes option repricing.</Text>
          <Text size={10} tone="dim">{`Simulation uses calendar-day steps to expiry. Current selected-contract metadata: ${data.contractDetails?.dte ?? 'unavailable'} DTE; saved run DTE is unavailable in the stored context. Probability means target premium touched before expiry, even if a stop is also reached. Median time is conditional on target hits, in calendar days; independent target probabilities can sum past 100%.`}</Text>
          <Text size={10} tone="dim">{`Current inherited holding/repricing settings (not saved run inputs): ${horizonPreset ?? 'backend default'}; hold minimum ${holdMin ?? 'default'}, maximum ${holdMax ?? 'default'} trading days. These are separate from the expiry simulation horizon.`}</Text>
          <Text size={11} tone="secondary">Monte Carlo does not propose a stop. Effective stock and premium barriers feed the companion Barrier Race; execution stops remain separate.</Text>
          <div className={styles.arithmeticBasis}>
            <KV label="Companion race stock barrier" value={raceIsShowable && firstPassage?.race ? `$${firstPassage.race.stockStopPrice.toFixed(2)} stock` : 'Unavailable — run or re-run estimate to confirm barriers'} mono />
            <KV label="Companion race premium exit-value barrier" value={raceIsShowable && firstPassage?.race ? `$${firstPassage.race.premiumStopPrice.toFixed(2)}/share` : 'Unavailable — run or re-run estimate to confirm barriers'} mono />
            <KV label="Execution stock invalidation" value={overlay.invalidation != null ? `$${overlay.invalidation.toFixed(2)} stock` : 'Unavailable'} mono />
            <KV label="Execution premium-stop loss amount" value={premiumStopReadOnly
              ? premiumStopTouched && overlay.premiumStop != null ? `$${overlay.premiumStop.toFixed(2)}/share · pinned` : `Global loss allowance: ${Number((globalPremiumStopPct * 100).toFixed(2))}% (fill-derived)`
              : effectivePremiumStop != null ? `$${effectivePremiumStop.toFixed(2)}/share${premiumStopTouched ? ' · override' : showsGlobalOnLiveMid ? ` · global ${Number((globalPremiumStopPct * 100).toFixed(2))}%` : ' · scan seed'}` : 'Unavailable'} mono />
          </div>
          <Text size={10} tone="dim">Independent stock-stop touch probability and time remain in the Barrier Race disclosure. T1/T2/T3 are editable option-profit percentages, 1–500%; Run estimates the entered targets.</Text>
          <div className={styles.targetPctRow}>
            {(['t1', 't2', 't3'] as const).map((key) => (
              <label key={key} className={styles.targetPctInput}>
                <Text size={11} tone="secondary">{key.toUpperCase()}</Text>
                <input
                  type="number"
                  className={styles.editInput}
                  min={1}
                  max={500}
                  aria-label={`${key.toUpperCase()} profit target %`}
                  value={Math.round(targetPct[key] * 100)}
                  onChange={(e) => {
                    const pct = Math.max(0.01, Math.min(5.0, Number(e.target.value) / 100));
                    setTargetPct((prev) => ({ ...prev, [key]: pct }));
                  }}
                />
                <Text size={11} tone="secondary">%</Text>
              </label>
            ))}
          </div>
          <div className={styles.structuralStop}>
            {/* Disabled while EITHER level the simulation depends on is still
                in flight, not just while the estimate itself is. Awaiting the
                auto-refresh inside the handler closed the case where nothing
                had been fetched yet; it does not cover a fetch the user
                started first. Both of these are the two most natural button
                sequences on the card:
                  - "Check structure" then Estimate: the handler skipped its
                    own refresh (structuralLoading was already true), sent the
                    flat scan stop, and the in-flight structural then landed
                    and moved sharedStop.
                  - "Compute Arithmetic Plan" then Estimate: the plan landed
                    afterwards and sharedStop switched to its exit_plan branch.
                Either way the race cleared itself with "Barriers changed" on a
                click the user had just made, and the Monte Carlo probability
                had been measured against a different stop from the one on
                screen — the D1 discrepancy this card is not allowed to have.
                Disabling is preferred over awaiting a foreign promise: it
                needs no second copy of "which level wins" and cannot go stale
                against the sharedStop memo the freshness check compares to. */}
            <button
              type="button"
              className={styles.btn}
              onClick={estimateFirstPassage}
              disabled={
                firstPassageLoading || structuralLoading || exitPlanLoading || !data.contractDetails
              }
            >
              <Text size={12} weight={500}>
                {firstPassageLoading ? 'Estimating…' : 'Run Monte Carlo Estimate'}
              </Text>
            </button>
            {!firstPassageLoading && (structuralLoading || exitPlanLoading) && (
              <Text size={11} tone="dim">
                Waiting for the stop this estimate races against…
              </Text>
            )}
            {firstPassageError && (
              <Text size={11} tone="reject">Couldn&apos;t compute an estimate — try again.</Text>
            )}
          </div>
          {firstPassage && (
            <div className={styles.targetsTable}>
              {firstPassage.targets.map((t, i) => (
                <ProfitTargetRow
                  key={`${t.pct}-${i}`}
                  target={t}
                  estimatePremium={mcPremium != null && mcPremium > 0 ? mcPremium : null}
                  quantity={overlay.contracts}
                  structuralPaired={structuralPairing === 'ok'}
                  structuralPending={structuralLoading}
                  structuralUnavailable={structuralStop === null}
                  structuralZeroRisk={
                    sharedStop != null
                    && firstPassageContext != null && structuralPairing === 'zero_risk'
                    && !structuralLoading && structuralPairEligible
                  }
                  sharedStopPrice={sharedStop?.price ?? null}
                />
              ))}
            </div>
          )}
          {/* Rendered INSIDE the estimate block on purpose. Outside it, this
               ran before anything had been estimated — "each probability above
               is measured on its own" with no probabilities above it, pointing
               at a Barrier Race card that renders null — and in every race-less
               state it described a move that had not happened, since the
               invalidation row is only over there when the race is. */}
          {/* The round-7 caution note that stood here is GONE ON PURPOSE, and
               must not come back. It said the Fixed % Ladder still back-solved
               at half the contract's life while "Stock price" above used the
               resolved holding horizon. Both now call
               reprice_horizon.display_reprice_years() with the same arguments,
               so the disagreement it disclosed no longer exists and the note
               would be a false disclosure — worse than none, because a trader
               would discount two numbers that actually agree. The agreement is
               pinned, not assumed: backend/tests/test_reprice_horizon_agreement.py
               (equal inputs, equal horizon, per preset) and
               frontend/lib/__tests__/repriceHorizonPayload.test.ts (the two
               paths send equal inputs). Re-derive from those before writing any
               note here again. */}
          {firstPassage && raceIsShowable && (
            <Text size={10} tone="dim">
              Each probability above is measured on its own, so they can sum past 100% — a path that
              hits the target and later the stop is counted in both. The Barrier Race card below
              counts every path once, for whichever barrier it reached first. The invalidation row
              moved there too, for the same reason.
            </Text>
          )}
        </section>

        </div>

        {/* Barrier Race (barrier-race spec section 3.2) — its own card, directly
             below Monte Carlo, off the SAME simulation and the same click. It
             proposes no level of its own; it only decides which of the three
             existing barriers each simulated path reaches first. */}
        <BarrierRaceCard
          quantity={overlay.contracts}
          isSpread={!!data.spreadType && data.spreadType !== 'single'}
          // Gated on freshness too: `firstPassage` holds the PREVIOUS
          // contract's estimate for the frame between a contract switch and the
          // reset effect, so an un-gated `race === null` put "Not simulated —
          // contract expires today" under the new contract's header whenever
          // the previous one was 0-DTE. The refusal copy depends on no live
          // BARRIER, but it does depend on which contract is on screen.
          race={estimateIsFresh ? firstPassage?.race : undefined}
          invalidation={firstPassage?.invalidation ?? null}
          // See stopCostShown's declaration: the race must not name a readout
          // the page is not showing.
          stopCostShown={stopCostShown && stopRisk != null}
          premiumStopFromField={raceBarriers?.fromField ?? false}
          premiumStopField={overlay.premiumStop ?? null}
          // raceIsShowable, not the inline expression this used to carry. The
          // hoisted gate was applied to the Monte Carlo note and the Final
          // Recommendation but not to the card itself, so the card kept the
          // one term the gate exists for — that raceBarriers belongs to THIS
          // contract — and painted the previous contract's bars, medians, risk
          // legs and dollar edge for the frame between commit and the reset
          // effect. Verified with a useLayoutEffect probe: bars leaked, the
          // Final Recommendation did not.
          isFresh={estimateIsFresh}
          barriersChanged={raceBarriersMoved}
          stockStopMoved={stockStopMoved}
          onSelectTarget={racePickOption?.unavailable == null ? selectRaceTarget : undefined}
          selectedTargetPct={selectedRaceTarget}
        />




        {/* Selected method's own results, with latest-run fallback before a choice. */}
        <section aria-label="Final Recommendation" className={`${styles.scoreCard} ${styles[`final_${data.finalStatus}`]}`}>
          <div className={styles.scoreCardHeader}>
            <Text size={14} weight={600}>Final Recommendation</Text>
            {decisionTarget === undefined ? methodSelector
              : decisionTarget ? createPortal(methodSelector, decisionTarget) : null}
            <LabeledStatusBadge
              label="Final Status"
              status={data.finalStatus}
              tooltip="Overall recommendation for this trade, combining the stock signal's historical accuracy and the contract's quality verdict — see the Stock Scorecard and Contract panels."
            />
          </div>
          <div className={styles.scoreCardBody}>
            <Text size={13} weight={500}>{methodPick || recommendationUnavailable ? 'Selected method results' : 'Latest calculation'}</Text>
            <Text size={11} tone="secondary">
              Choosing a method records your decision; it does not run a calculation or apply
              its values to the order and exit fields.
            </Text>
            <section aria-label="Chosen method and target" className={styles.arithmeticBasis}>
              <KV label="Chosen method" value={methodPick ? pickedOption?.label ?? 'Unavailable' : 'Not selected — latest-calculation fallback is not a choice'} />
              {methodPick && !recommendationUnavailable && <>
                <KV label="Chosen target" value={chosenRow?.label ?? (methodPick.rowStockPrice == null && methodPick.rowOptionPrice == null ? 'Target not selected' : chosenMatches.length > 1 ? 'Recorded target — multiple result rows match; evidence unavailable' : 'Recorded target — matching result unavailable')} />
                <KV label="Recorded stock target" value={methodPick.rowStockPrice == null ? (methodPick.method === 'barrier_race' ? 'Not supplied by Barrier Race' : 'Not selected / unavailable') : summaryPrice(methodPick.rowStockPrice, 'stock')} mono />
                <KV label="Recorded option target" value={methodPick.rowOptionPrice == null ? 'Not recorded by this choice' : summaryPrice(methodPick.rowOptionPrice, '/share')} mono />
                {chosenRow && <>
                  <KV label="Matched result option premium" value={summaryPrice(chosenPremium, '/share')} mono />
                  <KV label={chosenRace ? 'Allocated target-first probability' : 'Independent target probability before expiry'} value={chosenRace ? `${weightPercents(chosenRace)[0]}%` : chosenProbability != null && Number.isFinite(chosenProbability) && chosenProbability >= 0 && chosenProbability <= 1 ? `${(chosenProbability * 100).toFixed(0)}%` : 'Unavailable'} mono />
                  <KV label="Conditional target median" value={chosenDays != null && Number.isFinite(chosenDays) && chosenDays >= 0 ? chosenRace ? `~${days(chosenDays)} (calendar days)` : `~${Math.round(chosenDays)} calendar days` : 'Unavailable'} mono />
                  <KV label="Result pricing model" value={chosenModel || 'Unavailable — no result model evidence'} />
                </>}
                <KV label="Judged on basis" value={methodPick.stopBasis === 'premium' ? 'Premium stop' : 'Stock stop'} />
                <KV label="Decision timestamp" value={methodPick.pickedAt} mono />
              </>}
              <KV label="Applicable quantity" value={`${overlay.contracts} entered contracts × 100 shares; selected-contract full exit${chosenLadder?.contractsToSell != null ? `; ladder rung allocation ${chosenLadder.contractsToSell} contracts` : ''}`} />
              {data.spreadType && data.spreadType !== 'single' && <Text size={10} tone="caution">Selected-contract basis; not whole-spread quantities or risk.</Text>}
              <Text size={10} tone="dim">Execution fields below are the current order inputs. Selection does not synchronize them. Stock-stop and premium-stop alerts remain independent.</Text>
              <KV label="Execution order / limit" value={`${data.entry.orderType} / ${summaryPrice(overlay.entryLimit, '/share')}`} mono />
              <KV label="Execution stock stop" value={summaryPrice(overlay.invalidation, 'stock')} mono />
              <KV label="Execution premium stop" value={effectivePremiumStop != null ? summaryPrice(effectivePremiumStop, '/share') : `Global ${Number((globalPremiumStopPct * 100).toFixed(2))}% — resolved against fill`} mono />
              <KV label="Execution time exit" value={`${TIME_STOP_DTE} DTE`} mono />
            </section>
            {recommendationUnavailable && (
              <Text size={11} tone="caution">Selected method results unavailable — run its calculation if needed, then choose an exit method again.</Text>
            )}
            {!recommendationUnavailable && recommendationMethod === 'arithmetic' && exitPlan && (
              <>
                <Text size={11} tone="dim">computed via: Arithmetic, {formatHHMM(exitPlan.computedAt)}</Text>
                <div className={styles.scoreRow}>
                  <Text size={12} tone="secondary">Bottom (final stop)</Text>
                  <Data size={14} tone="primary">${exitPlan.stop.price.toFixed(2)}</Data>
                </div>
                <Text size={10} tone="dim">{stopJustification(exitPlan.stop)}</Text>
                {exitPlan.targets.map((t) => (
                  <div className={styles.scoreRow} key={t.rrRatio}>
                    <Text size={12} tone="secondary">{t.rrRatio}:1 target</Text>
                    <Data size={13} tone="primary">${t.price.toFixed(2)} ({(t.probability * 100).toFixed(0)}%)</Data>
                  </div>
                ))}
                <Text size={10} tone="caution">
                  This stop price is not automatically monitored by alerts unless copied into the position&apos;s
                  stop field after opening.
                </Text>
              </>
            )}
            {!recommendationUnavailable && recommendationMethod === 'monte_carlo' && firstPassage && (
              <>
                <Text size={11} tone="dim">
                  computed via: Monte Carlo{firstPassage.computedAt ? `, ${formatHHMM(firstPassage.computedAt)}` : ''}
                </Text>
                {/* TARGET-VINTAGE-2026-09-04 — GATED ON FRESHNESS, the same
                     rule the Barrier Race already applies, and for the reason
                     the comment below used to only NOTE: `firstPassage` is
                     restored from the parent's per-contract cache on mount and
                     `lastRunMethod` is derived from `computedAt` alone, so a
                     restored estimate reinstated this whole branch at whatever
                     vintage it was cached at. With the invalidation fallback
                     gone these rows are the only numbers left in the branch,
                     which made an ungated vintage the branch's entire content.

                     Rendering nothing until Estimate is clicked is the accepted
                     cost: consistency with how the rest of the card treats
                     stale numbers wins. It is not rendered SILENTLY, though —
                     a blank branch under a "computed via Monte Carlo" heading
                     asserts a method ran and then shows no answer. The line
                     below says which it is, matching the "Barriers changed —
                     re-run the estimate" copy the race card paints for the
                     same class of staleness. */}
                {estimateIsFresh ? (
                  firstPassage.targets.map((t, i) => (
                    <div className={styles.scoreRow} key={`${t.pct}-${i}`}>
                      <Text size={12} tone="secondary">{`T${Math.round(t.pct * 100)}%`}</Text>
                      <Data size={13} tone="primary">
                        ${t.optionPrice.toFixed(2)} ({(t.probability * 100).toFixed(0)}%)
                      </Data>
                    </div>
                  ))
                ) : (
                  <Text size={11} tone="caution">
                    Not re-run this session — click Estimate to price these targets against the
                    current premium.
                  </Text>
                )}
              </>
            )}
            {/* A selected race shows exclusive race outcomes. Only the initial
                no-pick latest-MC fallback retains the combined summary. */}
            {!recommendationUnavailable && firstPassage &&
              (recommendationMethod === 'barrier_race' ||
                (methodPick === null && recommendationMethod === 'monte_carlo')) && (
              <>
                {recommendationMethod === 'barrier_race' && (
                  <Text size={11} tone="dim">computed via: Barrier Race{firstPassage.computedAt ? `, ${formatHHMM(firstPassage.computedAt)}` : ''}</Text>
                )}
                {firstPassage.race && raceIsShowable ? (
                  <>
                    <div className={styles.scoreRow}>
                      <Text size={12} tone="secondary">Armed stop (whichever fires first)</Text>
                      <Data size={13} tone="primary">
                        ${firstPassage.race.premiumStopPrice.toFixed(2)} option / $
                        {firstPassage.race.stockStopPrice.toFixed(2)} stock
                      </Data>
                    </div>
                    {firstPassage.race.outcomes.map((o) => (
                      <div className={styles.scoreRow} key={`edge-${o.targetPct}`}>
                        <Text size={12} tone="secondary">
                          {`T${Math.round(o.targetPct * 100)}% edge`}
                        </Text>
                        <Data size={13} tone="primary">
                          {recommendationMethod === 'barrier_race' && `$${o.targetOptionPrice.toFixed(2)} option (${weightPercents(o)[0]}% target first) — `}
                          {o.edgePerContract != null ? money(o.edgePerContract) : '—'}
                          {o.rrStockStop != null ? ` at ${o.rrStockStop.toFixed(2)}x` : ''}
                        </Data>
                      </div>
                    ))}
                    <Text size={10} tone="dim">
                      Edge is per contract, before commissions, and assumes IV is unchanged when a
                      barrier is reached. See the Barrier Race card for the full arithmetic.
                    </Text>
                  </>
                ) : null}
              </>
            )}
            {!recommendationUnavailable && (recommendationMethod === 'ladder' || recommendationMethod === null) && (
              <>
                <Text size={11} tone="caution">
                  {methodPick?.method === 'ladder' ? 'Selected method: Fixed % Ladder Plan' : 'No method explicitly run — showing Fixed % Ladder Plan (default)'}
                </Text>
                {data.exit.targets.map((t, i) => (
                  <div className={styles.scoreRow} key={t.id ?? i}>
                    <Text size={12} tone="secondary">{t.id ? t.id.toUpperCase() : `T${i + 1}`}</Text>
                    <Data size={13} tone="primary">${(t.targetPrice ?? t.stockPrice).toFixed(2)}</Data>
                  </div>
                ))}
                {/* "Projected R/R (+8% stock move)" stood here and is GONE,
                     together with the model/"— edited" attribution line whose
                     only job was to caption it. It was the third R:R on one
                     page and the least defensible of the three: reward from a
                     hardcoded +8% stock move nobody chose, risk from a flat
                     percentage of premium.

                     Note WHERE this was, because it explains why it outlived
                     its own removal. The Ladder's copy of this readout went in
                     an earlier round (see the note in section 6) — but this
                     branch is the Ladder DEFAULT, rendered by the Final
                     Recommendation when no method has been run, and it carried
                     its own copy. Deleting the readout in one place left it on
                     screen in the state a trader sees first, before clicking
                     anything.

                     overlay.premiumStop is UNTOUCHED, for the reasons the
                     section 6 note gives: it is the premium-stop alert level
                     and the barrier race's third barrier. Only the readouts
                     went. */}
              </>
            )}
          </div>
        </section>



      </div>

      {/* 8. Actions */}
      <div className={styles.actions}>
        <button
          type="button"
          className={`${styles.btn} ${styles.btnPrimary}`}
          onClick={onSendToBroker}
          disabled={sendDisabled || !onSendToBroker}
        >
          <Text size={13} weight={500}>{sendLabel ?? 'Send to broker'}</Text>
        </button>
        <button
          type="button"
          className={styles.btn}
          onClick={() => setChartOpen((v) => !v)}
          aria-expanded={chartOpen}
        >
          <Text size={13} weight={500}>{chartOpen ? 'Hide chart' : 'View chart'}</Text>
        </button>
        <button
          type="button"
          className={styles.btn}
          onClick={() => {
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${data.symbol}-trade-card.json`;
            a.click();
            URL.revokeObjectURL(url);
          }}
        >
          <Text size={13} weight={500}>Export JSON</Text>
        </button>
      </div>

      <div className={styles.recIdFooter}>
        <Text size={11} tone="dim">{displayRecId}</Text>
      </div>

      <InlineChartPanel
        open={chartOpen}
        symbol={data.symbol}
        onClose={() => setChartOpen(false)}
      />
    </div>
  );
}

function EditableTargetRow({
  target,
  index,
  editedStockPrice,
  entryLimit,
  premiumStop,
  authoritativeRr,
  data,
  onStockPriceChange,
  totalContracts,
}: {
  target: TargetLevel;
  index: number;
  editedStockPrice: number;
  entryLimit: number;
  premiumStop: number;
  authoritativeRr?: number;
  data: TradeCardData;
  onStockPriceChange: (v: number) => void;
  totalContracts: number;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(String(editedStockPrice ?? 0));

  const startEdit = useCallback(() => {
    setDraft(String(editedStockPrice ?? 0));
    setEditing(true);
  }, [editedStockPrice]);

  const save = useCallback(() => {
    const parsed = parseFloat(draft);
    if (!isNaN(parsed) && parsed > 0) {
      onStockPriceChange(Math.round(parsed * 100) / 100);
    }
    setEditing(false);
  }, [draft, onStockPriceChange]);

  const handleKey = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') save();
      if (e.key === 'Escape') setEditing(false);
    },
    [save],
  );

  const originalStockPrice = target.targetPrice ?? target.stockPrice;
  const isTargetEdited = editedStockPrice !== originalStockPrice;

  const estOptionPrice = isTargetEdited
    ? recomputeTargetEstOption(editedStockPrice, entryLimit, data)
    : (target.estimatedOptionPrice ?? 0);

  // Use the same cents shown in this row, including local-edit estimates.
  const premiumAvailable = Number.isFinite(estOptionPrice) && estOptionPrice >= 0
    && (isTargetEdited ? data.contractDetails != null : target.estimatedOptionPrice != null);
  const entryAvailable = Number.isFinite(entryLimit) && entryLimit > 0;
  const rewardCents = premiumAvailable && entryAvailable
    ? Math.round(Number(estOptionPrice.toFixed(2)) * 100) - Math.round(Number(entryLimit.toFixed(2)) * 100)
    : null;
  const dollarOutcome = (quantity: number) => rewardCents != null && Number.isInteger(quantity) && quantity >= 0
    ? `$${(rewardCents * quantity).toFixed(2)}` : 'Unavailable';

  const rr = !isTargetEdited && authoritativeRr !== undefined ? authoritativeRr : rrContribution(estOptionPrice, entryLimit, premiumStop);

  const statusVal = target.status;
  const rowTone = statusVal === 'HIT' ? 'pass' : statusVal === 'MISSED' ? 'reject' : undefined;
  const statusClass = statusVal ? styles[`target_${statusVal}`] : styles.target_PENDING;
  const badgeStatus = statusVal === 'HIT' ? 'PASS' : statusVal === 'MISSED' ? 'REJECT' : 'PENDING';
  const isScaleOut = target.contractsToSell !== undefined && target.contractsToSell < totalContracts;
  const label = target.id ? target.id.toUpperCase() : `T${index + 1}`;

  return (
    <div className={`${styles.targetRow} ${statusClass}`}>
      <div className={styles.targetMain}>
        <div className={styles.targetId}>
          <Text size={12} weight={600} tone={rowTone}>{label}</Text>
          {statusVal && <StatusBadge status={badgeStatus as 'PENDING' | 'PASS' | 'REJECT'} tooltip={targetStatusTooltip(statusVal)} />}
          {isTargetEdited && (
            <span className={styles.editBadge}>
              <Text size={10} tone="accent">edited</Text>
            </span>
          )}
        </div>
        <div className={styles.targetValues}>
          <div className={styles.kvRow}>
            <Text size={12} tone="secondary">Stock price</Text>
            {editing ? (
              <input
                type="number"
                className={styles.editTargetInput}
                value={draft}
                min={0.01}
                onChange={(e) => setDraft(e.target.value)}
                onBlur={save}
                onKeyDown={handleKey}
                autoFocus
                aria-label={`Edit target stock price for ${label}`}
              />
            ) : (
              <span
                className={styles.editValue}
                onClick={startEdit}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') startEdit();
                }}
                aria-label={`Edit target stock price for ${label}`}
              >
                <Data size={13} weight={500} tone={rowTone}>
                  ${(editedStockPrice ?? 0).toFixed(2)}
                </Data>
              </span>
            )}
          </div>
          {estOptionPrice > 0 && (
            <KV label="Est. option" value={`$${estOptionPrice.toFixed(2)}`} mono tone={rowTone} />
          )}
          {estOptionPrice > 0 && entryLimit > 0 && premiumStop > 0 && (
            <KV label="R:R" value={`${rr.toFixed(1)}x`} mono tone={rr < 0 ? 'reject' : undefined} />
          )}
          <KV label={`Full-position outcome (${totalContracts} contracts × 100 shares)`} value={dollarOutcome(totalContracts)} mono tone={rowTone} />
          <KV label={target.contractsToSell !== undefined ? `Rung outcome (${target.contractsToSell} contracts × 100 shares)` : 'Rung outcome (allocation unavailable)'} value={target.contractsToSell !== undefined ? dollarOutcome(target.contractsToSell) : 'Unavailable'} mono tone={rowTone} />
          {target.contractsToSell !== undefined && (
            <KV label="Contracts" value={`${target.contractsToSell}`} mono />
          )}
        </div>
        {isScaleOut && target.contractsToSell !== undefined && (
          <Text size={11} tone="caution">
            Scale out: sell {target.contractsToSell} of {totalContracts}
          </Text>
        )}
      </div>
      <Text size={10} tone="dim">{isTargetEdited ? 'Edited target: local stock-move approximation' : 'Scan/restored plan target and stored option estimate'}</Text>
      {target.pricingMethod && (
        <span className={styles.pricingBadge}>
          <Text size={10} tone="dim">{target.pricingMethod}</Text>
        </span>
      )}
    </div>
  );
}

/** Exported for tests only (P2-20). */
export function EditableKV({
  label,
  value,
  onChange,
  onRevert,
  min,
  max,
  mono,
  tone,
  prefix = '',
  suffix = '',
  decimals = 2,
  nullLabel = 'not computed',
}: {
  label: string;
  /** NULL renders `nullLabel` and starts the editor with an EMPTY draft, so a
   *  field whose plan value is "not computed" can still be typed into. Only
   *  the Invalidation field passes null today — see
   *  `TradeCardData.exit.invalidation`. */
  value: number | null;
  onChange: (v: number) => void;
  /** Optional "clear the field to go back to inheriting the plan's value".
   *  Only the three threaded fields pass it; for every other field an empty
   *  input still means "I changed my mind", i.e. nothing happens. */
  onRevert?: () => void;
  min?: number;
  max?: number;
  mono?: boolean;
  tone?: 'pass' | 'caution' | 'reject';
  prefix?: string;
  suffix?: string;
  decimals?: number;
  /** What to show in place of a number when `value` is null. Required in
   *  practice for any field that can be null: the default is deliberately
   *  wordy rather than a bare dash, because a dash beside an editable field
   *  reads as zero. */
  nullLabel?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value == null ? '' : String(value));
  // ROUND 9 finding 17 -- the out-of-range REJECT used to be entirely silent:
  // `setEditing(false)` and the field showed the old number again, so a user
  // who typed 1400 and looked away could not tell a refusal from an
  // acceptance, and nothing hinted that a legitimately wider value was
  // available inside the range. A safety gate nobody can perceive teaches
  // nothing. Announced politely (aria-live) rather than as an alert: the value
  // on screen is correct throughout, it is the typed one that was dropped.
  const [rejected, setRejected] = useState<string | null>(null);

  /** CODE ROUND 1, C1-2 -- did the user TYPE since the editor opened? The
   *  value-comparison guards in `save` compare the draft (seeded once, at
   *  `startEdit`) with the CURRENT `value` prop, so a value that moves while
   *  the field is open -- TradeCard's untouched premium stop switching from
   *  the scan seed to `round(liveMid x global, 2)` when the live quote lands
   *  -- made a bare focus-and-blur commit the stale seed as a deliberate,
   *  touched stop. Nothing typed is nothing committed, whatever `value` did. */
  const typedRef = useRef(false);

  const startEdit = useCallback(() => {
    setDraft(value == null ? '' : String(value));
    setRejected(null);
    typedRef.current = false;
    setEditing(true);
  }, [value]);

  const save = useCallback(() => {
    if (!typedRef.current) {
      setEditing(false);
      return;
    }
    // A COMPLETE decimal literal, or nothing. `parseFloat` is happy to
    // TRUNCATE: it reads "2." as 2 and "2.7abc" as 2.7, and nothing downstream
    // can tell a finished number from an interrupted one.
    //
    // Round 8 moved this input to type="text" so a half-typed "2." would stop
    // being sanitized to "" and misread as the clear-to-inherit gesture. That
    // was right, and it left the other half open: the string now survives all
    // the way to `parseFloat`, which quietly commits 2. A user with a
    // committed $2.71 who reopened the field to type $2.40, got as far as "2."
    // and tabbed away, ended up with $2.00 shown, `touched` set, and
    // `limit_price: 2.00` on a live BUY/OPEN order -- round 8 traded "reverts
    // to a value the user didn't choose" for "commits a value the user didn't
    // choose", and only the second one reaches a broker.
    //
    // A trailing point is the interrupted case; ".5" is a complete way to
    // write 0.5 and stays accepted. Anything incomplete is a no-op, showing
    // the previous value back -- the same honest answer the out-of-range
    // policy below gives.
    const trimmed = draft.trim();
    const isCompleteNumber = /^-?(?:\d+(?:\.\d+)?|\.\d+)$/.test(trimmed);
    if (trimmed !== '' && !isCompleteNumber) {
      // ROUND 10 finding 9 -- SAY SO HERE TOO. Round 9 added this guard four
      // lines above the fix for "the reject gave no feedback whatsoever", and
      // gave it exactly that property: a user who typed "2." and tabbed away
      // saw the old value return with nothing to explain it. Same defect, same
      // commit, different branch.
      setRejected(`That is not a complete number — kept the previous value.`);
      setEditing(false);
      return;
    }
    const parsed = parseFloat(draft);
    if (isNaN(parsed)) {
      // An EMPTY field is a deliberate gesture, not a typo: on a field that can
      // inherit, it means "stop pinning this, follow the plan again". Anything
      // else unparseable ("abc", "1.2.3") keeps the old no-op behaviour.
      if (onRevert && draft.trim() === '') onRevert();
      setEditing(false);
      return;
    }
    const minVal = min ?? -Infinity;
    const maxVal = max ?? Infinity;
    // OUT OF RANGE REVERTS, IT DOES NOT CLAMP.
    //
    // Round 8: clamping turns a fat-finger into a plausible-looking WRONG
    // number rather than rejecting it. On a $150 bullish card, "1400" typed for
    // "140" clamped to $148.50 -- 1% below spot -- which `buildPaperPosition`
    // stores as `PortfolioPosition.stop` and `alertEngine` fires STOP_REACHED
    // on at the first ordinary intraday wiggle, Gmail and Telegram behind it,
    // while the user believes their stop is 7% away. The mirror case "14"
    // clamped to $75.00, a 50% stop, equally silently.
    //
    // The portfolio EditDrawer's premium-stop editor already took this
    // position on the identical question ("Out of range REVERTS, it does not
    // clear ... showing the previous value back is the honest answer"). Two
    // editors in one branch with opposite policies, and the card had the unsafe
    // one on the field that becomes the position's stop.
    //
    // Reverting retired round 6's seed-outside-bounds WRITE at the source: the
    // clamp was what made `next !== value` on a bare focus-and-blur when the
    // SEED itself sat outside [min,max]. With no clamp there is nothing to
    // differ, so nothing is written.
    //
    // It did not retire the MESSAGE, and round 2 of the follow-up audit found
    // that half still live: this check sat ABOVE the no-op guard, so a seed
    // outside the bounds printed "Must be between $X and $Y — kept the
    // previous value." for a value the user never typed, merely for clicking
    // the field to read it. The no-op guard is therefore hoisted above this
    // one. Nothing typed is nothing judged -- the same rule PremiumStopEditor's
    // `if (!dirtyRef.current)` guard applies in the drawer.
    //
    // Reachable, and this branch widened it: `premiumStopDollarBounds` rounds
    // the minimum UP (it must, or the card's own boundary falls below the band
    // the drawer enforces) while the seed is `round(mid x global, 2)`
    // (trade_plan.py). At a global of 0.10 -- the minimum Settings offers --
    // those two disagree by a cent on 2184 of 4999 cent-mids from $0.02 to
    // $50, against 3 before.
    if (parsed === value) {
      setEditing(false);
      return;
    }
    if (parsed < minVal || parsed > maxVal) {
      setRejected(
        maxVal === Infinity
          ? `Must be at least ${prefix}${minVal.toFixed(decimals)}${suffix} — kept the previous value.`
          : `Must be between ${prefix}${minVal.toFixed(decimals)}${suffix} and `
            + `${prefix}${maxVal.toFixed(decimals)}${suffix} — kept the previous value.`,
      );
      setEditing(false);
      return;
    }
    // P2-20 -- rounds at THIS field's `decimals`, not always at 2.
    const scale = 10 ** decimals;
    const next = Math.round(parsed * scale) / scale;
    // A BLUR IS NOT AN EDIT. `save` runs on every blur, so clicking into a
    // field to read it and clicking away used to emit `onChange(sameValue)`.
    // That was invisible while the page inferred "did the user touch this?" by
    // comparing the reported value against the card's seed -- a no-op write
    // reported the seed, which compared equal and was discarded. Now that
    // touched-ness is tracked rather than inferred, the same no-op write MARKS
    // THE FIELD AS TOUCHED: a stray click on Premium stop posted the seeded
    // default ($3.12 = round(5.20 mid x 0.60 global, 2)) as a deliberate stop,
    // which the server re-anchored to the $4.00 live fill and stored as 78% --
    // exactly the defect the tracked flag was introduced to remove, re-entered
    // through the one path that does not go through a keystroke.
    // Skipping the no-op is also just correct for every other field.
    //
    // COMPARED BEFORE CLAMPING, AND NOW BEFORE BOUNDING. `startEdit` seeds the
    // draft from `value`, so when `value` itself sits outside [min,max] the
    // clamp alone changed it and the post-clamp guard below could not see that
    // nothing was typed -- a bare focus-and-blur then reported a deliberate
    // edit. That comparison lives above the range check now, for the same
    // reason one step further out. Round 5 added
    // 10-99%-of-mid bounds to the Premium stop field and re-opened exactly the
    // defect this guard exists to close: the seed is `round(mid x global, 2)`
    // (trade_plan.py), and the global was allowed up to 1.0 (risk_settings.py
    // `le=1.0`; 0.99 since P2-02, but a stored legacy 1.0 still loads), at
    // which point the seed IS the mid and the max is 99% of it --
    // 1951 of 2000 mids from $0.01 to $20.00 seed above the bound. Clicking the
    // field to read it and clicking away would pin a per-position stop nobody
    // chose, on a card with no way back to inheriting.
    if (next === value) {
      setEditing(false);
      return;
    }
    setRejected(null);
    onChange(next);
    setEditing(false);
  }, [draft, min, max, onChange, onRevert, decimals, value, prefix, suffix]);

  const handleKey = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') save();
      if (e.key === 'Escape') setEditing(false);
    },
    [save],
  );

  const displayValue = value == null
    ? nullLabel
    : decimals === 0
      ? `${prefix}${value}${suffix}`
      : `${prefix}${value.toFixed(decimals)}${suffix}`;

  return (
    <div className={`${styles.kvRow} ${styles.kvRowEditable}`}>
      <Text size={12} tone="secondary">{label}</Text>
      {editing ? (
        <input
          // TEXT, not number, and this is load-bearing rather than cosmetic.
          //
          // `<input type="number">` applies value sanitization: `e.target.value`
          // is the EMPTY STRING for anything that is not a valid floating-point
          // literal, "132." and ".5" included. Round 8 found what that does now
          // that an empty draft means "revert to inheriting": a user with a
          // committed 132.00 who reopens the field to make it 132.50 types
          // "132." and tabs away -- the browser hands us "", the field jumps
          // back to the plan's $140.00, the touched flag clears, and the order
          // goes out at 140. A `draft.trim() === ''` check cannot tell that
          // apart from a real deletion, because they are the same string.
          //
          // With type="text" the draft is the literal keystrokes, so "132."
          // stays "132." (parseFloat gives 132) and only an actually empty
          // field reads as empty. `min`/`max`/`step` are dropped from the DOM
          // with it -- browser-native range enforcement is not what guards this
          // input anyway; `save` is, and it now reverts rather than clamps.
          type="text"
          inputMode="decimal"
          className={styles.editInput}
          value={draft}
          onChange={(e) => { typedRef.current = true; setDraft(e.target.value); }}
          onBlur={save}
          onKeyDown={handleKey}
          autoFocus
          aria-label={`Edit ${label}`}
          // The only surfacing of the clear-to-inherit gesture. A tooltip
          // rather than a line of copy or a revert button, because the card's
          // layout is governed by the schematic and the card-level edited
          // indicator is a separate, still-unbuilt decision
          // (EDITED-FLAG-2026-09-04) that this must not pre-empt.
          title={onRevert ? `Clear to go back to the plan's ${label.toLowerCase()}` : undefined}
        />
      ) : (
        <span
          className={styles.editValue}
          onClick={startEdit}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') startEdit();
          }}
          aria-label={`Edit ${label}`}
        >
          {value == null
            ? <Text size={13} weight={400} tone="dim">{displayValue}</Text>
            : mono
              ? <Data size={13} weight={500} tone={tone}>{displayValue}</Data>
              : <Text size={13} weight={500}>{displayValue}</Text>}
        </span>
      )}
      {/* The refusal, announced. `aria-live="polite"` rather than an alert
          role: nothing on screen is wrong, a typed value was declined.
    *
          ROUND 10 finding 10 -- THE REGION IS ALWAYS MOUNTED, only its text
          changes. Round 9 rendered the region and its content together under
          `{rejected && …}`, which is the canonical way to get no announcement
          at all: a live region has to be in the DOM before its contents change
          for assistive tech to observe the mutation. The round-9 test used
          `findByText`, which passes either way and so could not tell
          "announced" from "rendered". Kept out of the layout when empty via
          the empty-string child rather than by unmounting. */}
      <span
        className={rejected ? styles.editRejected : styles.editRejectedEmpty}
        aria-live="polite"
      >
        {rejected ? <Text size={11} tone="caution">{rejected}</Text> : ''}
      </span>
    </div>
  );
}

function TargetRow({
  target,
  index,
  totalContracts,
}: {
  target: TargetLevel;
  index: number;
  totalContracts: number;
}) {
  const statusVal = target.status;
  const rowTone = statusVal === 'HIT' ? 'pass' : statusVal === 'MISSED' ? 'reject' : undefined;
  const statusClass = statusVal ? styles[`target_${statusVal}`] : styles.target_PENDING;
  const badgeStatus = statusVal === 'HIT' ? 'PASS' : statusVal === 'MISSED' ? 'REJECT' : 'PENDING';
  const isScaleOut = target.contractsToSell !== undefined && target.contractsToSell < totalContracts;
  const label = target.id ? target.id.toUpperCase() : `T${index + 1}`;

  return (
    <div className={`${styles.targetRow} ${statusClass}`}>
      <div className={styles.targetMain}>
        <div className={styles.targetId}>
          <Text size={12} weight={600} tone={rowTone}>{label}</Text>
          {statusVal && <StatusBadge status={badgeStatus as 'PENDING' | 'PASS' | 'REJECT'} tooltip={targetStatusTooltip(statusVal)} />}
        </div>
        <div className={styles.targetValues}>
          <KV label="Stock price" value={`$${(target.targetPrice ?? target.stockPrice).toFixed(2)}`} mono tone={rowTone} />
          {target.estimatedOptionPrice !== undefined && (
            <KV label="Est. option" value={`$${target.estimatedOptionPrice.toFixed(2)}`} mono tone={rowTone} />
          )}
          {target.rrContribution !== undefined && (
            <KV label="R:R" value={`${target.rrContribution.toFixed(1)}x`} mono />
          )}
          {target.contractsToSell !== undefined && (
            <KV label="Contracts" value={`${target.contractsToSell}`} mono />
          )}
        </div>
        {isScaleOut && target.contractsToSell !== undefined && (
          <Text size={11} tone="caution">
            Scale out: sell {target.contractsToSell} of {totalContracts}
          </Text>
        )}
      </div>
      {target.pricingMethod && (
        <span className={styles.pricingBadge}>
          <Text size={10} tone="dim">{target.pricingMethod}</Text>
        </span>
      )}
    </div>
  );
}

function KV({
  label,
  value,
  mono,
  tone,
}: {
  label: string;
  value: string;
  mono?: boolean;
  tone?: 'pass' | 'caution' | 'reject';
}) {
  return (
    <div className={styles.kvRow}>
      <Text size={12} tone="secondary">{label}</Text>
      {mono
        ? <Data size={13} weight={500} tone={tone}>{value}</Data>
        : <Text size={13} weight={500}>{value}</Text>}
    </div>
  );
}

function ProfitTargetRow({
  target,
  estimatePremium,
  quantity,
  structuralPaired,
  structuralPending,
  structuralUnavailable,
  structuralZeroRisk,
  sharedStopPrice,
}: {
  target: FirstPassageTarget;
  estimatePremium: number | null;
  quantity: number;
  /** Both the stop and the estimate were confirmed fresh THIS mount, and the
   *  stop is not sitting on the price it was measured against. Only then is
   *  the level below honest to show. */
  structuralPaired: boolean;
  structuralPending: boolean;
  structuralUnavailable: boolean;
  structuralZeroRisk: boolean;
  /** The stop level itself — sourced from `sharedStop`
   *  (Piece 2: the exit plan's structural+ATR stop when computed this mount,
   *  else the raw Check-Structure level), NOT necessarily the same object
   *  the standalone "Check Structure" block above renders. Only the price is
   *  needed here (for the "Structural level found" line), so this is a
   *  number, not the full StructuralStop shape. */
  sharedStopPrice: number | null;
}) {
  const label = `T${Math.round(target.pct * 100)}%`;
  const optionAvailable = Number.isFinite(target.optionPrice) && target.optionPrice >= 0;
  const outcome = estimatePremium != null && optionAvailable && Number.isFinite(quantity) && quantity >= 0
    ? (Math.round(Number(target.optionPrice.toFixed(2)) * 100) - Math.round(estimatePremium * 100)) * quantity
    : null;
  // The "R:R vs. structural stop" cell that used to stand here is gone
  // (barrier-race spec section 3.4, Kenneth's OK obtained). Its risk leg was
  // premium x a fixed percentage, so premium cancelled out and the ratio
  // degenerated to the typed target % over the typed stop % — the same number
  // on every contract. The Barrier Race card's stock-stop R:R replaces it with
  // one whose risk leg is `premium - BS(stop, ...)`, which does not cancel.
  //
  // `structuralPaired` SURVIVES the removal as the freshness token for the
  // "Structural level found" row below: true means the structural stop and the
  // estimate were BOTH confirmed fresh this mount. That pairing is what five
  // audit rounds built, and the price shown below is only honest under exactly
  // the same condition the ratio was. (It was `structuralRRValue != null` when
  // the ratio still existed; the prop carries the pairing now, not a number.)

  // "Structural level found" — Feature 2's line, carrying the SAME four
  // gating states the removed R:R row used (Checking… / No structural stop
  // found / N/A (stop = price) / —), with a price as the success case.
  // Deliberately gated on `structuralPaired`
  // (not merely `structuralStop != null`) — a truthy structuralStop can
  // be on screen while this cell still shows '—' because the freshness
  // pairing hasn't been reconfirmed this mount (see the comment above); this
  // line must show that SAME gated state, not a confident-looking price next
  // to a gated ratio.
  const structuralLevelValue = structuralPaired && sharedStopPrice != null
    ? `$${sharedStopPrice.toFixed(2)}`
    : structuralPending
      ? 'Checking…'
      : structuralUnavailable
        ? 'No structural stop found'
        : structuralZeroRisk
          ? 'N/A (stop = price)'
          : '—';

  return (
    <div className={styles.targetRow}>
      <div className={styles.targetMain}>
        <div className={styles.targetId}>
          <Text size={12} weight={600}>{label}</Text>
        </div>
        <div className={styles.resultColumns}>
        <div className={styles.targetValues}>
          <KV label="Option premium" value={optionAvailable ? `$${target.optionPrice.toFixed(2)}` : 'Unavailable'} mono />
          <KV label="Estimated dollar outcome" value={outcome != null ? `$${outcome.toFixed(2)}` : estimatePremium == null ? 'Unavailable — estimate premium basis missing' : 'Unavailable'} mono />
          <KV
            label="Stock-price equivalent (display approximation)"
            value={target.stockPrice == null ? 'not reachable' : Number.isFinite(target.stockPrice) ? `$${target.stockPrice.toFixed(2)}` : 'Unavailable'}
            mono
          />
          <KV label="Structural level found" value={structuralLevelValue} mono />
        </div>
        <div className={styles.probabilityColumn}>
          <KV label="Probability before expiry" value={Number.isFinite(target.probability) ? `${(target.probability * 100).toFixed(0)}%` : 'Unavailable'} mono />
          <KV
            label="Conditional median time"
            value={target.expectedDays != null && Number.isFinite(target.expectedDays) ? `~${Math.round(target.expectedDays)} calendar days` : 'Unavailable — no conditional median'}
            mono
          />
        </div>
        </div>
      </div>
    </div>
  );
}

function DetailCell({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className={styles.detailsCell}>
      <Text size={10} tone="dim">{label.toUpperCase()}</Text>
      {mono
        ? <Data size={13} weight={500}>{value}</Data>
        : <Text size={13} weight={500}>{value}</Text>}
    </div>
  );
}

/** Feature 5 — pre-trade max-loss override editor in the order inputs.
 *  Mirrors the shape of the Portfolio EditDrawer's post-trade MaxLossBanner
 *  override UI (mode toggle + input + Apply), but usable before a position
 *  exists — and deliberately without a free-text "Reason" field (explicitly
 *  decided against) and without the post-trade banner's own lossAtStop/
 *  exceeded display (there's no live position to check yet, just the budget
 *  this card's recommendedSize draws from). Always displays the resolved $
 *  basis, whether or not an override is active — never silently uses it. */
function MaxLossOverrideEditor({
  override,
  limitDollar,
  onApply,
}: {
  override: MaxLossOverride | null;
  limitDollar: number;
  onApply: (v: MaxLossOverride | null) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draftMode, setDraftMode] = useState<'dollar' | 'percent'>(override?.mode ?? 'percent');
  const [draftValue, setDraftValue] = useState(() =>
    override
      ? (override.mode === 'percent' ? override.value * 100 : override.value)
      : 0,
  );

  const startEdit = () => {
    setDraftMode(override?.mode ?? 'percent');
    setDraftValue(override ? (override.mode === 'percent' ? override.value * 100 : override.value) : 0);
    setEditing(true);
  };

  const apply = () => {
    const value = draftMode === 'percent' ? draftValue / 100 : draftValue;
    onApply({ mode: draftMode, value });
    setEditing(false);
  };

  const clear = () => {
    onApply(null);
    setEditing(false);
  };

  return (
    <div className={styles.structuralStop}>
      <Text size={10} tone="dim">Max loss budget</Text>
      <Text size={11} tone="secondary">
        ${Math.round(limitDollar).toLocaleString('en-US')}
        {override
          ? ` (override: ${override.mode === 'percent' ? `${(override.value * 100).toFixed(2)}%` : `$${override.value.toLocaleString('en-US')}`})`
          : ' (account default)'}
      </Text>
      {!editing ? (
        <button type="button" className={styles.btn} onClick={startEdit}>
          <Text size={12} weight={500}>{override ? 'Edit trade loss budget' : 'Set trade loss budget'}</Text>
        </button>
      ) : (
        <div className={styles.targetPctRow}>
          <button
            type="button"
            className={styles.btn}
            onClick={() => setDraftMode('percent')}
            aria-pressed={draftMode === 'percent'}
          >
            <Text size={12} weight={draftMode === 'percent' ? 600 : 400}>%</Text>
          </button>
          <button
            type="button"
            className={styles.btn}
            onClick={() => setDraftMode('dollar')}
            aria-pressed={draftMode === 'dollar'}
          >
            <Text size={12} weight={draftMode === 'dollar' ? 600 : 400}>$</Text>
          </button>
          <input
            type="number"
            className={styles.editInput}
            value={draftValue}
            min={0}
            step={draftMode === 'percent' ? 0.25 : 10}
            onChange={(e) => setDraftValue(Math.max(0, Number(e.target.value) || 0))}
            aria-label="Max loss override value"
          />
          <button type="button" className={styles.btn} onClick={apply} aria-label="Apply max loss override">
            <Text size={12} weight={500}>Apply</Text>
          </button>
          {override && (
            <button type="button" className={styles.btn} onClick={clear}>
              <Text size={12} weight={500}>Use default</Text>
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export type { EditOverlay, TouchedFields };
export { triggerDetailText, pullbackDetailText, trendDetailText, eventDetailText, volDetailText };
