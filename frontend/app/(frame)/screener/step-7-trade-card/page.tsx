'use client';

/*
 * Screener Step 7 — Trade Card.
 * Prev/Next cycles ranked candidates, basket pins multiple. Send basket
 * opens a review dialog where any row can be switched from auto-send
 * (sent to broker mock) to manual (added to portfolio tagged MANUAL).
 * Successful submits surface a bottom-right toast with a Portfolio link.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { Title, Text } from '@/components/primitives';
import { TradeCard } from '@/components/organisms/TradeCard';
import { CandidateNav } from '@/components/molecules/CandidateNav';
import { SendToBrokerDialog, type DraftOrder } from '@/components/organisms/SendToBrokerDialog';
import { usePortfolioStore, persistPosition } from '@/lib/portfolioStore';
import { useRiskStore } from '@/lib/riskStore';
import { contractId as buildContractId } from '@/types/domain';
import { useScanStore } from '@/lib/scanStore';
import { logAudit } from '@/lib/audit';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import type { PortfolioPosition, TradeCardData } from '@/types/domain';
import { BrokerPicker }      from '@/components/organisms/BrokerPicker';
import { AutoTradeArm }      from '@/components/organisms/AutoTradeArm';
import { useAutoTradeStore } from '@/lib/autoTradeStore';
import { api }               from '@/lib/api';
import {
  applyPickedContract, contractKeyFor, mergePlan, resolveBasketCards, rrOverridesFrom,
  type OverriddenCard, type RecomputedPlanShape,
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
  };
}

function positionFromOrder(order: DraftOrder): PortfolioPosition {
  const c   = order.card;
  const cd  = c.contractDetails;
  const mid = cd?.mid ?? c.entry.limit;
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
    stop:          c.exit.invalidation,
    targets:       c.exit.targets,
    status:        c.finalStatus,
    ivRank:        cd?.ivRank,
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
  const [sizeAdjustedNote, setSizeAdjustedNote] = useState<string | null>(null);
  const [liveQuote,      setLiveQuote]        = useState<{ price: number; delta: number; theta: number; ivRank: number; spread: number; volume: number } | null>(null);
  const [liveStockPrice, setLiveStockPrice]   = useState<number | null>(null);
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
  useEffect(() => { setPaperOrderId(null); setOrderError(null); setSizeAdjustedNote(null); }, [active]);

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

  // Every basket item, override-resolved and (if overridden) merged with its
  // recomputed plan. `basketPlansPending` gates the whole "Send to broker" flow
  // so a basket order can never go out carrying an overridden contract whose
  // Entry/Exit/RR still describe the auto-pick — the exact bug this recompute
  // machinery exists to prevent, previously reachable only via Send basket.
  // (resolveBasketCards is the same pure logic exercised directly in
  // lib/__tests__/tradeCardOverride.test.ts.)
  const { cards: basketCards, pending: basketPlansPending } = useMemo(
    () => resolveBasketCards(basket, cardIndex, pickedContracts, contractsBySymbol, plansBySymbol),
    [basket, cardIndex, pickedContracts, contractsBySymbol, plansBySymbol],
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
          setLiveQuote(q);
          if (sq) setLiveStockPrice(sq.price);
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
          ...rrOverridesFrom(useScanStore.getState().scanOverrides),
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
        ...rrOverridesFrom(useScanStore.getState().scanOverrides),
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
  function buildPaperPosition(card: TradeCardData, orderType: 'LMT' | 'MKT', broker: string, orderId: string, livePrice?: number): PortfolioPosition {
    const cd  = card.contractDetails;
    const mid = livePrice ?? cd?.mid ?? card.entry.limit;
    const dte = cd?.dte ?? 24;
    const brokerLabel =
      broker === 'tradier_paper' ? 'Tradier Paper' :
      broker === 'tastytrade_paper' ? 'Tastytrade Paper' :
      'IBKR Paper';
    const typeLabel   = orderType === 'LMT' ? 'Limit' : 'Market';
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
      stop:          card.exit.invalidation,
      targets:       card.exit.targets,
      status:        card.finalStatus,
      ivRank:        cd?.ivRank,
      delta:         cd?.delta,
      theta:         cd?.theta,
      vega:          0.20,
      contracts:     1,
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
    setLimitPlacing(true); setOrderError(null);
    try {
      const res = await api.postOptionOrder({
        broker:        selectedBroker,
        symbol:        card.symbol,
        option_symbol: toOptionSymbol(card),
        action:        'BUY',
        quantity:      1,
        order_type:    'LMT',
        limit_price:   card.entry.limit,
        tif:           'DAY',
      });
      const pos = buildPaperPosition(card, 'LMT', selectedBroker, res.order_id, liveQuote?.price);
      const saved = await persistPosition(pos);
      if (!saved.ok) {
        setOrderError(`Order placed in Tradier but portfolio tracking rejected: ${saved.detail}`);
        return;
      }
      if (saved.adjustedQty != null) {
        setSizeAdjustedNote(`Size reduced to ${saved.adjustedQty} contract${saved.adjustedQty === 1 ? '' : 's'} to fit exposure limits.`);
      }
      setPaperOrderId(res.order_id);
      void addPosition(pos);
    } catch (e) {
      setOrderError(String(e));
    } finally {
      setLimitPlacing(false);
    }
  }

  async function placeMarketNow() {
    const card = effectiveCard;
    if (!card || !selectedBroker) return;
    setMarketPlacing(true); setOrderError(null);
    try {
      const res = await api.postOptionOrder({
        broker:        selectedBroker,
        symbol:        card.symbol,
        option_symbol: toOptionSymbol(card),
        action:        'BUY',
        quantity:      1,
        order_type:    'MKT',
        limit_price:   null,
        tif:           'DAY',
      });
      const pos = buildPaperPosition(card, 'MKT', selectedBroker, res.order_id, liveQuote?.price);
      const saved = await persistPosition(pos);
      if (!saved.ok) {
        setOrderError(`Order placed in Tradier but portfolio tracking rejected: ${saved.detail}`);
        return;
      }
      if (saved.adjustedQty != null) {
        setSizeAdjustedNote(`Size reduced to ${saved.adjustedQty} contract${saved.adjustedQty === 1 ? '' : 's'} to fit exposure limits.`);
      }
      setPaperOrderId(res.order_id);
      void addPosition(pos);
    } catch (e) {
      setOrderError(String(e));
    } finally {
      setMarketPlacing(false);
    }
  }

  const idx = symbols.indexOf(active);

  const goPrev = () => { if (idx > 0) setActive(symbols[idx - 1]!); };
  const goNext = () => { if (idx >= 0 && idx < symbols.length - 1) setActive(symbols[idx + 1]!); };

  const togglePin = () =>
    setBasket((b) => (b.includes(active) ? b.filter((s) => s !== active) : [...b, active]));
  const removePin = (sym: string) => setBasket((b) => b.filter((s) => s !== sym));

  const handleSubmit = async (orders: DraftOrder[], _riskOverridden: boolean) => {
    usePortfolioStore.getState().clearSyncError();
    let auto = 0, manual = 0, queued = 0;
    const failures: string[] = [];
    const adjusted: string[] = [];

    for (const o of orders) {
      // One canonical recId per order: addPosition syncs it to the backend
      // (a single POST), so there is no second POST to conflict (409) with.
      const recId = recIdMap[o.card.symbol] ?? generateRecId();
      const res = await addPosition({ ...positionFromOrder(o), recId });

      if (res.status === 'rejected') {
        // Backend refused it and the optimistic row was dropped — a real failure.
        failures.push(`${o.card.symbol}: ${res.detail ?? 'not saved'}`);
        continue;
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
            <StatusBadge status="PENDING" label="User-selected" />
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
              data={effectiveCard}
              recId={recIdMap[effectiveCard.symbol]}
              onSendToBroker={() => !basketEmpty && !basketPlansPending && setDialogOpen(true)}
              sendLabel={sendLabel}
              sendDisabled={basketEmpty || basketPlansPending}
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
          {liveQuote && !fetchingQuote && (
            <Text size={11} tone="secondary">Live mid: ${liveQuote.price.toFixed(2)}</Text>
          )}
          {liveStockPrice != null && !fetchingQuote && (
            <Text size={11} tone="secondary">Live stock: ${liveStockPrice.toFixed(2)}</Text>
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
                  disabled={limitPlacing || marketPlacing || !planReady}
                >
                  {limitPlacing ? 'Placing…' : planReady ? `Place Limit @ $${effectiveCard.entry.limit}` : 'Place Limit'}
                </button>
                <button
                  type="button"
                  className={paperStyles.paperBtnMarket}
                  onClick={placeMarketNow}
                  disabled={limitPlacing || marketPlacing || !planReady}
                >
                  {marketPlacing ? 'Placing…' : 'Right Now — Market'}
                </button>
              </div>
              {!planReady && (
                <Text size={11} tone="caution">
                  Recomputing the plan for your selected contract — ordering enabled once it&apos;s ready.
                </Text>
              )}
              {paperOrderId && <Text size={12} tone="pass">Order placed — ID: {paperOrderId}</Text>}
              {sizeAdjustedNote && <Text size={12} tone="caution">{sizeAdjustedNote}</Text>}
              {orderError   && <Text size={12} tone="reject">{orderError}</Text>}
              {planReady && <AutoTradeArm card={effectiveCard} broker={selectedBroker} />}
            </>
          )}
        </div>
      )}

      {dialogOpen && (
        <SendToBrokerDialog
          cards={basketCards}
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
