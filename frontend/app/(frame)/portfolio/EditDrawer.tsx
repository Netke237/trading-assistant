'use client';

/*
 * Portfolio position editor — split out of page.tsx (a Next.js App Router
 * page.tsx file may only export `default` plus a small whitelisted set of
 * route-config symbols; a stray `export function EditDrawer` there fails
 * Next.js's generated route-typing check under `tsc --noEmit`/`next build`,
 * even though a plain `tsc --noEmit` in a fresh checkout with no `.next`
 * build cache present won't yet have the generated file to catch it against).
 * This file is a normal sibling module, so it's free to export whatever its
 * tests need.
 */

import { useEffect, useRef, useState } from 'react';
import { Text, Data } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { SymbolNotes } from '@/components/molecules/SymbolNotes';
import { flushPendingPositionPatches, useIsSymbolHeld, usePortfolioStore } from '@/lib/portfolioStore';
import { rejectionMessage } from '@/lib/portfolioRejection';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { useRiskStore } from '@/lib/riskStore';
import { maxLossAtStop, resolveMaxLossLimitDollar, recommendedContractSize, formatRecommendedContractSizeRaw } from '@/lib/risk';
import { useSettingsStore } from '@/lib/settingsStore';
import { _horizonEnum } from '@/lib/analysisStore';
import { useAlertStore } from '@/lib/alertStore';
import { api } from '@/lib/api';
import { POSITION_ALERT_TYPES } from '@/types/domain';
import type { PortfolioPosition, AlertOverrides, PositionAlertType, TpMethod, PickedMethod, PickedStopBasis } from '@/types/domain';
import styles from './page.module.css';
import { resolvePremiumStopPct, hasOwnPremiumStopPct, percentStopFiringPrice, premiumStopIsSubCent, isShortStockPosition, formatPremiumStopPct, premiumStopPctLabel, PREMIUM_STOP_MIN_PCT, PREMIUM_STOP_MAX_PCT } from '@/lib/premiumStop';
import { TIME_STOP_DTE } from '@/lib/alertEngine';

/** `position.contract` for an option position is a backend-generated,
 *  pipe-delimited machine ID — "SYMBOL|STRIKE|EXPIRY|C/P" (see
 *  backend/app/routers/scan.py's `contract=f"{symbol}|{int(strike)}|..."`
 *  and backend/app/schemas/__init__.py's persistence-schema comment). Note
 *  the `int(strike)` truncation — this id is INTEGER-only, so it silently
 *  rounds down any fractional strike (e.g. 187.5 -> "187"). Every option
 *  position, old or new, has this format, unlike `tradeCardSnapshot.strike`,
 *  which is only populated for positions opened after this Monte Carlo
 *  feature shipped — so this is used strictly as the FALLBACK for
 *  pre-existing positions that predate the snapshot, never preferred over
 *  it. Callers must try `tradeCardSnapshot.strike` first. */
/** A complete positive price. A trailing dot is an unfinished number, not a price. */
function parsePositivePrice(raw: string): number | null {
  const t = raw.trim();
  if (!/^(?:\d+(?:\.\d+)?|\.\d+)$/.test(t)) return null;
  const n = Number(t);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function optionStrikeFromContract(contract: string): number | null {
  const parts = contract.split('|');
  if (parts.length !== 4) return null;
  const strike = Number(parts[1]);
  return Number.isFinite(strike) && strike > 0 ? strike : null;
}

export function EditDrawer({
  position,
  onClose,
  onChange,
  onRemove,
}: {
  position: PortfolioPosition;
  onClose: () => void;
  onChange: (patch: Partial<PortfolioPosition>) => void;
  onRemove: () => void;
}) {
  // Send any debounced-but-not-yet-fired edit immediately when this drawer
  // instance goes away — covers both its own close button and the parent
  // swapping `editing` to a different row (which unmounts this instance
  // without ever calling `onClose`).
  useEffect(() => {
    return () => { flushPendingPositionPatches(position.recId); };
  }, [position.recId]);

  // Computed, not assumed: this drawer only ever renders for a position
  // still present in `positions`, so `isHeld` is always true here — but
  // deriving it from the same gate the Chart sidebar uses (rather than
  // hardcoding `editable`) keeps all three note surfaces honoring one rule.
  const isHeld = useIsSymbolHeld(position.symbol);
  const isWatched = useWatchlistStore((s) => s.isWatched(position.symbol));

  const isStock = position.contract.endsWith('|STOCK');
  const snapshot = position.tradeCardSnapshot ?? {};
  // Carries each target's real id (T1/T2/…) alongside its price through both
  // filters below, so a partially-cleared position's remaining targets keep
  // their own labels in the estimate result instead of being renumbered from
  // whatever index they land at in the filtered array (see runEstimate's use
  // of allStockTargets/stockTargets below — T1 cleared, T2 still ahead must
  // render as "T2", not be relabeled "T1" just because it's now first in the
  // filtered list).
  const allStockTargets = position.targets
    .map((t) => ({ id: t.id, price: t.targetPrice ?? t.stockPrice }))
    .filter((t): t is { id: string | undefined; price: number } => typeof t.price === 'number' && t.price > 0);
  const allStockTargetPrices = allStockTargets.map((t) => t.price);
  // Only targets still AHEAD of the current price are meaningful to a
  // forward-looking Monte Carlo estimate — a target the price has already run
  // past is a normal winning-trade state (targets[].status isn't kept synced
  // to 'HIT' anywhere in this codebase; see the comment below), not evidence
  // the position's data is broken. Filtering here, rather than requiring
  // EVERY target ever set on the position to still be ahead, is what lets a
  // partially-profitable position (T1 already cleared, T2 still ahead) keep
  // estimating against its remaining targets instead of the whole feature
  // going silently disabled the moment the first target is crossed.
  //
  // Labelled by the target's ORIGINAL 1-based position (T1, T2, ...), not by
  // its position within this filtered array — the backend response comes
  // back positionally, one entry per price actually sent, so relabelling
  // from T1 whenever an earlier target has been filtered out would show the
  // user's real T2 result under the label "T1".
  const pendingStockTargets = position.targets
    .map((t, idx) => ({ price: t.targetPrice ?? t.stockPrice, label: `T${idx + 1}` }))
    .filter((t): t is { price: number; label: string } => typeof t.price === 'number' && t.price > 0)
    .filter((t) => (position.direction === 'Bullish' ? t.price > position.currentPrice : t.price < position.currentPrice));
  const stockTargetPrices = pendingStockTargets.map((t) => t.price);
  // A stored strike of 0 (a corrupted snapshot) must not pass this `== null`
  // guard through to the backend, which rejects strike <= 0 with a raw 422
  // instead of the button simply going disabled.
  const optionStrike = (typeof snapshot.strike === 'number' && snapshot.strike > 0 ? snapshot.strike : null) ?? optionStrikeFromContract(position.contract);
  const optionTrend = (snapshot.stockBreakdown as { trend?: number } | undefined)?.trend;
  const defaultTargetPct = useSettingsStore((s) => s.targetProfitPct);
  // Piece 4 — the GLOBAL premium stop. Positions that carry their own value
  // override it; this is only the fallback, and what the editor labels
  // "(global)".
  const globalPremiumStopPct = useSettingsStore((s) => s.premiumStopPct);

  // Mirrors backend/app/routers/stock_scan.py's own directional validation for
  // /api/stocks/first-passage (the stop must be on the correct side of the
  // current price for the trade's direction) — a stop on the wrong side is a
  // genuine data problem (the position should have been stopped out already),
  // unlike a crossed target above, which is filtered out rather than treated
  // as invalid.
  const stockDirectionValid = isStock && position.stop
    ? position.direction === 'Bullish'
      ? position.stop < position.currentPrice
      : position.stop > position.currentPrice
    : true;

  // The explicit `> 0` checks below (stock: currentPrice, the underlying
  // price; option: currentPrice, the premium, AND currentStockPrice, the
  // underlying) mirror the backend's own `Field(..., gt=0)` on
  // `stock_price`/`premium` in the first-passage request schemas. A live
  // quote with no price sets the field to `0.0`, not null — `currentPrice`
  // via `quote.get("price") or 0.0` (portfolio.py), `currentStockPrice` via
  // `stock_prices.get(schema.symbol)` landing on a `0.0` from
  // `fetch_price_async` for a bad/halted quote — both real states for
  // illiquid/deep-OTM contracts, not hypotheticals, and both would otherwise
  // reach the backend as a raw 422 instead of the button going disabled.
  // `currentStockPrice`'s existing `== null` check alone let a `0` value
  // straight through, since `0 != null`. On the stock side this is mostly
  // "belt and suspenders": `stockDirectionValid` already rejects
  // `currentPrice = 0` for a Bullish position incidentally (a 0 price can
  // never be above a positive stop), and a Bearish position instead falls
  // through the empty-`stockTargetPrices` branch — but neither of those is
  // an intentional guard against this specific case, so it's checked
  // explicitly here too rather than relying on the incidental backstop.
  const estimateDisabled = isStock
    ? stockTargetPrices.length === 0 || !position.stop || !stockDirectionValid || !(position.currentPrice > 0)
    : optionStrike == null || !(position.currentStockPrice != null && position.currentStockPrice > 0) || !position.stop || !(position.currentPrice > 0);

  // Same AbortController pattern as StockPositionCard's onEstimate/estimateReq
  // (the template this section mirrors): abort a still-in-flight request when
  // the button is re-fired or this drawer instance goes away (closing the
  // drawer, or the parent switching `editing` to a different row), so a late
  // response for a request the user has already moved on from can never land.
  const estimateReq = useRef<AbortController | null>(null);
  useEffect(() => {
    return () => { estimateReq.current?.abort(); };
  }, [position.recId]);

  const [mcLoading, setMcLoading] = useState(false);
  const [mcError, setMcError] = useState<string | null>(null);
  const [mcResult, setMcResult] = useState<{
    targets: { label: string; price: number; probability: number; expectedDays: number | null }[];
    invalidation: { probability: number; expectedDays: number | null };
    horizonNote?: string;
    modelCaveat?: string | null;
  } | null>(null);

  // True once the user has explicitly edited the "Current price" EditField
  // in this drawer session since the last estimate — set ONLY by that
  // field's own onChange below, never derived by comparing mcResult's
  // captured price against position.currentPrice/currentStockPrice on every
  // render. A value-comparison approach was tried first and had to be
  // reverted: portfolioStore's syncFromBackend() re-enriches currentPrice/
  // currentStockPrice from the broker every 30s (see the "clear entirely"
  // effect's own comment on this same tick, which excludes these fields for
  // exactly this reason) while this drawer stays mounted in place — a
  // comparison-based flag would have relabeled that routine price refresh as
  // "the user changed something," firing a false "stale" caution roughly
  // every poll cycle during market hours even when nobody touched anything.
  const [priceEditedSinceEstimate, setPriceEditedSinceEstimate] = useState(false);
  // An increase stays a draft until the fill price is confirmed. `heldTotal`
  // is that draft; the saved quantity on `position` does not move with it.
  const [heldTotal, setHeldTotal] = useState<number | null>(null);
  const [fillPrice, setFillPrice] = useState('');
  const [priceRejected, setPriceRejected] = useState<string | null>(null);
  const confirmingFill = useRef(false);
  const fillErrorAt = usePortfolioStore((s) => {
    const err = s.lastSyncError;
    if (!err || err.contract !== position.contract) return 0;
    if (/stale_expected_qty|added_fill_price_required|expected_qty_required/.test(err.detail)) return err.at;
    return 0;
  });
  const exposureBreach = usePortfolioStore((s) =>
    s.lastExposureBreach?.contract === position.contract ? s.lastExposureBreach.detail : null);
  const seenFillError = useRef(0);
  if (fillErrorAt !== seenFillError.current) {
    seenFillError.current = fillErrorAt;
    if (fillErrorAt !== 0 && heldTotal != null) setHeldTotal(null);
  }
  const savedQty = position.contracts ?? 1;
  const pendingIncrease = heldTotal != null && heldTotal > savedQty ? heldTotal : null;

  // Clear a stale Monte Carlo result — and abort an in-flight request — when
  // the user edits stop/targets in this same open drawer (EditDrawer doesn't
  // unmount on those edits; the parent just re-renders it with new props).
  // Without this, the panel keeps showing probabilities computed against the
  // OLD stop/targets after the user changes them. Keyed by VALUE (not the
  // `position.targets` array reference, which gets a new identity on
  // unrelated store updates like a routine price-sync tick) so this doesn't
  // spuriously wipe a fresh estimate on every sync poll — only on a genuine
  // stop/target edit. Deliberately excludes currentPrice/currentStockPrice,
  // which tick frequently and would defeat the point of showing a result.
  const targetPricesKey = position.targets.map((t) => t.targetPrice ?? t.stockPrice).join(',');
  useEffect(() => {
    estimateReq.current?.abort();
    estimateReq.current = null;
    // Aborting means this drawer no longer cares about the in-flight
    // request's outcome — reset mcLoading here too, unconditionally.
    // runEstimate's own `finally` only clears mcLoading when
    // estimateReq.current still === its own controller, which is no longer
    // true once this effect has nulled the ref: without this line the
    // button would be stuck on "Estimating…" until the drawer remounts.
    setMcLoading(false);
    setMcResult(null);
    setMcError(null);
    setPriceEditedSinceEstimate(false);
  }, [position.stop, targetPricesKey]);

  // Feature D: the resolvedTpPrice snapshot is refreshed ONLY when the user
  // manually re-runs the method backing it — so a fresh Monte Carlo estimate
  // re-stamps the snapshot if, and only if, 'monte_carlo' is the active TP
  // method. Without this the position would keep alerting on the target price
  // from an estimate the user has just visibly replaced.
  const mcActive = (position.activeTpMethod ?? 'ladder') === 'monte_carlo';
  /** P2-12 (R1-4, R2-5) -- WHICH Monte Carlo target is "the" MC price.
   *
   *  It used to be `targets[0]` unconditionally, so a re-run silently moved a
   *  position the user had pointed at T2 back to T1. Now, only while Monte
   *  Carlo is the ACTIVE method: the rung with the stamped label from the
   *  previous result in this drawer, else the target nearest the current
   *  stamp, else `targets[0]`. With another method active this is `targets[0]`
   *  as before. One function feeds both the re-stamp and the selector's
   *  `mcTargetPrice`, so the selector shows the rung that is stamped. */
  const mcRung = <T extends { label: string; price: number }>(targets: T[], label: string | null): T | undefined => {
    if (!mcActive) return targets[0];
    const byLabel = label != null ? targets.find((t) => t.label === label && t.price > 0) : undefined;
    return byLabel ?? nearestTarget(targets, position.resolvedTpPrice) ?? targets[0];
  };
  const mcRungPrice = mcResult ? mcRung(mcResult.targets, null)?.price ?? null : null;

  const restampIfActive = (method: TpMethod, price: number | null) => {
    if ((position.activeTpMethod ?? 'ladder') !== method) return;
    // `> 0`, not just non-null — the option-side estimate maps a target with no
    // stockPrice to 0, and stamping that would make the alert engine's
    // `price >= 0` comparison true forever. Leaving the previous snapshot in
    // place is the safer failure: it's stale, not permanently triggered.
    if (price == null || price <= 0) return;
    onChange(tpMethodPatch(method, price));
  };

  const runEstimate = async () => {
    // P2-12 -- the rung the current Monte Carlo stamp belongs to, captured
    // BEFORE the previous result is cleared (R3-9). Only when this drawer
    // still holds that result; after a reopen the new run falls back to the
    // target nearest the stamp.
    const stampedLabel = mcActive && mcResult
      ? nearestTarget(mcResult.targets, position.resolvedTpPrice)?.label ?? null
      : null;
    estimateReq.current?.abort();
    const ctrl = new AbortController();
    estimateReq.current = ctrl;
    setMcLoading(true);
    setMcError(null);
    setMcResult(null);
    setPriceEditedSinceEstimate(false);
    try {
      if (isStock) {
        if (stockTargetPrices.length === 0 || !position.stop || !stockDirectionValid || !(position.currentPrice > 0)) throw new Error('missing target/stop');
        // A position minted with no snapshot (the after-scan auto-execute path
        // deliberately omits one — see paperTrade.ts/step-4-stocks's own
        // comment) has no real strategy name to send. An empty string just
        // never matches the backend's mean-reversion caveat check, which is a
        // safe under-trigger — a wrong HARDCODED guess here would misrepresent
        // which strategy this trade actually came from.
        const strategy = (snapshot.strategy as { strategy?: string } | undefined)?.strategy ?? '';
        const horizonLabel = typeof snapshot.horizon === 'string' ? snapshot.horizon : undefined;
        const res = await api.getStockFirstPassage({
          symbol: position.symbol,
          direction: position.direction,
          horizon: _horizonEnum(horizonLabel),
          strategy,
          stock_price: position.currentPrice,
          stop_price: position.stop,
          targets: stockTargetPrices,
          trend_score: typeof snapshot.stock_score === 'number' ? snapshot.stock_score : 50,
        }, ctrl.signal);
        if (ctrl.signal.aborted) return;
        // The response is positional (one entry per price in the `targets`
        // array just sent), so pair it back up with pendingStockTargets'
        // ORIGINAL labels rather than relabelling from T1.
        const targets = res.targets.map((t, i) => ({ label: pendingStockTargets[i]?.label ?? `T${i + 1}`, price: t.price, probability: t.probability, expectedDays: t.expectedDays }));
        setMcResult({
          targets,
          invalidation: res.invalidation,
          horizonNote: `${res.horizonDays} trading days`,
          modelCaveat: res.modelCaveat,
        });
        restampIfActive('monte_carlo', mcRung(targets, stampedLabel)?.price ?? null);
      } else {
        if (optionStrike == null || !(position.currentStockPrice != null && position.currentStockPrice > 0) || !position.stop || !(position.currentPrice > 0)) {
          throw new Error('missing option context');
        }
        const res = await api.getFirstPassageEstimate({
          symbol: position.symbol,
          direction: position.direction,
          stock_price: position.currentStockPrice,
          strike: optionStrike,
          dte: position.dteRemaining,
          premium: position.currentPrice,
          delta: position.delta ?? 0.45,
          trend_score: optionTrend ?? 50,
          invalidation_price: position.stop,
          t1_pct: defaultTargetPct.t1,
          t2_pct: defaultTargetPct.t2,
          t3_pct: defaultTargetPct.t3,
        }, ctrl.signal);
        if (ctrl.signal.aborted) return;
        const targets = res.targets.map((t) => ({ label: `T${Math.round(t.pct * 100)}%`, price: t.stockPrice ?? 0, probability: t.probability, expectedDays: t.expectedDays }));
        setMcResult({
          targets,
          invalidation: res.invalidation,
        });
        restampIfActive('monte_carlo', mcRung(targets, stampedLabel)?.price ?? null);
      }
    } catch (e) {
      if (ctrl.signal.aborted) return;
      // Mirrors StockPositionCard's onEstimate, which captures the real
      // error (setEstimateErr(String(e))) rather than a single static
      // message — a genuine backend rejection (bad symbol, missing candle
      // data, a 500) reads very differently from "try again" being useless
      // forever after the directional-guard case above.
      setMcError(String(e));
    } finally {
      if (estimateReq.current === ctrl) {
        estimateReq.current = null;
        setMcLoading(false);
      }
    }
  };

  // True when the user has explicitly edited Current Price in this drawer
  // session since the estimate was fetched, so the displayed probabilities
  // were computed against a now-stale price. Deliberately a flag set only by
  // the EditField's own onChange (see priceEditedSinceEstimate's declaration
  // above), not a comparison against the live position price — the live
  // price ticks on its own via the 30s portfolio sync regardless of whether
  // the user touched anything.
  const mcPriceStale = mcResult != null && priceEditedSinceEstimate;

  /* The magnitude sanity range for the two UNDERLYING-price fields (Stop and
   * Structural stop). Anchored on the LIVE underlying where the row has one,
   * falling back to the stock price captured when the position was opened.
   * Note the option `currentPrice` beside them is a premium, not a stock
   * level, and is not a candidate anchor.
   *
   * Deliberately wide ([0.2x, 3x]): it exists to catch a misplaced decimal
   * point ("1400" for "140", "14" for "140"), not to have an opinion about how
   * far a stop should sit from the price. `null` when the position carries
   * neither anchor, which leaves those fields exactly as unbounded as they
   * were rather than inventing a reference. */
  /* P2-11 (R1-5) -- without a live underlying, the scan price alone can be
   * months old, so a stop legitimately moved far from it was refused. The
   * range is then the HULL of the range around the position's own current
   * stop (a level already accepted against a recent price) and the range
   * around the scan price, so a mis-stored stop can still be corrected back
   * toward the scan price. With a live underlying: live only, as before. */
  const rangeAround = (anchor: number) => ({ min: anchor * 0.2, max: anchor * 3 });
  const liveAnchor = position.currentStockPrice && position.currentStockPrice > 0 ? position.currentStockPrice : null;
  const fallbackRanges = [
    position.stop != null && position.stop > 0 ? rangeAround(position.stop) : null,
    position.scanStockPrice && position.scanStockPrice > 0 ? rangeAround(position.scanStockPrice) : null,
  ].filter((r): r is { min: number; max: number } => r != null);
  const stockLevelRange = liveAnchor != null
    ? rangeAround(liveAnchor)
    : fallbackRanges.length > 0
      ? {
          min: Math.min(...fallbackRanges.map((r) => r.min)),
          max: Math.max(...fallbackRanges.map((r) => r.max)),
        }
      : null;

  const confirmFill = async () => {
    if (confirmingFill.current || pendingIncrease == null) return;
    const price = parsePositivePrice(fillPrice);
    if (price == null) {
      setPriceRejected('Fill price must be a positive number — the quantity increase was not saved.');
      return;
    }
    setPriceRejected(null);
    confirmingFill.current = true;
    try {
      await usePortfolioStore.getState().confirmAddedFill(position.contract, pendingIncrease, price);
    } finally {
      confirmingFill.current = false;
    }
    // A newer quantity typed while this request was in flight keeps its draft.
    // The saved row already moved; this only closes the form when it still
    // describes that same total.
    const savedNow = usePortfolioStore.getState().positions
      .find((p) => p.contract === position.contract)?.contracts ?? savedQty;
    if (pendingIncrease > savedNow) return;
    setHeldTotal(null);
    setFillPrice('');
  };

  return (
    <div className={styles.editDrawer}>
      <div className={styles.editHeader}>
        <Text size={12} weight={400}>Edit {position.contract}</Text>
        <button type="button" className={styles.editClose} onClick={onClose} aria-label="Close editor">×</button>
      </div>

      <div className={styles.editGrid}>
        <EditField
          label="Stop"
          // DIRECTION-AWARE. The old copy said "drops below" unconditionally,
          // which is the wrong instruction for every Bearish position -- a
          // bearish stop sits ABOVE the price and fires on a RISE.
          hint={
            position.direction === 'Bearish'
              ? 'Exit if the underlying stock rises above this price (invalidates the trade thesis).'
              : 'Exit if the underlying stock drops below this price (invalidates the trade thesis).'
          }
          value={position.stop ?? 0}
          range={stockLevelRange}
          onChange={(n) => onChange({ stop: n > 0 ? n : null })}
        />
        <EditField
          label="Structural stop"
          hint="Tighter, chart-based stop (order block / swing level) from Check structure. Optional — 0 means none was captured."
          value={position.structuralStop ?? 0}
          range={stockLevelRange}
          onChange={(n) => onChange({ structuralStop: n > 0 ? n : null })}
        />
        <PremiumStopEditor
          position={position}
          globalPremiumStopPct={globalPremiumStopPct}
          onChange={onChange}
        />
        <TargetEditor
          targets={position.targets}
          onChange={(targets) => onChange({ targets })}
        />
        {!position.contract.endsWith('|STOCK') && (
          <ExitPlanEditor position={position} onChange={onChange} />
        )}
        {!position.contract.endsWith('|STOCK') && (
          <MaxLossBanner position={position} onChange={onChange} />
        )}
        {/* The RECORD (what was picked) sits directly above the SELECTOR (what
            drives the alert today), because the whole point of §4.3's degraded
            rows is that those two can legitimately disagree — and a trader can
            only see that they disagree if both are on screen together. */}
        <PickedMethodRecord position={position} />
        <TpMethodSelector
          position={position}
          mcTargetPrice={mcRungPrice}
          onChange={onChange}
        />
        <AlertOverridesEditor position={position} onChange={onChange} />
        <div className={styles.addedFill}>
          <EditField
            label="Contracts"
            hint="Number of option contracts held."
            value={savedQty}
            // A quantity, not a level: 0 contracts is not "no override", it is a
            // position that does not exist. Closing one is the row's Close
            // button, not a 0 typed here.
            zeroClears={false}
            draftEpoch={fillErrorAt}
            // An increase is an added fill. Hold it and ask for the price.
            // A decrease still commits on blur, as it always has.
            onCommit={(n) => {
              const next = Math.max(1, Math.round(n));
              if (next > savedQty) {
                setHeldTotal(next);
                setPriceRejected(null);
                return false;
              }
              setHeldTotal(null);
              return true;
            }}
            onChange={(n) => onChange({ contracts: Math.max(1, Math.round(n)) })}
          />
          <Text size={10} tone="dim">{`Average entry $${position.entryPrice.toFixed(2)}`}</Text>
          {pendingIncrease != null && (
            <div className={styles.addedFillRow}>
              <label className={styles.editField}>
                <Text size={11} tone="secondary">Added fill price</Text>
                <input
                  type="text"
                  inputMode="decimal"
                  className={styles.editInput}
                  value={fillPrice}
                  aria-label="Added fill price"
                  onChange={(e) => { setPriceRejected(null); setFillPrice(e.target.value); }}
                  onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void confirmFill(); } }}
                />
              </label>
              <button type="button" className={styles.mcBtn} onClick={() => { void confirmFill(); }}>
                Confirm added fill
              </button>
            </div>
          )}
          {priceRejected && <Text size={10} tone="caution">{priceRejected}</Text>}
          {exposureBreach && <Text size={10} tone="caution">{rejectionMessage(exposureBreach)}</Text>}
        </div>
        <EditField
          label="Current price"
          // NO-LIVE-QUOTE NLQ-1 (round-2 G1): a row GET /api/portfolio got no
          // quote for carries a 0 currentPrice that is not a price. The field
          // shows it as unknown -- empty, with a placeholder -- exactly as the
          // table shows "—", never as 0.
          hint={position.quoteUnavailable
            ? 'Quote unavailable'
            : 'Manual override — will refresh from broker in live mode.'}
          value={position.currentPrice}
          unknown={position.quoteUnavailable === true}
          placeholder="— (no quote)"
          // 0 is refused here (decision Q6): it would write `currentPrice: 0`
          // and a -100% P&L onto the row. The way to mark a position worthless
          // is to CLOSE it at $0, which the close path supports end to end.
          //
          // How long a typed value survives (P2-14, corrected): it is not sent
          // to the backend -- `toUpdatePayload` omits currentPrice/pnlDollar/
          // pnlPct -- but it IS persisted to localStorage (partialize keeps
          // `positions`), so it survives a reload for as long as syncs fail.
          // A successful sync's `fromBackend` rewrites all three.
          zeroClears={false}
          zeroMessage="Must be greater than 0 — to mark it worthless, close the position at $0 (Close button). Kept the previous value."
          onChange={(n) => {
            const mult = position.contract.endsWith('|STOCK') ? 1 : 100;
            const pnlDollar = (n - position.entryPrice) * mult * (position.contracts ?? 1);
            const pnlPct    = ((n - position.entryPrice) / position.entryPrice) * 100;
            // A typed price IS a mark: the row is no longer "no quote" until the
            // next sync says otherwise (fromBackend rewrites the flag). Without
            // this the override would be written while the field, the table and
            // the totals all kept showing it as unknown.
            onChange({ currentPrice: n, pnlDollar, pnlPct, quoteUnavailable: false });
            setPriceEditedSinceEstimate(true);
          }}
        />
      </div>

      <div className={styles.mcSection}>
        <Text size={12} weight={500}>Monte Carlo estimate</Text>
        <div className={styles.mcRow}>
          <button type="button" className={styles.mcBtn} onClick={runEstimate} disabled={mcLoading || estimateDisabled}>
            <Text size={12} weight={500}>{mcLoading ? 'Estimating…' : 'Estimate'}</Text>
          </button>
          {mcError && <Text size={11} tone="reject">{mcError}</Text>}
        </div>
        {isStock && !(position.currentPrice > 0) && (
          <Text size={11} tone="dim">
            No live current price yet — can&apos;t estimate until a price is available.
          </Text>
        )}
        {isStock && position.currentPrice > 0 && !stockDirectionValid && (
          <Text size={11} tone="dim">
            The stop is already on the wrong side of the current price — sync the position&apos;s stop before estimating.
          </Text>
        )}
        {isStock && position.currentPrice > 0 && stockDirectionValid && stockTargetPrices.length === 0 && allStockTargetPrices.length > 0 && (
          <Text size={11} tone="dim">
            Every target has already been reached — add a new target to estimate further upside.
          </Text>
        )}
        {mcResult?.horizonNote && (
          <Text size={10} tone="dim">Chance of reaching each target within {mcResult.horizonNote}</Text>
        )}
        {mcResult && (
          <div className={styles.mcResultRow}>
            {mcResult.targets.map((t, i) => (
              <div key={`${t.label}-${i}`}>
                <Text size={10} tone="dim">{t.label.toUpperCase()}</Text>
                <Data size={14} weight={500} tone="pass">{`${Math.round(t.probability * 100)}%`}</Data>
                <Text size={10} tone="dim">{t.expectedDays != null ? `~${Math.round(t.expectedDays)}d` : 'unlikely'}</Text>
              </div>
            ))}
            <div>
              <Text size={10} tone="dim">STOP HIT</Text>
              <Data size={14} weight={500} tone="reject">{`${Math.round(mcResult.invalidation.probability * 100)}%`}</Data>
              <Text size={10} tone="dim">{mcResult.invalidation.expectedDays != null ? `~${Math.round(mcResult.invalidation.expectedDays)}d` : 'unlikely'}</Text>
            </div>
          </div>
        )}
        {mcResult?.modelCaveat && (
          <Text size={11} tone="caution">{mcResult.modelCaveat}</Text>
        )}
        {mcPriceStale && (
          <Text size={11} tone="caution">Price has changed since this estimate was computed.</Text>
        )}
      </div>

      <div className={styles.targetEditor}>
        <Text size={11} tone="secondary">Notes</Text>
        <SymbolNotes symbol={position.symbol} editable={isHeld || isWatched} />
      </div>

      <div className={styles.editFooter}>
        <Text size={11} tone="secondary">
          Stop, structural stop, and targets save automatically. A larger quantity is saved only with its fill price.
        </Text>
        <button type="button" className={styles.editRemove} onClick={onRemove}>
          Close position
        </button>
      </div>
    </div>
  );
}

function TargetEditor({
  targets,
  onChange,
}: {
  targets: import('@/types/domain').TargetLevel[];
  onChange: (targets: import('@/types/domain').TargetLevel[]) => void;
}) {
  return (
    <div className={styles.targetEditor}>
      <Text size={11} tone="secondary">Targets</Text>
      <div className={styles.targetList}>
        {targets.map((t, i) => (
          <div key={t.id ?? i} className={styles.targetItem}>
            <div className={styles.targetHeader}>
              <Text size={12} weight={600}>{t.id?.toUpperCase()}</Text>
              <span className={styles.targetStatus}>{t.status}</span>
            </div>
            <div className={styles.targetGrid}>
              <div>
                <Text size={10} tone="dim">Stock</Text>
                <Data size={12} weight={500}>${t.stockPrice.toFixed(2)}</Data>
              </div>
              {t.estimatedOptionPrice !== undefined && (
                <div>
                  <Text size={10} tone="dim">Est. option</Text>
                  <Data size={12} weight={500}>${t.estimatedOptionPrice.toFixed(2)}</Data>
                </div>
              )}
              <div>
                <Text size={10} tone="dim">Sell</Text>
                <input
                  type="number"
                  min={1}
                  step={1}
                  className={styles.targetInput}
                  value={t.contractsToSell ?? 0}
                  onChange={(e) => {
                    const n = Number(e.target.value);
                    if (!Number.isFinite(n) || n < 1) return;
                    onChange(
                      targets.map((x) => (x.id === t.id ? { ...x, contractsToSell: n } : x)),
                    );
                  }}
                />
              </div>
            </div>
            {t.pricingMethod && (
              <Text size={10} tone="dim">Method: {t.pricingMethod}</Text>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/** "Compute Exit Plan" for an OPEN option position — post-trade counterpart
 *  to TradeCard's pre-trade button. Persists the result verbatim via the
 *  same `onChange` -> updatePosition -> PATCH /api/portfolio/{recId} path
 *  every other drawer field already uses; refreshed only on manual re-click,
 *  never automatically. Options-only (the repricing chain needs strike/dte/
 *  premium, which a stock position doesn't have) — the caller only renders
 *  this for non-'|STOCK' contracts. */
function ExitPlanEditor({
  position,
  onChange,
}: {
  position: PortfolioPosition;
  onChange: (patch: Partial<PortfolioPosition>) => void;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const exitPlan = position.exitPlan;
  // Same guarded strike derivation and the same `> 0` premium check as the
  // Monte Carlo section's optionStrike/estimateDisabled above — a corrupted
  // 0/malformed strike or a 0 premium (a live quote with no price, a real
  // state for illiquid/deep-OTM contracts) must not reach the backend, which
  // rejects both with a raw 422 that the blanket catch{} below turns into a
  // permanent "try again" the user can never resolve by actually trying again.
  const snapshot = position.tradeCardSnapshot ?? {};
  const strike = (typeof snapshot.strike === 'number' && snapshot.strike > 0 ? snapshot.strike : null) ?? optionStrikeFromContract(position.contract);
  // `?? position.entryPrice` alone doesn't fall through on a `0` —
  // `currentStockPrice` lands on exactly `0.0` (not null) for a bad/halted
  // quote, same failure class as the strike/premium checks above, and the
  // backend's entry_price: Field(..., gt=0) rejects it the same way.
  const effectiveEntryPrice = position.currentStockPrice != null && position.currentStockPrice > 0
    ? position.currentStockPrice : position.entryPrice;
  const computeDisabled = loading || strike == null || !(position.currentPrice > 0) || !(effectiveEntryPrice > 0);

  const compute = async () => {
    if (strike == null || !(position.currentPrice > 0) || !(effectiveEntryPrice > 0)) return;
    setLoading(true);
    setError(false);
    try {
      // trend_score isn't available for an already-open position (the scan-time
      // score isn't carried on PortfolioPosition) — neutral 50 means zero
      // directional drift bias in the Monte Carlo leg, an honest default
      // rather than fabricating a score from partial data.
      const res = await api.getExitPlan({
        symbol: position.symbol,
        direction: position.direction,
        entry_price: effectiveEntryPrice,
        strike,
        dte: position.dteRemaining,
        premium: position.currentPrice,
        trend_score: 50,
        ...(Number.isFinite(position.exitPlan?.targets[0]?.rrRatio) && position.exitPlan!.targets[0].rrRatio > 0 && position.exitPlan!.targets[0].rrRatio <= 10
          ? { target_r_multiple: position.exitPlan!.targets[0].rrRatio } : {}),
      });
      const plan = { ...res, computedAt: new Date().toISOString() };
      // Feature D: a re-computed plan re-stamps the TP snapshot when one of its
      // rows is the active TP method — the same "refresh only on a manual
      // re-compute" rule the Monte Carlo path follows. Sent as ONE patch so the
      // plan and the snapshot derived from it can never be persisted apart.
      const active = position.activeTpMethod ?? 'ladder';
      // POSITIONAL, the same fix and the same reason as `tpMethodOptions`
      // below — and this is the site that MATTERS more. This used to be
      // `find((t) => t.rrRatio === rr)` with rr hardcoded to 2 / 3: under
      // `rr_ratios: [1.5, 4.0]` with `exit_plan_2r` active it matched nothing,
      // so `tpMethodPatch` was omitted from the patch while `exitPlan` in the
      // SAME patch was replaced. The persisted `resolved_tp_price` then kept
      // pointing at a row of the PREVIOUS plan and TP_HIT fired on a price no
      // longer anywhere on screen — a stale number that still fires, which is
      // worse than the read side's missing label.
      const rowIndex = active === 'exit_plan_2r' ? 0 : active === 'exit_plan_3r' ? 1 : null;
      const rawRowPrice = rowIndex != null ? plan.targets[rowIndex]?.price ?? null : null;
      // `> 0`, not just non-null — same rule as the Monte Carlo path's
      // restampIfActive: a 0 price would make the alert engine's `price >= 0`
      // comparison true forever, so leave the previous snapshot in place instead.
      const rowPrice = rawRowPrice != null && rawRowPrice > 0 ? rawRowPrice : null;
      onChange({
        exitPlan: plan,
        ...(rowIndex != null && rowPrice != null ? tpMethodPatch(active, rowPrice) : {}),
      });
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.targetEditor}>
      <Text size={11} tone="secondary">Exit Plan</Text>
      <button type="button" className={styles.exitPlanBtn} onClick={compute} disabled={computeDisabled}>
        {loading ? 'Computing exit plan…' : 'Compute Exit Plan'}
      </button>
      {!loading && (strike == null || !(position.currentPrice > 0) || !(effectiveEntryPrice > 0)) && (
        <Text size={10} tone="dim">Missing a valid strike, premium, or entry price — can&apos;t compute an exit plan yet.</Text>
      )}
      {error && <Text size={10} tone="reject">Couldn&apos;t compute an exit plan — try again.</Text>}
      {exitPlan && (
        <div className={styles.targetList}>
          <div className={styles.targetItem}>
            <div className={styles.targetHeader}>
              <Text size={12} weight={600}>
                Stop {exitPlan.stop.source === 'structural' ? '(structural)' : '(ATR-widened)'}
              </Text>
            </div>
            <div className={styles.targetGrid}>
              <div>
                <Text size={10} tone="dim">Stock</Text>
                <Data size={12} weight={500}>${exitPlan.stop.price.toFixed(2)}</Data>
              </div>
              <div>
                <Text size={10} tone="dim">Contract</Text>
                <Data size={12} weight={500}>${exitPlan.stop.contractPrice.toFixed(2)}</Data>
              </div>
            </div>
            <Text size={10} tone="dim">Method: {exitPlan.stop.rrModel}</Text>
          </div>
          {exitPlan.targets.map((t) => (
            <div key={t.rrRatio} className={styles.targetItem}>
              <div className={styles.targetHeader}>
                <Text size={12} weight={600}>{t.rrRatio}R {t.qualityGood ? '✓' : '⚠'}</Text>
                <span className={styles.targetStatus}>{t.tpSource === 'structural_snap' ? 'snapped' : 'arithmetic'}</span>
              </div>
              <div className={styles.targetGrid}>
                <div>
                  <Text size={10} tone="dim">Stock</Text>
                  <Data size={12} weight={500}>${t.price.toFixed(2)}</Data>
                </div>
                <div>
                  <Text size={10} tone="dim">Contract</Text>
                  <Data size={12} weight={500}>${t.contractPrice.toFixed(2)}</Data>
                </div>
                <div>
                  <Text size={10} tone="dim">Probability</Text>
                  <Data size={12} weight={500}>{(t.probability * 100).toFixed(0)}%</Data>
                </div>
              </div>
              <Text size={10} tone="dim">Method: {t.rrModel}</Text>
              {!t.qualityGood && (
                <Text size={10} tone="caution">
                  {t.qualityReasons.includes('stop_widened') ? 'Stop ATR-widened. ' : ''}
                  {t.qualityReasons.includes('target_capped') ? 'Bearish target capped at the price floor. ' : ''}
                  {t.qualityReasons.includes('target_beyond_structural') ? 'Target overshoots structural level.' : ''}
                </Text>
              )}
            </div>
          ))}
          <Text size={10} tone="dim">as of {new Date(exitPlan.computedAt).toLocaleTimeString()}</Text>
        </div>
      )}
    </div>
  );
}

/** Feature C (exit-plan pipeline plan) — inline max-loss-at-stop badge for an
 *  OPEN option position. Warning-only, never blocks any action here (nothing
 *  is being submitted from the Portfolio editor). Basis is strictly the
 *  exit-plan pipeline's final stop, repriced to a contract price — same rule
 *  TradeCard-time's checkTradeRisk() uses — so it only renders once an exit
 *  plan has been computed; options-only like ExitPlanEditor above it. */
function MaxLossBanner({
  position,
  onChange,
}: {
  position: PortfolioPosition;
  onChange: (patch: Partial<PortfolioPosition>) => void;
}) {
  const limits = useRiskStore((s) => s.limits);
  const exitPlan = position.exitPlan;
  const contracts = position.contracts ?? 1;
  const override = position.maxLossOverride ?? null;

  // The loss figure is a pure client computation — exitPlan.stop.contractPrice
  // is already repriced, no network round trip needed — so this debounce is
  // purely to stop the number/badge flashing on every keystroke while the
  // user is still typing a new contracts count or override value, not to
  // throttle a live backend call (that already happens 600ms-debounced,
  // separately, in portfolioStore's scheduleRemotePositionPatch).
  const [debounced, setDebounced] = useState({ contracts, override });
  useEffect(() => {
    const t = setTimeout(() => setDebounced({ contracts, override }), 400);
    return () => clearTimeout(t);
  }, [contracts, override]);

  const [editingOverride, setEditingOverride] = useState(false);
  const [draftMode, setDraftMode] = useState<'dollar' | 'percent'>(override?.mode ?? 'percent');
  const [draftValue, setDraftValue] = useState(() =>
    override
      ? (override.mode === 'percent' ? override.value * 100 : override.value)
      : Math.round(limits.maxLossPerTradePct * 100 * 100) / 100
  );

  // entryPrice <= 0 is a data-integrity glitch, not a real 0-loss trade
  // (mirrors the "never a real premium" convention `floorStop` applies to
  // stock prices elsewhere in this store) — without this guard the formula
  // below reports a reassuring "PASS — $0 max loss" for a position whose
  // loss genuinely can't be computed.
  if (!exitPlan || position.contract.endsWith('|STOCK') || position.entryPrice <= 0) return null;

  const lossAtStop = maxLossAtStop(position.entryPrice, exitPlan.stop.contractPrice, debounced.contracts);
  const limitDollar = resolveMaxLossLimitDollar(limits.portfolioValue, limits.maxLossPerTradePct, debounced.override);
  const exceeded = lossAtStop > limitDollar;
  const riskPerContract = maxLossAtStop(position.entryPrice, exitPlan.stop.contractPrice, 1);
  const sizing = recommendedContractSize(limitDollar, riskPerContract);

  const applyOverride = () => {
    const value = draftMode === 'percent' ? draftValue / 100 : draftValue;
    onChange({ maxLossOverride: { mode: draftMode, value } });
    setEditingOverride(false);
  };
  const clearOverride = () => {
    onChange({ maxLossOverride: null });
    setEditingOverride(false);
  };

  return (
    <div className={styles.targetEditor}>
      <Text size={11} tone="secondary">Max loss at stop</Text>
      <div className={styles.targetItem}>
        <div className={styles.targetHeader}>
          <Data size={13} weight={500} tone={exceeded ? 'reject' : 'pass'}>
            ${Math.round(lossAtStop).toLocaleString('en-US')}
          </Data>
          <StatusBadge status={exceeded ? 'REJECT' : 'PASS'} />
        </div>
        <Text size={10} tone="dim">
          Limit ${Math.round(limitDollar).toLocaleString('en-US')}
          {override
            ? ` (override: ${override.mode === 'percent' ? `${(override.value * 100).toFixed(2)}%` : `$${override.value.toLocaleString('en-US')}`})`
            : ' (account default)'}
        </Text>
        {sizing && (
          <Text size={10} tone="dim">
            Risk-derived size: {sizing.recommended} contract{sizing.recommended === 1 ? '' : 's'} ({formatRecommendedContractSizeRaw(sizing)} exact)
          </Text>
        )}
        {!editingOverride ? (
          <button type="button" className={styles.exitPlanBtn} onClick={() => setEditingOverride(true)}>
            {override ? 'Edit override' : 'Set override'}
          </button>
        ) : (
          <div className={styles.targetGrid}>
            <div className={styles.maxLossModeToggle}>
              <button
                type="button"
                className={draftMode === 'percent' ? styles.maxLossModeBtnActive : styles.maxLossModeBtn}
                onClick={() => setDraftMode('percent')}
              >
                %
              </button>
              <button
                type="button"
                className={draftMode === 'dollar' ? styles.maxLossModeBtnActive : styles.maxLossModeBtn}
                onClick={() => setDraftMode('dollar')}
              >
                $
              </button>
            </div>
            <input
              type="number"
              className={styles.targetInput}
              value={draftValue}
              min={0}
              step={draftMode === 'percent' ? 0.25 : 10}
              onChange={(e) => setDraftValue(Math.max(0, Number(e.target.value) || 0))}
              aria-label="Max loss override value"
            />
            <button type="button" className={styles.exitPlanBtn} onClick={applyOverride}>Apply</button>
            {override && (
              <button type="button" className={styles.editRemove} onClick={clearOverride}>Use default</button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** The target whose price is nearest `stamp` (P2-12). Undefined when there is
 *  no positive stamp or no positive-priced target. */
function nearestTarget<T extends { price: number }>(targets: T[], stamp: number | null | undefined): T | undefined {
  if (stamp == null || !(stamp > 0)) return undefined;
  let best: T | undefined;
  for (const t of targets) {
    if (!(t.price > 0)) continue;
    if (best == null || Math.abs(t.price - stamp) < Math.abs(best.price - stamp)) best = t;
  }
  return best;
}

function EditField({
  label,
  hint,
  value,
  onChange,
  /** ROUND 10 finding 3 — an optional MAGNITUDE sanity range.
   *
   *  The drawer is the only editor a user reaches for an already-open
   *  position, and its Stop field had no bound of any kind: "1400" typed for
   *  "140" on a $145 stock PATCHed straight through, after which
   *  alert_generator's `price <= pos.stop` is permanently true and every
   *  backend scan raises a Critical STOP_REACHED with Gmail and Telegram
   *  behind it.
   *
   *  MAGNITUDE, not direction — and the difference matters. On a NEW position
   *  a wrong-side stop can only be a typo, which is why the create endpoint
   *  refuses one. On an OPEN position a stop the underlying has already moved
   *  through is a stop that is CORRECTLY about to fire, and tightening a stop
   *  onto the current price is an ordinary thing to do. A directional check
   *  here would reject exactly those legitimate states, so the range is wide
   *  and only catches a misplaced decimal point. */
  range,
  /** ROUND 12 finding 5 — does 0 MEAN anything on this field?
   *
   *  `commit`'s empty-draft message reads "Enter 0 to clear this level", and on
   *  Stop / Structural stop that is exactly true: both call sites map 0 to
   *  `null` and the hints document it. It was printed unconditionally, so the
   *  two fields where 0 clears nothing said it too:
   *
   *    - Contracts (`Math.max(1, Math.round(n))`) — typing 0 stores 1 while
   *      `setDraft(String(n))` leaves "0" on screen, because `stored` never
   *      changed and the follow-the-stored-value sync only runs when it does.
   *      The field then shows a quantity the position does not hold.
   *    - Current price — 0 is a real write, not a clear: it stores
   *      `currentPrice: 0` and derives `pnlPct = ((0 - entry) / entry) * 100`,
   *      i.e. a -100% P&L on the row, on a gesture the field itself invited.
   *
   *  So the prompt to type 0 is now opt-in, and where it is off, a committed 0
   *  is REVERTED rather than written — the same honest answer the range check
   *  gives, and it puts `stored` back in the box. */
  zeroClears = true,
  /** P2-01 -- the message a refused 0 shows when `zeroClears` is off. Current
   *  price uses it to point at the real gesture (close the position at $0). */
  zeroMessage = 'Must be greater than 0 — kept the previous value.',
  /** NO-LIVE-QUOTE NLQ-1 (round-2 G1) -- `value` is not a real value (Current
   *  price on a row with no quote). The field then holds an EMPTY draft and
   *  shows `placeholder`; an empty commit reverts to empty and writes nothing,
   *  silently, since there is no previous value to "keep". */
  unknown = false,
  placeholder,
  /** Return false to keep the typed draft and skip `onChange`. */
  onCommit,
  /** Bump to drop a held draft and show `value` again (a rejected fill). */
  draftEpoch = 0,
}: {
  label: string;
  hint?: string;
  value: number;
  onChange: (n: number) => void;
  range?: { min: number; max: number } | null;
  zeroClears?: boolean;
  zeroMessage?: string;
  unknown?: boolean;
  placeholder?: string;
  onCommit?: (n: number) => boolean;
  draftEpoch?: number;
}) {
  // DRAFT-THEN-COMMIT, and TEXT rather than number. Round 11 findings 1 and 2.
  //
  // This field used to be a fully controlled `<input type="number">` with no
  // draft, committing on every keystroke. Round 10 then added the magnitude
  // `range` above, which `return`s without calling `onChange` for an
  // out-of-range value. Those two together make ordinary typing impossible,
  // and the failure mode is not "nothing happens" -- it is "the stop is
  // deleted", because `Number("") === 0`, the range check exempts 0, and both
  // Stop call sites map 0 to `null`:
  //
  //   Stop $140 on a $145 underlying (range [29.00, 435.00]), retyped as 130:
  //     clear the field  -> ""   -> 0   -> exempt -> onChange(0)  -> stop: NULL
  //     type "1"         -> "01" -> 1   -> below 29, rejected, React restores
  //     type "3"         -> "03" -> 3   -> below 29, rejected, restored
  //     type "0"         -> "00" -> 0   -> exempt -> onChange(0)  -> stop: NULL
  //
  // 130 is unreachable because every prefix of it (1, 13) is below the floor,
  // so the field cannot pass through the intermediate states that lead to a
  // legal one. Before round 10 those prefixes committed harmlessly and the
  // final keystroke landed 130; the range is what turned a transient null into
  // a permanent one.
  //
  // It is silent and it is money: `stop: null` PATCHes through, and BOTH alert
  // engines gate on the stop existing (alertEngine.ts's `stop != null`,
  // alert_generator.py's `pos.stop is not None`), so the position can never
  // raise STOP_REACHED again while the user believes they just set one. The
  // same wiring on Structural stop does it to STRUCTURAL_STOP_BREACHED.
  //
  // `type="number"` was the second half: the browser sanitizes any half-typed
  // literal to "", so merely typing the "." of 132.50 produced the same empty
  // string and the same deleted stop. That is round 8's finding, fixed then in
  // TradeCard's EditableKV and in PremiumStopEditor below, and never carried to
  // the two fields on this drawer that hold PortfolioPosition.stop itself.
  //
  // So: keystrokes only move a local draft, the range is judged once on commit,
  // and an empty draft REVERTS rather than clearing. Typing an explicit 0 is
  // still the way to clear -- it is what the hints already document, and it is
  // the one gesture that cannot be confused with a half-finished number.
  const stored = unknown ? '' : String(value);
  const [draft, setDraft] = useState(stored);
  const [rejected, setRejected] = useState<string | null>(null);
  // A BLUR IS NOT AN EDIT -- the same lesson as PremiumStopEditor below, which
  // learned it across rounds 4 and 5. Clicking into a field to read it and
  // clicking away must not write.
  const dirtyRef = useRef(false);
  const epochRef = useRef(draftEpoch);
  if (epochRef.current !== draftEpoch) {
    epochRef.current = draftEpoch;
    dirtyRef.current = false;
    if (draft !== stored) setDraft(stored);
  }
  // Follow the stored value when it changes from outside (a different position,
  // the 30s sync) but never while the user is mid-edit on this one.
  const lastStoredRef = useRef(stored);
  if (lastStoredRef.current !== stored) {
    lastStoredRef.current = stored;
    if (!dirtyRef.current && draft !== stored) setDraft(stored);
    // NOT cleared here (decision Q15): a rejection message is retired only by
    // the user's own edits -- a keystroke (onChange below) or a commit. An
    // external change (the 30s sync, a second client) used to wipe it, so a
    // refusal could vanish before it was read.
  }

  const revert = (msg: string | null) => {
    setDraft(stored);
    setRejected(msg);
    dirtyRef.current = false;
  };

  // A COMMITTED VALUE THE CALL SITE NORMALISED must not stay on screen.
  //
  // The follow-the-stored-value sync above only fires when `stored` CHANGES,
  // so a commit the parent normalises back to the value it already holds
  // leaves the typed text sitting in the box: Contracts is
  // `Math.max(1, Math.round(n))`, so on a position holding 1 a typed "0.4"
  // stores 1 -- unchanged -- while `setDraft(String(n))` below has already
  // put "0.4" on screen. The field then shows a quantity the position does
  // not hold, which is the display-vs-store split this work exists to remove.
  //
  // "0.4" and not "0": a literal 0 on Contracts is refused by `zeroClears`
  // before it ever reaches here, and on the two fields where 0 IS the clear
  // gesture the call sites map it to null, so `stored` becomes "0" and this
  // has nothing to correct.
  //
  // `onChange` reaches a Zustand `set` synchronously (page.tsx hands it
  // `updatePosition`), so the render immediately after a commit already
  // carries the parent's answer -- this reads it and puts it back.
  const committedRef = useRef(false);
  useEffect(() => {
    if (!committedRef.current) return;
    committedRef.current = false;
    if (!dirtyRef.current && draft !== stored) setDraft(stored);
  });

  const commit = () => {
    // Clears `rejected` as well, matching PremiumStopEditor below. Without it
    // a message outlives the gesture that produced it: type "abc" into Stop,
    // blur (message shown), then click in and out without typing -- the
    // caution stays, now describing nothing, while the identical gesture on
    // Premium stop retires it.
    if (!dirtyRef.current) { setDraft(stored); setRejected(null); return; }
    const raw = draft.trim();
    if (raw === '') {
      revert(
        unknown
          ? null
          : zeroClears
            ? 'Enter 0 to clear this level — an empty field keeps the previous value.'
            : 'Empty is not a value — kept the previous one.',
      );
      return;
    }
    // A COMPLETE decimal literal, or a no-op. `Number("132.")` is 132, so
    // without this a user interrupted part-way through 132.50 commits 132 --
    // round 9's finding, reached here through the same parser. ".5" is a
    // complete way to write 0.5 and stays accepted; a trailing point is the
    // interrupted case. Negative is not a price and is refused with it.
    if (!/^(?:\d+(?:\.\d+)?|\.\d+)$/.test(raw)) {
      revert('Not a complete number — kept the previous value.');
      return;
    }
    const n = Number(raw);
    if (!Number.isFinite(n)) { revert('Not a complete number — kept the previous value.'); return; }
    // Where 0 is not the "none" gesture it is not a value either: see
    // `zeroClears`. Refused BEFORE the range exemption below, which would
    // otherwise wave it through.
    if (n === 0 && !zeroClears) {
      revert(zeroMessage);
      return;
    }
    // 0 is the documented "none" for these fields and always passes; the range
    // only judges a number the user meant as a level.
    if (range && n !== 0 && (n < range.min || n > range.max)) {
      revert(
        `Must be between ${range.min.toFixed(2)} and ${range.max.toFixed(2)} `
        + `— kept the previous value.`,
      );
      return;
    }
    if (onCommit && !onCommit(n)) {
      // Held, not written. A later refresh must not snap this draft away.
      setRejected(null);
      dirtyRef.current = true;
      setDraft(String(n));
      return;
    }
    setRejected(null);
    dirtyRef.current = false;
    committedRef.current = true;
    setDraft(String(n));
    if (n !== value) onChange(n);
  };

  return (
    <label className={styles.editField}>
      <Text size={11} tone="secondary">{label}</Text>
      <input
        type="text"
        inputMode="decimal"
        className={styles.editInput}
        value={draft}
        placeholder={placeholder}
        onChange={(e) => { dirtyRef.current = true; setRejected(null); setDraft(e.target.value); }}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commit(); } }}
      />
      {hint && <Text size={10} tone="dim">{hint}</Text>}
      <span aria-live="polite">
        {rejected && <Text size={10} tone="caution">{rejected}</Text>}
      </span>
    </label>
  );
}

/* ------------------------------------------------------------------------ *
 * Piece 4 — per-position premium stop
 * (docs/superpowers/plans/2026-09-02-piece-4-per-position-premium-stop-spec.md)
 * ------------------------------------------------------------------------ */

/** Editable per-position premium stop, shown as a whole percentage.
 *
 *  Empty (or any non-positive entry) CLEARS the override and returns the
 *  position to inheriting the global — which is why the field renders empty,
 *  not `60`, when nothing is set. Pre-filling it with the resolved global
 *  would make an inherited value indistinguishable from a set one, and a user
 *  who then saved the drawer would silently freeze the position at today's
 *  global. The hint states which of the two states is live. */
function PremiumStopEditor({
  position,
  globalPremiumStopPct,
  onChange,
}: {
  position: PortfolioPosition;
  globalPremiumStopPct: number;
  onChange: (patch: Partial<PortfolioPosition>) => void;
}) {
  const isStock = position.contract.endsWith('|STOCK');
  // STOP-SEMANTICS-2026-10-02 -- a short stock's stop fires on a RISE, at
  // entry x (1 + pct). It is never sub-cent, and a global of 100% or more
  // still fires for it (at 2x entry or above), so neither caution applies.
  const shortStock = isShortStockPosition(position.contract, position.direction);
  const own = position.premiumStopPct;
  const inherited = !hasOwnPremiumStopPct(own);
  const outsideBand = own != null && (own < PREMIUM_STOP_MIN_PCT || own > PREMIUM_STOP_MAX_PCT);
  const globalNeverFires = inherited && globalPremiumStopPct >= 1 && !shortStock;
  // The engines' own test at the lowest live quote -- one spelling of the rule
  // (premiumStopIsSubCent), shared with the commit refusal below and the
  // backend's save-time refusal.
  const subCent = premiumStopIsSubCent(
    position.entryPrice, resolvePremiumStopPct(own, globalPremiumStopPct), shortStock);
  // TWO DECIMALS OF PERCENT, not a whole number. `Math.round(own * 100)` was
  // lossy in both directions and the loss was silent:
  //
  //   - A stop the SERVER derived is almost never a whole percent -- add_position
  //     stores premiumStopDollar / entry_price, e.g. 2.00 / 4.13 = 0.484261.
  //     Rendering "48" and committing 0.48 meant merely clicking into the field
  //     and clicking away rewrote the stored stop, with no edit and no
  //     confirmation, moving the alert threshold from $2.130 to $2.148.
  //   - A fraction below 0.005 rendered "0" and one at or above 0.995 rendered
  //     "100", neither of which `commit` will accept back (it bounds at
  //     0 < pct < 100), so the field sat showing a value it would itself reject.
  //     The card's premium-stop field has min={0.01}, so a $0.01 stop on a
  //     $5.20 premium derives 0.0019 and lands exactly there.
  //
  // Keeping the precision the store holds makes focus-blur a true round-trip.
  const stored = own != null ? String(Number((own * 100).toFixed(2))) : '';

  // DRAFT-THEN-COMMIT. This editor reached the pattern first, across rounds 4
  // and 5: it holds a stop PERCENTAGE, whose intermediate values are live risk
  // settings, so typing "45" used to persist 4% first -- below the noise on
  // essentially any contract -- and the 30s alert scan in between fired a
  // Critical PREMIUM_STOP for a threshold that existed for one keystroke.
  //
  // The EditField siblings above once persisted on every keystroke instead, on
  // the argument that they hold a stop PRICE, where an intermediate value is
  // merely a level not yet reached. Round 10's magnitude range broke that
  // argument (an intermediate value is now REJECTED, so the field cannot reach
  // the number being typed) and round 11 found what it cost: a deleted stop and
  // a position that can no longer raise STOP_REACHED. They use this same
  // pattern now -- see the round 11 note on EditField.
  const [draft, setDraft] = useState(stored);
  // WHY A REVERT NOW SAYS SO. Every rejecting path below used to
  // `setDraft(stored)` in silence: type 5, blur, and the field simply shows 45
  // again with no reason given, which reads as a field that ignores you rather
  // than one that refused a value. The EditField siblings above have said why
  // since round 11; this one holds the tighter band, so it needs it more.
  const [rejected, setRejected] = useState<string | null>(null);
  // A BLUR IS NOT AN EDIT. `commit` runs on every blur, so clicking into the
  // field to read it and clicking away used to PATCH the server. Comparing the
  // committed value against the stored one is not enough on its own: the
  // stored fraction is `premiumStopDollar / entry_price`, e.g.
  // `2.00 / 4.13 = 0.48426150121065376`, which no fixed number of decimals in
  // the editor round-trips exactly -- rendering "48.43" and committing 0.4843
  // still differs from 0.484261..., so a bare focus-and-blur rewrote the stop.
  // Same lesson as TradeCard's premium-stop field: track whether the user
  // actually typed, rather than inferring it from values.
  const dirtyRef = useRef(false);
  // Follow the stored value when it changes from outside (a different position
  // in the drawer, a sync) but never while the user is mid-edit on this one.
  //
  // "never while the user is mid-edit" is enforced by consulting dirtyRef, not
  // merely asserted: the drawer re-renders on the 30s syncFromBackend, so a
  // sync (or a second client) landing a new value mid-typing would otherwise
  // overwrite the characters in the field -- and leave dirtyRef set, feeding
  // the spurious PATCH above. The stored value is still RECORDED so the next
  // external change is detected against the current one; only the visible
  // draft is left alone.
  const lastStoredRef = useRef(stored);
  if (lastStoredRef.current !== stored) {
    lastStoredRef.current = stored;
    if (!dirtyRef.current && draft !== stored) setDraft(stored);
    // NOT cleared here -- decision Q15, same as the EditField siblings above:
    // only the user's own keystroke or commit retires a rejection.
  }

  // Every REJECTING exit goes through here, so none of them can forget to
  // clear `dirtyRef` (the defect the round-5 note below describes) or to
  // explain itself. Not every exit that keeps the previous value: the
  // successful path below also keeps it whenever the committed value matches
  // what is stored, and that is a no-op, not a refusal.
  const revert = (msg: string | null) => {
    setDraft(stored);
    setRejected(msg);
    dirtyRef.current = false;
  };

  const commit = () => {
    // A BLUR IS NOT AN EDIT -- and now that a rejection SAYS SO, the old
    // "check dirtyRef at each write" shape was not enough. A row stored
    // outside the new band (a legacy stop, or one the backend derived against
    // a fill far from the mid the card bounded the dollar against) reached the
    // band check on a bare focus-and-blur with nothing typed, and the new
    // message accused the user of a value they never entered. `EditField` has
    // had this guard since round 11; this editor tracked dirtiness but still
    // ran the whole commit.
    if (!dirtyRef.current) { setDraft(stored); setRejected(null); return; }
    const raw = draft.trim();
    // Empty is the documented way back to inheriting, and the only way: see
    // the hint below.
    if (raw === '') {
      setDraft('');
      setRejected(null);
      // Clearing is only an edit if the user did it -- and the guard at the top
      // of `commit` is now what establishes that, so this asks only whether
      // there is an override to clear. (It used to re-test `dirtyRef` here,
      // which after that guard can no longer be false.)
      if (own != null) onChange({ premiumStopPct: null });
      dirtyRef.current = false;
      return;
    }
    // A COMPLETE decimal literal, or a no-op. Same round-9 finding as the trade
    // card's EditableKV, reached through a different parser: `Number("48.")` is
    // 48, so a user part-way through typing 48.5 who tabbed away PATCHed a live
    // per-position alert threshold to 0.48. Round 8 moved this input to
    // type="text" precisely so half-typed literals would stop being sanitized
    // to "" and misread as the clear-to-inherit gesture -- which is exactly
    // what lets an interrupted literal reach `Number` intact.
    //
    // ".5" is a complete way to write 0.5 and stays accepted; a trailing point
    // is the interrupted case. Reverting to `stored` is the same honest answer
    // the two bounds checks below give.
    if (!/^-?(?:\d+(?:\.\d+)?|\.\d+)$/.test(raw.trim())) {
      revert('Not a complete number — kept the previous value.');
      return;
    }
    const pct = Number(raw);
    // Out of range REVERTS, it does not clear. It used to clear, so typing
    // 100 -- the natural way to ask for "hold it to zero" -- silently dropped
    // the override and handed the position back to the global, i.e. a TIGHTER
    // stop than the one asked for, with the typed digits gone and no message.
    // The backend bounds this at (0, 1) exclusive, so 100 has no
    // representation; showing the previous value back is the honest answer.
    // dirtyRef is cleared on EVERY exit from commit, revert paths included.
    // Leaving it set on a revert re-opened the exact defect it was added to
    // close: type 100, blur (reverted, still "dirty"), then click into the
    // field to read it and click away -- the second commit sees a clean draft,
    // a still-true dirtyRef, and a rounded value that does not equal the
    // unrounded stored fraction, and PATCHes a live risk setting nobody
    // touched.
    // Still load-bearing, and now REACHABLE -- the guard above rejects a
    // non-numeric draft first, but this one is what stops any future edit to
    // that regex from letting a NaN through to the bounds checks (where
    // `!(NaN > 0 && NaN < 1)` happens to revert, by luck rather than design).
    if (!Number.isFinite(pct)) { revert('Not a complete number — kept the previous value.'); return; }
    // 4dp on the fraction == 2dp on the percent, the precision `stored` renders.
    const next = Number((pct / 100).toFixed(4));
    // BOUNDED ON THE ROUNDED VALUE, not on the typed one. The column's contract
    // is the OPEN interval (0, 1) and the backend enforces `gt=0, lt=1`, but
    // rounding happens after the check: 0.004 typed passed a `pct > 0` guard
    // and then rounded to 0.0000, and 99.996 passed `pct < 100` and rounded to
    // 1.0000. Both 422 server-side -- and `updatePosition` writes optimistically
    // with no revert, so the rejected value sat in local state for up to 30s.
    // A stored 0 is the dangerous one: the threshold becomes `entry * (1 - 0)`,
    // i.e. the entry itself, so EVERY position at or below entry raised a
    // Critical PREMIUM_STOP toast on every 30s scan with no backend alert
    // behind it.
    //
    // ROUND 12 finding 13 — the band is now `premiumStop.ts`'s, the same one
    // TradeCard's dollar field derives its bounds from. The two editors of
    // this one number used to disagree about what a stop even is: the card
    // refuses anything below 10% of the mid (a 0.19% stop raises a Critical
    // PREMIUM_STOP on the first cent of adverse move), while this field, editing
    // the same `premiumStopPct` on the same position, accepted 0.01% — and
    // advertised it in its own hint. Anything the card will not create could
    // still be typed onto the position here.
    //
    // The old `(0, 1)` mirrored the BACKEND schema, which stays as it is: it
    // is the outer bound, and a row created before this band existed still has
    // to load and be editable upward. Below the floor is now a REVERT with a
    // reason, not a 422 and not a silent snap-back.
    if (!(next >= PREMIUM_STOP_MIN_PCT && next <= PREMIUM_STOP_MAX_PCT)) {
      revert(
        `Must be between ${premiumStopPctLabel(PREMIUM_STOP_MIN_PCT)} and `
        + `${premiumStopPctLabel(PREMIUM_STOP_MAX_PCT)} — kept the previous value.`,
      );
      return;
    }
    // STOP-SEMANTICS (b) -- a stop whose threshold is below $0.01 at THIS
    // entry can never fire; the backend refuses it (late 422), so refuse it
    // here first, with the reason, the same way as the band.
    if (premiumStopIsSubCent(position.entryPrice, next, shortStock)) {
      revert(
        `At this entry a ${premiumStopPctLabel(next)} stop fires below $0.01 and could never fire — kept the previous value.`,
      );
      return;
    }
    // COMPARED AT THE EDITOR'S OWN PRECISION, not against the raw stored
    // fraction. `stored` renders `own` at 2dp of a percent, and `next` is
    // re-derived from the typed text at 4dp of a fraction, so for any `own`
    // that is not exactly representable at 2dp the two never agree -- and the
    // stored fraction is `premiumStopDollar / entry_price` (e.g.
    // `2.00 / 4.13 = 0.48426150121065376`), so it usually is not. dirtyRef
    // alone does not save this: it only asks "did the user type", and typing a
    // character and deleting it back to the value already on screen is
    // typing. That path PATCHed 0.4843 over 0.484261..., silently moving a
    // live alert threshold on a field the user restored by hand.
    //
    // 2dp of a percent is all this editor can express, so a draft that renders
    // identically to `stored` IS the stored value as far as it is concerned.
    // `next !== own` is kept as well: it still catches the case where the
    // rendered text differs but the derived fraction does not.
    // DERIVED FROM `next`, NOT FROM THE TYPED `pct` -- defensively, not as a
    // bug fix. Round 2 of the follow-up audit argued the two could disagree
    // (typing 10.005 storing 0.1 while showing "10.01"); they cannot, because
    // `next` quantises to 0.0001 of a fraction, which is exactly the 0.01 of a
    // percent this line renders, so double-rounding has nothing left to lose.
    // The change is that the visible text and the stored value are now derived
    // from ONE expression -- the same one `stored` uses -- rather than two
    // that happen to agree. A future edit to either quantisation would
    // otherwise separate them silently.
    const rendered = String(Number((next * 100).toFixed(2)));
    setDraft(rendered);
    setRejected(null);
    // `dirtyRef` is guaranteed true by the guard at the top of `commit`; what
    // is left is the two value comparisons, which is what this line was always
    // really asking.
    if (rendered !== stored && next !== own) onChange({ premiumStopPct: next });
    dirtyRef.current = false;
  };

  return (
    <label className={styles.editField}>
      <Text size={11} tone="secondary">
        {/* P2-13 -- a stock position's percent stop is a STOCK price level,
            not a premium. STOP-SEMANTICS-2026-10-02: a short's fires on a
            RISE (entry x (1 + pct)), a long's on a fall (entry x (1 - pct)). */}
        {isStock
          ? `Stock stop — fires ${formatPremiumStopPct(own, globalPremiumStopPct)} ${shortStock ? 'above' : 'below'} entry`
          : `Premium stop — ${formatPremiumStopPct(own, globalPremiumStopPct)}`}
      </Text>
      <input
        // TEXT, not number. `<input type="number">` sanitizes its value, so
        // `e.target.value` is "" for any half-typed literal -- "48." and ".5"
        // included. On THIS field an empty draft means "clear the override and
        // inherit the global", and `commit` PATCHes that to the server: a user
        // with a 48.43% stop who reopens the field to make it 48.50, types
        // "48." and tabs away had their per-position stop deleted. The two
        // cases are the same string, so no check on `draft` can separate them;
        // the input has to stop throwing the keystrokes away. Bounds are
        // enforced in `commit` (which reverts, not clamps), not by the browser.
        type="text"
        inputMode="decimal"
        className={styles.editInput}
        // ROUND 10 finding 17 -- through the shared helper, not Math.round.
        // A global of 0.605 rendered "60.5% (global)" in the label two lines
        // up and "61" here, the exact 0%/100% lossiness `premiumStopPctLabel`
        // was extracted to remove (round 5 fixed it on the Alerts page and
        // left the component the helper came from).
        placeholder={`${premiumStopPctLabel(globalPremiumStopPct)} (global)`}
        aria-label="Premium stop percent"
        value={draft}
        onChange={(e) => { dirtyRef.current = true; setRejected(null); setDraft(e.target.value); }}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commit(); } }}
      />
      <Text size={10} tone="dim">
        {inherited
          ? `Inheriting the global — this position moves whenever the global does. Enter a percent (${premiumStopPctLabel(PREMIUM_STOP_MIN_PCT)}–${premiumStopPctLabel(PREMIUM_STOP_MAX_PCT)}) and press Enter to pin it${isStock ? '' : ' for this contract only'}.`
          // The band belongs on THIS branch too, and arguably more: a position
          // that already carries its own stop is the one being edited when the
          // bound is hit, and it used to learn the field had a floor only from
          // the rejection.
          : `Set for this position only (${premiumStopPctLabel(PREMIUM_STOP_MIN_PCT)}–${premiumStopPctLabel(PREMIUM_STOP_MAX_PCT)}). Clear the field to go back to inheriting the global (${premiumStopPctLabel(globalPremiumStopPct)}).`}
      </Text>
      {outsideBand && (
        // P2-04 (decision Q9) -- a stored ratio outside the band fires as
        // stored; the dollar stop is the truth. Said, not changed.
        <Text size={10} tone="caution">
          {`Stored at ${premiumStopPctLabel(own as number)} of the fill — outside the ${premiumStopPctLabel(PREMIUM_STOP_MIN_PCT)}–${premiumStopPctLabel(PREMIUM_STOP_MAX_PCT)} the editors accept, because it was set in dollars against the mid. It fires as stored.`}
        </Text>
      )}
      {globalNeverFires ? (
        // R2-7 / R4-1 -- only a global of 100% or more can never fire. A
        // stored 99.5% does fire (at entry x 0.005) and gets no claim here.
        <Text size={10} tone="caution">
          The global stop is 100% and can never fire — lower it in Settings.
        </Text>
      ) : subCent && (
        // STOP-SEMANTICS (b) -- new sub-cent stops are refused at save, so this
        // is only reachable two ways: an INHERITED global that is sub-cent at
        // this entry (the global has no entry and is not refused, Q1), or an
        // own value stored before the refusal existed.
        <Text size={10} tone="caution">
          {inherited
            ? 'At this entry the global stop fires below $0.01 and can never fire — pin a lower percent.'
            : 'Stored before sub-cent stops were refused; it can never fire — set a lower percent.'}
        </Text>
      )}
      <span aria-live="polite">
        {rejected && <Text size={10} tone="caution">{rejected}</Text>}
      </span>
    </label>
  );
}

/* ------------------------------------------------------------------------ *
 * Feature D (docs/superpowers/plans/2026-08-26-exit-plan-pipeline.md)
 * ------------------------------------------------------------------------ */

/** Label + resolved stock price for each selectable TP method. A method whose
 *  price can't be resolved yet (no exit plan computed, no Monte Carlo run, no
 *  ladder target) comes back with `price: null` and is rendered disabled —
 *  picking it would stamp a null snapshot, which alertEngine would silently
 *  fall back to the ladder for, i.e. a selector that appears to do nothing. */
function tpMethodOptions(
  position: PortfolioPosition,
  mcTargetPrice: number | null,
): { method: TpMethod; label: string; price: number | null }[] {
  const exitPlan = position.exitPlan;
  // A non-positive price is "not resolvable", not a real level — 0 is never a
  // valid stock price here (see floorStop's convention in portfolioStore), and
  // both the ladder targets and the option-side Monte Carlo mapping can yield
  // one. Collapsing it to null renders the option disabled instead of offering
  // a "$0.00" method that would make TP_HIT fire on every tick.
  const usable = (p: number | null | undefined) => (p != null && p > 0 ? p : null);
  // POSITIONAL, NOT BY LITERAL R MULTIPLE — spec §4.3, fixed in Phase G build
  // step 3. `exit_plan_2r` / `exit_plan_3r` are row ORDINALS whose names
  // predate `rr_ratios` being configurable; they are NOT the numbers 2 and 3.
  // This used to be `targets.find((t) => t.rrRatio === rr)` with `rr` hardcoded
  // to 2 and 3, and under `rr_ratios: [1.5, 4.0]` that found nothing: the
  // backend seeds `exit_plan_2r` from the FIRST configured row (1.5R) and
  // TP_HIT fires there, while this selector rendered "2R plan" as the active
  // method with a null price beside it. The screen then named the active method
  // and showed no price while a real level drove the alert.
  //
  // Reading `targets[i]` is exactly the backend's rule expressed against the
  // plan on screen: `routers/contracts.py` builds `targets_out` by iterating
  // `rr_ratios` in order and appends EVERY row (a row it cannot score still
  // appends, with probability 0), so index i of `targets` is `rr_ratios[i]`.
  // `picked_method.py::_seed_for_rr` maps by the same ordinal.
  //
  // It also reads the ratios off the PLAN rather than off config, which is the
  // stronger choice for a drawer: a position's stored `exitPlan` was computed
  // under whatever `rr_ratios` were configured at the time, and the label must
  // match the row it is standing next to, not today's config.
  const row = (i: number) => exitPlan?.targets[i];
  // LABELLED FROM THE ROW'S OWN RATIO, so a 1.5R row reads "1.5R plan" instead
  // of being mislabelled "2R". Falls back to the enum's historical name only
  // when there is no row to read a ratio from — at which point the option is
  // disabled anyway (`price == null`), so the fallback is never a claim about a
  // number on screen.
  const rrLabel = (i: number, fallback: string) => {
    const rr = row(i)?.rrRatio;
    return rr != null ? `${rr}R plan` : fallback;
  };
  // mcTargetPrice comes from ephemeral component state (`mcResult`), which
  // starts null on every EditDrawer mount — it holds this SESSION's re-run,
  // not the persisted one. When Monte Carlo is the position's active method
  // and nothing's been re-run yet, fall back to the stamped `resolvedTpPrice`
  // so reopening the drawer doesn't show its own active method as unresolved.
  const mcPrice = usable(mcTargetPrice) ??
    (position.activeTpMethod === 'monte_carlo' ? usable(position.resolvedTpPrice) : null);
  return [
    { method: 'ladder',       label: 'Ladder',      price: usable(position.targets[0]?.stockPrice) },
    { method: 'monte_carlo',  label: 'Monte Carlo', price: mcPrice },
    { method: 'exit_plan_2r', label: rrLabel(0, '2R plan'), price: usable(row(0)?.price) },
    { method: 'exit_plan_3r', label: rrLabel(1, '3R plan'), price: usable(row(1)?.price) },
  ];
}

/** Build the patch that switches a position's active TP method.
 *
 *  'ladder' deliberately stamps `resolvedTpPrice: null` rather than the current
 *  first-target price: the ladder is the one method that should keep tracking
 *  its target live (the user edits those targets right here in this drawer), so
 *  a snapshot would go stale the moment they did. Every other method IS a
 *  snapshot, refreshed only when the user re-computes its source.
 *
 *  Exported for the unit tests — the stamping rule, not the click handler, is
 *  the part worth pinning down. */
export function tpMethodPatch(
  method: TpMethod,
  price: number | null,
  now: string = new Date().toISOString(),
): Partial<PortfolioPosition> {
  return method === 'ladder'
    ? { activeTpMethod: 'ladder', resolvedTpPrice: null, resolvedTpUpdatedAt: now }
    : { activeTpMethod: method, resolvedTpPrice: price, resolvedTpUpdatedAt: now };
}

/** The four pick labels, spelled exactly as the two cards that WRITE the pick
 *  spell them (`TradeCard`'s `methodPickOptions`, `StockPositionCard`'s
 *  three-option subset) — a trader must be able to read this record back and
 *  recognise the button they pressed. `Record<PickedMethod, string>` rather
 *  than a partial map on purpose: adding a fifth method to the union then
 *  fails typecheck here instead of silently rendering `undefined`. */
const PICKED_METHOD_LABELS: Record<PickedMethod, string> = {
  ladder:       'Ladder',
  arithmetic:   'Arithmetic',
  monte_carlo:  'Monte Carlo',
  barrier_race: 'Barrier Race',
};

const PICKED_STOP_BASIS_LABELS: Record<PickedStopBasis, string> = {
  stock:   'Stock',
  premium: 'Premium',
};

/** Phase G (piece 5, D4/D5) — the RECORD of what the trader actually picked.
 *
 *  WHY THIS EXISTS AT ALL, because it renders no number the alert engine reads
 *  and a future reader will be tempted to delete it as decoration. Spec §4.3
 *  discharges four of its eight mapping rows with one sentence: "The portfolio
 *  displays `picked_method`, never `active_tp_method`, so a degraded seed costs
 *  the ALERT its precision and costs the RECORD nothing." Four rows of that
 *  table deliberately degrade to `('ladder', NULL)` — every `barrier_race`
 *  pick, a `monte_carlo` pick whose row carried no underlying level, and an
 *  arithmetic pick on a row the configured `rr_ratios` cannot map. Until this
 *  block existed the second half of that sentence was false: `TpMethodSelector`
 *  below is the only method on screen, it renders `activeTpMethod ?? 'ladder'`,
 *  and so a trader who picked the Barrier Race was shown "Ladder" with nothing
 *  anywhere telling them otherwise. The record was being kept and never shown.
 *
 *  IT READS `pickedMethod` AND NEVER `activeTpMethod`. Those are different
 *  questions — the pick is the input to §4.3's mapping, the active method is
 *  its server-derived output — and showing the output here would reintroduce
 *  exactly the lie this block was added to remove.
 *
 *  NULL RENDERS "—", NEVER "Ladder" (§4.2, and D11 via §9.7). A null pick is a
 *  REAL state, not a missing value: the position predates Phase G, or it was
 *  opened by the S5 after-scan auto-executor, which is exempt from the send
 *  gate (§7.3) and creates positions with all five fields null. `fromBackend`
 *  is already careful to pass these through with no `'ladder'`-style default
 *  (portfolioStore.ts) — coercing one in here would throw that away at the last
 *  step.
 *
 *  THE TWO PRICES ARE LABELLED WITH THEIR SPACES AND ARE NOT INTERCHANGEABLE.
 *  `pickedRowStockPrice` is underlying space and is the only one of the five
 *  that may ever seed `resolved_tp_price`; `pickedRowOptionPrice` is premium
 *  space and is record-only. They are rendered as two separately labelled rows
 *  rather than one "price" for the same reason §4.1 split the field names: a
 *  $6.24 premium read as a stock level makes `price >= 6.24` true on the first
 *  tick and fires TP_HIT instantly on every bullish position. Nothing here
 *  writes, so this cannot cause that — but this is the one screen where a
 *  reader checks the two against each other, and an un-suffixed label is what
 *  would make a real mix-up invisible.
 *
 *  IT DOES NOT RE-DERIVE §4.3's MAPPING to say whether the pick and the active
 *  method diverge. That rule lives server-side in `picked_method.py` and the
 *  spec is explicit that it must not be copied; a second copy here would be a
 *  third place to keep in sync and could state a divergence that isn't one
 *  (`arithmetic` correctly maps to `exit_plan_2r`/`3r`, which is the same
 *  choice under another name, not a degradation). The hint states the
 *  relationship in words instead, which cannot drift out of sync. */
function PickedMethodRecord({ position }: { position: PortfolioPosition }) {
  const method = position.pickedMethod ?? null;
  const basis = position.pickedStopBasis ?? null;
  const pickedAt = position.pickedAt ?? null;
  // Same `> 0` guard `tpMethodOptions` applies to every price it renders, and
  // the same one the backend enforces with `gt=0` on both fields. A zero that
  // slipped past an upstream `?? 0` is not a price and must not print as one.
  const prices = ([
    ['Stock', position.pickedRowStockPrice],
    ['Premium', position.pickedRowOptionPrice],
  ] as const).filter(([, p]) => p != null && p > 0);

  return (
    <div className={styles.targetEditor}>
      <Text size={11} tone="secondary">Picked at trade</Text>
      <div className={styles.pickedRecordRow}>
        {/* `Text`, not `Data` — a method NAME is a label, not a number, and
            `TpMethodSelector` below spells its own labels the same way. The
            prices further down are the only `Data` in this block. */}
        <Text size={13} weight={500} tone={method ? 'primary' : 'dim'}>
          {method ? PICKED_METHOD_LABELS[method] : '\u2014'}
        </Text>
        {basis && (
          <Text size={11} tone="secondary">{PICKED_STOP_BASIS_LABELS[basis]} stop</Text>
        )}
        {pickedAt && (
          <Text size={10} tone="dim">picked {new Date(pickedAt).toLocaleString()}</Text>
        )}
      </div>
      {prices.length > 0 && (
        <div className={styles.pickedRecordRow}>
          {prices.map(([label, price]) => (
            <span key={label} className={styles.pickedRecordPrice}>
              <Text size={10} tone="dim">{label}</Text>
              <Data size={11}>${price!.toFixed(2)}</Data>
            </span>
          ))}
        </div>
      )}
      <Text size={10} tone="dim">
        {method
          ? 'The method you chose for this trade, frozen when it was sent. The active TP method below is derived from this pick and can differ \u2014 a pick carrying no underlying level falls back to the ladder for alerting. Only the alert degrades; this record keeps the choice.'
          : 'No pick recorded \u2014 this position was opened before per-trade method picks existed, or by the after-scan auto-executor, which places orders with no human in the loop.'}
      </Text>
    </div>
  );
}

function TpMethodSelector({
  position,
  mcTargetPrice,
  onChange,
}: {
  position: PortfolioPosition;
  mcTargetPrice: number | null;
  onChange: (patch: Partial<PortfolioPosition>) => void;
}) {
  const active = position.activeTpMethod ?? 'ladder';
  const options = tpMethodOptions(position, mcTargetPrice);

  return (
    <div className={styles.targetEditor}>
      <Text size={11} tone="secondary">Active TP method</Text>
      <div className={styles.tpMethodRow} role="radiogroup" aria-label="Active TP method">
        {options.map((o) => (
          <button
            key={o.method}
            type="button"
            role="radio"
            aria-checked={active === o.method}
            aria-label={o.label}
            disabled={o.price == null}
            className={active === o.method ? styles.tpMethodBtnActive : styles.tpMethodBtn}
            onClick={() => onChange(tpMethodPatch(o.method, o.price))}
          >
            <Text size={11} weight={500}>{o.label}</Text>
            <Data size={11} weight={400} tone="dim">
              {o.price != null ? `$${o.price.toFixed(2)}` : '—'}
            </Data>
          </button>
        ))}
      </div>
      <Text size={10} tone="dim">
        Drives this position&apos;s TP_HIT alert. The ladder tracks its first target live;
        the other methods snapshot a price when picked, refreshed only when you re-compute them.
      </Text>
    </div>
  );
}

/** What price (or window) each position-scoped alert type currently fires
 *  against, for the "fires at" line under each toggle. Returns null when the
 *  type has no threshold set on this position, which the UI renders as "not
 *  set" — an alert that is switched on but has nothing to compare against
 *  should say so rather than look armed. */
function alertFiresAgainst(
  position: PortfolioPosition,
  type: PositionAlertType,
  /** The GLOBAL premium stop. Resolved against the position's own value below
   *  (piece 4) so this preview cannot disagree with the alert that fires. */
  globalPremiumStopPct: number,
): string | null {
  const isStock = position.contract.endsWith('|STOCK');
  switch (type) {
    case 'TP_HIT': {
      // Same snapshot-then-ladder resolution (and same `> 0` rule) the alert
      // engine uses, so this line can never disagree with what actually fires.
      const snapshot = position.resolvedTpPrice != null && position.resolvedTpPrice > 0
        ? position.resolvedTpPrice : null;
      const price = snapshot ?? position.targets[0]?.stockPrice ?? null;
      return price != null && price > 0 ? `stock $${price.toFixed(2)}` : null;
    }
    case 'STOP_REACHED':
      return position.stop != null ? `stock $${position.stop.toFixed(2)}` : null;
    case 'STRUCTURAL_STOP_BREACHED':
      return position.structuralStop != null ? `stock $${position.structuralStop.toFixed(2)}` : null;
    case 'PREMIUM_STOP':
      // The backend's threshold (entry_price * (1 - premiumStopPct)) is
      // compared against fetch_contract_quote_async's price for the position's
      // own contract, which for a `|STOCK` position IS the stock quote, not an
      // option premium (see market.py's stock-format branch — `opt_price` is
      // just this generic "current quote for pos.contract", named for the
      // option case it originated from). Labeling that threshold "premium"
      // for a stock position misattributes a stock-price level as an option
      // concept the position doesn't even have.
      // Resolved through `premiumStopFiringPrice`, NOT rounded and not floored
      // inline. Both engines compare `currentPrice <= threshold` at FULL
      // precision, and a server-derived stop is `premiumStopDollar /
      // entry_price`, so the threshold almost never lands on a whole cent:
      // entry $5.20 at 0.4855 gives 2.6754, which `toFixed(2)` advertised as
      // "Fires at premium $2.68" -- above the threshold, firing nothing.
      //
      // Flooring fixed that case and not the general one: `Math.floor(t * 100)
      // / 100` rounds `t * 100` up onto the exact integer on about 3% of
      // ordinary positions, printing a price still ABOVE the threshold. Entry
      // $4.00 at 7% printed "$3.72" where the alert arms at $3.71. The helper
      // steps back a cent when that happens; see its own doc.
      //
      // STOP-SEMANTICS-2026-10-02 -- a short stock's stop fires on a RISE; the
      // helper then names the smallest 2dp price at or above its threshold.
      return position.entryPrice > 0
        ? `${isStock ? 'stock' : 'premium'} $${percentStopFiringPrice(
            position.entryPrice,
            resolvePremiumStopPct(position.premiumStopPct, globalPremiumStopPct),
            isShortStockPosition(position.contract, position.direction),
          ).toFixed(2)}`
        : null;
    case 'TIME_STOP':
      // Stock positions carry no expiry. STOCKS-HORIZON-T1 H6: one sent with
      // the scan's hold fires once held that many days (alertEngine.ts's
      // stock rule); without a hold it never fires — "not set" rather than a
      // threshold that looks armed but isn't.
      if (isStock) return position.holdMaxDays != null ? `held ≥ ${position.holdMaxDays} days` : null;
      return `${TIME_STOP_DTE} DTE or less`;
    case 'EVENT_RISK':
      return 'event within 3 days';
  }
}

const ALERT_TYPE_LABELS: Record<PositionAlertType, string> = {
  TP_HIT:                   'Target hit',
  STOP_REACHED:             'Stop reached',
  STRUCTURAL_STOP_BREACHED: 'Structural stop',
  PREMIUM_STOP:             'Premium / stock stop',
  TIME_STOP:                'Time stop',
  EVENT_RISK:               'Event risk',
};

/** Per-position alert-type overrides. Three states per row — Inherit / On /
 *  Off — where Inherit is the DEFAULT and is visually distinct from an
 *  explicit On even when the global setting is also on, because the two behave
 *  differently the moment the user changes the global. Inherit is stored as an
 *  absent key, not `undefined`, so the persisted JSON matches the backend's
 *  `alert_overrides` column exactly. */
function AlertOverridesEditor({
  position,
  onChange,
}: {
  position: PortfolioPosition;
  onChange: (patch: Partial<PortfolioPosition>) => void;
}) {
  const globalEnabled = useAlertStore((s) => s.config.enabledTypes);
  const premiumStopPct = useSettingsStore((s) => s.premiumStopPct);
  const overrides = position.alertOverrides ?? {};

  const setOverride = (type: PositionAlertType, value: boolean | null) => {
    const next: AlertOverrides = { ...overrides };
    if (value === null) delete next[type];
    else next[type] = value;
    onChange({ alertOverrides: next });
  };

  return (
    <div className={styles.targetEditor}>
      <Text size={11} tone="secondary">Alerts for this position</Text>
      <div className={styles.alertOverrideList}>
        {POSITION_ALERT_TYPES.map((type) => {
          const override = overrides[type];
          const inherited = globalEnabled.includes(type);
          const effective = override ?? inherited;
          const firesAgainst = alertFiresAgainst(position, type, premiumStopPct);
          const states: { value: boolean | null; label: string }[] = [
            { value: null,  label: `Inherit (${inherited ? 'on' : 'off'})` },
            { value: true,  label: 'On' },
            { value: false, label: 'Off' },
          ];
          return (
            <div key={type} className={styles.alertOverrideRow}>
              <div className={styles.alertOverrideHeader}>
                <Text size={12} weight={500}>{ALERT_TYPE_LABELS[type]}</Text>
                <div className={styles.tpMethodRow} role="radiogroup" aria-label={`${ALERT_TYPE_LABELS[type]} alert`}>
                  {states.map((s) => (
                    <button
                      key={String(s.value)}
                      type="button"
                      role="radio"
                      aria-checked={(override ?? null) === s.value}
                      aria-label={`${ALERT_TYPE_LABELS[type]}: ${s.label}`}
                      className={(override ?? null) === s.value ? styles.tpMethodBtnActive : styles.tpMethodBtn}
                      onClick={() => setOverride(type, s.value)}
                    >
                      <Text size={10} weight={500}>{s.label}</Text>
                    </button>
                  ))}
                </div>
              </div>
              <Text size={10} tone={effective ? 'dim' : 'secondary'}>
                {effective
                  ? (firesAgainst ? `Fires at ${firesAgainst}.` : 'On, but no level is set on this position yet.')
                  : 'Off — this position raises no alert of this type.'}
              </Text>
            </div>
          );
        })}
      </div>
    </div>
  );
}
