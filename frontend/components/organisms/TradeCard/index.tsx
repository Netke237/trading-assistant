'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Text, Data } from '@/components/primitives';
import { SymbolHeader } from '@/components/molecules/SymbolHeader';
import { ScoreCardPanel } from '@/components/molecules/ScoreCardPanel';
import { AlternativeContractRow } from '@/components/molecules/AlternativeContractRow';
import { MarketSentiment } from '@/components/molecules/MarketSentiment';
import { FundamentalHealthCard } from '@/components/molecules/FundamentalHealthCard';
import { InlineChartPanel } from '@/components/organisms/InlineChartPanel';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { LabeledStatusBadge } from '@/components/molecules/LabeledStatusBadge';
import { capitalAtRisk } from '@/lib/risk';
import { api } from '@/lib/api';
import { useSettingsStore } from '@/lib/settingsStore';
import type { TradeCardData, TargetLevel, StructuralStop, FirstPassageEstimate, FirstPassageContext, FirstPassageTarget } from '@/types/domain';
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

interface EditOverlay {
  entryLimit: number;
  maxFill: number;
  invalidation: number;
  premiumStop: number;
  timeStopDays: number;
  targets: number[];
  contracts: number;
}

function defaultOverlay(data: TradeCardData): EditOverlay {
  return {
    entryLimit: data.entry.limit,
    maxFill: data.entry.maxFill,
    invalidation: data.exit.invalidation,
    premiumStop: data.exit.premiumStop,
    timeStopDays: data.exit.timeStopDays,
    targets: data.exit.targets.map((t) => t.targetPrice ?? t.stockPrice),
    contracts: 1,
  };
}

function isDirty(overlay: EditOverlay, data: TradeCardData): boolean {
  return (
    overlay.entryLimit !== data.entry.limit ||
    overlay.maxFill !== data.entry.maxFill ||
    overlay.invalidation !== data.exit.invalidation ||
    overlay.premiumStop !== data.exit.premiumStop ||
    overlay.timeStopDays !== data.exit.timeStopDays ||
    overlay.targets.some(
      (t, i) => t !== (data.exit.targets[i]?.targetPrice ?? data.exit.targets[i]?.stockPrice),
    ) ||
    overlay.contracts !== 1
  );
}

function computeEditedRR(
  overlay: EditOverlay,
  data: TradeCardData,
): { rr: number; model: string } {
  const entryPrice = overlay.entryLimit;
  const riskBasis = overlay.premiumStop;
  if (entryPrice <= 0 || riskBasis <= 0) return { rr: 0, model: 'Edit (delta approx)' };
  if (overlay.targets.length === 0) return { rr: data.rrRatio, model: data.rrModel };

  const cd = data.contractDetails;
  if (!cd) return { rr: data.rrRatio, model: data.rrModel };

  const isCall = cd.right === 'C';
  const strike = cd.strike;
  const currentStockPrice = data.price;
  const targetStockPrice = overlay.targets[0];
  const delta =
    (isCall && targetStockPrice > strike) || (!isCall && targetStockPrice < strike)
      ? 0.5
      : 0.3;
  const priceMove = Math.abs(targetStockPrice - currentStockPrice);
  const estOptionPrice = Math.max(0.01, entryPrice + delta * priceMove);
  const reward = estOptionPrice - entryPrice;
  // Risk basis is the planned dollar stop (premiumStop), not the full entry
  // price — matches the backend's estimate_rr(): risk = current_premium *
  // premium_stop_pct. Mirrors the backend's reward_risk.py M2 fix: a
  // negative reward's sign/magnitude is preserved, not flattened to 0
  // (entryPrice<=0 or riskBasis<=0 above are the only genuinely
  // not-computable cases).
  const rr = Math.round((reward / riskBasis) * 100) / 100;

  return { rr, model: 'Edit (delta approx)' };
}

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
  // Risk basis is the planned dollar stop (entryLimit * premium_stop_pct,
  // already computed backend-side and surfaced as overlay.premiumStop) —
  // NOT the full entry price. Matches the backend's own reward_risk.py
  // estimate_targets(): risk_basis = current_premium * premium_stop_pct.
  // Mirrors the backend's reward_risk.py M2 fix: a negative reward's sign/
  // magnitude is preserved, not flattened to 0 — a target priced below entry
  // is a real loss the trader should see, not an indistinguishable "no data".
  // Guards both operands (not just riskBasis) for symmetry with
  // computeEditedRR's equivalent guard, even though today's UI already
  // clamps entryLimit to a positive minimum before it can reach here.
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
}): StructuralStop | null {
  return res.available && res.price != null && res.source != null
    && res.confidence != null && res.distancePct != null
    ? { price: res.price, source: res.source, confidence: res.confidence, distancePct: res.distancePct }
    : null;
}

interface TradeCardProps {
  data: TradeCardData;
  recId?: string;
  onSendToBroker?: () => void;
  sendLabel?: string;
  sendDisabled?: boolean;
  contracts?: number;
  onEditsChange?: (overlay: EditOverlay) => void;
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
}

function targetStatusTooltip(statusVal: TargetLevel['status']): string {
  if (statusVal === 'HIT') return 'This profit target has been reached.';
  if (statusVal === 'MISSED') return 'Price moved past this target level without filling — treated as missed.';
  return 'Target not yet reached.';
}

function generateRecId(): string {
  return 'REC-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6).toUpperCase();
}

export function TradeCard({
  data,
  recId: propRecId,
  onSendToBroker,
  sendLabel,
  sendDisabled,
  contracts: initialContracts = 1,
  onEditsChange,
  onStructuralStopChange,
  onFirstPassageChange,
}: TradeCardProps) {
  const [chartOpen, setChartOpen] = useState(false);
  const [altOpen, setAltOpen] = useState(false);
  const [overlay, setOverlay] = useState<EditOverlay>(() => ({
    ...defaultOverlay(data),
    contracts: initialContracts,
  }));
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
  // leave structuralRR null and every row's R:R cell showing the defensive '—'.
  const [structuralStopStockPrice, setStructuralStopStockPrice] = useState<number | null>(
    data.exit.structuralStopStockPrice ?? null,
  );
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
  // auto-fetch never fires again for this candidate, and structuralRR then
  // permanently combines that stale check-time price with the FRESH
  // premium/delta the estimate just fetched — silently overstating or
  // understating risk by however much the stock has moved since the cache was
  // written. Not state: it never needs to trigger a render on its own, only
  // to gate a callback's branch the next time it runs.
  const structuralIsFreshRef = useRef(false);
  // The mirror image of structuralIsFreshRef, tracking the OTHER side of
  // structuralRR's pairing: whether the current firstPassageContext was
  // obtained by a fetch performed this mount, as opposed to a cache restore.
  // estimateFirstPassage already auto-refreshes a not-yet-fresh
  // structuralStop when Estimate is clicked, so that direction is covered —
  // but a MANUAL "Check structure" click can independently refresh
  // structuralStop while a restored (possibly stale) estimate is still on
  // screen, which is exactly the same mixed-vintage hazard structuralRR
  // exists to avoid, just from the other side. Rather than also auto-firing
  // a full Estimate computation from "Check structure" (tried, reverted — it
  // adds two unwanted network calls for a user who only asked to check
  // structure, and duplicates a fetch on the very next real Estimate click
  // regardless), this ref instead feeds structuralRR's own gate below:
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
  const firstPassageRequestRef = useRef<AbortController | null>(null);

  const prevSymbolRef = useRef(data.symbol);
  const prevContractRef = useRef(data.contract);
  // Single effect resetting BOTH structuralStop and firstPassage state on a
  // contract change — deliberately not two separate effects each comparing
  // against prevSymbolRef/prevContractRef: effects run in declaration order
  // within the same commit, so a first effect that updates those refs would
  // make a second effect's own "did it change" comparison always see "no
  // change" (the first effect already advanced the ref). Caught by the
  // first-passage stale-response regression test below.
  useEffect(() => {
    if (data.symbol !== prevSymbolRef.current || data.contract !== prevContractRef.current) {
      structuralRequestRef.current?.abort();
      firstPassageRequestRef.current?.abort();
      setOverlay({ ...defaultOverlay(data), contracts: initialContracts });
      // Every one of these five reads data.exit — for a candidate nothing has
      // been run on they are all absent and this is still a full reset (the
      // pre-existing behaviour). When the parent has a cached result for the
      // incoming contract it splices all of them in together, so the estimate,
      // its baseline premium/delta, its % inputs, the structural stop and the
      // price that stop was measured against are restored as ONE consistent
      // set — never a half-restore that would leave structuralRR null.
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
      setFirstPassageError(false);
      setFirstPassageLoading(false);
      prevSymbolRef.current = data.symbol;
      prevContractRef.current = data.contract;
    }
  }, [data.symbol, data.contract, initialContracts, defaultTargetPct]);

  // Cancel any outstanding requests on unmount.
  useEffect(() => () => structuralRequestRef.current?.abort(), []);
  useEffect(() => () => firstPassageRequestRef.current?.abort(), []);

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

  const estimateFirstPassage = useCallback(async () => {
    firstPassageRequestRef.current?.abort();
    const controller = new AbortController();
    firstPassageRequestRef.current = controller;
    setFirstPassageLoading(true);
    setFirstPassageError(false);
    setFirstPassage(undefined);
    setFirstPassageContext(null);
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
      if (controller.signal.aborted) return;
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
      // rather than leaving the old one in place. Either way structuralRR
      // never combines a stop it can't vouch for as fresh with THIS click's
      // premium/delta: it either gets a same-vintage pair or nothing to
      // compute from, never a silent mismatch. Deliberately not awaited
      // before continuing to the first-passage fetch below — it manages its
      // own loading/error state independently via structuralRequestRef, same
      // as a manual "Check structure" click would, and that ref-swap means
      // the existing contract-change cleanup effect still aborts it
      // correctly if the user navigates away.
      if (!structuralIsFreshRef.current && !structuralLoading) {
        structuralRequestRef.current?.abort();
        const structuralController = new AbortController();
        structuralRequestRef.current = structuralController;
        setStructuralLoading(true);
        setStructuralError(false);
        api.getStructuralStop({
          symbol: data.symbol,
          direction: data.direction,
          stock_price: referenceStockPrice,
        }, structuralController.signal)
          .then((res) => {
            if (structuralController.signal.aborted) return;
            setStructuralStop(normalizeStructuralStopResponse(res));
            setStructuralStopStockPrice(referenceStockPrice);
            structuralIsFreshRef.current = true;
          })
          .catch(() => {
            if (structuralController.signal.aborted) return;
            setStructuralError(true);
            // This refresh only ever runs because structuralIsFreshRef was
            // false — i.e. whatever structuralStop currently holds (a cache
            // restore, or nothing) was never confirmed fresh this mount. On
            // failure, don't leave that unconfirmed pair sitting next to
            // firstPassageContext, which below may already hold THIS click's
            // fresh premium/delta by the time this rejection lands —
            // structuralRR would otherwise silently render a mixed-vintage
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
            setStructuralStop(null);
            setStructuralStopStockPrice(null);
          })
          .finally(() => {
            if (!structuralController.signal.aborted) setStructuralLoading(false);
          });
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
        invalidation_price: data.exit.invalidation,
        t1_pct: targetPct.t1,
        t2_pct: targetPct.t2,
        t3_pct: targetPct.t3,
      }, controller.signal);
      if (controller.signal.aborted) return;
      setFirstPassage({ targets: res.targets, invalidation: res.invalidation });
      // optionPrice in each target is premium*(1+pct) built from THIS
      // premium (first_passage.py) — persist it so a later R:R calc
      // subtracts the matching baseline, not data.contractDetails.mid.
      // targetPct is snapshotted here (not read back later) so the trio
      // stored alongside the estimate is exactly the trio the request above
      // carried, even if the user edited an input while it was in flight.
      setFirstPassageContext({ premium, delta, targetPct: { ...targetPct } });
      firstPassageIsFreshRef.current = true;
    } catch {
      if (controller.signal.aborted) return;
      setFirstPassageError(true);
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
      setFirstPassage(null);
      setFirstPassageContext(null);
    } finally {
      if (!controller.signal.aborted) setFirstPassageLoading(false);
    }
  }, [data.symbol, data.direction, data.price, data.contractDetails, data.stockBreakdown.trend, data.exit.invalidation, targetPct, structuralLoading]);

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
  const structuralRR = useMemo(() => {
    if (!structuralStop || structuralStopStockPrice == null || !firstPassage || !firstPassageContext) {
      return null;
    }
    // Both existing isn't enough on its own — they also have to be safe to
    // combine. EACH must be independently confirmed fresh this mount, or one
    // side could be a stale restore sitting next to the other's live value —
    // a manual "Check structure" landing next to a still-restored (and now
    // provably older) estimate, or the reverse — which is exactly the
    // mixed-vintage number this whole mechanism exists to prevent. See
    // firstPassageIsFreshRef's declaration for why this no longer has a
    // "trust a restored pair" exemption. This reads two refs during render,
    // which is safe here specifically because every path that flips either
    // of them also changes one of this memo's real dependencies below in the
    // same update, so the memo is guaranteed to re-evaluate at the moment the
    // answer could change.
    if (!structuralIsFreshRef.current || !firstPassageIsFreshRef.current) {
      return null;
    }
    const stockMove = Math.abs(structuralStop.price - structuralStopStockPrice);
    const deltaEst = Math.max(Math.abs(firstPassageContext.delta), 0.05);
    // A long option's max loss is capped at the premium paid — the linear
    // delta approximation has no such cap and can overshoot it for a distant
    // structural stop or a low-delta contract, implying a loss bigger than
    // the trade could ever actually produce. Clamp to premium.
    const risk = Math.min(stockMove * deltaEst, firstPassageContext.premium);
    if (risk <= 0) return null;
    return firstPassage.targets.map((t) => {
      const reward = t.optionPrice - firstPassageContext.premium;
      // Mirrors the backend's reward_risk.py M2 fix: a negative reward's
      // sign/magnitude is preserved, not nulled out to "—" (indistinguishable
      // from "not yet computed") — risk<=0 above is the only genuinely
      // not-computable case.
      return { pct: t.pct, rr: reward / risk };
    });
  }, [structuralStop, structuralStopStockPrice, firstPassage, firstPassageContext]);

  // Re-derives the SAME pairing eligibility structuralRR's memo checks
  // internally, for the render below: structuralZeroRisk's "N/A (stop =
  // price)" label specifically means "this pair WAS eligible and the risk
  // still came out ≤0" — without this, a pair blocked purely for staleness
  // (structuralRR null for a reason OTHER than risk≤0) would wrongly claim
  // the stop sits at the current price. Plain read, not memoized: cheap
  // boolean, and it only needs to be current as of this render anyway.
  const structuralPairEligible = structuralIsFreshRef.current && firstPassageIsFreshRef.current;

  const checkStructure = useCallback(async () => {
    structuralRequestRef.current?.abort();
    const controller = new AbortController();
    structuralRequestRef.current = controller;
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
      const stockQuote = await api.getStockQuote(data.symbol, controller.signal).catch(() => null);
      if (controller.signal.aborted) return;
      const referenceStockPrice = stockQuote?.price ?? data.price;
      const res = await api.getStructuralStop({
        symbol: data.symbol,
        direction: data.direction,
        stock_price: referenceStockPrice,
      }, controller.signal);
      if (controller.signal.aborted) return;
      setStructuralStop(normalizeStructuralStopResponse(res));
      setStructuralStopStockPrice(referenceStockPrice);
      structuralIsFreshRef.current = true;
    } catch {
      if (controller.signal.aborted) return;
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
      if (!controller.signal.aborted) setStructuralLoading(false);
    }
  }, [data.symbol, data.direction, data.price]);

  useEffect(() => {
    setOverlay((prev) => ({ ...prev, contracts: initialContracts }));
  }, [initialContracts]);

  const patch = useCallback(
    (partial: Partial<EditOverlay>) => {
      setOverlay((prev) => {
        const next = { ...prev, ...partial };
        onEditsChange?.(next);
        return next;
      });
    },
    [onEditsChange],
  );

  const displayRecId = useMemo(() => propRecId ?? generateRecId(), [propRecId]);
  const car = useMemo(
    () => capitalAtRisk(data.contractDetails?.mid ?? 0, overlay.contracts),
    [data.contractDetails?.mid, overlay.contracts],
  );

  const dirty = useMemo(() => isDirty(overlay, data), [overlay, data]);

  const editedRR = useMemo(() => {
    if (!dirty) return { rr: data.rrRatio, model: data.rrModel };
    return computeEditedRR(overlay, data);
  }, [dirty, overlay, data]);

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

  return (
    <div className={styles.wrap}>
      {/* 1. Header */}
      <div className={styles.headerCard}>
        <SymbolHeader
          ticker={data.symbol}
          company={data.company}
          price={data.price}
          direction={data.direction}
          status={data.status}
          size={24}
          showChartButton
        />
      </div>

      <div className={styles.grid}>
        {/* 2. Market Sentiment — full-width top bar */}
        <div className={styles.fullWidth}>
          <MarketSentiment s={data.sentiment} />
        </div>

        {/* 3. Stock Scorecard | Contract — side by side */}
        <ScoreCardPanel
          title="Stock Scorecard"
          bars={stockBars}
          total={data.stockScore}
          confidence={data.stockConfidence}
          confidenceScore={data.confidence ?? null}
          confidenceText={data.confidenceText ?? null}
          statusTooltip="Backtested confidence tier for the stock signal. CAUTION means the pattern's historical win rate is marginal — consider reducing position size or waiting for a higher-conviction entry."
        />

        <ScoreCardPanel
          title={`Contract — ${data.contract}`}
          bars={contractBars}
          total={data.contractScore}
          confidence={data.contractConfidence}
          statusTooltip="Overall contract quality verdict. Combines DTE fit, delta, IV attractiveness, liquidity, and spread. CAUTION means at least one component is borderline — try a different strike or expiry for a cleaner contract."
          statusTooltipAlignRight
        />

        {/* 4. Fundamental Health — full-width bar below scorecards */}
        <div className={styles.fullWidth}>
          <FundamentalHealthCard f={data.fundamentals} />
        </div>

        {/* 5. Contract Details */}
        {data.contractDetails && (
          <section className={styles.detailsCard}>
            <Text size={14} weight={600}>Contract Details</Text>
            <div className={styles.detailsGrid}>
              <DetailCell label="Strike" value={`$${data.contractDetails.strike}`} />
              <DetailCell label="Expiry" value={data.contractDetails.expiry} />
              <DetailCell label="Right" value={data.contractDetails.right === 'C' ? 'Call' : 'Put'} />
              <DetailCell label="Mid" value={`$${data.contractDetails.mid.toFixed(2)}`} />
              <DetailCell label="Δ" value={data.contractDetails.delta.toFixed(2)} mono />
              <DetailCell label="Θ / day" value={`$${data.contractDetails.theta.toFixed(2)}`} mono />
              <DetailCell label="IV rank" value={`${data.contractDetails.ivRank}`} mono />
              <DetailCell label="DTE" value={`${data.contractDetails.dte}d`} mono />
              <DetailCell label="CaR" value={`$${car.toFixed(0)}`} mono />
            </div>
          </section>
        )}

        {/* 5b. Spread legs panel — shown only for multi-leg spreads */}
        {data.spreadType && data.spreadType !== 'single' && data.legs && data.legs.length > 0 && (
          <section className={`${styles.detailsCard} ${styles.spreadLegsCard}`}>
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

        {/* 4. Entry plan */}
        <section className={styles.planCard}>
          <Text size={14} weight={600}>Entry Plan</Text>
          <dl className={styles.kvList}>
            <KV label="Order type" value={data.entry.orderType} />
            <EditableKV
              label="Limit"
              value={overlay.entryLimit}
              onChange={(v) => patch({ entryLimit: v })}
              prefix="$"
              min={0.01}
              step={0.01}
              mono
            />
            <EditableKV
              label="Max fill"
              value={overlay.maxFill}
              onChange={(v) => patch({ maxFill: v })}
              prefix="$"
              min={0.01}
              step={0.01}
              mono
            />
            <EditableKV
              label="Contracts"
              value={overlay.contracts}
              onChange={(v) => patch({ contracts: v })}
              min={1}
              step={1}
              mono
              decimals={0}
            />
          </dl>
        </section>

        {/* 5. Exit plan */}
        <section className={styles.planCard}>
          <Text size={14} weight={600}>Exit Plan</Text>
          <dl className={styles.kvList}>
            <EditableKV
              label="Invalidation"
              value={overlay.invalidation}
              onChange={(v) => patch({ invalidation: v })}
              prefix="$"
              min={0.01}
              step={0.01}
              mono
            />
            <EditableKV
              label="Premium stop"
              value={overlay.premiumStop}
              onChange={(v) => patch({ premiumStop: v })}
              prefix="$"
              min={0.01}
              step={0.01}
              mono
            />
            <EditableKV
              label="Time stop"
              value={overlay.timeStopDays}
              onChange={(v) => patch({ timeStopDays: v })}
              min={1}
              step={1}
              suffix="d"
              mono
              decimals={0}
            />
          </dl>
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
            {!structuralError && structuralStop === null && (
              <Text size={11} tone="dim">No order block or swing level found nearby.</Text>
            )}
            {structuralStop && (
              <dl className={styles.kvList}>
                <KV
                  label={structuralStop.source === 'order_block' ? 'Structural stop — Order Block'
                    : structuralStop.source === 'swing_low' ? 'Structural stop — Swing Low'
                    : 'Structural stop — Swing High'}
                  value={`$${structuralStop.price.toFixed(2)} (${structuralStop.distancePct.toFixed(1)}% away)`}
                  mono
                />
              </dl>
            )}
          </div>
        </section>

        {/* 5c. Profit-target first-passage estimate */}
        <section className={`${styles.planCard} ${styles.fullWidth}`}>
          <Text size={14} weight={600}>Profit Targets</Text>
          <Text size={10} tone="dim">Monte Carlo estimate — independent of the Sell-to-Close Plan below; the two can disagree.</Text>
          <div className={styles.targetPctRow}>
            {(['t1', 't2', 't3'] as const).map((key) => (
              <label key={key} className={styles.targetPctInput}>
                <Text size={11} tone="secondary">{key.toUpperCase()}</Text>
                <input
                  type="number"
                  className={styles.editInput}
                  min={1}
                  max={500}
                  step={1}
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
            <button
              type="button"
              className={styles.btn}
              onClick={estimateFirstPassage}
              disabled={firstPassageLoading || !data.contractDetails}
            >
              <Text size={12} weight={500}>
                {firstPassageLoading ? 'Estimating…' : 'Estimate'}
              </Text>
            </button>
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
                  structuralRRValue={structuralRR?.find((r) => r.pct === t.pct)?.rr ?? null}
                  structuralPending={structuralLoading}
                  structuralUnavailable={structuralStop === null}
                  structuralZeroRisk={
                    structuralStop != null && structuralStopStockPrice != null
                    && firstPassageContext != null && structuralRR == null && !structuralLoading
                    && structuralPairEligible
                  }
                />
              ))}
              <div className={styles.targetRow}>
                <div className={styles.targetMain}>
                  <div className={styles.targetId}>
                    <Text size={12} weight={600}>Invalidation</Text>
                  </div>
                  <div className={styles.targetValues}>
                    <KV
                      label="Probability before expiry"
                      value={`${(firstPassage.invalidation.probability * 100).toFixed(0)}%`}
                      mono
                    />
                    <KV
                      label="Expected time"
                      value={firstPassage.invalidation.expectedDays != null ? `~${Math.round(firstPassage.invalidation.expectedDays)}d` : 'unlikely'}
                      mono
                    />
                  </div>
                </div>
              </div>
            </div>
          )}
        </section>

        {/* 5b. Sell-to-close plan */}
        <section className={`${styles.planCard} ${styles.targetsCard}`}>
          <Text size={14} weight={600}>Sell-to-Close Plan</Text>
          <Text size={10} tone="dim">Fixed-formula ladder — independent of the Profit Targets estimate above; the two can disagree.</Text>
          <div className={styles.targetsTable}>
            {data.exit.targets.map((t, i) => (
              <EditableTargetRow
                key={t.id ?? i}
                target={t}
                index={i}
                editedStockPrice={overlay.targets[i] ?? t.targetPrice ?? t.stockPrice}
                entryLimit={overlay.entryLimit}
                premiumStop={overlay.premiumStop}
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

        {/* 6. R:R */}
        <section className={styles.rrCard}>
          <Text size={14} weight={600}>Risk / Reward</Text>
          <div className={styles.rrBody}>
            <Data size={24} weight={500}>{editedRR.rr.toFixed(1)}×</Data>
            <Text size={11} tone="secondary">
              {editedRR.model}
              {dirty ? ' — edited' : ''}
            </Text>
          </div>
        </section>

        {/* 7. Final Recommendation Scorecard */}
        <section className={`${styles.scoreCard} ${styles[`final_${data.finalStatus}`]}`}>
          <div className={styles.scoreCardHeader}>
            <Text size={14} weight={600}>Final Recommendation</Text>
            <LabeledStatusBadge
              label="Final Status"
              status={data.finalStatus}
              tooltip="Overall recommendation for this trade — the worse of the stock signal's historical accuracy and the contract's quality verdict below."
            />
          </div>
          <div className={styles.scoreCardBody}>
            <div className={styles.scoreRow}>
              <Text size={12} tone="secondary">Historical accuracy (3×ATR exit)</Text>
              <StatusBadge
                status={data.stockConfidence}
                tooltip="Backtested confidence tier for the stock signal. CAUTION means the pattern's historical win rate is marginal — consider reducing position size or waiting for a higher-conviction entry."
              />
            </div>
            <div className={styles.scoreRow}>
              <Text size={12} tone="secondary">Contract confidence</Text>
              <StatusBadge
                status={data.contractConfidence}
                tooltip="Overall contract quality verdict. Combines DTE fit, delta, IV attractiveness, liquidity, and spread. CAUTION means at least one component is borderline — try a different strike or expiry for a cleaner contract."
              />
            </div>
            <div className={styles.scoreRow}>
              <Text size={12} tone="secondary">Projected R/R (+8% stock move)</Text>
              <Data size={14} tone="primary">{editedRR.rr.toFixed(2)}x</Data>
            </div>
            <div className={styles.scoreRow}>
              <Text size={11} tone="dim">
                {editedRR.model}
                {dirty ? ' — edited' : ''}
              </Text>
            </div>
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
  data,
  onStockPriceChange,
  totalContracts,
}: {
  target: TargetLevel;
  index: number;
  editedStockPrice: number;
  entryLimit: number;
  premiumStop: number;
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

  const rr = rrContribution(estOptionPrice, entryLimit, premiumStop);

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
                step={0.01}
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

function EditableKV({
  label,
  value,
  onChange,
  min,
  max,
  step,
  mono,
  tone,
  prefix = '',
  suffix = '',
  decimals = 2,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  mono?: boolean;
  tone?: 'pass' | 'caution' | 'reject';
  prefix?: string;
  suffix?: string;
  decimals?: number;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(String(value));

  const startEdit = useCallback(() => {
    setDraft(String(value));
    setEditing(true);
  }, [value]);

  const save = useCallback(() => {
    const parsed = parseFloat(draft);
    if (isNaN(parsed)) {
      setEditing(false);
      return;
    }
    const minVal = min ?? -Infinity;
    const maxVal = max ?? Infinity;
    const clamped = Math.min(maxVal, Math.max(minVal, parsed));
    onChange(decimals === 0 ? Math.round(clamped) : Math.round(clamped * 100) / 100);
    setEditing(false);
  }, [draft, min, max, onChange, decimals]);

  const handleKey = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') save();
      if (e.key === 'Escape') setEditing(false);
    },
    [save],
  );

  const displayValue = decimals === 0
    ? `${prefix}${value}${suffix}`
    : `${prefix}${value.toFixed(decimals)}${suffix}`;

  return (
    <div className={styles.kvRow}>
      <Text size={12} tone="secondary">{label}</Text>
      {editing ? (
        <input
          type="number"
          className={styles.editInput}
          value={draft}
          min={min}
          max={max}
          step={step ?? (decimals === 0 ? 1 : 0.01)}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={save}
          onKeyDown={handleKey}
          autoFocus
          aria-label={`Edit ${label}`}
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
          {mono
            ? <Data size={13} weight={500} tone={tone}>{displayValue}</Data>
            : <Text size={13} weight={500}>{displayValue}</Text>}
        </span>
      )}
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
  structuralRRValue,
  structuralPending,
  structuralUnavailable,
  structuralZeroRisk,
}: {
  target: FirstPassageTarget;
  structuralRRValue: number | null;
  structuralPending: boolean;
  structuralUnavailable: boolean;
  structuralZeroRisk: boolean;
}) {
  const label = `T${Math.round(target.pct * 100)}%`;
  // Order matters: a stop that resolved to exactly the current stock price
  // (structuralZeroRisk) is a completed check with an undefined ratio, not
  // "not yet checked" — it must be distinguished from the true not-yet-run
  // fallback ('—', which should be unreachable once every real state above
  // it is covered, kept only as a defensive catch-all).
  const structuralValue = structuralRRValue != null
    ? `${structuralRRValue.toFixed(1)}×`
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
        <div className={styles.targetValues}>
          <KV label="Est. option" value={`$${target.optionPrice.toFixed(2)}`} mono />
          <KV
            label="Stock price"
            value={target.stockPrice != null ? `$${target.stockPrice.toFixed(2)}` : 'not reachable'}
            mono
          />
          <KV label="Probability" value={`${(target.probability * 100).toFixed(0)}%`} mono />
          <KV
            label="Expected time"
            value={target.expectedDays != null ? `~${Math.round(target.expectedDays)}d` : 'unlikely'}
            mono
          />
          <KV label="R:R vs. structural stop" value={structuralValue} mono />
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

export type { EditOverlay };
export { triggerDetailText, pullbackDetailText, trendDetailText, eventDetailText, volDetailText };