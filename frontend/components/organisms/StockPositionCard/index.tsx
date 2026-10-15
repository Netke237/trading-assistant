'use client';

import { type ReactNode, useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Text, Data } from '@/components/primitives';
import { useScanStore } from '@/lib/scanStore';
import { selectCardEdits, pickedFieldsFrom } from '@/lib/cardEdits';
import { MethodPickSelector } from '@/components/molecules/MethodPickSelector';
import type { MethodPickOption } from '@/components/molecules/MethodPickSelector';
import type { MethodPick, PickedMethod } from '@/types/domain';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useRiskStore } from '@/lib/riskStore';
import { buildPaperStockPosition, stockCardSnapshotOf, invalidTargetRungs, stockPositionLevels } from '@/lib/paperTrade';
import { checkMethodPick, MISSING_METHOD_PICK_TITLE, MISSING_METHOD_PICK_MESSAGE } from '@/lib/risk';
import { BEARISH_UNVALIDATED_MESSAGE, isBearishUnvalidated } from '@/lib/unvalidated';
import { stockEarningsGate, EARNINGS_VETO_MESSAGE } from '@/lib/earningsGate';
import { api } from '@/lib/api';
import { buildCandidateChartHref } from '@/lib/candidateChart';
import { useStockExecutionField, useStockExecutionIdentity } from '@/lib/useStockExecutionField';
import { defaultStockOverlay as defaultOverlay, patchStockOverlay, stockExecutionBlock, useStockOrderOwnershipStore, type StockEditOverlay } from '@/lib/stockExecutionSession';
import { sendStockSaveFirst } from '@/lib/stockDirectSend';
import { _horizonEnum } from '@/lib/analysisStore';
import { sanitizeHoldDays } from '@/lib/horizonPresets';
import { stockStatusTooltip, winRateTooltip } from '@/lib/statusTooltips';
import type { PositionCardData } from '@/types/stockDomain';
// The SAME prose the options card's Arithmetic Profit Target section uses.
// The stocks plan is built from the same compute_final_stop /
// compute_target_row and reports the same fields under the same names, so
// there is one implementation of these sentences, not two.
import { stopJustification, targetCompareState, targetCompareLabel } from '@/lib/exitPlanLabels';
import type { Direction } from '@/types/domain';
import { StockAutoTradeArm } from '@/components/organisms/StockAutoTradeArm';
import { MarketSentiment } from '@/components/molecules/MarketSentiment';
import { FundamentalHealthCard } from '@/components/molecules/FundamentalHealthCard';
import styles from './StockPositionCard.module.css';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { ConfidenceBadge } from '@/components/atoms/ConfidenceBadge';
import { PositionEvidence } from './PositionEvidence';
import { InitialStrategyTargets } from './InitialStrategyTargets';

function PositionDisclosure({ active, children }: { active: boolean; children: ReactNode }) {
  return active ? <details className={styles.autoTrade}><summary>Auto-trade execution</summary>{children}</details> : <>{children}</>;
}

function PositionGroup({ active, tag = 'div', children, ...props }: { active: boolean; tag?: 'div' | 'section' | 'aside' | 'details'; children: ReactNode; className?: string; id?: string }) {
  if (!active) return <>{children}</>;
  const Tag = tag;
  return <Tag {...props}>{children}</Tag>;
}

/** Position presentation reorders evidence only; embedded cards retain their order. */
function MethodEvidenceStack({ position, original, arithmetic, monteCarlo }: {
  position: boolean; original: ReactNode; arithmetic: ReactNode; monteCarlo: ReactNode;
}) {
  return position ? <>
    <section aria-label="Original ladder evidence" className={styles.workspaceCard}>{original}</section>
    <section aria-label="Arithmetic evidence">{arithmetic}</section>
    <section aria-label="Monte Carlo evidence">{monteCarlo}</section>
  </> : <>{monteCarlo}{arithmetic}</>;
}

// Backend stock barrier statistics use trading-day medians; half-days can occur.
function medianTradingDays(days: number | null) {
  return days != null ? `~${days} trading days` : 'unlikely';
}

// ─── Types ────────────────────────────────────────────────────────────────────

/** The single-position concentration check that stands beside the recommended
 *  share count — Kenneth's decision SHARE-SIZING-CONCENTRATION-FLAG-2026-09-09.
 *
 *  The recommendation sizes off the RISK BUDGET (how much do I lose if I'm
 *  wrong) and never consults the single-position cap (how much of the account
 *  sits in one name). Those are different questions, and a TIGHTER stop makes
 *  the gap WIDER: 239 shares of a $211 stock is a ~$50,570 position against a
 *  5%-of-$100k cap of $5,000 — ~10x over, and ~23 shares by the cap.
 *
 *  It FLAGS, it never clamps. `recommendedShares` stays exactly the number the
 *  piece-6 spec pins (floor(riskBudget / riskPerShare), spec test 6), Apply
 *  stays enabled, and the trader makes the call with the conflict in front of
 *  him. Capping would silently overrule a spec-mandated number and would make
 *  the recommendation useless on any liquid large-cap with a tight stop.
 *
 *  `cap` and `portfolioValue` MUST arrive from riskStore. The cap is the STOCK
 *  single-position cap `maxSingleStockPositionPct` — the number check_position_risk
 *  judges a stock save against and computeMetrics' stock concentration band uses
 *  (STOCK-SENDS) — never a second copy that would drift from Settings.
 *
 *  Returns null when there is nothing truthful to say: no recommendation, or a
 *  portfolio value / cap that cannot produce a meaningful limit. A cap of 100%
 *  is legal in Settings and simply never fires. */
function concentrationFlag(
  shares: number | null,
  entry: number,
  portfolioValue: number,
  cap: number,
): { positionDollar: number; capDollar: number; positionPct: number; capShares: number } | null {
  if (shares == null || !Number.isFinite(shares) || shares <= 0) return null;
  if (!Number.isFinite(entry) || entry <= 0) return null;
  if (!Number.isFinite(portfolioValue) || portfolioValue <= 0) return null;
  if (!Number.isFinite(cap) || cap <= 0) return null;

  const positionDollar = shares * entry;
  const capDollar      = portfolioValue * cap;
  if (positionDollar <= capDollar) return null;

  return {
    positionDollar,
    capDollar,
    positionPct: (positionDollar / portfolioValue) * 100,
    // What the cap WOULD allow, so the flag is actionable rather than merely
    // disapproving. Floor for the same reason the backend floors: a share count
    // rounded up is a position over the cap it was derived from.
    capShares: Math.floor(capDollar / entry),
  };
}

interface StockPositionCardProps {
  presentation?: 'embedded' | 'position';
  card: PositionCardData;
  strategyKey: string;
  afterScanArmed?: boolean;
  onAfterScanToggle?: (symbol: string, armed: boolean) => void;
}

type ExecMode = 'recommendation' | 'ibkr_paper' | 'tradier_paper' | 'alpaca_paper' | 'tastytrade_paper';

/** The subset of `/api/contracts/structural-stop`'s response this card keeps. */
// ─── Helpers ──────────────────────────────────────────────────────────────────

// ─── EditableField ────────────────────────────────────────────────────────────

function EditableField({
  label,
  value,
  onChange,
  tone,
  decimals = 2,
  integer = false,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  tone?: 'pass' | 'caution' | 'reject';
  decimals?: number;
  integer?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft]     = useState('');

  const startEdit = () => { setDraft(String(value)); setEditing(true); };
  const save = () => {
    const p = parseFloat(draft);
    if (!isNaN(p) && p > 0) onChange(integer ? Math.round(p) : Math.round(p * 100) / 100);
    setEditing(false);
  };

  return (
    <div className={styles.editCell}>
      <Text size={10} tone="dim">{label}</Text>
      {editing ? (
        <input
          type="number"
          className={styles.editInput}
          value={draft}
          min={0.01}
          step={integer ? 1 : 0.01}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={save}
          onKeyDown={(e) => {
            if (e.key === 'Enter') save();
            if (e.key === 'Escape') setEditing(false);
          }}
          autoFocus
        />
      ) : (
        <span
          className={styles.editValue}
          onClick={startEdit}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') startEdit(); }}
        >
          <Data size={14} weight={500} tone={tone}>
            {integer ? String(value) : value.toFixed(decimals)}
          </Data>
        </span>
      )}
    </div>
  );
}

// ─── StockPositionCard ────────────────────────────────────────────────────────

/** The refusal line for a pick the card's clear rule just removed, or null
 *  when there is nothing specific to say (never picked, or a Ladder pick --
 *  Ladder is always available, so it is never the one cleared). */
export function clearedPickMessage(method: PickedMethod | null): string | null {
  if (method === 'monte_carlo') {
    return 'Your Monte Carlo pick was cleared because its estimate is no longer on screen — '
      + 'run Estimate again and re-pick before submitting.';
  }
  if (method === 'arithmetic') {
    return 'Your Arithmetic pick was cleared because its plan is no longer on screen — '
      + 'run the Arithmetic plan again and re-pick before submitting.';
  }
  return null;
}

export function StockPositionCard({
  presentation = 'embedded',
  card,
  strategyKey,
  afterScanArmed,
  onAfterScanToggle,
}: StockPositionCardProps) {
  const executionIdentity = useStockExecutionIdentity(card.symbol);
  const position = presentation === 'position';
  const [latest, setLatest] = useState<{ identity: string | null; method: 'arithmetic' | 'monte_carlo' } | null>(null);
  const sessionAfterScanArmed = useScanStore(s => !!s.stockAfterScanIntent[card.symbol]);
  const toggleAfterScanIntent = useScanStore(s => s.setStockAfterScanIntent);
  const orderOwnership = useStockOrderOwnershipStore(s => s.bySymbol[card.symbol]);
  const [overlayValue, setOverlay] = useStockExecutionField(executionIdentity, 'overlay', defaultOverlay(card));
  const overlay = overlayValue!;
  const [spotPrice, setSpotPrice] = useState<number | null>(null);
  const [fetchingSpot, setFetchingSpot] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setSpotPrice(null);
    setFetchingSpot(true);
    Promise.resolve().then(() => api.getStockQuote(card.symbol)).then(q => {
      if (!cancelled) setSpotPrice(q.price);
    }).catch(() => {}).finally(() => { if (!cancelled) setFetchingSpot(false); });
    return () => { cancelled = true; };
  }, [executionIdentity, card.symbol]);
  // The concentration flag beside the recommended share count reads the SAME
  // portfolio value and single-position cap the risk checks use, so editing
  // either in Settings moves this warning with them.
  const riskLimits = useRiskStore((s) => s.limits);

  const patch = useCallback((partial: Partial<StockEditOverlay>) => {
    setOverlay((prev) => {
      return patchStockOverlay(prev, partial);
    });
    // A displayed estimate/structural-stop result is a snapshot computed
    // against the overlay values AT THE MOMENT the user clicked Estimate /
    // Check structure (onEstimate sends overlay.entry/stop/t1/t2/t3;
    // onCheckStructure sends overlay.entry as its reference price). Neither
    // result was ever invalidated by a later overlay edit — an adversarial
    // audit round caught this: edit the stop after running Estimate and the
    // card kept showing the OLD probability/expected-days next to the NEW
    // stop value, silently implying they were computed together. Clear
    // whichever result depends on what just changed (and abort it if still
    // in flight, so a late response for the pre-edit values can't land
    // either) — the user re-runs the click-gated fetch to get numbers that
    // actually match the edit.
    if ('entry' in partial || 'stop' in partial || 't1' in partial || 't2' in partial || 't3' in partial) {
      estimateReq.current?.abort();
      setEstimate(null);
      setEstimateErr(null);
    }
    if ('entry' in partial) {
      structuralReq.current?.abort();
      setStructural(null);
      setStructuralErr(null);
      // The arithmetic plan DERIVES its own stop and targets from the entry
      // price alone — that is the whole point of it — so `entry` is its only
      // overlay input, and the only edit that can strand it. Editing the stop
      // must NOT clear it: the plan's stop is deliberately a second opinion
      // standing beside the card's, and clearing it on a stop edit would
      // destroy the comparison the moment the user acted on it.
      planReq.current?.abort();
      setPlan(null);
      setPlanErr(null);
    }
  }, [executionIdentity]);

  // Derived values
  const riskPerShare = Math.abs(overlay.entry - overlay.stop);
  const riskDollars  = overlay.shares * riskPerShare;
  const sizeDollars  = overlay.shares * overlay.entry;
  const rrAt = (t: number) =>
    riskPerShare > 0 ? Math.abs(t - overlay.entry) / riskPerShare : 0;

  // Match the stop basis accepted by the existing position builder, including
  // its direction check and cent rounding. Invalid stops have no valid displayed
  // risk basis; a trade with an invalid stop must not be described as riskless.
  const roundedExecutionStop = stockPositionLevels(overlay.entry, card.direction as Direction, overlay.stop).stop;
  const stopDistance = roundedExecutionStop == null ? null : (card.direction === 'Bullish'
    ? overlay.entry - roundedExecutionStop : roundedExecutionStop - overlay.entry);
  const executionStop = roundedExecutionStop != null && roundedExecutionStop > 0
    && stopDistance != null && Number.isFinite(stopDistance) && stopDistance > 0 ? roundedExecutionStop : null;
  const executionRiskPerShare = executionStop == null ? null : stopDistance;
  const enteredSharesValid = Number.isFinite(overlay.shares) && overlay.shares >= 0;
  const positionValue = Number.isFinite(overlay.entry) && overlay.entry > 0 && enteredSharesValid
    ? overlay.entry * overlay.shares : null;
  const executionRiskDollars = executionRiskPerShare != null && enteredSharesValid
    ? executionRiskPerShare * overlay.shares : null;
  const executionMoney = (value: number | null) => value != null && Number.isFinite(value)
    ? `$${value.toFixed(2)}` : 'Unavailable';

  // Store selectors
  // Display label like "Swing (5–15d)"; _horizonEnum maps it to the backend enum.
  const scanHorizonLabel = useScanStore((s) => s.context?.horizon ?? null);
  const recordedRequest = useScanStore((s) => s.stockScanRequest);
  // STOCKS-HORIZON-P0B B7: earnings inside the scan's veto window
  // max(reject_days, hold), aged by the scan's age. Unknown never blocks.
  const scanTimestamp = useScanStore((s) => s.stockScanResult?.timestamp);
  const scanVetoDays  = useScanStore((s) => s.stockScanResult?.veto_days);
  const earningsVeto  = stockEarningsGate(card, scanTimestamp, scanVetoDays).veto;
  // STOCKS-HORIZON-T1 H6: the scan's hold, written on the position so a stock
  // raises TIME_STOP once held that long. No scan context -> no hold.
  const scanContext  = useScanStore((s) => s.context);
  const holdMaxDays  = scanContext
    ? sanitizeHoldDays(scanContext.holdMin, scanContext.holdMax).hold_max_days
    : null;
  const stockBasket  = useScanStore((s) => s.stockBasket);
  const addToBasket  = useScanStore((s) => s.addToStockBasket);
  const removeBasket = useScanStore((s) => s.removeFromStockBasket);
  const addPosition  = usePortfolioStore((s) => s.addPosition);
  const ibkrPaper    = useSettingsStore((s) => s.ibkrPaper);
  const tradierPaper = useSettingsStore((s) => s.tradierPaper);

  const [execMode, setExecMode] = useStockExecutionField(executionIdentity, 'execMode', 'recommendation');
  const [placingType, setPlacingType] = useStockExecutionField(executionIdentity, 'placingType', null);
  const [orderId, setOrderId] = useStockExecutionField(executionIdentity, 'orderId', null);
  // STOCK-SENDS: what to say about `orderId`'s order -- placed (with any
  // resize, R1-2) or status unknown.
  const [orderMsg, setOrderMsg]         = useStockExecutionField(executionIdentity, 'orderMsg', null);
  const [err, setErr] = useStockExecutionField(executionIdentity, 'err', null);
  const [warning, setWarning] = useStockExecutionField(executionIdentity, 'warning', null);
  const [added, setAdded] = useStockExecutionField(executionIdentity, 'added', false);
  const [queued, setQueued] = useStockExecutionField(executionIdentity, 'queued', false);
  const [adding, setAdding] = useStockExecutionField(executionIdentity, 'adding', false);
  const [alpacaConfigured, setAlpacaConfigured] = useState(false);
  const [tastytradeConfigured, setTastytradeConfigured] = useState(false);

  // ── On-demand analytics (Approach B) ──────────────────────────────────────
  const [estimate, setEstimate] = useStockExecutionField(executionIdentity, 'estimate', null);
  const [estimating, setEstimating] = useStockExecutionField(executionIdentity, 'estimating', false);
  const [estimateErr, setEstimateErr] = useStockExecutionField(executionIdentity, 'estimateErr', null);
  const [structural, setStructural] = useStockExecutionField(executionIdentity, 'structural', null);
  const [checkingStructure, setCheckingStructure] = useStockExecutionField(executionIdentity, 'checkingStructure', false);
  const [structuralErr, setStructuralErr] = useStockExecutionField(executionIdentity, 'structuralErr', null);
  const [plan, setPlan] = useStockExecutionField(executionIdentity, 'plan', null);
  const [planning, setPlanning] = useStockExecutionField(executionIdentity, 'planning', false);
  const [planErr, setPlanErr] = useStockExecutionField(executionIdentity, 'planErr', null);
  const estimateInputKey = JSON.stringify([card.symbol, card.direction, _horizonEnum(scanHorizonLabel ?? undefined), card.strategy.strategy, card.stock_score, overlay.entry, overlay.stop, overlay.t1, overlay.t2, overlay.t3]);
  const planInputKey = JSON.stringify([card.symbol, card.direction, _horizonEnum(scanHorizonLabel ?? undefined), card.strategy.strategy, card.stock_score, overlay.entry]);
  const structuralInputKey = JSON.stringify([card.symbol, card.direction, overlay.entry]);
  useEffect(() => {
    if (!executionIdentity) return;
    const state = useScanStore.getState();
    const previous = state.stockExecution[executionIdentity] ?? {};
    const patch: import('@/lib/stockExecutionSession').StockExecutionRecord = {};
    if (previous.estimateInputKey !== estimateInputKey) Object.assign(patch, { estimateInputKey, estimate: null, estimateErr: null, estimating: false, estimateRevision: (previous.estimateRevision ?? 0) + 1 });
    if (previous.planInputKey !== planInputKey) Object.assign(patch, { planInputKey, plan: null, planErr: null, planning: false, entryRevision: (previous.entryRevision ?? 0) + 1 });
    if (previous.structuralInputKey !== structuralInputKey) Object.assign(patch, { structuralInputKey, structural: null, structuralErr: null, checkingStructure: false, structuralRevision: (previous.structuralRevision ?? 0) + 1 });
    if (Object.keys(patch).length) state.patchStockExecution(executionIdentity, patch);
  }, [executionIdentity, estimateInputKey, planInputKey, structuralInputKey]);
  const estimateReq   = useRef<AbortController | null>(null);
  const structuralReq = useRef<AbortController | null>(null);
  const planReq       = useRef<AbortController | null>(null);
  const estimateToken = useRef<number | null>(null);
  const planToken = useRef<number | null>(null);
  const structuralToken = useRef<number | null>(null);

  useEffect(() => { estimateReq.current?.abort(); }, [executionIdentity, estimateInputKey]);
  useEffect(() => { planReq.current?.abort(); }, [executionIdentity, planInputKey]);
  useEffect(() => { structuralReq.current?.abort(); }, [executionIdentity, structuralInputKey]);

  // ─── Phase G piece 5 (D4/D5) — the per-trade method pick ───────────────────
  //
  // Spec §6.3. NO PROP PAIR, unlike TradeCard: this card holds its own state
  // and sends from inside itself, so it reads and writes the store directly.
  // KEYED BY SYMBOL because stocks mode has no contract — the same reason every
  // other stocks-mode edit is symbol-keyed.
  //
  // `selectCardEdits`, never `state.stocksCardEdits`: the selector returns an
  // EMPTY slice when the slice's stamp does not match the scan currently in the
  // store, which is what stops last scan's pick from being sent with this
  // scan's numbers. Stocks mode has no contract-switch reset of its own
  // (TradeCard's is options-only), so that stamp is the ONLY thing standing
  // between a stale pick and a position — §7.4 says so in as many words.
  const stocksPicks   = useScanStore((st) => selectCardEdits(st, 'stocks').picks);
  const setCardEdit   = useScanStore((st) => st.setCardEdit);
  const clearCardPick = useScanStore((st) => st.clearCardPick);
  const methodPick    = stocksPicks[card.symbol] ?? null;
  // Phase G piece 5, build step 4 (§7.2, S1/S2). Stocks mode had no pre-send
  // refusal of any kind before this — this is that gate's own local reading,
  // same shape as step 7's `pickMissing`.

  // READ FROM THE STORE, NOT MIRRORED INTO LOCAL STATE, and that buys a
  // property the typed-price fields do not have. `lib/stockScan.ts` sets
  // `stockScanResult` to null for the DURATION of every stock scan, so a click
  // landing in that window has no stamp to write under and `writeCardEdit`
  // drops it (G2-6). Because the radio's checked state comes from the store and
  // not from a local copy, a dropped write simply does not light the button up:
  // the user sees nothing happen and clicks again. Compare `writeCardEdit`'s own
  // note, where the same drop on a TYPED PRICE leaves the card showing $2.71
  // while the order carries $2.50 — there the safety is unreachability, here it
  // is visibility. Mirroring the pick into `useState` to make the click feel
  // instant would trade that away.
  const applyMethodPick = useCallback((next: MethodPick | null) => {
    if (next) setCardEdit('stocks', 'picks', card.symbol, next);
    else clearCardPick('stocks', card.symbol);
  }, [setCardEdit, clearCardPick, card.symbol]);

  /** THREE OPTIONS, NOT FOUR (§6.3). There is no Barrier Race here: the race
   *  is a contest between an option's premium stop and the underlying's stock
   *  stop, and a stock position has only one of those.
   *
   *  EVERY ROW IS STOCK SPACE, so `rowOptionPrice` is null on all of them. That
   *  is not a simplification of §6.1's table — it is what the table says for a
   *  card with no premium anywhere on it, and it means a stocks pick can always
   *  seed `resolved_tp_price` (§4.3) where a Barrier Race pick never can. */
  const methodPickOptions = useMemo<MethodPickOption[]>(() => [
    {
      // Always selectable — the ladder is the card's own editable T1/T2/T3 and
      // needs no fetch. These are `overlay` values, not `card.strategy.targets`,
      // so the pick records the rows the user has edited and is about to send.
      method: 'ladder' as const,
      label: 'Ladder',
      unavailable: null,
      rows: ([
        { key: 'T1', price: overlay.t1 },
        { key: 'T2', price: overlay.t2 },
        { key: 'T3', price: overlay.t3 },
      ]).map((r) => ({
        key: r.key, label: r.key, displayPrice: r.price,
        rowStockPrice: r.price, rowOptionPrice: null,
      })),
    },
    {
      method: 'arithmetic' as const,
      label: 'Arithmetic',
      unavailable: plan ? null : 'Run Arithmetic plan first',
      rows: (plan?.targets ?? []).map((t) => ({
        key: `arith-${t.rrRatio}`,
        label: `${t.rrRatio}R`,
        displayPrice: t.price,
        rowStockPrice: t.price,
        rowOptionPrice: null,
      })),
    },
    {
      // `estimate` is cleared by `patch` on any edit to entry/stop/T1/T2/T3 and
      // by dependency/replacement invalidation, so "present" means "computed against the
      // numbers on screen". That is this card's equivalent of TradeCard's
      // `estimateIsFresh`, and it is enforced by the clearing rather than by a
      // flag.
      method: 'monte_carlo' as const,
      label: 'Monte Carlo',
      unavailable: estimate ? null : 'Run Estimate first',
      rows: (estimate?.targets ?? []).map((t, i) => ({
        key: `mc-${i}`,
        label: `T${i + 1}`,
        displayPrice: t.price,
        rowStockPrice: t.price,
        rowOptionPrice: null,
      })),
    },
  ], [overlay.t1, overlay.t2, overlay.t3, plan, estimate]);

  // Evidence and overlay are selected synchronously by execution identity,
  // so a candidate switch cannot mix the old analytics with the new pick.
  // A selected row must match its displayed price; a method-only choice
  // remains valid under the established explicit-pick contract.
  const pickedOption = methodPick
    ? methodPickOptions.find((o) => o.method === methodPick.method) ?? null
    : null;
  const pickedMethodGone = methodPick != null
    && (pickedOption == null || pickedOption.unavailable != null
      || ((methodPick.rowStockPrice != null || methodPick.rowOptionPrice != null)
        && !pickedOption.rows.some(row => row.rowStockPrice === methodPick.rowStockPrice
          && row.rowOptionPrice === methodPick.rowOptionPrice)));
  const pickMissing = !checkMethodPick(methodPick) || pickedMethodGone;

  // Picks persist a price pair, not a row key. Duplicate prices cannot identify
  // which row supplied its statistics; never borrow the first matching result.
  const selectedMatches = !pickedMethodGone && methodPick && pickedOption
    ? pickedOption.rows.filter(row => row.rowStockPrice === methodPick.rowStockPrice
      && row.rowOptionPrice === methodPick.rowOptionPrice) : [];
  const selectedRow = selectedMatches.length === 1 ? selectedMatches[0] : null;
  const selectedTarget = !pickedMethodGone ? methodPick?.rowStockPrice ?? null : null;
  const arithmeticMatches = selectedRow && methodPick?.method === 'arithmetic'
    ? (plan?.targets ?? []).filter(row => `arith-${row.rrRatio}` === selectedRow.key && row.price === selectedTarget) : [];
  const arithmeticTarget = arithmeticMatches.length === 1 ? arithmeticMatches[0] : null;
  const mcTarget = selectedRow && methodPick?.method === 'monte_carlo'
    ? estimate?.targets.find((row, index) => `mc-${index}` === selectedRow.key && row.price === selectedTarget) ?? null : null;
  const selectedEvidence = arithmeticTarget ?? mcTarget;
  const selectedWindow = arithmeticTarget ? plan?.horizonDays : mcTarget ? estimate?.horizonDays : null;
  const selectedMove = selectedTarget != null && Number.isFinite(overlay.entry) && overlay.entry > 0
    && (card.direction === 'Bullish' || card.direction === 'Bearish')
    ? (card.direction === 'Bullish' ? selectedTarget - overlay.entry : overlay.entry - selectedTarget) : null;
  const selectedReward = methodPick?.method === 'arithmetic'
    ? arithmeticTarget && selectedMove != null ? Math.sign(selectedMove) * arithmeticTarget.rewardPerShare : null
    : selectedMove;
  const selectedOutcome = selectedReward != null && enteredSharesValid ? selectedReward * overlay.shares : null;
  const selectedCalculationStop = methodPick?.method === 'arithmetic' && !pickedMethodGone ? plan?.stop.price ?? null : executionStop;


  const applyMethodPickRef = useRef(applyMethodPick);
  useEffect(() => { applyMethodPickRef.current = applyMethodPick; }, [applyMethodPick]);
  // Keep the unavailable-method explanation with this execution identity.
  const [clearedPickMethod, setClearedPickMethod] = useStockExecutionField(executionIdentity, 'clearedPickMethod', null);
  // The note is about THIS symbol's pick. Step 4 remounts per symbol, but a
  // caller that switches `card` on one instance must not carry it across.
  // Declared BEFORE the clear effect so that, when a switch lands on a symbol
  // whose own pick is cleared in the same commit, the reset runs first.

  const methodPickRef = useRef(methodPick);
  useEffect(() => { methodPickRef.current = methodPick; }, [methodPick]);
  useEffect(() => {
    if (!pickedMethodGone) return;
    setClearedPickMethod(methodPickRef.current?.method ?? null);
    applyMethodPickRef.current(null);
  }, [pickedMethodGone]);
  // Any new, AVAILABLE pick retires the note. `!pickedMethodGone` is what
  // keeps this from undoing the line above: on the mount that clears, both
  // effects run in one commit, in declaration order, while `methodPick` still
  // holds the pick being cleared.
  useEffect(() => {
    if (methodPick != null && !pickedMethodGone) setClearedPickMethod(null);
  }, [methodPick, pickedMethodGone]);

  useEffect(() => {
    if (executionIdentity) return;
    // A read-only card without a result stamp has no shared session. Changing
    // its symbol must still not carry the preceding symbol's local evidence.
    setOverlay(defaultOverlay(card));
    setEstimate(null); setPlan(null); setStructural(null);
    setEstimateErr(null); setPlanErr(null); setStructuralErr(null);
    setEstimating(false); setPlanning(false); setCheckingStructure(false);
    setErr(null); setWarning(null); setClearedPickMethod(null);
    setAdded(false); setQueued(false); setAdding(false);
  }, [executionIdentity, card.symbol]);

  // Navigation aborts analytics owned by this mounted card, never mutations.
  useEffect(() => () => {
    const record = executionIdentity ? useScanStore.getState().stockExecution[executionIdentity] : null;
    if (estimateReq.current) {
      estimateReq.current.abort();
      if (!record || record.estimateRequestToken === estimateToken.current) setEstimating(false);
    }
    if (structuralReq.current) {
      structuralReq.current.abort();
      if (!record || record.structuralRequestToken === structuralToken.current) setCheckingStructure(false);
    }
    if (planReq.current) {
      planReq.current.abort();
      if (!record || record.planRequestToken === planToken.current) setPlanning(false);
    }
  }, [executionIdentity]);

  const pinned            = stockBasket.some((c) => c.symbol === card.symbol);
  const ibkrConfigured    = !!ibkrPaper.accountId && !!ibkrPaper.baseUrl;
  const tradierConfigured = !!tradierPaper.token && !!tradierPaper.accountId;

  useEffect(() => {
    api.getBrokerStatus()
      .then((s) => {
        setAlpacaConfigured(s.alpaca_paper?.configured ?? false);
        setTastytradeConfigured(s.tastytrade_paper?.configured ?? false);
      })
      .catch(() => {});
  }, []);

  async function submit(orderType: 'LMT' | 'MKT') {
    if (execMode === 'recommendation' || orderId != null || placingType != null || orderOwnership) return;
    if (isBearishUnvalidated(card.direction)) { setErr(BEARISH_UNVALIDATED_MESSAGE); return; }
    if (earningsVeto) { setErr(EARNINGS_VETO_MESSAGE); return; }
    const validationBlock = stockExecutionBlock();
    if (validationBlock) { setErr(validationBlock); return; }
    // Phase G piece 5, build step 4 (§7.2, S1) — belt-and-braces beside the
    // button's own `disabled`, on the same reading `pickMissing` was derived
    // from. Same shape as step 7's direct-send handlers.
    if (pickMissing) return;
    setPlacingType(orderType);
    setErr(null);
    setWarning(null);
    // STOCK-SENDS (P1-STOCK-CLAMP-REAL-SHARES-DEFERRED-2026-09-25): SAVE first,
    // then the order at the quantity the save approved (lib/stockDirectSend.ts).
    try {
      const outcome = await sendStockSaveFirst({
        pos: {
          ...buildPaperStockPosition(
            card.symbol, overlay.entry, overlay.shares, card.direction as Direction,
            stockCardSnapshotOf(card, scanHorizonLabel ?? 'Swing', {
              entry: overlay.entry,
              stop: overlay.stop,
              targets: [overlay.t1, overlay.t2, overlay.t3],
              shares: overlay.shares,
            }),
            {
              stop: overlay.stop,
              targets: [
                { price: overlay.t1, shares: overlay.sharesT1 },
                { price: overlay.t2, shares: overlay.sharesT2 },
                { price: overlay.t3, shares: overlay.sharesT3 },
              ],
              structuralStop: structural?.price ?? null,
            },
          ),
          // Phase G (piece 5) — `methodPick` is this card's own local pick
          // state (synced from stocksCardEdits.picks).
          ...pickedFieldsFrom(methodPick),
          holdMaxDays,
        },
        broker: execMode,
        orderType,
        limitPrice: orderType === 'LMT' ? overlay.entry : null,
        action: card.direction === 'Bullish' ? 'BUY' : 'SELL',
        addPosition,
        earningsVeto,
      });
      // A placed order, or one whose status is unknown after a confirmed save,
      // disables the buttons: a second click could duplicate a live order.
      if (outcome.kind === 'placed' || (outcome.kind === 'unknown' && outcome.qty != null)) {
        const sizedLine = outcome.resizedFrom != null
          ? ` Portfolio sized it to ${outcome.qty} shares; the order was sent for ${outcome.qty}.`
          : '';
        setOrderId(outcome.kind === 'placed' ? outcome.orderId : 'UNKNOWN');
        setOrderMsg(outcome.kind === 'placed'
          ? { text: `Order placed — ID: ${outcome.orderId}.${sizedLine}`, tone: 'pass' }
          : { text: `${outcome.message}${sizedLine}`, tone: 'caution' });
      } else {
        setErr(outcome.message);
      }
    } catch (e) {
      // Only pre-save work can throw here: nothing saved, no order sent.
      setErr(`No order was sent — ${String(e)}`);
    } finally {
      setPlacingType(null);
    }
  }

  async function onEstimate() {
    if (estimating || (executionIdentity && useScanStore.getState().stockExecution[executionIdentity]?.estimating)) return;
    estimateReq.current?.abort();
    const requestToken = executionIdentity ? (useScanStore.getState().stockExecution[executionIdentity]?.estimateRequestToken ?? 0) + 1 : 0;
    estimateToken.current = requestToken;
    if (executionIdentity) useScanStore.getState().patchStockExecution(executionIdentity, { estimateRequestToken: requestToken });
    const revision = executionIdentity ? useScanStore.getState().stockExecution[executionIdentity]?.estimateRevision ?? 0 : 0;
    const dependencyCurrent = () => !executionIdentity || (useScanStore.getState().isStockExecutionCurrent(executionIdentity) && (useScanStore.getState().stockExecution[executionIdentity]?.estimateRevision ?? 0) === revision && useScanStore.getState().stockExecution[executionIdentity]?.estimateRequestToken === requestToken);
    const ctrl = new AbortController();
    estimateReq.current = ctrl;
    setEstimating(true);
    setEstimateErr(null);
    try {
      const res = await api.getStockFirstPassage({
        symbol: card.symbol,
        direction: card.direction as Direction,
        horizon: _horizonEnum(scanHorizonLabel ?? undefined),
        strategy: card.strategy.strategy,
        // The EDITED overlay, not the pristine signal: the overlay is what the
        // user intends to trade, so it is what the probabilities must describe.
        stock_price: overlay.entry,
        stop_price: overlay.stop,
        targets: [overlay.t1, overlay.t2, overlay.t3],
        // `stock_score` is the 5-rule composite (trend / pullback / trigger /
        // event / vol), NOT a pure trend score — the parameter name is the
        // estimator's, inherited from the options path. It is the only 0-100
        // conviction number this card has, and the estimator uses it solely as a
        // drift scale (mu = sign * (score - 50) / 50 * max_drift_pct), so a
        // composite conviction is a defensible proxy. It is still a proxy.
        trend_score: card.stock_score,
      }, ctrl.signal);
      if (ctrl.signal.aborted || !dependencyCurrent()) return;
      setEstimate(res);
      setLatest({ identity: executionIdentity, method: 'monte_carlo' });
    } catch (e) {
      if (ctrl.signal.aborted || !dependencyCurrent()) return;
      setEstimateErr(String(e));
    } finally {
      if (estimateReq.current === ctrl) {
        estimateReq.current = null;
        if (dependencyCurrent()) setEstimating(false);
      }
    }
  }

  async function onArithmeticPlan() {
    if (planning || (executionIdentity && useScanStore.getState().stockExecution[executionIdentity]?.planning)) return;
    planReq.current?.abort();
    const requestToken = executionIdentity ? (useScanStore.getState().stockExecution[executionIdentity]?.planRequestToken ?? 0) + 1 : 0;
    planToken.current = requestToken;
    if (executionIdentity) useScanStore.getState().patchStockExecution(executionIdentity, { planRequestToken: requestToken });
    const revision = executionIdentity ? useScanStore.getState().stockExecution[executionIdentity]?.entryRevision ?? 0 : 0;
    const dependencyCurrent = () => !executionIdentity || (useScanStore.getState().isStockExecutionCurrent(executionIdentity) && (useScanStore.getState().stockExecution[executionIdentity]?.entryRevision ?? 0) === revision && useScanStore.getState().stockExecution[executionIdentity]?.planRequestToken === requestToken);
    const ctrl = new AbortController();
    planReq.current = ctrl;
    setPlanning(true);
    setPlanErr(null);
    try {
      const res = await api.getStockExitPlan({
        symbol: card.symbol,
        direction: card.direction as Direction,
        // The EDITED entry, same as the other two fetches: the overlay is what
        // the user intends to trade. Deliberately NOT overlay.stop — the plan
        // derives its own stop, and feeding it the card's would make it echo
        // the number it exists to offer an alternative to.
        entry_price: overlay.entry,
        horizon: _horizonEnum(scanHorizonLabel ?? undefined),
        strategy: card.strategy.strategy,
        // Same proxy, same caveat, as onEstimate's: the 5-rule composite is the
        // only 0-100 conviction number this card has, and the estimator uses it
        // solely as a drift scale.
        trend_score: card.stock_score,
      }, ctrl.signal);
      if (ctrl.signal.aborted || !dependencyCurrent()) return;
      setPlan(res);
      setLatest({ identity: executionIdentity, method: 'arithmetic' });
    } catch (e) {
      if (ctrl.signal.aborted || !dependencyCurrent()) return;
      setPlanErr(String(e));
    } finally {
      if (planReq.current === ctrl) {
        planReq.current = null;
        if (dependencyCurrent()) setPlanning(false);
      }
    }
  }

  async function onCheckStructure() {
    if (checkingStructure || (executionIdentity && useScanStore.getState().stockExecution[executionIdentity]?.checkingStructure)) return;
    structuralReq.current?.abort();
    const requestToken = executionIdentity ? (useScanStore.getState().stockExecution[executionIdentity]?.structuralRequestToken ?? 0) + 1 : 0;
    structuralToken.current = requestToken;
    if (executionIdentity) useScanStore.getState().patchStockExecution(executionIdentity, { structuralRequestToken: requestToken });
    const revision = executionIdentity ? useScanStore.getState().stockExecution[executionIdentity]?.structuralRevision ?? 0 : 0;
    const dependencyCurrent = () => !executionIdentity || (useScanStore.getState().isStockExecutionCurrent(executionIdentity) && (useScanStore.getState().stockExecution[executionIdentity]?.structuralRevision ?? 0) === revision && useScanStore.getState().stockExecution[executionIdentity]?.structuralRequestToken === requestToken);
    const ctrl = new AbortController();
    structuralReq.current = ctrl;
    setCheckingStructure(true);
    setStructuralErr(null);
    try {
      // The existing /api/contracts/structural-stop — instrument-agnostic despite
      // the legacy /contracts/ prefix (find_structural_stop takes only candles,
      // direction and a reference price). Deliberately NOT forked into an alias.
      const res = await api.getStructuralStop({
        symbol: card.symbol,
        direction: card.direction as Direction,
        stock_price: overlay.entry,
      }, ctrl.signal);
      if (ctrl.signal.aborted || !dependencyCurrent()) return;
      setStructural(
        res.available && res.price != null && res.price > 0
          ? { price: res.price, source: res.source, confidence: res.confidence, distancePct: res.distancePct }
          : null,
      );
      if (!res.available || res.price == null || res.price <= 0) {
        setStructuralErr('No structural level found on recent candles.');
      }
    } catch (e) {
      if (ctrl.signal.aborted || !dependencyCurrent()) return;
      setStructuralErr(String(e));
    } finally {
      if (structuralReq.current === ctrl) {
        structuralReq.current = null;
        if (dependencyCurrent()) setCheckingStructure(false);
      }
    }
  }

  async function onAddToPortfolio() {
    if (adding || added || queued || useStockOrderOwnershipStore.getState().bySymbol[card.symbol]) return; // guards against a double-click firing two adds
    // Phase G piece 5, build step 4 (§7.2, S2) — same gate `submit()` above
    // carries, belt-and-braces beside this button's own `disabled`.
    if (pickMissing) return;
    // stockPositionLevels() silently DROPS a target on the wrong side of entry —
    // a fat-fingered T1/T2/T3 (EditableField has no side check) would otherwise
    // lose that rung, and the shares allocated to it, from the sell-to-close
    // plan with no indication anything happened. Block and say exactly which
    // target(s), rather than silently truncating the ladder.
    const badTargets = invalidTargetRungs(overlay.entry, card.direction as Direction, [
      { price: overlay.t1 }, { price: overlay.t2 }, { price: overlay.t3 },
    ]);
    if (badTargets.length > 0) {
      const plural = badTargets.length > 1;
      setErr(
        `Target${plural ? 's' : ''} ${badTargets.map((p) => p.toFixed(2)).join(', ')} ` +
        `${plural ? 'are' : 'is'} on the wrong side of entry (${overlay.entry.toFixed(2)}) and ` +
        `would be dropped from the sell-to-close plan — fix before adding.`
      );
      return;
    }
    setAdding(true);
    setErr(null);
    setWarning(null);
    try {
      // The user's EDITED overlay is what gets persisted as the live stop/targets —
      // it is what they intend to trade, and it is what TP_HIT / STOP_REACHED will
      // fire on. The pristine signal rides along inside the snapshot for the audit
      // trail. stockPositionLevels() drops anything non-positive or on the wrong
      // side of entry, so a half-edited overlay can never send a 0 stop.
      const position = {
        ...buildPaperStockPosition(
          card.symbol, overlay.entry, overlay.shares, card.direction as Direction,
          stockCardSnapshotOf(card, scanHorizonLabel ?? 'Swing', {
            entry: overlay.entry,
            stop: overlay.stop,
            targets: [overlay.t1, overlay.t2, overlay.t3],
            shares: overlay.shares,
          }),
          {
            stop: overlay.stop,
            targets: [
              { price: overlay.t1, shares: overlay.sharesT1 },
              { price: overlay.t2, shares: overlay.sharesT2 },
              { price: overlay.t3, shares: overlay.sharesT3 },
            ],
            // Only ever set when the user explicitly ran "Check structure" — it
            // is a chart-level REFERENCE, not the risk basis (that stays
            // `stop`). This is what lets STRUCTURAL_STOP_BREACHED fire for a
            // stock position, which it never could before.
            structuralStop: structural?.price ?? null,
          },
        ),
        // Phase G (piece 5) — same confirmed send-path gap as submit() above.
        ...pickedFieldsFrom(methodPick),
        holdMaxDays,
      };
      const ownership = useStockOrderOwnershipStore.getState();
      if (!ownership.claim(card.symbol, { identity: executionIdentity, recId: position.recId, status: 'in-flight' })) return;
      let res;
      try { res = await addPosition(position); }
      catch (error) {
        const message = `Save status unknown — ${String(error)}`;
        ownership.finish(card.symbol, position.recId, 'unknown', message);
        setWarning(message); setQueued(true); return;
      }
      ownership.finish(card.symbol, position.recId,
        res.status === 'rejected' ? null : res.status === 'pending' ? 'unknown' : 'placed',
        res.status === 'pending' ? 'Queued — will sync automatically.'
          : res.status === 'rejected' ? res.detail ?? 'Portfolio rejected this position.'
          : res.adjustedQty != null && res.adjustedQty !== overlay.shares
            ? `Portfolio sized it to ${res.adjustedQty} shares (exposure limit).` : 'Added to research portfolio.');
      if (res.status === 'rejected') {
        setErr(res.detail ?? 'Portfolio rejected this position.');
        return;
      }
      if (res.status === 'pending') {
        // Optimistically added but not confirmed by the backend — syncFromBackend's
        // poll will retry. Show it as queued, NOT as saved, and block re-clicks
        // (the row is already in the store; another add would merge/duplicate).
        setQueued(true);
        return;
      }
      // STOCK-SENDS (§A4): the SHARES field must not be the only number on
      // screen when Portfolio stored a smaller one.
      if (res.adjustedQty != null && res.adjustedQty !== overlay.shares) {
        setWarning(`Portfolio sized it to ${res.adjustedQty} shares (exposure limit).`);
      }
      setAdded(true);
    } finally {
      setAdding(false);
    }
  }

  const rrT1 = rrAt(overlay.t1);
  const rrT2 = rrAt(overlay.t2);
  const rrT3 = rrAt(overlay.t3);

  const winTone = card.backtest.win_rate >= 0.5 ? 'pass' : 'caution';
  const bearishUnvalidated = isBearishUnvalidated(card.direction);

  return (
    <div className={position ? styles.workspace : styles.wrap} key={executionIdentity ?? card.symbol}>
      {position && <>
        <header data-presentation="stocks-v2" className={styles.identity} aria-label="Stock context">
          <div><Data size={24}>{card.symbol}</Data><Text size={14} weight={600}>{card.company}</Text><Text size={11} tone="secondary">{card.direction} · {card.strategy.strategy.replace(/_/g, ' ')}</Text></div>
          <div className={styles.identityBadges}><ConfidenceBadge confidence={card.confidence} title={card.confidence_text ?? undefined} /><StatusBadge status={card.stock_status} tooltip={stockStatusTooltip(card.stock_status, card.stock_score)} /></div>
          <Text size={12} tone="secondary">Now: {fetchingSpot ? 'Loading…' : spotPrice != null ? `$${spotPrice.toFixed(2)}` : '—'}</Text>
          <Text size={12} tone="secondary">Scan price: {Number.isFinite(card.price) ? `$${card.price.toFixed(2)}` : 'Unavailable'}</Text>
          <Text size={12} tone="secondary">Stock score: {Number.isFinite(card.stock_score) ? `${card.stock_score} / 100` : 'Unavailable'}</Text>
          <Text size={12} tone="secondary">{recordedRequest?.horizon
            ? `Recorded horizon: ${recordedRequest.horizon}${recordedRequest.hold_max_days != null ? ` · hold ${recordedRequest.hold_max_days} days` : ''}`
            : 'Recorded horizon unavailable'}</Text>
          <div className={styles.actionRow}>        <a
          href={buildCandidateChartHref(card, 'stocks')}
          target="_blank"
          rel="noopener noreferrer"
          className={styles.actionBtn}
        >
          <Text size={12}>View Chart</Text>
        </a>
        <button
          type="button"
          className={styles.actionBtn}
          onClick={() => (pinned ? removeBasket(card.symbol) : addToBasket(card))}
        >
          <Text size={12}>{pinned ? 'Unpin from Basket' : 'Pin to Basket'}</Text>
        </button>
</div>
        </header>
        <section id="market-sentiment"><MarketSentiment s={card.sentiment} compact /></section>
        <nav aria-label="Position sections" className={styles.sectionLinks}>
          <a href="#initial-targets">Initial strategy targets</a><a href="#order-exits">Order &amp; exits</a><a href="#calculations">Calculations</a><a href="#qualification">Qualification</a><a href="#decision">Your decision</a><a href="#race">Which comes first</a><a href="#market-sentiment">Market sentiment</a><a href="#fundamentals">Fundamentals</a>
        </nav>
        <details className={styles.help}><summary>How this page works</summary><Text size={12}>Review the order and evidence, calculate a second opinion, then pick an exit method. Saving and sending use your existing edited order. Risk limits require server validation.</Text></details>
      </>}
      <PositionGroup active={position} className={styles.workspaceNotes}>
      <Text size={12} tone="caution">{bearishUnvalidated ? BEARISH_UNVALIDATED_MESSAGE : stockExecutionBlock()}</Text>
      {earningsVeto && <Text size={12} tone="reject">{EARNINGS_VETO_MESSAGE}</Text>}
      {!position && <Text size={12} tone="secondary">Now: {fetchingSpot ? 'Loading…' : spotPrice != null ? `$${spotPrice.toFixed(2)}` : '—'}</Text>}

      {orderOwnership && !added && !queued && !warning && <Text size={12} tone="caution">{orderOwnership.message ?? `${card.symbol}: stock send in flight — do not resend.`}</Text>}
      </PositionGroup>
      {position && <section id="fundamentals"><FundamentalHealthCard f={card.fundamentals} compact /></section>}
      {position && <InitialStrategyTargets card={card} shares={overlay.shares} />}
      {position && <section className={styles.latest} aria-label="Latest calculation">
        <Text size={11} tone="dim">Latest calculation</Text>
        {!latest || latest.identity !== executionIdentity ? <Text size={12}>Calculation chronology unavailable</Text>
          : !(latest.method === 'arithmetic' ? plan : estimate) ? <Text size={12}>Latest result unavailable — recalculate</Text>
          : <><Text size={12}>Latest: {latest.method === 'arithmetic' ? 'Arithmetic' : 'Monte Carlo'}</Text>
            {latest.method === 'arithmetic' && plan && <Data size={12}>Stop {plan.stop.price.toFixed(2)} · risk/share {plan.stop.riskPerShare.toFixed(2)} · {plan.horizonDays} trading days</Data>}
            {latest.method === 'monte_carlo' && estimate && <Data size={12}>Stop {overlay.stop.toFixed(2)} · {(estimate.invalidation.probability * 100).toFixed(0)}% · {estimate.horizonDays} trading days</Data>}
            {(latest.method === 'arithmetic' ? plan?.targets : estimate?.targets)?.map((t, i) => <Data key={i} size={12}>T{i + 1} {t.price.toFixed(2)} · {(t.probability * 100).toFixed(0)}%{t.expectedDays != null ? ` · ${medianTradingDays(t.expectedDays)}` : ' · unlikely'}</Data>)}</>}
      </section>}
      <PositionGroup active={position} className={styles.workspaceColumns}>
      <PositionGroup active={position} className={styles.workspaceMain}>
      <PositionGroup active={position} tag="section" id="order-exits" className={styles.workspaceCard}>
      {position && <h3>Order &amp; exits</h3>}
      {/* Section 1 — Sizing grid, Row 1 */}
      <div className={styles.grid4}>
        <EditableField label="ENTRY"    value={overlay.entry} onChange={(v) => patch({ entry: v })} />
        <EditableField label="STOP"     value={overlay.stop}  onChange={(v) => patch({ stop: v })}  tone="reject" />
        {position ? <EditableField label="SHARES" value={overlay.shares}
          onChange={(v) => patch({ shares: Math.max(1, Math.round(v)) })} integer />
          : <EditableField label="T1 TARGET" value={overlay.t1} onChange={(v) => patch({ t1: v })} tone="pass" />}
        <div className={styles.editCell}>
          {position ? <><Text size={10} tone="dim">WIN %</Text>
            <Data size={14} weight={500} tone={winTone} title={winRateTooltip(card.backtest.win_rate, 0.5)}>
              {(card.backtest.win_rate * 100).toFixed(0)}%
            </Data></> : <><Text size={10} tone="dim">R:R AT T1</Text>
            <Data size={14} weight={500}>{rrT1.toFixed(1)}×</Data></>}
        </div>
      </div>

      {position && <section aria-label="Execution risk" className={styles.executionRisk}>
        <div className={styles.riskGrid}>
          <div><Text size={11} tone="dim">Position value</Text><Data size={14}>{executionMoney(positionValue)}</Data></div>
          <div><Text size={11} tone="dim">Execution risk / share</Text><Data size={14} tone="reject">{executionMoney(executionRiskPerShare)}</Data></div>
          <div><Text size={11} tone="dim">Execution risk / position</Text><Data size={14} tone="reject">{executionMoney(executionRiskDollars)}</Data></div>
        </div>
        <Text size={11} tone="secondary">Entered {overlay.shares} shares · current {card.direction.toLowerCase()} entry and execution stop · before costs</Text>
        {executionStop == null && <Text size={12} tone="reject">Execution stop invalid — use a positive stop {card.direction === 'Bullish' ? 'below' : 'above'} the entered entry.</Text>}
      </section>}
      {/* Section 1 — Sizing grid, Row 2 (embedded presentation) */}
      {!position && <div className={styles.grid4}>
        <EditableField
          label="SHARES"
          value={overlay.shares}
          onChange={(v) => patch({ shares: Math.max(1, Math.round(v)) })}
          integer
        />
        <div className={styles.editCell}>
          <Text size={10} tone="dim">RISK $</Text>
          <Data size={14} weight={500} tone="reject">{riskDollars.toFixed(0)}</Data>
        </div>
        <div className={styles.editCell}>
          <Text size={10} tone="dim">SIZE $</Text>
          <Data size={14} weight={500}>{sizeDollars.toFixed(0)}</Data>
        </div>
        <div className={styles.editCell}>
          <Text size={10} tone="dim">WIN %</Text>
          <Data size={14} weight={500} tone={winTone} title={winRateTooltip(card.backtest.win_rate, 0.5)}>
            {(card.backtest.win_rate * 100).toFixed(0)}%
          </Data>
        </div>
      </div>}

      {/* Section 2 — Sell-to-Close plan (T1 / T2 / T3) */}
      <PositionGroup active={position} tag="details" className={styles.exitEditors}>
      {position && <summary>Edit T1 / T2 / T3 and share allocations</summary>}
      <div className={styles.targetsSection}>
        <div className={styles.targetsHeading}>
          <Text size={11} tone="dim">SELL-TO-CLOSE PLAN</Text>
        </div>

        {([
          {
            id: 'T1',
            price: overlay.t1,
            onPrice: (v: number) => patch({ t1: v }),
            shares: overlay.sharesT1,
            onShares: (v: number) => patch({ sharesT1: v }),
            rr: rrT1,
          },
          {
            id: 'T2',
            price: overlay.t2,
            onPrice: (v: number) => patch({ t2: v }),
            shares: overlay.sharesT2,
            onShares: (v: number) => patch({ sharesT2: v }),
            rr: rrT2,
          },
          {
            id: 'T3',
            price: overlay.t3,
            onPrice: (v: number) => patch({ t3: v }),
            shares: overlay.sharesT3,
            onShares: (v: number) => patch({ sharesT3: v }),
            rr: rrT3,
          },
        ] as const).map(({ id, price, onPrice, shares: sh, onShares, rr }) => {
          const profitPct = overlay.entry > 0
            ? (card.direction === 'Bullish'
                ? (price - overlay.entry) / overlay.entry
                : (overlay.entry - price) / overlay.entry) * 100
            : 0;
          const targetInputValid = Number.isFinite(price) && price > 0
            && Number.isFinite(overlay.entry) && overlay.entry > 0;
          const executionRR = executionRiskPerShare != null && targetInputValid
            ? (card.direction === 'Bullish' ? price - overlay.entry : overlay.entry - price) / executionRiskPerShare : null;
          const displayedRR = position ? executionRR : rr;
          const rrAvailable = !position || (displayedRR != null && Number.isFinite(displayedRR));
          const retPct = profitPct.toFixed(1);
          return (
            <div key={id} className={styles.targetRow}>
              <div className={styles.targetLabel}>
                <Text size={12} weight={500}>{id}</Text>
              </div>
              <div className={styles.targetValues}>
                <EditableField label={position ? `${id} TARGET` : ''} value={price} onChange={onPrice} />
                <Data size={12} tone={!rrAvailable ? 'dim' : displayedRR! >= 1.5 ? 'pass' : displayedRR! >= 1 ? 'caution' : 'reject'}>
                  {rrAvailable ? `${displayedRR!.toFixed(1)}×` : 'Unavailable'}
                </Data>
                <Data size={12} tone={position && !targetInputValid ? 'dim' : profitPct > 0 ? 'pass' : 'reject'}>
                  {position && !targetInputValid ? 'Unavailable' : `${retPct}%`}
                </Data>
                <EditableField
                  label={position ? `${id} SHARES` : ''}
                  value={sh}
                  onChange={(v) => onShares(Math.max(0, Math.round(v)))}
                  integer
                />
              </div>
            </div>
          );
        })}
      </div>

      </PositionGroup>
      {position && err?.includes('wrong side of entry') && <Text size={12} tone="reject">{err}</Text>}
      {position && <section id="structure-stops" aria-label="Structure & Stops" className={styles.targetsSection}>
        <h3>Structure &amp; Stops</h3>
        <div className={styles.stopComparison}>
          <section aria-label="Entered execution stop" className={styles.stopBasis}>
            <Text size={12}>Entered execution stop</Text>
            <div><Text size={11} tone="dim">Stop price</Text><Data size={14}>{executionMoney(executionStop)}</Data></div>
            <div><Text size={11} tone="dim">Risk / share</Text><Data size={14} tone="reject">{executionMoney(executionRiskPerShare)}</Data></div>
            <div><Text size={11} tone="dim">Loss for entered {overlay.shares} shares</Text><Data size={14} tone="reject">{executionMoney(executionRiskDollars)}</Data></div>
            <Text size={11} tone="secondary">Current entered entry and execution stop · before costs</Text>
            {executionStop == null && <Text size={11} tone="reject">Execution stop invalid — use a positive stop {card.direction === 'Bullish' ? 'below' : 'above'} the entered entry.</Text>}
          </section>
          {plan ? <section aria-label="Arithmetic final stop" className={styles.stopBasis}>
            <Text size={12}>Arithmetic final stop</Text>
            <div><Text size={11} tone="dim">Stop price</Text><Data size={14}>{executionMoney(plan.stop.price)}</Data></div>
            <div><Text size={11} tone="dim">Risk / share</Text><Data size={14} tone="reject">{executionMoney(plan.stop.riskPerShare)}</Data></div>
            <div><Text size={11} tone="dim">Loss for entered {overlay.shares} shares</Text><Data size={14} tone="reject">{executionMoney(enteredSharesValid ? plan.stop.riskPerShare * overlay.shares : null)}</Data></div>
            <div><Text size={11} tone="dim">Loss for suggested {plan.recommendedShares != null ? `${plan.recommendedShares} ` : ''}shares</Text><Data size={14} tone="reject">{executionMoney(plan.recommendedShares != null && Number.isFinite(plan.recommendedShares) && plan.recommendedShares >= 0 ? plan.stop.riskPerShare * plan.recommendedShares : null)}</Data></div>
            <Text size={11} tone="secondary">Returned Arithmetic stop and risk / share · before costs</Text>
            <div><Text size={11} tone="dim">Final stop source</Text><Text size={11}>{plan.stop.source}</Text></div>
            <div><Text size={11} tone="dim">Structural candidate</Text><Data size={12}>{executionMoney(plan.stop.structuralPrice)}</Data><Text size={11}>{plan.stop.structuralSource ?? 'Unavailable'}</Text></div>
            <div><Text size={11} tone="dim">Structural confidence</Text><Data size={12}>{plan.stop.structuralConfidence ?? 'Unavailable'}</Data></div>
            <div><Text size={11} tone="dim">ATR(14)</Text><Data size={12}>{executionMoney(plan.atr)}</Data></div>
            <div><Text size={11} tone="dim">ATR floor</Text><Data size={12}>{executionMoney(plan.stop.atrFloorPrice)}</Data></div>
            <div><Text size={11} tone="dim">Candidate / floor distance</Text><Data size={12}>{executionMoney(plan.stop.distanceDollar)}</Data></div>
            <Text size={11} tone="secondary">{stopJustification(plan.stop)}</Text>
          </section> : <div className={styles.stopBasis}>
            <Text size={12}>Arithmetic final stop</Text>
            <Text size={11} tone="secondary">{planning ? 'Computing Arithmetic final stop…' : 'Not computed or stale — run Arithmetic plan for the current inputs.'}</Text>
          </div>}
        </div>
        {planErr && <Text size={11} tone="reject">Arithmetic calculation failed: {planErr}</Text>}
        <Text size={11} tone="secondary">Checking structure, computing or selecting Arithmetic does not change the entered execution stop. The structural candidate is a reference; only the returned Arithmetic final stop defines that plan&apos;s risk.</Text>
        <Text size={11} tone="dim">{checkingStructure ? 'Checking current structure…' : !structural && !structuralErr ? 'Structural check not computed or stale — check the current entry.' : 'Structural check result'}</Text>          <button
            type="button"
            className={styles.actionBtn}
            onClick={onCheckStructure}
            disabled={checkingStructure}
          >
            <Text size={12}>{checkingStructure ? 'Checking…' : 'Check structure'}</Text>
          </button>        {structuralErr && <Text size={11} tone="caution">{structuralErr}</Text>}

        {structural && (
          <div className={styles.estimateBlock}>
            <div className={styles.estimateRow}>
              <Text size={11} tone="dim">STRUCTURAL</Text>
              <Data size={12}>{structural.price.toFixed(2)}</Data>
              {structural.distancePct != null && (
                // Same "(N% away)" format the options TradeCard already shows next
                // to its own structural-stop price — distancePct was captured here
                // but had never actually been rendered.
                <Text size={11} tone="dim">({structural.distancePct.toFixed(1)}% away)</Text>
              )}
              <Text size={11} tone="dim">{structural.source ?? '—'}</Text>
              <Text size={11} tone="dim">Confidence: {structural.confidence ?? 'Unavailable'}</Text>
              <Data size={12} tone="dim">
                {/* Guarded: a structural level that lands exactly on entry would
                    otherwise divide by zero and render Infinity. */}
                {Math.abs(overlay.entry - structural.price) > 0
                  ? `${(Math.abs(overlay.t1 - overlay.entry) / Math.abs(overlay.entry - structural.price)).toFixed(1)}× R:R`
                  : '—'}
              </Data>
            </div>
            <Text size={11} tone="dim">
              Reference level only — the risk basis stays your STOP. Saved with the
              position so STRUCTURAL STOP BREACHED can fire.
            </Text>
          </div>
        )}</section>}
      </PositionGroup>
      <PositionGroup active={position} tag="section" id="calculations" className={styles.workspaceMain}>
      {position && <h3>Calculations</h3>}
      <MethodEvidenceStack position={position} original={<>
        <h4>Original ladder</h4>
        <Text size={12} tone="secondary">Source: editable execution targets · entry {executionMoney(overlay.entry)} · execution stop {executionMoney(executionStop)}</Text>
        <div className={styles.initialTableWrap}><table className={styles.initialTable}>
          <thead><tr>{['Target', 'Stock price', `Full exit / ${overlay.shares} entered shares`, 'Allocated shares', 'Allocated outcome', 'Reward / share', 'R:R'].map(label => <th key={label} scope="col"><Text size={11} tone="dim">{label}</Text></th>)}</tr></thead>
          <tbody>{[
            { label: 'T1', price: overlay.t1, shares: overlay.sharesT1 },
            { label: 'T2', price: overlay.t2, shares: overlay.sharesT2 },
            { label: 'T3', price: overlay.t3, shares: overlay.sharesT3 },
          ].map(t => {
            const reward = Number.isFinite(overlay.entry) && overlay.entry > 0 && Number.isFinite(t.price) && t.price > 0
              ? (card.direction === 'Bullish' ? t.price - overlay.entry : overlay.entry - t.price) : null;
            const rr = reward != null && executionRiskPerShare != null ? reward / executionRiskPerShare : null;
            return <tr key={t.label}>
              <th scope="row"><Text size={12}>{t.label}</Text></th>
              <td><Data size={14}>{executionMoney(t.price)}</Data></td>
              <td><Data size={14}>{executionMoney(reward != null && enteredSharesValid ? reward * overlay.shares : null)}</Data></td>
              <td><Data size={12}>{Number.isFinite(t.shares) && t.shares >= 0 ? t.shares : 'Unavailable'}</Data></td>
              <td><Data size={12}>{executionMoney(reward != null && Number.isFinite(t.shares) && t.shares >= 0 ? reward * t.shares : null)}</Data></td>
              <td><Data size={12}>{executionMoney(reward)}</Data></td>
              <td><Data size={12}>{rr != null && Number.isFinite(rr) ? `${rr.toFixed(2)}×` : 'Unavailable'}</Data></td>
            </tr>;
          })}</tbody>
        </table></div>
        <Text size={11} tone="secondary">Each row is a separate full-exit scenario before costs; do not add full exits together. Allocated outcomes use the existing entered rung allocations. No probability or time estimate for this method.</Text>
        <Text size={11} tone="dim">Original selects the editable ladder; the initial scanned strategy targets above remain separate.</Text>
      </>} monteCarlo={<>
      {/* Section 2b — On-demand analytics: first-passage estimate + structural stop.
          Both are explicit user actions, never fired by the scan — the Monte
          Carlo is CPU work and the structural lookup is a candle fetch. */}
      <div className={position ? styles.workspaceCard : styles.targetsSection}>
        <div className={styles.targetsHeading}>
          <>{position ? <h4>Monte Carlo stock estimate</h4> : <Text size={11} tone="dim">PROBABILITY &amp; STRUCTURE</Text>}</>
        </div>

        <div className={styles.actionRow}>
          <button
            type="button"
            className={styles.actionBtn}
            onClick={onEstimate}
            disabled={estimating}
          >
            <Text size={12}>{estimating ? 'Estimating…' : 'Estimate'}</Text>
          </button>
          {!position && <>          <button
            type="button"
            className={styles.actionBtn}
            onClick={onCheckStructure}
            disabled={checkingStructure}
          >
            <Text size={12}>{checkingStructure ? 'Checking…' : 'Check structure'}</Text>
          </button></>}
        </div>

        {position && <Text size={12} tone="secondary">GBM stock simulation · editable execution entry / stop / targets. Execution entry {executionMoney(overlay.entry)} · stop {executionMoney(executionStop)}</Text>}
        {position && !estimate && <Text size={11} tone="dim">{estimating ? 'Estimating current inputs…' : 'Not computed or stale — run Estimate for the current inputs.'}</Text>}
        {estimateErr && <Text size={11} tone="reject">{estimateErr}</Text>}

        {estimate && (
          <div className={styles.estimateBlock}>
            {/* A probability without its window is meaningless, so the window is
                never optional chrome. Trading days, not calendar days — the
                window comes from confidence_backtest.n_days, which counts bars. */}
            <Text size={11} tone="dim">
              Chance of reaching each target within {estimate.horizonDays} trading days
            </Text>
            {position && <Text size={11} tone="secondary">Independent reach probabilities; the same path can also hit the stop. Conditional median time among paths that reach each barrier, regardless of which barrier is hit first. Full-exit outcomes for {overlay.shares} entered shares, before costs.</Text>}
            {estimate.targets.map((t, i) => (
              <div key={`fp-${i}`} className={position ? styles.methodTargetRow : styles.estimateRow}>
                <Text size={11} tone="dim">T{i + 1}</Text>
                <Data size={12}>{t.price.toFixed(2)}</Data>
                {position && <div><Text size={10} tone="dim">Full exit / {overlay.shares} shares</Text><Data size={14}>{executionMoney(enteredSharesValid && Number.isFinite(overlay.entry) && overlay.entry > 0 ? (card.direction === 'Bullish' ? t.price - overlay.entry : overlay.entry - t.price) * overlay.shares : null)}</Data></div>}
                <Data size={12} tone={t.probability >= 0.5 ? 'pass' : t.probability >= 0.25 ? 'caution' : 'reject'}>
                  {(t.probability * 100).toFixed(0)}%
                </Data>
                <Data size={12} tone="dim">
                  {position ? medianTradingDays(t.expectedDays) : t.expectedDays != null ? `~${t.expectedDays.toFixed(0)}d` : 'unlikely'}
                </Data>
              </div>
            ))}
            <div className={styles.estimateRow}>
              <Text size={11} tone="dim">STOP</Text>
              <Data size={12}>{overlay.stop.toFixed(2)}</Data>
              <Data size={12} tone={estimate.invalidation.probability >= 0.5 ? 'reject' : 'caution'}>
                {(estimate.invalidation.probability * 100).toFixed(0)}%
              </Data>
              <Data size={12} tone="dim">
                {position ? medianTradingDays(estimate.invalidation.expectedDays) : estimate.invalidation.expectedDays != null
                  ? `~${estimate.invalidation.expectedDays.toFixed(0)}d`
                  : 'unlikely'}
              </Data>
            </div>
            {estimate.modelCaveat && (
              <Text size={11} tone="caution">{estimate.modelCaveat}</Text>
            )}
          </div>
        )}

        {!position && <>        {structuralErr && <Text size={11} tone="caution">{structuralErr}</Text>}

        {structural && (
          <div className={styles.estimateBlock}>
            <div className={styles.estimateRow}>
              <Text size={11} tone="dim">STRUCTURAL</Text>
              <Data size={12}>{structural.price.toFixed(2)}</Data>
              {structural.distancePct != null && (
                // Same "(N% away)" format the options TradeCard already shows next
                // to its own structural-stop price — distancePct was captured here
                // but had never actually been rendered.
                <Text size={11} tone="dim">({structural.distancePct.toFixed(1)}% away)</Text>
              )}
              <Text size={11} tone="dim">{structural.source ?? '—'}</Text>
              <Data size={12} tone="dim">
                {/* Guarded: a structural level that lands exactly on entry would
                    otherwise divide by zero and render Infinity. */}
                {Math.abs(overlay.entry - structural.price) > 0
                  ? `${(Math.abs(overlay.t1 - overlay.entry) / Math.abs(overlay.entry - structural.price)).toFixed(1)}× R:R`
                  : '—'}
              </Data>
            </div>
            <Text size={11} tone="dim">
              Reference level only — the risk basis stays your STOP. Saved with the
              position so STRUCTURAL STOP BREACHED can fire.
            </Text>
          </div>
        )}</>}
      </div>
      </>} arithmetic={<>
      {/* Section 2c — ARITHMETIC PROFIT TARGET (piece 6, the stocks arithmetic
          plan). The options card's section with every option row removed:
          no contract price, no pricing model, no IV, no delta, no premium stop
          and NO STOP-COST BADGE. A stock's stop cost is exact — riskPerShare,
          times however many shares — so the options gate's question does not
          arise, and a badge that looked like it would be answering a different
          one. Sizing off the risk budget below is what serves that protective
          role here.

          Click-gated like the two fetches above, and for the same reason: a
          candle fetch plus a Monte Carlo is not scan work. */}
      <div className={position ? styles.workspaceCard : styles.targetsSection}>
        <div className={styles.targetsHeading}>
          <>{position ? <h4>Arithmetic</h4> : <Text size={11} tone="dim">ARITHMETIC PROFIT TARGET</Text>}</>
        </div>

        <div className={styles.actionRow}>
          <button
            type="button"
            className={styles.actionBtn}
            onClick={onArithmeticPlan}
            disabled={planning}
          >
            <Text size={12}>{planning ? 'Computing…' : 'Arithmetic plan'}</Text>
          </button>
        </div>

        {position && !plan && <Text size={11} tone="dim">{planning ? 'Computing current inputs…' : 'Not computed or stale — run Arithmetic plan for the current inputs.'}</Text>}
        {planErr && <Text size={11} tone="reject">{planErr}</Text>}

        {plan && (
          <div className={styles.estimateBlock}>
            {position && <Text size={11} tone="secondary">GBM stock simulation · {plan.horizonDays} {plan.daysBasis} days. All target rows share the returned final stop {executionMoney(plan.stop.price)}. Independent reach probabilities; conditional median time among paths that reach each barrier, regardless of which barrier is hit first. Full-exit outcomes for {overlay.shares} entered shares, before costs.</Text>}
            {/* ── The stop row ─────────────────────────────────────────── */}
            <div className={styles.planRow}>
              <Text size={11} tone="dim">STOP</Text>
              <Data size={13}>{plan.stop.price.toFixed(2)}</Data>
              <Text size={11} tone="dim">
                {plan.stop.source === 'structural'
                  ? `structural — ${plan.stop.structuralSource ?? 'level'}`
                  : 'widened to ATR floor'}
              </Text>
              <Data size={12} tone="dim">ATR(14) {plan.atr.toFixed(2)}</Data>
            </div>
            <Text size={10} tone="dim">{stopJustification(plan.stop)}</Text>

            <div className={styles.planRow}>
              <Text size={11} tone="dim">RISK/SHARE</Text>
              <Data size={13} tone="reject">{plan.stop.riskPerShare.toFixed(2)}</Data>
              {/* Spec 3.3 — the options card never reports this, and it is the
                  most decision-relevant number here. */}
              <Data size={12} tone={plan.stop.probability >= 0.5 ? 'reject' : 'caution'}>
                {(plan.stop.probability * 100).toFixed(0)}% reached
              </Data>
              <Data size={12} tone="dim">
                {position ? medianTradingDays(plan.stop.expectedDays) : plan.stop.expectedDays != null
                  ? `~${plan.stop.expectedDays.toFixed(0)} trading days`
                  : 'unlikely'}
              </Data>
            </div>

            {/* This plan's stop is a SECOND OPINION standing beside the card's,
                not a replacement for it — arming a stop per trade is piece 5,
                which does not exist yet. Say so wherever the two differ, rather
                than letting two stop prices sit on one card unexplained. */}
            {Math.abs(plan.stop.price - overlay.stop) >= 0.01 && (
              <Text size={10} tone="caution">
                The card&apos;s stop is ${overlay.stop.toFixed(2)} — this plan is a
                second opinion and does not change it. Risk and R:R above the fold
                still measure against the card&apos;s stop.
              </Text>
            )}

            {/* ── Target rows ──────────────────────────────────────────── */}
            {plan.targets.map((t, i) => (
              <div key={`plan-t-${i}`} className={styles.planTarget}>
                <div className={position ? styles.methodTargetRow : styles.planRow}>
                  <Text size={11} tone="dim">{t.rrRatio}R</Text>
                  <Data size={13} tone="pass">{t.price.toFixed(2)}</Data>
                  {position && <div><Text size={10} tone="dim">Full exit / {overlay.shares} shares</Text><Data size={14}>{executionMoney(enteredSharesValid ? t.rewardPerShare * overlay.shares : null)}</Data></div>}
                  <Data size={12} tone={t.probability >= 0.5 ? 'pass' : t.probability >= 0.25 ? 'caution' : 'reject'}>
                    {(t.probability * 100).toFixed(0)}% reached
                  </Data>
                  <Data size={12} tone="dim">
                    {position ? medianTradingDays(t.expectedDays) : t.expectedDays != null
                      ? `~${t.expectedDays.toFixed(0)} trading days`
                      : 'unlikely'}
                  </Data>
                </div>
                <div className={styles.planRow}>
                  <Text size={10} tone="dim">reward/share</Text>
                  <Data size={12}>{t.rewardPerShare.toFixed(2)}</Data>
                  <Text size={10} tone="dim">
                    {/* The arithmetic the user checks in his head. The backend
                        quantizes the stop to cents before building the target
                        off it, so this identity holds exactly on screen.

                        THE SIGN IS DIRECTION-DERIVED, never hardcoded: a
                        Bearish target is entry MINUS rr x risk, and a '+' here
                        printed '100.00 + 2 × 4.00 = 92.00' on every row of
                        every bearish scan — a false equation on the one row
                        whose entire purpose is being checkable. */}
                    {`${overlay.entry.toFixed(2)} ${card.direction === 'Bullish' ? '+' : '−'} ${t.rrRatio} × ${plan.stop.riskPerShare.toFixed(2)} = ${t.arithmeticPrice.toFixed(2)}`}
                  </Text>
                  <Text size={10} tone="dim">
                    {t.structuralPrice != null
                      ? `structure ${t.structuralPrice.toFixed(2)} · ${t.distanceDollar?.toFixed(2) ?? '—'} away · tol ${t.toleranceDollar.toFixed(2)}`
                      : `tol ${t.toleranceDollar.toFixed(2)}`}
                  </Text>
                </div>
                <Text size={10} tone={t.qualityGood ? 'dim' : 'caution'}>
                  {targetCompareLabel(targetCompareState(t))}
                  {!t.qualityGood && t.qualityReasons.includes('stop_widened')
                    ? ' Stop needed ATR widening.'
                    : ''}
                </Text>
              </div>
            ))}

            {/* ── Sizing ───────────────────────────────────────────────── */}
            <div className={styles.planRow}>
              <Text size={11} tone="dim">SHARES</Text>
              <Data size={13}>{plan.recommendedShares ?? '—'}</Data>
              <Text size={10} tone="dim">
                {`risk budget $${plan.riskBudget.toFixed(2)} ÷ $${plan.stop.riskPerShare.toFixed(2)}`}
              </Text>
              {plan.recommendedShares != null && (
                <Text size={10} tone="dim">
                  {`≈ $${(plan.recommendedShares * overlay.entry).toFixed(0)} position`}
                </Text>
              )}
            </div>

            {/* Concentration flag (SHARE-SIZING-CONCENTRATION-FLAG-2026-09-09).
                It sits directly under the SHARES row because the implied-notional
                line above already ships and is easy to skim past next to a bold
                share number. A FLAG, never a gate: Apply stays enabled below. */}
            {(() => {
              const c = concentrationFlag(
                plan.recommendedShares,
                overlay.entry,
                riskLimits.portfolioValue,
                // STOCK-SENDS (R2-2): the STOCK single-position cap, the one the
                // server judges a stock save against -- not the options 5%.
                riskLimits.maxSingleStockPositionPct,
              );
              if (!c) return null;
              return (
                <Text size={10} tone="caution">
                  Concentration: ≈${c.positionDollar.toFixed(0)} is{' '}
                  {c.positionPct.toFixed(1)}% of your ${riskLimits.portfolioValue.toFixed(0)}{' '}
                  account — over the {(riskLimits.maxSingleStockPositionPct * 100).toFixed(0)}%
                  {' '}single-position cap (${c.capDollar.toFixed(0)}, ≈{c.capShares} shares).
                  Sized by risk budget, as the plan intends. Nothing is blocked — your call.
                </Text>
              );
            })()}
            {/* `> 0` as well as non-null: the backend already refuses to call a
                floor of zero a size, and this is the second half of that same
                guard. Without it an "Apply 0 shares" button wrote shares: 0
                straight past the SHARES field's own clamp, into the order
                quantity and into the persisted position. */}
            {plan.recommendedShares != null && plan.recommendedShares > 0
              && plan.recommendedShares !== overlay.shares && (
              <div className={styles.actionRow}>
                <button
                  type="button"
                  className={styles.actionBtn}
                  onClick={() => {
                    // Narrowed inside the callback rather than asserted: the
                    // enclosing guard does not survive into the closure.
                    if (plan.recommendedShares != null) patch({ shares: plan.recommendedShares });
                  }}
                >
                  <Text size={11}>Apply {plan.recommendedShares} shares</Text>
                </button>
                {/* Sized against THIS plan's stop. If the card's stop differs,
                    the Risk figure above the fold will not equal the risk
                    budget — say which stop the number came from rather than
                    letting the two disagree silently. */}
                {Math.abs(plan.stop.price - overlay.stop) >= 0.01 && (
                  <Text size={10} tone="caution">
                    Sized for the ${plan.stop.price.toFixed(2)} stop above, not the
                    card&apos;s ${overlay.stop.toFixed(2)}.
                  </Text>
                )}
              </div>
            )}

            {/* ── The two-barrier race ─────────────────────────────────── */}
            {plan.race && (
              <div id={position ? 'race' : undefined} className={styles.planRace}>
                <Text size={10} tone="dim">
                  Which comes first, over {plan.horizonDays} trading days
                  ({plan.race.nPaths.toLocaleString()} simulated paths). These three
                  add to 100% because every path is counted once — unlike the
                  percentages above, which are each measured on their own.
                </Text>
                {position && <><h4>Which comes first</h4><Text size={11} tone="secondary">Target first / stock stop first / neither are exclusive outcomes. Conditional median time among paths where that barrier wins. Neither can end with a gain or loss; its terminal mean is the average ending stock price. Supporting evidence only.</Text><Text size={11} tone="dim">Race stock stop {executionMoney(plan.race.stopPrice)}</Text></>}
                {position && plan.race.outcomes.map((o, i) => <div key={`bar-${i}`} className={styles.raceDrawing} aria-label={`${card.direction} target ${o.targetPrice.toFixed(2)} race`}>
                  <Data size={12}>Target {o.targetPrice.toFixed(2)}</Data>
                  {[['Target', o.weightTarget], ['Stop', o.weightStop], ['Neither', o.weightNeither]].map(([label, weight]) => <label key={String(label)}><Text size={11}>{label}</Text><meter className={label === 'Target' ? styles.raceTarget : label === 'Stop' ? styles.raceStop : styles.raceNeither} min="0" max="1" value={Number(weight)} /><Data size={11} tone={label === 'Target' ? 'pass' : label === 'Stop' ? 'reject' : 'dim'}>{(Number(weight) * 100).toFixed(0)}%</Data></label>)}
                </div>)}
                {plan.race.outcomes.map((o, i) => (
                  <div key={`race-${i}`} className={styles.planRow}>
                    <Data size={11} tone="dim">{o.targetPrice.toFixed(2)}</Data>
                    {/* The ALLOCATED weights, never the raw p* — they are
                        allocated to hundredths so the three always sum to
                        exactly 100%. Re-rounding the raw values here is how a
                        row ends up printing 18 / 40 / 42 and adding to 99. */}
                    <Data size={12} tone="pass">
                      {position ? 'Target first' : 'target'} {(o.weightTarget * 100).toFixed(0)}%
                      {o.daysTarget != null ? position ? ` (${medianTradingDays(o.daysTarget)})` : ` (~${o.daysTarget.toFixed(0)}d)` : ''}
                    </Data>
                    <Data size={12} tone="reject">
                      {position ? 'Stock stop first' : 'stop'} {(o.weightStop * 100).toFixed(0)}%
                      {o.daysStop != null ? position ? ` (${medianTradingDays(o.daysStop)})` : ` (~${o.daysStop.toFixed(0)}d)` : ''}
                    </Data>
                    <Data size={12} tone="dim">
                      neither {(o.weightNeither * 100).toFixed(0)}%
                      {o.terminalMean != null ? ` (~$${o.terminalMean.toFixed(2)})` : ''}
                    </Data>
                  </div>
                ))}
              </div>
            )}

            {plan.modelCaveat && (
              <Text size={11} tone="caution">{plan.modelCaveat}</Text>
            )}

            <Text size={10} tone="dim">
              Independent of the other profit-target methods on this page; they can
              disagree.
            </Text>
          </div>
        )}
      </div>
      </>} />

      </PositionGroup>
      {position && <PositionEvidence card={card} pickMissing={pickMissing} earningsVeto={earningsVeto} ownership={orderOwnership?.status} />}
      </PositionGroup>
      {!position && <MarketSentiment s={card.sentiment} />}
      {!position && <FundamentalHealthCard f={card.fundamentals} />}
      <PositionGroup active={position} tag="aside" id="decision" className={styles.decision}>
      {position && <h3>Your decision</h3>}

      {/* Section 2d — Phase G piece 5 (§6.3): which exit method this trade is
           being taken on. Placed directly above the actions, after all three
           methods' numbers, because it is a decision ABOUT those numbers and
           the send paths are what read it. THREE options, no Barrier Race. */}
      <MethodPickSelector
        options={methodPickOptions}
        pick={methodPick}
        onChange={applyMethodPick}
      />

      {position && <section aria-label="Selected stock plan" className={styles.workspaceCard}>
        <h4>Selected stock plan</h4>
        {!methodPick || pickedMethodGone ? <Text size={12}>Choose a method</Text> : <>
          <div><Text size={11} tone="dim">Selected method / target</Text><Data size={14}>{pickedOption?.label} · {selectedTarget == null ? 'Choose a target' : selectedRow?.label ?? (selectedMatches.length > 1 ? 'Target row ambiguous' : 'Target row unavailable')}</Data></div>
          <div className={styles.riskGrid}>
            <div><Text size={11} tone="dim">Stock target</Text><Data size={14}>{executionMoney(selectedTarget)}</Data></div>
            <div><Text size={11} tone="dim">Calculation stop basis</Text><Data size={14}>{methodPick.method === 'arithmetic' ? 'Arithmetic final stop' : 'Current execution stop'} · {executionMoney(selectedCalculationStop)}</Data></div>
            <div><Text size={11} tone="dim">Execution stop</Text><Data size={14}>{executionMoney(executionStop)}</Data></div>
            <div><Text size={11} tone="dim">Entered quantity</Text><Data size={14}>{enteredSharesValid ? `${overlay.shares} shares` : 'Unavailable'}</Data></div>
            <div><Text size={11} tone="dim">Full-position outcome</Text><Data size={14}>{executionMoney(selectedOutcome)}</Data></div>
          </div>
          {selectedEvidence ? <>
            <div><Text size={11} tone="dim">Target hit probability</Text><Data size={14}>{Number.isFinite(selectedEvidence.probability) ? `${(selectedEvidence.probability * 100).toFixed(0)}%` : 'Unavailable'} within {selectedWindow} trading days</Data></div>
            <div><Text size={11} tone="dim">Median first-touch time</Text><Data size={14}>{selectedEvidence.expectedDays != null && Number.isFinite(selectedEvidence.expectedDays) ? `${selectedEvidence.expectedDays} trading days` : 'Unavailable'}</Data></div>
            <Text size={11} tone="secondary">Independent target hit probability within the simulated window; the same path can also hit the stop. Time is the median first-touch time among paths that reach the target, using 1/252-year trading days.</Text>
          </> : <Text size={11} tone="dim">Probability and time unavailable — no uniquely matching current calculation.</Text>}
          <Text size={11} tone="secondary">{card.direction} full exit at the selected target, before costs, using entered shares. Selection records intent and does not apply a stop, target or share change.</Text>
        </>}
      </section>}

      {position && <h3>Execution</h3>}
      {/* Section 3 — Action buttons */}
      <div className={styles.actionRow}>
        {!position && <>        <a
          href={buildCandidateChartHref(card, 'stocks')}
          target="_blank"
          rel="noopener noreferrer"
          className={styles.actionBtn}
        >
          <Text size={12}>View Chart</Text>
        </a>
        <button
          type="button"
          className={styles.actionBtn}
          onClick={() => (pinned ? removeBasket(card.symbol) : addToBasket(card))}
        >
          <Text size={12}>{pinned ? 'Unpin from Basket' : 'Pin to Basket'}</Text>
        </button>
</>}
        <button
          type="button"
          className={styles.actionBtn}
          onClick={onAddToPortfolio}
          disabled={added || adding || queued || !!orderOwnership || pickMissing}
          title={pickMissing ? MISSING_METHOD_PICK_TITLE : undefined}
        >
          <Text size={12}>
            {added ? 'Added to Portfolio' : queued ? 'Queued — will sync' : adding ? 'Adding…' : 'Add to Portfolio'}
          </Text>
        </button>
      </div>
      {pickMissing && (
        <Text size={11} tone="reject">
          {clearedPickMessage(clearedPickMethod) ?? MISSING_METHOD_PICK_MESSAGE}
        </Text>
      )}

      {/* Section 4 — Broker mode selector */}
      <div className={styles.modeRow}>
        {([
          ['recommendation', 'Recommendation', true],
          ['ibkr_paper',    'IBKR Paper',      ibkrConfigured],
          ['tradier_paper', 'Tradier Paper',   tradierConfigured],
          ['alpaca_paper',  'Alpaca Paper',    alpacaConfigured],
          ['tastytrade_paper', 'Tastytrade Paper', tastytradeConfigured],
        ] as Array<[ExecMode, string, boolean]>).map(([mode, label, ok]) => (
          <button
            key={mode}
            type="button"
            className={`${styles.modeBtn} ${execMode === mode ? styles.modeBtnActive : ''}`}
            disabled={!ok}
            title={!ok ? 'Not configured — Settings → Brokers' : undefined}
            onClick={() => setExecMode(mode)}
          >
            <Text size={12} weight={500}>{label}</Text>
          </button>
        ))}
      </div>

      {/* Section 5 — Order buttons */}
      {execMode !== 'recommendation' && (
        <div className={styles.actionRow}>
          <button
            type="button"
            className={styles.actionBtn}
            onClick={() => submit('LMT')}
            disabled={placingType !== null || orderId !== null || pickMissing || bearishUnvalidated || earningsVeto}
            title={bearishUnvalidated ? BEARISH_UNVALIDATED_MESSAGE : earningsVeto ? EARNINGS_VETO_MESSAGE : pickMissing ? MISSING_METHOD_PICK_TITLE : undefined}
          >
            <Text size={12}>{placingType === 'LMT' ? 'Placing…' : `Limit @ $${overlay.entry.toFixed(2)}`}</Text>
          </button>
          <button
            type="button"
            className={styles.actionBtn}
            onClick={() => submit('MKT')}
            disabled={placingType !== null || orderId !== null || pickMissing || bearishUnvalidated || earningsVeto}
            title={bearishUnvalidated ? BEARISH_UNVALIDATED_MESSAGE : earningsVeto ? EARNINGS_VETO_MESSAGE : pickMissing ? MISSING_METHOD_PICK_TITLE : undefined}
          >
            <Text size={12}>{placingType === 'MKT' ? 'Placing…' : 'Market Order'}</Text>
          </button>
        </div>
      )}

      {/* Section 6 — Order result / error */}
      {orderId && orderMsg && <Text size={12} tone={orderMsg.tone}>{orderMsg.text}</Text>}
      {err && !(position && err.includes('wrong side of entry')) && <Text size={12} tone="reject">{err}</Text>}
      {warning  && <Text size={12} tone="caution">{warning}</Text>}
      {queued   && <Text size={12} tone="caution">Queued — backend unreachable, will sync automatically.</Text>}

      {/* Section 7 — Auto-trade arm */}
      <PositionDisclosure active={position}>
      <StockAutoTradeArm
        symbol={card.symbol}
        strategyKey={strategyKey}
        direction={card.direction === 'Bullish' ? 'Bullish' : 'Bearish'}
        afterScanArmed={afterScanArmed ?? sessionAfterScanArmed}
        onAfterScanToggle={onAfterScanToggle ?? toggleAfterScanIntent}
      />
      </PositionDisclosure>
      {position && <PositionEvidence checklistOnly card={card} pickMissing={pickMissing} earningsVeto={earningsVeto} ownership={orderOwnership?.status} />}
      </PositionGroup>
      </PositionGroup>
    </div>
  );
}
