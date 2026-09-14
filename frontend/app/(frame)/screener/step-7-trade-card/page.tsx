'use client';

/*
 * Screener Step 7 — Trade Card.
 * Prev/Next cycles ranked candidates, basket pins multiple. Send basket
 * opens a review dialog where any row can be switched from auto-send
 * (sent to broker mock) to manual (added to portfolio tagged MANUAL).
 * Successful submits surface a bottom-right toast with a Portfolio link.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { Title, Text } from '@/components/primitives';
import { TradeCard, type EditOverlay, type TouchedFields } from '@/components/organisms/TradeCard';
import { CandidateNav } from '@/components/molecules/CandidateNav';
import { SendToBrokerDialog, type DraftOrder } from '@/components/organisms/SendToBrokerDialog';
import { usePortfolioStore, persistPosition, applyPersistedPosition } from '@/lib/portfolioStore';
import { useRiskStore } from '@/lib/riskStore';
import { contractId as buildContractId } from '@/types/domain';
import { useScanStore } from '@/lib/scanStore';
import { selectCardEdits } from '@/lib/cardEdits';
import { logAudit } from '@/lib/audit';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import type {
  PortfolioPosition, TradeCardData, StructuralStop, FirstPassageEstimate, FirstPassageContext, ExitPlan, MaxLossOverride,
} from '@/types/domain';
import { BrokerPicker }      from '@/components/organisms/BrokerPicker';
import { AutoTradeArm }      from '@/components/organisms/AutoTradeArm';
import { useAutoTradeStore } from '@/lib/autoTradeStore';
import { premiumStopDollarToSend } from '@/lib/premiumStop';
import { checkInvalidation, MISSING_INVALIDATION_MESSAGE, MISSING_INVALIDATION_TITLE } from '@/lib/risk';
import { api }               from '@/lib/api';
import {
  applyPickedContract, contractKeyFor, horizonFieldsFrom, mergePlan, resolveBasketCards,
  rrOverridesFrom, withCachedEstimate,
  cacheStructural, cacheFirstPassage, cacheExitPlan,
  type OverriddenCard, type RecomputedPlanShape, type CachedFirstPassage, type CachedStructural, type CachedExitPlan,
} from '@/lib/tradeCardOverride';
import styles from '../screener.module.css';
import toastStyles from './toast.module.css';
import paperStyles from './page.module.css';

function nowISOLocal(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

function todayISO(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function generateRecId(): string {
  return 'REC-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6).toUpperCase();
}

// The "why was this bought" snapshot — attached to the position once, at buy
// time, so it survives independent of later scans overwriting scanStore.
function tradeCardSnapshotOf(card: TradeCardData): Record<string, unknown> {
  return {
    stockScore: card.stockScore,
    stockConfidence: card.stockConfidence,
    stockBreakdown: card.stockBreakdown,
    contractScore: card.contractScore,
    contractConfidence: card.contractConfidence,
    contractBreakdown: card.contractBreakdown,
    rrRatio: card.rrRatio,
    rrModel: card.rrModel,
    strike: card.contractDetails?.strike ?? null,
  };
}

function positionFromOrder(
  order: DraftOrder,
  structuralStop: number | null = null,
  exitPlan: ExitPlan | null = null,
  // Feature 5 — the active pre-trade override for this symbol, read by the
  // caller from the shared maxLossOverrideBySymbol cache (this is a module-
  // level function, no closure access to component state).
  maxLossOverride: MaxLossOverride | null = null,
  // Piece 4 — the per-trade premium stop derived from the card's editable
  // "Premium stop" dollar field. Module-level function, so the caller reads it
  // the same way it reads maxLossOverride above.
  // The card's "Premium stop" field holds a DOLLAR loss; the percentage is
  // derived below against this path's own `mid`, so the stored fraction is
  // always relative to the entryPrice actually persisted — which is exactly
  // what the alert compares (`opt_price <= entry_price * (1 - pct)`).
  premiumStopDollar: number | null = null,
  // The card's editable Invalidation, resolved by the caller through
  // `invalidationFor` (module-level function, no closure access to component
  // state -- same shape as maxLossOverride above). Defaults to the card's own
  // value so an untouched card behaves exactly as before.
  invalidation: number | null = null,
  // The card's editable Entry limit, resolved through `entryLimitFor`. Only
  // reached as a fallback for `mid` below, but it must be the SAME value the
  // broker order was placed at or the position's entry price disagrees with
  // the order that created it.
  entryLimit: number | null = null,
  /** ROUND 10 finding 7 — the LIVE option mid, when the caller has one.
   *
   *  `buildPaperPosition` takes `livePrice` and prefers it; this path did not,
   *  so the two send paths stored different `entryPrice` values for the same
   *  card whenever a quote had been fetched — the denominator the premium stop
   *  is derived against, and the threshold both alert engines compare. The
   *  round-9 "two send paths cannot disagree" test could not see it: its
   *  fixture set the contract-quote mock to exactly `contractDetails.mid`, so
   *  live and scan were the same number. */
  livePrice: number | null = null,
): PortfolioPosition {
  const c   = order.card;
  const cd  = c.contractDetails;
  const mid = (livePrice != null && livePrice > 0 ? livePrice : null)
    ?? cd?.mid ?? entryLimit ?? c.entry.limit;
  const dte = cd?.dte ?? 24;
  return {
    symbol:        c.symbol,
    contract:      c.contract,
    direction:     c.direction,
    entryDate:     todayISO(),
    expiry:        cd?.expiry ?? new Date(Date.now() + dte * 86_400_000).toISOString().slice(0, 10),
    dteRemaining:  dte,
    dteTotal:      dte,
    entryPrice:    mid,
    currentPrice:  mid,
    pnlDollar:     0,
    pnlPct:        0,
    stop:          invalidation ?? c.exit.invalidation,
    // Non-null here means the caller resolved a TOUCHED field, so the stop is
    // an absolute price the user typed and the backend must not re-anchor it.
    stopIsUserSet: invalidation != null,
    structuralStop,
    exitPlan,
    maxLossOverride,
    // Sent as DOLLARS; the backend derives the fraction against the entry
    // price it persists (which may be a live quote, not this `mid`).
    premiumStopDollar,
    targets:       c.exit.targets,
    status:        c.finalStatus,
    // Both quantities travel to the position, kept apart
    // (PHASE-A-NULL-IVRANK-2026-09-06). Dropping `iv` here would blank the
    // portfolio's IV column for every position opened from a card until a
    // live quote happened to refill it.
    ivRank:        cd?.ivRank,
    iv:            cd?.iv,
    delta:         cd?.delta,
    theta:         cd?.theta,
    vega:          0.20,
    contracts:     order.contracts,
    source:        order.autoSend ? 'broker' : 'manual',
    orderedAt:     nowISOLocal(),
    recId:         generateRecId(),
    tradeCardSnapshot: tradeCardSnapshotOf(c),
  };
}

interface ToastState {
  auto:    number;
  manual:  number;
  queued:  number;   // subset of auto+manual that is pending a backend retry
  // Positions whose requested size was auto-reduced by the backend's risk
  // check to fit exposure limits — "SYMBOL: N contracts" per entry.
  adjusted: string[];
}

export default function Step7Page() {
  const [cards, setCards]         = useState<TradeCardData[]>([]);
  const [active, setActive]       = useState<string>('');
  const [basket, setBasket]       = useState<string[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [toast, setToast]         = useState<ToastState | null>(null);
  const [recIdMap, setRecIdMap]   = useState<Record<string, string>>({});
  // "Check structure" results captured from the active TradeCard, per SYMBOL — the
  // structural level is a function of (symbol, direction, stock_price) only, so the
  // contract never enters the key. Serves two readers: the order-send path (which
  // needs just `.stop.price`) and the TradeCard restore path (which needs the whole
  // level plus the price it was measured against, so the Exit Plan section can
  // still show the restored level itself — the R:R-vs-structural-stop column is
  // a separate matter: it never recomputes from a restore alone, only from a
  // fresh Estimate click with both sides independently reconfirmed, see round 5
  // of the plan's audit notes). Only ever populated for
  // whichever symbol is/was the active card, since "Check structure" is a
  // single-card, user-triggered action (see TradeCard's onStructuralStopChange doc
  // comment). Undefined (never fetched/reset) leaves a symbol's entry untouched
  // rather than clearing it, so navigating away and back to an already-checked
  // candidate doesn't lose its captured level.
  const [structuralBySymbol, setStructuralBySymbol] = useState<Record<string, CachedStructural>>({});
  // "Estimate" (Monte Carlo first-passage) results, per CONTRACT — unlike the
  // structural stop these ARE contract-specific (every optionPrice is
  // premium*(1+pct) off that contract's own premium), so they're keyed by
  // contractKeyFor, the same identity plansBySymbol tags its entries with.
  const [estimatesByContract, setEstimatesByContract] = useState<Record<string, CachedFirstPassage>>({});
  // "Compute Exit Plan" results, per CONTRACT — same reasoning as
  // estimatesByContract: the plan's repricing/probability is computed off
  // that contract's own strike/dte/premium, so it must be keyed by contract,
  // not symbol.
  const [exitPlanByContract, setExitPlanByContract] = useState<Record<string, CachedExitPlan>>({});
  // Feature 7 — the single shared source of truth for "how many contracts" a
  // given symbol's order carries. Keyed by SYMBOL (not contract), matching
  // structuralBySymbol's keying: a contract switch within the same symbol
  // should not reset a user's sizing choice. Fed into TradeCard's existing
  // `contracts` prop (which already seeds `overlay.contracts` on mount and
  // re-syncs via a `[initialContracts]` effect) and updated from the existing
  // `onEditsChange` callback — no new prop/callback pair needed on TradeCard
  // itself. Every order-placement path (quick Place Limit/Market, auto-trade
  // arm, and SendToBrokerDialog's initial row seed) reads from this same map,
  // fixing the pre-existing bug where each of those defaulted to a hardcoded
  // 1 independent of what the card displayed.
  // Named `orderContractsBySymbol` (not `contractsBySymbol`) to avoid
  // colliding with the pre-existing scanStore selector of that name below
  // (`Record<symbol, OptionContract[]>` — the picked-contract-per-symbol map,
  // an unrelated concept that happens to share a plausible name).
  const [orderContractsBySymbol, setOrderContractsBySymbol] = useState<Record<string, number>>({});
  // Piece 4 — the card's editable "Premium stop" DOLLAR field, cached off the
  // overlay channel that already carries `contracts`.
  //
  // Keyed by CONTRACT, not by symbol, unlike `orderContractsBySymbol` beside
  // it. A contracts count is genuinely a decision about the underlying; a
  // dollar premium stop is meaningful only against the premium of the one
  // contract it was typed on. TradeCard resets its overlay on a contract
  // change with a bare `setOverlay` that does not call `onEditsChange`, so a
  // symbol-keyed map kept the PREVIOUS contract's dollar: edit the AAPL 190C
  // ($5.20 mid, $3.12 stop), switch to the 200C ($4.00 mid), send, and the
  // 200C was armed at 78% — or, on a cheaper contract, at a ratio above 1,
  // which the router stores as NULL so the user's choice vanished silently.
  // Same keying as `exitPlanByContract`/`estimatesByContract`, for the same
  // reason.
  // NULL means "the user has not touched this card's premium stop", which is a
  // distinct state from any dollar amount and the reason this cache cannot
  // simply hold `overlay.premiumStop`: the overlay is SEEDED with
  // `exit.premiumStop` (the global percentage in dollars), the card reports its
  // whole overlay on every patch, and the seed itself moves under an untouched
  // field when `mergePlan` lands. Only the card knows which it is, so it tells
  // us -- see `onEditsChange`'s `meta.touched.premiumStop`.
  // PHASE G piece 5, build step 2 (spec §5). These four caches used to be
  // `useState` on this page. They now live in ONE scan-stamped slice on
  // scanStore, read through `selectCardEdits` -- which returns an EMPTY slice
  // whenever the slice's `scan_id` stamp does not match the scan currently in
  // the store, so a previous run's typed levels can never render on a card
  // built from new prices.
  //
  // READ THE SLICE ONLY THROUGH THIS SELECTOR. `state.optionsCardEdits` read
  // directly would skip the stamp check, which is the single defect this design
  // exists to make impossible.
  const cardEdits = useScanStore((s) => selectCardEdits(s, 'options'));
  const setCardEdit = useScanStore((s) => s.setCardEdit);
  const premiumStopByContract = cardEdits.premiumStop;
  // The card's editable INVALIDATION -- the underlying stock level that becomes
  // `PortfolioPosition.stop` and drives STOP_REACHED. Keyed by SYMBOL, like
  // `structuralBySymbol` and `maxLossOverrideBySymbol` beside it and unlike
  // `premiumStopByContract`: an invalidation is a price level on the
  // UNDERLYING, so it is the same thesis whichever strike expresses it, while a
  // dollar premium stop is meaningful only against one contract's premium.
  //
  // NULL means "untouched, use the card's own `exit.invalidation`" -- the same
  // distinct state `premiumStopByContract` carries, for the same reason: the
  // seed moves under an untouched field when `mergePlan` lands, so a cached
  // seed would pin the stop to a level the plan has since replaced.
  const invalidationBySymbol = cardEdits.invalidation;
  // The card's editable ENTRY LIMIT -- the option premium posted as the broker
  // order's `limit_price`. Contract-keyed for the same reason the premium stop
  // is: it is a price for one contract, meaningless against another.
  const entryLimitByContract = cardEdits.entryLimit;
  /** Bumped in lockstep with clearing the three edit caches below, and handed
   *  to TradeCard as `resetKey`. Without it the parent dropped a cached edit
   *  while the card kept showing (and keeping touched) the same value -- the
   *  card said $2.71 and the order said $6.00. See the prop's own note. */
  const [scanEpoch, setScanEpoch] = useState(0);
  const handleEditsChange = (
    symbol: string,
    cardContractKey: string | null,
    overlay: EditOverlay,
    meta: { touched: TouchedFields },
  ) => {
    setOrderContractsBySymbol((prev) =>
      prev[symbol] === overlay.contracts ? prev : { ...prev, [symbol]: overlay.contracts },
    );
    // The identity-preserving guard these three carried inline now lives in
    // `writeCardEdit` (lib/cardEdits.ts), for the same reason it existed here:
    // the card reports its whole overlay on every patch, so an unchanged write
    // must not produce a new object or every render re-triggers this cascade.
    // `null` still means "untouched", which is why `meta.touched` gates each.
    setCardEdit('options', 'invalidation', symbol,
      meta.touched.invalidation ? overlay.invalidation : null);
    if (!cardContractKey) return;
    setCardEdit('options', 'premiumStop', cardContractKey,
      meta.touched.premiumStop ? overlay.premiumStop : null);
    setCardEdit('options', 'entryLimit', cardContractKey,
      meta.touched.entryLimit ? overlay.entryLimit : null);
  };
  /** The cache key for the two CONTRACT-keyed edits (entry limit, premium
   *  stop). `contractKeyFor` returns null whenever `contractDetails` is
   *  missing a strike, an expiry or a right, and `handleEditsChange` used to
   *  early-return on that null — so on such a card the user's typed entry
   *  limit was displayed, then silently dropped: the card showed $2.71 while
   *  `entryLimitFor` fell back to `card.entry.limit` and the button label AND
   *  the posted `limit_price` were both $2.50. That is the display-vs-send
   *  disagreement this whole branch exists to remove, re-entered through the
   *  one code path that skipped the cache.
   *
   *  The fallback embeds `card.contract` (the display label the send path
   *  already falls back to in `toOptionSymbol`), so it is still per-contract:
   *  it cannot merge an edit made on one contract into another, which is the
   *  property `contractKeyFor` exists to guarantee. Writer and both readers go
   *  through this one function, so they cannot disagree about the key. */
  const editKeyFor = (card: TradeCardData | undefined): string | null => {
    const strict = contractKeyFor(card);
    if (strict) return strict;
    if (!card?.symbol || !card.contract) return null;
    return `${card.symbol}|${card.contract}`;
  };

  // The ONE place either send path decides what to post. Reading the map is
  // not enough on its own: the overlay is seeded with `exit.premiumStop`, which
  // is the global percentage rendered in dollars rather than anything the user
  // chose, and the card reports its whole overlay on every patch. See
  // `premiumStopDollarToSend`.
  const premiumStopDollarFor = (card: TradeCardData): number | null => {
    const key = editKeyFor(card);
    return premiumStopDollarToSend(key ? premiumStopByContract[key] : null);
  };
  // The ONE place every send path resolves the invalidation stop, so a position
  // cannot be stored at a level different from the one the card was showing.
  // Falls back to the card's own value, which is what an untouched field means
  // -- and which stays live as `mergePlan` updates it, precisely because an
  // untouched field caches `null` rather than a snapshot of the seed.
  // NULLABLE since piece 3: `card.exit.invalidation` is null on a candidate
  // restored from a scan session persisted before it, whose stored flat
  // percentage the scanStore v15 migration stripped. The user can clear that by
  // typing a stop, which lands in this same cache.
  //
  // EVERY send path refuses such a card as of DIRECT-SEND-STOP-GATE-2026-09-09,
  // and it took a second build to get there. `missing_invalidation` is raised by
  // `checkTradeRisk`, which runs ONLY in SendToBrokerDialog -- the basket path.
  // The two DIRECT buttons ("Place Limit", "Right Now — Market") never called it
  // and stored `PortfolioPosition.stop = null` instead. That was not a wrong
  // number -- the field is already `number | null`, and both alert engines skip a
  // null stop (alertEngine.ts's STOP_REACHED, the backend `alert_generator`'s
  // `pos.stop is not None`) -- so it sat below the audit gate and was logged
  // against main rather than widened into the piece-3 branch. What it DID mean is
  // that a position opened that way armed no stop alert at all and looked
  // entirely normal in the portfolio list, which is discovered at the worst
  // possible moment. Kenneth chose the refusal over a marker on the position.
  // `stopMissing` below is that gate, and AutoTradeArm takes the same check as a
  // prop -- gating only these two would have moved the hole rather than closed
  // it.
  const invalidationFor = (card: TradeCardData): number | null =>
    invalidationBySymbol[card.symbol] ?? card.exit.invalidation;
  // Whether the value `invalidationFor` just returned was TYPED or inherited.
  // The cache holds null for an untouched field precisely so these two can be
  // told apart. The backend re-anchors a plan-derived stop by
  // (live price - scanStockPrice) and must be told to skip that for a typed
  // one: a $180 stop typed against a $200 quote on a stock scanned at $145
  // was stored as $235, above spot, raising a Critical STOP_REACHED on the
  // first backend scan for a stop the user believed was 10% away.
  const invalidationIsUserSetFor = (card: TradeCardData): boolean =>
    invalidationBySymbol[card.symbol] != null;
  /** The RAW cache entry -- null while the field is untouched.
   *
   *  ROUND 10 finding 6. The basket path passed `invalidationFor(o.card)`,
   *  which falls back to `card.exit.invalidation` and is therefore NEVER null,
   *  so `positionFromOrder`'s `stopIsUserSet: invalidation != null` was true
   *  for every basket position including ones nobody had edited. Two send
   *  paths reported two different values of a flag whose entire job is to tell
   *  the server whether a human typed the number -- and a `true` there tells
   *  the router to skip re-anchoring a stop that IS plan-derived. Passing the
   *  raw entry is also what `positionFromOrder` was written for: it applies
   *  `invalidation ?? c.exit.invalidation` internally. */
  const invalidationRawFor = (card: TradeCardData): number | null =>
    invalidationBySymbol[card.symbol] ?? null;
  // Likewise for the limit price every order path posts, and for the button
  // label that promises it. A label showing one price while the order carries
  // another is the same defect wearing a different hat.
  const entryLimitFor = (card: TradeCardData): number => {
    const key = editKeyFor(card);
    return (key ? entryLimitByContract[key] : null) ?? card.entry.limit;
  };
  // Feature 5 — the shared pre-trade max-loss override cache, keyed by SYMBOL
  // (a risk decision about the underlying, same keying as structuralBySymbol,
  // not exitPlanByContract). Fed into TradeCard's initialMaxLossOverride prop
  // and updated from onMaxLossOverrideChange; also read by
  // buildPaperPosition/positionFromOrder (to carry the override onto the
  // created PortfolioPosition) and SendToBrokerDialog (so its own risk check
  // knows about an active override and doesn't force a spurious extra
  // confirmation click).
  // Phase G piece 5 -- in the same stamped slice as the three above. It was the
  // one edit cache the `[scanResult]` effect below forgot to clear (spec §5.1
  // calls that "an omission, not a decision"); sharing one slice with one stamp
  // is what makes forgetting it again impossible rather than merely fixed.
  const maxLossOverrideBySymbol = cardEdits.maxLossOverride;
  const handleMaxLossOverrideChange = (symbol: string, override: MaxLossOverride | null) => {
    setCardEdit('options', 'maxLossOverride', symbol, override);
  };
  // Both write paths delegate to a pure reducer in lib/tradeCardOverride.ts,
  // alongside the read side (withCachedEstimate) — the two rules they enforce are
  // the highest-consequence logic in this feature and are unit-tested there rather
  // than living as untestable inline closures here:
  //   1. a `undefined`/`null` sentinel (reset on contract switch, or cleared at the
  //      start of a re-run) is IGNORED, so an in-flight or failed re-run never
  //      destroys the value already on screen;
  //   2. an unchanged write returns the IDENTICAL `prev` object, which is what
  //      breaks the render cascade — the callback props passed to TradeCard below
  //      are fresh inline closures every render (matching this file's existing
  //      style for onSendToBroker etc.) and TradeCard keeps a ref synced to them
  //      via its own effect, so a write that always produced a new object would
  //      re-render the parent on every TradeCard render, re-create the props,
  //      re-fire that sync effect... unbounded. React skips the re-render on an
  //      identical state reference, so a no-op call here is genuinely a no-op.
  const handleStructuralStopChange = (
    symbol: string,
    stop: StructuralStop | null | undefined,
    stockPrice: number | null,
  ) => setStructuralBySymbol((prev) => cacheStructural(prev, symbol, stop, stockPrice));
  const handleFirstPassageChange = (
    key: string | null,
    estimate: FirstPassageEstimate | null | undefined,
    context: FirstPassageContext | null,
  ) => setEstimatesByContract((prev) => cacheFirstPassage(prev, key, estimate, context));
  const handleExitPlanChange = (
    key: string | null,
    plan: ExitPlan | null | undefined,
  ) => setExitPlanByContract((prev) => cacheExitPlan(prev, key, plan));

  useEffect(() => {
    setRecIdMap((prev) => {
      const next: Record<string, string> = {};
      for (const c of cards) {
        next[c.symbol] = prev[c.symbol] || generateRecId();
      }
      return next;
    });
  }, [cards]);

  const { selectedBroker, setSelectedBroker } = useAutoTradeStore();
  const [limitPlacing,   setLimitPlacing]     = useState(false);
  const [marketPlacing,  setMarketPlacing]    = useState(false);
  const [paperOrderId,   setPaperOrderId]     = useState<string | null>(null);
  const [orderError,     setOrderError]       = useState<string | null>(null);
  // A LIST, not one slot. Both writers below used to call `setSizeAdjustedNote`
  // on the same string state, so an order that was BOTH size-reduced and had
  // its premium stop dropped showed whichever landed second and silently lost
  // the other -- two independent things the user needs to know about the same
  // fill. Appending keeps both.
  const [saveNotes, setSaveNotes] = useState<string[]>([]);
  const addSaveNote = useCallback((note: string) => {
    setSaveNotes((prev) => (prev.includes(note) ? prev : [...prev, note]));
  }, []);
  const sizeNote = (adjustedQty: number) =>
    `Size reduced to ${adjustedQty} contract${adjustedQty === 1 ? '' : 's'} to fit exposure limits.`;
  // The one place the card can tell the user their premium stop did not survive
  // the save-time re-anchor. The router logs it server-side and the position
  // quietly inherits the global -- a TIGHTER stop than the one asked for.
  const droppedStopNote = (requested: number) =>
    `Premium stop of $${requested.toFixed(2)}/share could not be applied at the filled premium — this position inherits the global stop.`;
  /* ROUND 10 finding 1 — the quote CARRIES THE CONTRACT IT IS FOR.
   *
   * These used to be bare values, cleared at the top of the fetch effect. The
   * effect has an early return ABOVE that clear (the override-already-claimed
   * dedup gate), so on Next-then-Prev back to a candidate whose contract was
   * user-picked in step 6, the effect re-ran, returned early, and left the
   * OTHER candidate's quote standing. The AAA card then printed BBB's mid,
   * `buildPaperPosition` stored it as AAA's entryPrice, and round 9's own
   * `liveMid` prop carried it into the auto-trade arm request and into the
   * card's premium-stop bounds -- so a $2.22 contract accepted a $7.00
   * "premium stop" and the daily-loss gate booked the wrong premium entirely.
   *
   * Clearing before the early return would fix that one path. Keying fixes
   * every path, including the next early return someone adds: a quote whose
   * key does not match the card on screen is not this card's quote, and
   * `liveQuoteForCard` below is the only thing any consumer may read. */
  const [liveQuote,      setLiveQuote]        = useState<{ key: string; price: number; delta: number; theta: number; ivRank: number | null; iv: number | null; spread: number; volume: number } | null>(null);
  const [liveStockPrice, setLiveStockPrice]   = useState<{ symbol: string; price: number } | null>(null);
  const [fetchingQuote,  setFetchingQuote]    = useState(false);
  // Recomputed Entry/Exit/RR/targets, per SYMBOL, for every overridden contract —
  // the active card AND every overridden basket item share this one cache so a
  // basket "Send to broker" never falls back to an auto-pick's stale plan just
  // because that symbol isn't the currently-active card. Each entry is tagged
  // with the contract key it was computed for so a plan for contract A is never
  // merged onto contract B while B's recompute is still in flight.
  const [plansBySymbol, setPlansBySymbol]     = useState<Record<string, { key: string; plan: RecomputedPlanShape }>>({});
  const [planErrors,    setPlanErrors]        = useState<Record<string, string>>({});
  const [recomputeTick, setRecomputeTick]     = useState(0);   // bump to force a retry after a failure
  // Tracks which (symbol -> contractKey) a recompute has already been fired for,
  // so the effect below doesn't refire on every render — cleared per-symbol by
  // retryPlan() to force a refetch after a failure.
  const requestedPlanKeysRef = useRef<Record<string, string>>({});

  const scanResult          = useScanStore((s) => s.scanResult);
  const setSelectedSymbol   = useScanStore((s) => s.setSelectedSymbol);
  const pickedContracts     = useScanStore((s) => s.pickedContracts);
  const contractsBySymbol   = useScanStore((s) => s.contractsBySymbol);

  useEffect(() => {
    // A new scan invalidates every cached "Estimate" and "Check structure"
    // result: both were computed against the previous run's prices (and, for
    // the estimate, against that run's recomputed invalidation level), so
    // carrying them forward would show pre-scan numbers on post-scan cards.
    // NOTE this also clears the levels the order-send path reads — a structural
    // stop checked before a scan no longer rides along into a position opened
    // after it, which is the intended behaviour, not a side effect.
    //
    // In practice this line is belt-and-suspenders, not the primary guard:
    // `setScanResult` has exactly two production callers (RunScanButton, on
    // the separate step-3-direction route, and StoreHydration's mount-only
    // effect), so the only way this effect ever runs with a genuinely NEW
    // scanResult is if the user leaves this page to reach RunScanButton —
    // which unmounts Step7Page and, with it, these two useState caches,
    // independent of this call. Kept in case that ever stops being true (an
    // in-place scan re-run added to this page, a live scan-result push), so
    // this file doesn't silently rely on an invariant that lives elsewhere.
    setEstimatesByContract({});
    setStructuralBySymbol({});
    setExitPlanByContract({});
    // THE FOUR EDIT CACHES ARE NOT CLEARED HERE, AND MUST NOT BE (Phase G piece
    // 5, spec §5 / §5.1). They now live in one scan-stamped slice on scanStore,
    // and the stamp already does this job: a new `scan_id` makes every older
    // edit read as empty, by every path that lands a result rather than only
    // the ones someone remembered to wire.
    //
    // Re-adding a reset call here would be worse than redundant -- it would be
    // WRONG. This effect also runs on MOUNT, where `scanResult` has not changed
    // at all, and on mount the slice may legitimately hold edits StoreHydration
    // just restored alongside the very result they were stamped against. A
    // blanket reset would destroy a restored pick on every page load, which is
    // exactly what spec test 11b pins against.
    //
    // The three FETCHED caches above still clear, because they are still local
    // `useState` and are not stamped by anything.
    // The card must still reset with them:
    setScanEpoch((n) => n + 1);
    if (scanResult?.candidates?.length) {
      setCards(scanResult.candidates);
      if (scanResult.candidates[0]) setActive(scanResult.candidates[0].symbol);
    } else {
      setCards([]);
      setActive('');
    }
  }, [scanResult]);

  useEffect(() => {
    if (active) setSelectedSymbol(active);
  }, [active, setSelectedSymbol]);

  // Clear paper order feedback when the user navigates to a different candidate.
  useEffect(() => { setPaperOrderId(null); setOrderError(null); setSaveNotes([]); }, [active]);

  const addPosition = usePortfolioStore((s) => s.addPosition);
  const incrementDaily = useRiskStore((s) => s.incrementDaily);

  const cardIndex = useMemo(
    () => Object.fromEntries(cards.map((c) => [c.symbol, c])),
    [cards],
  );
  const symbols = cards.map((c) => c.symbol);

  const card = cardIndex[active] ?? cards[0];

  /** Resolve the picked (overridden) contract for any symbol, given the current
   *  scanStore picks — used for the active card AND every basket item so both
   *  paths apply the exact same override logic. */
  function resolvePickedCard(symbol: string): OverriddenCard | undefined {
    const raw = cardIndex[symbol];
    if (!raw) return undefined;
    const pid = pickedContracts[symbol];
    const picked = pid ? contractsBySymbol[symbol]?.find((c) => c.id === pid) : undefined;
    return applyPickedContract(raw, picked);
  }

  // The active card with the user-selected contract's details swapped in.
  // NOTE: this only updates the Contract Details block — Entry/Exit/RR/targets
  // are recomputed asynchronously (see the shared per-symbol effect below) and
  // merged into `effectiveCard`, so the whole card describes the selected contract.
  const pickedCard = card ? resolvePickedCard(card.symbol) : undefined;
  const isOverride = !!pickedCard?._userOverride;

  const liveQcd = pickedCard?.contractDetails;
  const contractKey = contractKeyFor(pickedCard);
  // The looser key the three edit caches use — see editKeyFor. Declared from
  // `effectiveCard` (not `pickedCard`) so it matches what the writer reports
  // and what `entryLimitFor`/`premiumStopDollarFor` read on the send paths.

  // The recompute is only valid for the contract it was computed for. This
  // guards the 1–3 s window while navigating between two overridden contracts.
  const activePlanEntry = pickedCard ? plansBySymbol[pickedCard.symbol] : undefined;
  const planForThisContract = isOverride && activePlanEntry?.key === contractKey ? activePlanEntry.plan : null;
  // For an overridden contract the plan must be loaded before Entry/Exit are
  // trustworthy; ordering is gated on this so no order is ever placed on the
  // auto-pick's Entry Plan for a contract the user swapped.
  const planReady = !isOverride || !!planForThisContract;
  const activePlanError = pickedCard ? planErrors[pickedCard.symbol] : undefined;

  // Merge the recomputed Entry/Exit/RR into the overridden card once it arrives.
  const effectiveCard = pickedCard && planForThisContract ? mergePlan(pickedCard, planForThisContract) : pickedCard;

  /* DIRECT-SEND-STOP-GATE-2026-09-09. The two direct buttons' half of the
   * refusal `checkTradeRisk` already raises as `missing_invalidation` on the
   * basket path -- see the long note on `invalidationFor` for what it is for.
   *
   * Read through `invalidationFor`, NOT `effectiveCard.exit.invalidation`, and
   * that is the whole point of the gate rather than an implementation detail:
   * a stop the user has TYPED into the Invalidation field lives in
   * `invalidationBySymbol`, and typing one is the single gesture that fixes a
   * restored card. Gating on the card alone would refuse it forever, which is
   * exactly the defect C2 gave `checkTradeRisk` its `resolvedInvalidation`
   * parameter to avoid -- the same mistake, one screen along.
   *
   * `checkInvalidation` rather than a local `!= null`, so the direct paths and
   * the basket cannot disagree about what counts as a stop (it also refuses 0
   * and negatives). Null-safe on `effectiveCard` because the buttons render
   * inside its own guard but the send handlers do not. */
  const resolvedInvalidationForCard = effectiveCard ? invalidationFor(effectiveCard) : null;
  const stopMissing = !checkInvalidation(resolvedInvalidationForCard);
  const editKey = editKeyFor(effectiveCard);

  // The card actually handed to <TradeCard>, with any cached "Estimate" /
  // "Check structure" result for this contract spliced into exit.* — the same
  // fields TradeCard reads for its initial state and its contract-change reset,
  // so a Prev/Next round trip restores the Profit Targets rows (and the
  // T1/T2/T3 inputs) without re-firing a single request. The R:R-vs-structural-
  // stop column is NOT restored this way (round 5 audit, see the plan's notes):
  // it requires both the structural stop and the estimate independently
  // reconfirmed fresh in the SAME mount before it will compute, so a restored
  // pair shows '—' until the user's next Estimate click.
  // DELIBERATELY applied after mergePlan (which replaces `exit` wholesale and
  // would otherwise discard the splice) and DELIBERATELY not used anywhere else:
  // ordering, sizing and the order-send path all keep reading `effectiveCard`,
  // so nothing about what gets sent to a broker depends on this display-only
  // enrichment.
  //
  // On the memo's limits: for a NON-overridden card `effectiveCard` is a stable
  // reference, so this genuinely holds `cardForDisplay` stable. For an OVERRIDDEN
  // card `applyPickedContract` rebuilds the object every render, so both change
  // identity every render regardless — already true of `effectiveCard` today, and
  // safe because no effect inside TradeCard depends on `data`'s identity (the
  // reset effect keys on data.symbol/data.contract, and the only whole-`data`
  // dependencies there are useMemos that set no state). A new `data` reference
  // therefore costs a recompute and can never re-trigger the reset that would
  // wipe the values we just restored.
  const cardForDisplay = useMemo(
    () => withCachedEstimate(
      effectiveCard,
      contractKey ? estimatesByContract[contractKey] : undefined,
      effectiveCard ? structuralBySymbol[effectiveCard.symbol] : undefined,
      contractKey ? exitPlanByContract[contractKey] : undefined,
    ),
    [effectiveCard, contractKey, estimatesByContract, structuralBySymbol, exitPlanByContract],
  );

  // Every basket item, override-resolved and (if overridden) merged with its
  // recomputed plan. `basketPlansPending` gates the whole "Send to broker" flow
  // so a basket order can never go out carrying an overridden contract whose
  // Entry/Exit/RR still describe the auto-pick — the exact bug this recompute
  // machinery exists to prevent, previously reachable only via Send basket.
  // (resolveBasketCards is the same pure logic exercised directly in
  // lib/__tests__/tradeCardOverride.test.ts.)
  const { cards: basketCards, pending: basketPlansPending } = useMemo(
    () => resolveBasketCards(basket, cardIndex, pickedContracts, contractsBySymbol, plansBySymbol, exitPlanByContract),
    [basket, cardIndex, pickedContracts, contractsBySymbol, plansBySymbol, exitPlanByContract],
  );

  // Basket symbols (other than the active one, surfaced separately via
  // activePlanError) whose override plan failed outright — each needs its own
  // visible error + retry, or the basket stays silently stuck on "Computing…"
  // with no way to recover short of navigating to make that symbol active.
  const basketPlanErrors = basket
    .filter((sym) => sym !== pickedCard?.symbol && planErrors[sym])
    .map((sym) => ({ symbol: sym, error: planErrors[sym]! }));

  /** Force a re-fetch of a symbol's plan after a failure (Retry button). */
  function retryPlan(symbol: string) {
    delete requestedPlanKeysRef.current[symbol];
    setPlanErrors((prev) => { const next = { ...prev }; delete next[symbol]; return next; });
    setRecomputeTick((t) => t + 1);
  }

  // Live quote + recompute for the ACTIVE card, CHAINED in one effect rather
  // than two separate ones. Two independent effects both keyed on `contractKey`
  // — one setting liveQuote, one reading it to build the recompute premium —
  // raced: they run in the same commit and read each other's PRE-update state,
  // so the recompute fired using a stale liveQuote (from whatever contract was
  // previously viewed), and requestedPlanKeysRef (keyed only on contractKey,
  // not on which premium was used) then blocked the correct request from ever
  // firing once the real quote arrived — silently caching a plan computed with
  // the wrong premium, or (if the stale request lost a request race) getting
  // aborted and never retried. Chaining removes the race: the recompute is
  // fired directly off THIS fetch's own resolution, never off separately-read
  // liveQuote state.
  useEffect(() => {
    if (!contractKey || !pickedCard?.symbol || !liveQcd?.strike || !liveQcd.expiry || !liveQcd.right) {
      setLiveQuote(null);
      setFetchingQuote(false);   // an in-flight fetch from a PRIOR invocation is aborted below (or never started for this one) — don't leave "Fetching…" stuck on if this invocation never issues a request of its own.
      return;
    }
    const keyAtRequest = contractKey;
    const symbol = pickedCard.symbol;
    const isOverrideAtRequest = isOverride;

    // Gate BEFORE issuing any request — mirrors the basket effect's own
    // upfront ref check. `recomputeTick` is a dependency shared by every
    // basket symbol's Retry button, so this effect can tear down and re-run
    // for a reason that has nothing to do with the active symbol (retrying an
    // unrelated basket item). Without this gate, that unrelated bump would
    // spawn a fresh, redundant live-quote refetch here every time, and if
    // THAT redundant fetch/recompute later got torn down mid-flight by yet
    // another unrelated bump, its own (correctly-scoped) `settled` closure
    // would still match the same ref key and delete what was actually an
    // unrelated, already-completed claim — silently discarding/renumbering a
    // perfectly valid cached plan. Skipping outright when this exact contract
    // is already claimed (whether its own fetch already succeeded, or is
    // still legitimately in flight under a DIFFERENT invocation) means no
    // redundant invocation — and therefore no redundant settled/cleanup
    // interaction — is ever created in the first place.
    if (isOverrideAtRequest && requestedPlanKeysRef.current[symbol] === keyAtRequest) {
      return;
    }

    const controller = new AbortController();
    // Flips true the instant THIS invocation's own request settles (success,
    // failure, or a same-key dedup skip) — read only in cleanup below, via
    // closure, never via React state (whose read timing can't be trusted
    // relative to when cleanup runs for an unrelated reason).
    let settled = false;
    setLiveQuote(null);
    setLiveStockPrice(null);
    setFetchingQuote(true);

    // Fetch the contract's own quote AND a fresh stock quote in parallel —
    // independent lookups, no reason to serialize them. Without the stock
    // fetch, recomputePlan below would silently use pickedCard.price (the
    // scan-time snapshot) even though the contract's premium/delta/spread are
    // live — the Exit Plan's stock-price side stays stale while its
    // option-price side doesn't.
    Promise.all([
      api.getContractQuote(pickedCard.symbol, liveQcd.strike, liveQcd.expiry, liveQcd.right as 'C' | 'P', controller.signal)
        .catch(() => null),   // silently ignore — scan-time mid used as fallback below
      api.getStockQuote(pickedCard.symbol, controller.signal)
        .catch(() => null),   // silently ignore — scan-time price used as fallback below
    ])
      .then(([q, sq]) => {
        if (!controller.signal.aborted) {
          setLiveQuote(q ? { ...q, key: keyAtRequest } : null);
          if (sq) setLiveStockPrice({ symbol, price: sq.price });
        }
        return [q, sq] as const;
      })
      .then(([q, sq]) => {
        if (controller.signal.aborted) { settled = true; return; }
        setFetchingQuote(false);
        if (!isOverrideAtRequest) { settled = true; return; }   // not overridden — no plan to recompute
        if (requestedPlanKeysRef.current[symbol] === keyAtRequest) { settled = true; return; }   // claimed by a concurrent invocation while this quote was in flight
        requestedPlanKeysRef.current[symbol] = keyAtRequest;

        api.recomputePlan({
          symbol,
          direction:   pickedCard.direction,
          stock_price: sq?.price ?? pickedCard.price,
          strike:      liveQcd.strike,
          dte:         liveQcd.dte,
          premium:     q?.price ?? liveQcd.mid,
          delta:       liveQcd.delta,
          spread:      q?.spread ?? 0,
          // PIECE 3 — round-trip the stop this card already resolved. The
          // endpoint echoes it and builds the plan around it, so an override
          // changes the CONTRACT and nothing about where the stock stop sits.
          final_stop:  pickedCard.exit.finalStop ?? null,
          ...rrOverridesFrom(useScanStore.getState().scanOverrides),
          ...horizonFieldsFrom(useScanStore.getState().context),
        }, controller.signal)
          .then((plan) => {
            settled = true;
            if (controller.signal.aborted) return;
            setPlansBySymbol((prev) => ({ ...prev, [symbol]: { key: keyAtRequest, plan } }));
            setPlanErrors((prev) => { const next = { ...prev }; delete next[symbol]; return next; });
          })
          .catch(() => {
            settled = true;
            if (controller.signal.aborted) return;
            setPlanErrors((prev) => ({ ...prev, [symbol]: 'Could not compute the plan for the selected contract. Ordering stays disabled until it succeeds.' }));
          });
      });

    return () => {
      controller.abort();
      // Release this invocation's claim ONLY if its own request never settled
      // (was still genuinely in flight when the abort hit). `recomputeTick` is
      // a dependency shared by every basket symbol's retry, so this effect can
      // tear down for a reason that has NOTHING to do with this symbol (e.g.
      // the user retried a different, failed basket item) — if we released the
      // claim unconditionally in that case, this symbol's successful plan
      // would still be cached in plansBySymbol, but the re-run below would
      // treat it as unclaimed and fire a redundant recomputePlan for it too,
      // and if THAT incidental call happened to fail, it would overwrite a
      // perfectly valid plan's status with a spurious error banner. Checking
      // `settled` keeps a genuinely-completed request's claim intact, so an
      // unrelated tick bump correctly no-ops for this symbol.
      if (!settled && requestedPlanKeysRef.current[symbol] === keyAtRequest) {
        delete requestedPlanKeysRef.current[symbol];
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contractKey, isOverride, recomputeTick]);

  // Recompute Entry/Exit/RR/targets for every OVERRIDDEN BASKET item other than
  // the active symbol (which the effect above owns exclusively — see the `sym
  // === pickedCard?.symbol` skip below). Deliberately independent of liveQuote/
  // contractKey: basket items don't have their own live-quote fetch, so there's
  // no equivalent race here — each uses the picked contract's scan-time mid.
  useEffect(() => {
    const controller = new AbortController();
    // Per-claim `settled` flags (closure, not React state — see the
    // active-card effect's cleanup comment for why). `recomputeTick` is one
    // dependency shared by every basket symbol's Retry button, so retrying
    // symbol Y forces this whole effect to tear down and re-run even though
    // symbols X/Z's requests may have already succeeded — cleanup must only
    // release a claim that never actually settled, or X/Z would be silently
    // refetched (and, if that incidental refetch happened to fail, show a
    // false error banner for a contract that was already fine).
    const claimedThisInvocation: { symbol: string; key: string; settled: () => boolean }[] = [];
    for (const sym of basket) {
      if (sym === pickedCard?.symbol) continue;   // owned by the active-card effect above
      const resolved = resolvePickedCard(sym);
      if (!resolved?._userOverride || !resolved.contractDetails) continue;
      const key = contractKeyFor(resolved);
      if (!key || requestedPlanKeysRef.current[sym] === key) continue;
      requestedPlanKeysRef.current[sym] = key;
      let settled = false;
      claimedThisInvocation.push({ symbol: sym, key, settled: () => settled });
      const cd = resolved.contractDetails;
      api.recomputePlan({
        symbol: sym,
        direction: resolved.direction,
        stock_price: resolved.price,
        strike: cd.strike,
        dte: cd.dte,
        premium: cd.mid,
        delta: cd.delta,
        spread: 0,
        final_stop: resolved.exit.finalStop ?? null,
        ...rrOverridesFrom(useScanStore.getState().scanOverrides),
        ...horizonFieldsFrom(useScanStore.getState().context),
      }, controller.signal)
        .then((plan) => {
          settled = true;
          if (controller.signal.aborted) return;
          setPlansBySymbol((prev) => ({ ...prev, [sym]: { key, plan } }));
          setPlanErrors((prev) => { const next = { ...prev }; delete next[sym]; return next; });
        })
        .catch(() => {
          settled = true;
          if (!controller.signal.aborted) {
            setPlanErrors((prev) => ({ ...prev, [sym]: 'Could not compute the plan for this basket contract.' }));
          }
        });
    }
    return () => {
      controller.abort();
      for (const { symbol, key, settled } of claimedThisInvocation) {
        if (!settled() && requestedPlanKeysRef.current[symbol] === key) {
          delete requestedPlanKeysRef.current[symbol];
        }
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basket, pickedContracts, contractsBySymbol, cardIndex, pickedCard?.symbol, recomputeTick]);

  /** Build the pipe-delimited option id the OCC converter and broker adapters expect. */
  function toOptionSymbol(card: TradeCardData): string {
    const cd = card.contractDetails;
    if (cd?.strike != null && cd.expiry && cd.right) {
      return buildContractId(card.symbol, cd.strike, cd.expiry, cd.right);
    }
    return card.contract; // fallback (display label — broker may reject, best effort)
  }

  /** Build a paper position object without touching the store.
   *  `livePrice` (the freshly-fetched mid for the active contract) takes
   *  precedence over the scan-time mid so the entry price reflects the market
   *  at fill time, not when the scan ran. The backend re-fetches again at save
   *  time as the authoritative baseline; this keeps the local view correct
   *  until the next portfolio sync. */
  function buildPaperPosition(card: TradeCardData, orderType: 'LMT' | 'MKT', broker: string, orderId: string, livePrice?: number, contracts = 1): PortfolioPosition {
    const cd  = card.contractDetails;
    const mid = livePrice ?? cd?.mid ?? entryLimitFor(card);
    const dte = cd?.dte ?? 24;
    const brokerLabel =
      broker === 'tradier_paper' ? 'Tradier Paper' :
      broker === 'tastytrade_paper' ? 'Tastytrade Paper' :
      'IBKR Paper';
    const typeLabel   = orderType === 'LMT' ? 'Limit' : 'Market';
    const cardContractKey = contractKeyFor(card);
    return {
      symbol:        card.symbol,
      contract:      toOptionSymbol(card),
      direction:     card.direction,
      entryDate:     todayISO(),
      expiry:        cd?.expiry ?? '2026-12-31',
      dteRemaining:  dte,
      dteTotal:      dte,
      entryPrice:    mid,
      currentPrice:  mid,
      pnlDollar:     0,
      pnlPct:        0,
      // The EDITED invalidation, not the card's original. This drives
      // STOP_REACHED, so storing the original meant an edit from $195.80 to
      // $193.00 sent the position out with a stop the user had replaced --
      // and the alert then fired $2.80 early, at a level nothing on screen
      // still showed.
      stop:          invalidationFor(card),
      // See invalidationIsUserSetFor: this path DOES send scanStockPrice, so
      // without the flag the router shifted the typed stop by
      // (live - scan) and stored a level the user never chose.
      stopIsUserSet: invalidationIsUserSetFor(card),
      structuralStop: structuralBySymbol[card.symbol]?.stop?.price ?? null,
      exitPlan:      cardContractKey ? exitPlanByContract[cardContractKey]?.plan ?? null : null,
      maxLossOverride: maxLossOverrideBySymbol[card.symbol] ?? null,
      // Piece 4 — MUST match what positionFromOrder produces for the same card,
      // which is now true by construction: both call premiumStopDollarFor.
      premiumStopDollar: premiumStopDollarFor(card),
      targets:       card.exit.targets,
      status:        card.finalStatus,
      ivRank:        cd?.ivRank,
      iv:            cd?.iv,
      delta:         cd?.delta,
      theta:         cd?.theta,
      vega:          0.20,
      contracts,
      source:        'paper',
      sourceLabel:   `${brokerLabel} — ${typeLabel} (ID: ${orderId})`,
      orderedAt:     nowISOLocal(),
      recId:         generateRecId(),
      scanStockPrice: card.price,
      tradeCardSnapshot: tradeCardSnapshotOf(card),
    };
  }

  async function placeLimitPaper() {
    const card = effectiveCard;
    if (!card || !selectedBroker) return;
    // DIRECT-SEND-STOP-GATE-2026-09-09. Belt and braces, and deliberately so:
    // this handler closes over the same render's `invalidationFor` that
    // `stopMissing` was derived from, so it cannot currently disagree with the
    // `disabled` on the button -- it is an INVARIANT on the function that
    // builds the position, not a second chance at a race. It is here because
    // `disabled` protects the button and this protects the ORDER: anything that
    // reaches this function by another route (a keyboard shortcut, a
    // programmatic retry, a future caller) inherits the refusal instead of
    // having to remember it. Exactly the shape SendToBrokerDialog.submit()
    // already uses beside its own `disabled`, and for the same reason.
    if (!checkInvalidation(invalidationFor(card))) return;
    // ROUND 10 finding 11 -- CLEAR THE NOTES PER ORDER. They are facts about
    // ONE save, and were only reset when the active candidate changed, so a
    // "Size reduced to 1 contract" from a previous fill sat under the next,
    // un-reduced order. Round 9's accumulate-don't-overwrite change made that
    // strictly worse: the stale note now sits BESIDE any new one instead of
    // being replaced by it.
    setLimitPlacing(true); setOrderError(null); setSaveNotes([]);
    try {
      // Floored defensively: the shared map is a plausible target for a
      // future write path to drop a sub-1 value into (e.g. Feature 3's Apply
      // button before its own clamp/disable) — `?? 1` alone only catches
      // null/undefined, not 0, and the backend rejects quantity:0 with an
      // opaque 422 that gives no clue this map is where it came from.
      const contracts = Math.max(1, orderContractsBySymbol[card.symbol] ?? 1);
      const res = await api.postOptionOrder({
        broker:        selectedBroker,
        symbol:        card.symbol,
        option_symbol: toOptionSymbol(card),
        action:        'BUY',
        effect:        'OPEN',
        quantity:      contracts,
        order_type:    'LMT',
        limit_price:   entryLimitFor(card),
        tif:           'DAY',
      });
      const pos = buildPaperPosition(card, 'LMT', selectedBroker, res.order_id, liveQuoteForCard?.price, contracts);
      const saved = await persistPosition(pos);
      const { rejected, detail } = applyPersistedPosition(
        saved, pos, addPosition,
        (adjustedQty) => addSaveNote(sizeNote(adjustedQty)),
        (requested) => addSaveNote(droppedStopNote(requested)),
      );
      if (rejected) {
        setOrderError(`Order placed in Tradier but portfolio tracking rejected: ${detail}`);
        return;
      }
      setPaperOrderId(res.order_id);
    } catch (e) {
      setOrderError(String(e));
    } finally {
      setLimitPlacing(false);
    }
  }

  async function placeMarketNow() {
    const card = effectiveCard;
    if (!card || !selectedBroker) return;
    // DIRECT-SEND-STOP-GATE-2026-09-09. Belt and braces, and deliberately so:
    // this handler closes over the same render's `invalidationFor` that
    // `stopMissing` was derived from, so it cannot currently disagree with the
    // `disabled` on the button -- it is an INVARIANT on the function that
    // builds the position, not a second chance at a race. It is here because
    // `disabled` protects the button and this protects the ORDER: anything that
    // reaches this function by another route (a keyboard shortcut, a
    // programmatic retry, a future caller) inherits the refusal instead of
    // having to remember it. Exactly the shape SendToBrokerDialog.submit()
    // already uses beside its own `disabled`, and for the same reason.
    if (!checkInvalidation(invalidationFor(card))) return;
    // See placeLimitPaper — notes describe this save only.
    setMarketPlacing(true); setOrderError(null); setSaveNotes([]);
    try {
      // Floored defensively — see placeLimitPaper's identical comment above.
      const contracts = Math.max(1, orderContractsBySymbol[card.symbol] ?? 1);
      const res = await api.postOptionOrder({
        broker:        selectedBroker,
        symbol:        card.symbol,
        option_symbol: toOptionSymbol(card),
        action:        'BUY',
        effect:        'OPEN',
        quantity:      contracts,
        order_type:    'MKT',
        limit_price:   null,
        tif:           'DAY',
      });
      const pos = buildPaperPosition(card, 'MKT', selectedBroker, res.order_id, liveQuoteForCard?.price, contracts);
      const saved = await persistPosition(pos);
      const { rejected, detail } = applyPersistedPosition(
        saved, pos, addPosition,
        (adjustedQty) => addSaveNote(sizeNote(adjustedQty)),
        (requested) => addSaveNote(droppedStopNote(requested)),
      );
      if (rejected) {
        setOrderError(`Order placed in Tradier but portfolio tracking rejected: ${detail}`);
        return;
      }
      setPaperOrderId(res.order_id);
    } catch (e) {
      setOrderError(String(e));
    } finally {
      setMarketPlacing(false);
    }
  }

  /* The keyed reads. Anything that wants "the live quote for the card on
   * screen" goes through these; the raw state is never read directly, so a
   * quote left standing for a different contract can only ever be ignored. */
  const liveQuoteForCard = liveQuote && liveQuote.key === contractKey ? liveQuote : null;
  const liveStockPriceForCard =
    liveStockPrice && liveStockPrice.symbol === effectiveCard?.symbol
      ? liveStockPrice.price
      : null;

  const idx = symbols.indexOf(active);

  const goPrev = () => { if (idx > 0) setActive(symbols[idx - 1]!); };
  const goNext = () => { if (idx >= 0 && idx < symbols.length - 1) setActive(symbols[idx + 1]!); };

  const togglePin = () =>
    setBasket((b) => (b.includes(active) ? b.filter((s) => s !== active) : [...b, active]));
  const removePin = (sym: string) => setBasket((b) => b.filter((s) => s !== sym));

  const handleSubmit = async (orders: DraftOrder[], _riskOverridden: boolean) => {
    usePortfolioStore.getState().clearSyncError();
    // Same reason as the two order paths: this submit's outcome, not the last
    // one's. Basket notes are symbol-qualified because several land at once.
    //
    // All THREE, matching placeLimitPaper and placeMarketNow. Clearing only
    // the notes left the red banner standing: a basket that partly failed set
    // `orderError`, and a second basket that fully succeeded then rendered
    // "Some orders were not saved" over a submit in which everything was.
    // Invisible before this branch (the banner was gated behind a selected
    // broker the basket never sets) and reachable the moment it was hoisted.
    setSaveNotes([]);
    setOrderError(null);
    setPaperOrderId(null);
    let auto = 0, manual = 0, queued = 0;
    const failures: string[] = [];
    const adjusted: string[] = [];

    for (const o of orders) {
      // One canonical recId per order: addPosition syncs it to the backend
      // (a single POST), so there is no second POST to conflict (409) with.
      const recId = recIdMap[o.card.symbol] ?? generateRecId();
      const structuralStop = structuralBySymbol[o.card.symbol]?.stop?.price ?? null;
      const orderContractKey = contractKeyFor(o.card);
      const orderExitPlan = orderContractKey ? exitPlanByContract[orderContractKey]?.plan ?? null : null;
      const orderMaxLossOverride = maxLossOverrideBySymbol[o.card.symbol] ?? null;
      const res = await addPosition({
        ...positionFromOrder(
          o, structuralStop, orderExitPlan, orderMaxLossOverride,
          premiumStopDollarFor(o.card), invalidationRawFor(o.card), entryLimitFor(o.card),
          // ROUND 10 finding 7 -- the LIVE mid, for the active symbol. The
          // direct path uses `liveQuoteForCard?.price` and this path used the
          // scan-time `contractDetails.mid`, so the two stored different
          // entryPrices for the same card -- the denominator the premium stop
          // is derived against and the threshold both alert engines compare.
          // Only the active card has a fetched quote; the rest legitimately
          // fall back to their scan mid.
          o.card.symbol === effectiveCard?.symbol ? liveQuoteForCard?.price ?? null : null,
        ),
        recId,
        // ROUND 10 finding 2 -- WITHOUT this the router never fetches the
        // underlying, so neither the re-anchor nor the wrong-side guard runs
        // on anything the basket sends.
        scanStockPrice: o.card.price,
      });

      if (res.status === 'rejected') {
        // Backend refused it and the optimistic row was dropped — a real failure.
        failures.push(`${o.card.symbol}: ${res.detail ?? 'not saved'}`);
        continue;
      }
      // ROUND 9 — the basket path could not report a dropped premium stop at
      // all: `addPosition`'s result carried no premium-stop outcome, so the
      // only two paths that told the user were placeLimitPaper and
      // placeMarketNow. Same fallback, same silence, one of four create paths
      // away. Symbol-qualified because a basket submits several at once.
      if (res.premiumStopDropped != null) {
        addSaveNote(`${o.card.symbol}: ${droppedStopNote(res.premiumStopDropped)}`);
      }
      if (res.status === 'pending') {
        // Optimistically added but not yet confirmed by the backend. Don't count it
        // toward the daily cap or write an APPROVE audit entry until it lands — a
        // premature APPROVE that a later retry rejects would be a false audit trail.
        queued++;
        continue;
      }
      // status === 'ok' — confirmed saved by the backend.
      incrementDaily();
      if (o.autoSend) auto++; else manual++;
      if (res.adjustedQty != null) {
        adjusted.push(`${o.card.symbol}: ${res.adjustedQty} contract${res.adjustedQty === 1 ? '' : 's'}`);
      }
      logAudit('APPROVE', recId, {
        symbol: o.card.symbol,
        contract: o.card.contract,
        contracts: o.contracts,
      });
    }
    setDialogOpen(false);
    setBasket([]);

    // Toast covers placed orders (saved or queued-for-retry); the red error banner
    // covers hard rejections. They describe DIFFERENT orders, so both may show for
    // a mixed basket — but a network-only submit shows just the toast (no
    // contradictory red banner) with the queued count reported distinctly.
    if (auto + manual + queued > 0) {
      setToast({ auto, manual, queued, adjusted });
      window.setTimeout(() => setToast(null), 6000);
    }
    if (failures.length) {
      setOrderError(`Some orders were not saved — ${failures.join('; ')}`);
    }
  };

  const basketEmpty = basket.length === 0;
  const sendLabel = basketEmpty ? 'Send to broker' : `Send basket (${basket.length})`;

  return (
    <div className={styles.main}>
      <div className={styles.stepHeader}>
        <Text size={11} tone="dim" weight={500}>STEP 7 OF 7</Text>
        <Title as="h1" size={24}>Trade Card</Title>
        <Text size={13} tone="secondary">
          Cycle candidates with Prev / Next. Pin multiple to the basket, then Send to broker — uncheck
          Auto-send for any contract you&apos;d rather place manually.
        </Text>
      </div>

      <CandidateNav
        symbols={symbols}
        activeSymbol={active}
        basket={basket}
        onPrev={goPrev}
        onNext={goNext}
        onSelect={setActive}
        onTogglePin={togglePin}
        onRemovePin={removePin}
      />

      {cards.length === 0 && (
        <Text size={13} tone="dim">Run a scan to generate trade cards.</Text>
      )}

      {effectiveCard && (
        <>
          {effectiveCard._userOverride && (
            <StatusBadge status="PENDING" label="User-selected" tooltip="Manually pinned as the active trade card — not a scoring verdict." />
          )}
          {/* For an overridden contract, don't render the card until its plan is
              recomputed — otherwise the Exit Plan / R-R would briefly show the
              auto-pick's numbers next to the selected contract. */}
          {isOverride && !planReady ? (
            <div aria-busy={!activePlanError}>
              {activePlanError ? (
                <>
                  <Text size={12} tone="reject">{activePlanError}</Text>
                  <button
                    type="button"
                    className={paperStyles.paperBtnMarket}
                    onClick={() => retryPlan(effectiveCard.symbol)}
                  >
                    Retry
                  </button>
                </>
              ) : (
                <Text size={12} tone="secondary">Preparing the plan for your selected contract…</Text>
              )}
            </div>
          ) : (
            <TradeCard
              data={cardForDisplay ?? effectiveCard}
              recId={recIdMap[effectiveCard.symbol]}
              onSendToBroker={() => !basketEmpty && !basketPlansPending && setDialogOpen(true)}
              sendLabel={sendLabel}
              sendDisabled={basketEmpty || basketPlansPending}
              contracts={orderContractsBySymbol[effectiveCard.symbol] ?? 1}
              // `editKeyFor(effectiveCard)`, not the strict `contractKey`:
              // the readers key off the effective card too, and a null key
              // used to drop the edit entirely (see editKeyFor).
              onEditsChange={(overlay, meta) => handleEditsChange(effectiveCard.symbol, editKeyFor(effectiveCard), overlay, meta)}
              // Piece 4 — round-tripped like `contracts` above. The card's
              // reset on a contract change does not call `onEditsChange`, so
              // without this the field fell back to its seed while this cache
              // kept the user's edit, and the two send paths posted a number
              // the card was no longer showing.
              // `editKeyFor`, matching the writer and both send-path readers.
              // Keyed off the strict `contractKey` these restored nothing on a
              // card whose contractDetails lack a strike/expiry/right, which is
              // exactly the card whose edits used to be dropped entirely.
              initialPremiumStop={editKey ? premiumStopByContract[editKey] ?? null : null}
              // These two round-trip for the same reason the premium stop does:
              // the card's reset on a candidate change would otherwise put the
              // seed back on screen while these caches kept the edit, so the
              // card showed $2.50 / $140.00 while the order went out at $2.71
              // with a stop of 132.
              initialEntryLimit={editKey ? entryLimitByContract[editKey] ?? null : null}
              initialInvalidation={invalidationBySymbol[effectiveCard.symbol] ?? null}
              // Anchors for the three fields' bounds. `data.price` and
              // `contractDetails.mid` come off a scanResult that scanStore
              // persists, so after a reload they can be days old; these two are
              // the same numbers the "Live stock:" / "Live mid:" lines below
              // are rendered from.
              liveStockPrice={liveStockPriceForCard}
              liveMid={liveQuoteForCard?.price ?? null}
              resetKey={scanEpoch}
              onStructuralStopChange={(stop, stockPrice) => handleStructuralStopChange(effectiveCard.symbol, stop, stockPrice)}
              onFirstPassageChange={(estimate, context) => handleFirstPassageChange(contractKey, estimate, context)}
              onExitPlanChange={(plan) => handleExitPlanChange(contractKey, plan)}
              initialMaxLossOverride={maxLossOverrideBySymbol[effectiveCard.symbol] ?? null}
              onMaxLossOverrideChange={(v) => handleMaxLossOverrideChange(effectiveCard.symbol, v)}
            />
          )}
          {!basketEmpty && basketPlansPending && basketPlanErrors.length === 0 && (
            <Text size={11} tone="caution">
              Computing the plan for an overridden contract in your basket — Send basket enables once it&apos;s ready.
            </Text>
          )}
          {basketPlanErrors.map(({ symbol, error }) => (
            <div key={symbol} style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
              <Text size={11} tone="reject">{symbol}: {error}</Text>
              <button type="button" className={paperStyles.paperBtnMarket} onClick={() => retryPlan(symbol)}>
                Retry {symbol}
              </button>
            </div>
          ))}
          {fetchingQuote && (
            <Text size={11} tone="dim">Fetching live price…</Text>
          )}
          {liveQuoteForCard && !fetchingQuote && (
            <Text size={11} tone="secondary">Live mid: ${liveQuoteForCard.price.toFixed(2)}</Text>
          )}
          {liveStockPriceForCard != null && !fetchingQuote && (
            <Text size={11} tone="secondary">Live stock: ${liveStockPriceForCard.toFixed(2)}</Text>
          )}
        </>
      )}

      {/* Paper broker execution */}
      {effectiveCard && (
        <div className={paperStyles.paperSection}>
          <BrokerPicker selected={selectedBroker} onChange={setSelectedBroker} />
          {selectedBroker && (
            <>
              <div className={paperStyles.paperButtons}>
                <button
                  type="button"
                  className={paperStyles.paperBtnLimit}
                  onClick={placeLimitPaper}
                  disabled={limitPlacing || marketPlacing || !planReady || stopMissing}
                  title={stopMissing ? MISSING_INVALIDATION_TITLE : undefined}
                >
                  {limitPlacing ? 'Placing…' : planReady ? `Place Limit @ $${entryLimitFor(effectiveCard).toFixed(2)}` : 'Place Limit'}
                </button>
                <button
                  type="button"
                  className={paperStyles.paperBtnMarket}
                  onClick={placeMarketNow}
                  disabled={limitPlacing || marketPlacing || !planReady || stopMissing}
                  title={stopMissing ? MISSING_INVALIDATION_TITLE : undefined}
                >
                  {marketPlacing ? 'Placing…' : 'Right Now — Market'}
                </button>
              </div>
              {!planReady && (
                <Text size={11} tone="caution">
                  Recomputing the plan for your selected contract — ordering enabled once it&apos;s ready.
                </Text>
              )}
              {/* Said, not merely disabled. A greyed button with no reason
                * beside it reads as a bug; the `title` above is a tooltip and
                * a tooltip is not a disclosure. Rendered independently of
                * `!planReady` rather than as its `else`, because the two are
                * unrelated conditions and can hold at once -- an overridden
                * contract still recomputing on a restored candidate -- and
                * suppressing this one behind the other would hide the only
                * refusal the user can actually act on. */}
              {stopMissing && (
                <Text size={11} tone="reject">
                  {MISSING_INVALIDATION_MESSAGE}
                </Text>
              )}
              {paperOrderId && <Text size={12} tone="pass">Order placed — ID: {paperOrderId}</Text>}
              {planReady && (
                <AutoTradeArm
                  // The same live quote TradeCard gets as `liveMid` and the
                  // page prints as "Live mid" -- it was in scope here all
                  // along and simply never handed down, leaving the arm path
                  // (and the daily-loss gate behind it) on the scan-time mid.
                  liveMid={liveQuoteForCard?.price ?? null}
                  card={effectiveCard}
                  broker={selectedBroker}
                  contracts={orderContractsBySymbol[effectiveCard.symbol] ?? 1}
                  // Piece 4 — the same resolution both send paths use, so a
                  // trade that is armed and a trade that is sent cannot end up
                  // at two different premium stops.
                  premiumStopDollar={premiumStopDollarFor(effectiveCard)}
                  // Same resolution as every other send path, for the same
                  // reason: an armed trade and a sent trade must not go out at
                  // two different limit prices.
                  entryLimit={entryLimitFor(effectiveCard)}
                  // DIRECT-SEND-STOP-GATE-2026-09-09. The arm REQUEST still
                  // carries no stop level -- this is the gate, not a payload.
                  // The same resolution `stopMissing` is derived from, passed
                  // rather than recomputed, so Arm and the two direct buttons
                  // cannot refuse on two different readings of one field.
                  resolvedInvalidation={resolvedInvalidationForCard}
                />
              )}
            </>
          )}
          {/* OUTSIDE the `selectedBroker` gate, deliberately.
            *
            * ROUND 12 finding 2 -- these two lines are the ONLY channel for
            * two things the basket path produces: the "premium stop could not
            * be applied" disclosure (`droppedStopNote`, written by
            * `handleSubmit` for every order the backend re-anchored) and the
            * hard-rejection banner (`setOrderError` on a failed save). The
            * basket reaches `handleSubmit` through TradeCard's Send button,
            * which never touches BrokerPicker -- so a user who pins a basket
            * and sends it without selecting a paper broker got neither
            * message. A required disclosure that renders only when an
            * unrelated control happens to be set is a disclosure that does not
            * exist.
            *
            * `paperOrderId` stays inside the gate above: only the two direct
            * paths set it, and both require a selected broker. */}
          {saveNotes.map((n) => (
            <Text key={n} size={12} tone="caution">{n}</Text>
          ))}
          {orderError && <Text size={12} tone="reject">{orderError}</Text>}
        </div>
      )}

      {dialogOpen && (
        <SendToBrokerDialog
          cards={basketCards}
          contractsBySymbol={orderContractsBySymbol}
          overridesBySymbol={maxLossOverrideBySymbol}
          invalidationBySymbol={Object.fromEntries(
            basketCards.map((c) => [c.symbol, invalidationFor(c)]),
          )}
          onClose={() => setDialogOpen(false)}
          onSubmit={handleSubmit}
        />
      )}

      {toast && (
        <div className={toastStyles.toast} role="status" aria-live="polite">
          <div>
            <Text size={13} weight={500}>
              {toast.auto + toast.manual + toast.queued} order{toast.auto + toast.manual + toast.queued === 1 ? '' : 's'} placed
            </Text>
            <Text size={11} tone="secondary">
              {toast.auto} sent to broker · {toast.manual} added manually
              {toast.queued > 0 ? ` · ${toast.queued} awaiting backend sync` : ''}
            </Text>
            {toast.adjusted.length > 0 && (
              <Text size={11} tone="caution">
                Size reduced to fit exposure limits — {toast.adjusted.join(', ')}
              </Text>
            )}
          </div>
          <Link href="/portfolio" className={toastStyles.link}>
            View Portfolio →
          </Link>
        </div>
      )}
    </div>
  );
}
