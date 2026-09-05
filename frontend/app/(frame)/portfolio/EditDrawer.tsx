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
import { flushPendingPositionPatches, useIsSymbolHeld } from '@/lib/portfolioStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { useRiskStore } from '@/lib/riskStore';
import { maxLossAtStop, resolveMaxLossLimitDollar, recommendedContractSize, formatRecommendedContractSizeRaw } from '@/lib/risk';
import { useSettingsStore } from '@/lib/settingsStore';
import { _horizonEnum } from '@/lib/analysisStore';
import { useAlertStore } from '@/lib/alertStore';
import { api } from '@/lib/api';
import { POSITION_ALERT_TYPES } from '@/types/domain';
import type { PortfolioPosition, AlertOverrides, PositionAlertType, TpMethod } from '@/types/domain';
import styles from './page.module.css';
import { resolvePremiumStopPct, hasOwnPremiumStopPct, premiumStopThresholdPrice, formatPremiumStopPct } from '@/lib/premiumStop';

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
        restampIfActive('monte_carlo', targets[0]?.price ?? null);
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
        restampIfActive('monte_carlo', targets[0]?.price ?? null);
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

  return (
    <div className={styles.editDrawer}>
      <div className={styles.editHeader}>
        <Text size={12} weight={400}>Edit {position.contract}</Text>
        <button type="button" className={styles.editClose} onClick={onClose} aria-label="Close editor">×</button>
      </div>

      <div className={styles.editGrid}>
        <EditField
          label="Stop"
          hint="Exit if the underlying stock drops below this price (invalidates the trade thesis)."
          value={position.stop ?? 0}
          onChange={(n) => onChange({ stop: n > 0 ? n : null })}
        />
        <EditField
          label="Structural stop"
          hint="Tighter, chart-based stop (order block / swing level) from Check structure. Optional — 0 means none was captured."
          value={position.structuralStop ?? 0}
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
        <TpMethodSelector
          position={position}
          mcTargetPrice={mcResult?.targets[0]?.price ?? null}
          onChange={onChange}
        />
        <AlertOverridesEditor position={position} onChange={onChange} />
        <EditField
          label="Contracts"
          hint="Number of option contracts held."
          value={position.contracts ?? 1}
          step={1}
          onChange={(n) => onChange({ contracts: Math.max(1, Math.round(n)) })}
        />
        <EditField
          label="Current price"
          hint="Manual override — will refresh from broker in live mode."
          value={position.currentPrice}
          onChange={(n) => {
            const mult = position.contract.endsWith('|STOCK') ? 1 : 100;
            const pnlDollar = (n - position.entryPrice) * mult * (position.contracts ?? 1);
            const pnlPct    = ((n - position.entryPrice) / position.entryPrice) * 100;
            onChange({ currentPrice: n, pnlDollar, pnlPct });
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
          Stop, structural stop, targets, and contract count save to your account automatically.
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
      });
      const plan = { ...res, computedAt: new Date().toISOString() };
      // Feature D: a re-computed plan re-stamps the TP snapshot when one of its
      // rows is the active TP method — the same "refresh only on a manual
      // re-compute" rule the Monte Carlo path follows. Sent as ONE patch so the
      // plan and the snapshot derived from it can never be persisted apart.
      const active = position.activeTpMethod ?? 'ladder';
      const rr = active === 'exit_plan_2r' ? 2 : active === 'exit_plan_3r' ? 3 : null;
      const rawRowPrice = rr != null ? plan.targets.find((t) => t.rrRatio === rr)?.price ?? null : null;
      // `> 0`, not just non-null — same rule as the Monte Carlo path's
      // restampIfActive: a 0 price would make the alert engine's `price >= 0`
      // comparison true forever, so leave the previous snapshot in place instead.
      const rowPrice = rawRowPrice != null && rawRowPrice > 0 ? rawRowPrice : null;
      onChange({
        exitPlan: plan,
        ...(rr != null && rowPrice != null ? tpMethodPatch(active, rowPrice) : {}),
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

function EditField({
  label,
  hint,
  value,
  step = 0.05,
  onChange,
}: {
  label: string;
  hint?: string;
  value: number;
  step?: number;
  onChange: (n: number) => void;
}) {
  return (
    <label className={styles.editField}>
      <Text size={11} tone="secondary">{label}</Text>
      <input
        type="number"
        className={styles.editInput}
        step={step}
        value={value}
        onChange={(e) => {
          const n = Number(e.target.value);
          if (Number.isFinite(n)) onChange(n);
        }}
      />
      {hint && <Text size={10} tone="dim">{hint}</Text>}
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
  const own = position.premiumStopPct;
  const inherited = !hasOwnPremiumStopPct(own);
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

  // DRAFT-THEN-COMMIT, unlike the EditField siblings above, which persist on
  // every keystroke. Those hold a stop PRICE, where an intermediate value is
  // merely a level that has not been reached. This holds a stop PERCENTAGE,
  // and the intermediate values are live risk settings: typing "45" persists
  // 4% first, and a 4% premium stop is below the noise on essentially any
  // contract, so the 30s alert scan in between fires a Critical PREMIUM_STOP
  // for a threshold that existed for one keystroke.
  const [draft, setDraft] = useState(stored);
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
  }

  const commit = () => {
    const raw = draft.trim();
    // Empty is the documented way back to inheriting, and the only way: see
    // the hint below.
    if (raw === '') {
      setDraft('');
      // Clearing is only an edit if the user did it; a blur on an already-empty
      // (inheriting) field must not PATCH.
      if (dirtyRef.current && own != null) onChange({ premiumStopPct: null });
      dirtyRef.current = false;
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
    if (!Number.isFinite(pct)) { setDraft(stored); dirtyRef.current = false; return; }
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
    if (!(next > 0 && next < 1)) { setDraft(stored); dirtyRef.current = false; return; }
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
    const rendered = String(Number(pct.toFixed(2)));
    setDraft(rendered);
    if (dirtyRef.current && rendered !== stored && next !== own) onChange({ premiumStopPct: next });
    dirtyRef.current = false;
  };

  return (
    <label className={styles.editField}>
      <Text size={11} tone="secondary">
        Premium stop — {formatPremiumStopPct(own, globalPremiumStopPct)}
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
        placeholder={`${Math.round(globalPremiumStopPct * 100)} (global)`}
        aria-label="Premium stop percent"
        value={draft}
        onChange={(e) => { dirtyRef.current = true; setDraft(e.target.value); }}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commit(); } }}
      />
      <Text size={10} tone="dim">
        {inherited
          ? `Inheriting the global — this position moves whenever the global does. Enter a percent (0.01–99.99) and press Enter to pin it${isStock ? '' : ' for this contract only'}.`
          : `Set for this position only. Clear the field to go back to inheriting the global (${Math.round(globalPremiumStopPct * 100)}%).`}
      </Text>
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
  const rowPrice = (rr: number) =>
    usable(exitPlan?.targets.find((t) => t.rrRatio === rr)?.price);
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
    { method: 'exit_plan_2r', label: '2R plan',     price: rowPrice(2) },
    { method: 'exit_plan_3r', label: '3R plan',     price: rowPrice(3) },
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
      // FLOORED to cents, not rounded. Both engines compare
      // `currentPrice <= threshold` at FULL precision, and a server-derived
      // stop is `premiumStopDollar / entry_price`, so the threshold almost
      // never lands on a whole cent: entry $5.20 at 0.4855 gives 2.6754, which
      // `toFixed(2)` advertised as "Fires at premium $2.68" -- a price that is
      // ABOVE the threshold and fires nothing. Roughly half of all derived
      // stops rounded up like that. Flooring names a price that actually
      // fires, which is the whole contract of a preview (see premiumStop.ts:
      // "a preview that disagrees with the alert that later fires is worse
      // than no preview").
      return position.entryPrice > 0
        ? `${isStock ? 'stock' : 'premium'} $${(Math.floor(premiumStopThresholdPrice(
            position.entryPrice,
            resolvePremiumStopPct(position.premiumStopPct, globalPremiumStopPct),
          ) * 100) / 100).toFixed(2)}`
        : null;
    case 'TIME_STOP':
      // Stock positions carry no expiry and (per alertEngine.ts's isStock
      // guard) can never fire this type — "not set" rather than a threshold
      // that looks armed but isn't.
      return isStock ? null : '3 DTE or less';
    case 'EVENT_RISK':
      return 'event within 3 days';
  }
}

const ALERT_TYPE_LABELS: Record<PositionAlertType, string> = {
  TP_HIT:                   'Target hit',
  STOP_REACHED:             'Stop reached',
  STRUCTURAL_STOP_BREACHED: 'Structural stop',
  PREMIUM_STOP:             'Premium stop',
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
