'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { Text, Data } from '@/components/primitives';
import { useScanStore } from '@/lib/scanStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { buildPaperStockPosition, stockCardSnapshotOf, invalidTargetRungs } from '@/lib/paperTrade';
import { api } from '@/lib/api';
import { _horizonEnum } from '@/lib/analysisStore';
import { winRateTooltip } from '@/lib/statusTooltips';
import type { PositionCardData, StockFirstPassageEstimate, StockExitPlan } from '@/types/stockDomain';
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

// ─── Types ────────────────────────────────────────────────────────────────────

interface StockEditOverlay {
  entry: number;
  stop: number;
  shares: number;
  t1: number;
  t2: number;
  t3: number;
  sharesT1: number;
  sharesT2: number;
  sharesT3: number;
}

interface StockPositionCardProps {
  card: PositionCardData;
  strategyKey: string;
  afterScanArmed?: boolean;
  onAfterScanToggle?: (symbol: string, armed: boolean) => void;
}

type ExecMode = 'recommendation' | 'ibkr_paper' | 'tradier_paper' | 'alpaca_paper' | 'tastytrade_paper';

/** The subset of `/api/contracts/structural-stop`'s response this card keeps. */
interface StructuralStopResult {
  price: number;
  source: 'order_block' | 'swing_low' | 'swing_high' | null;
  confidence: number | null;
  distancePct: number | null;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function defaultOverlay(card: PositionCardData): StockEditOverlay {
  const entry = card.strategy.entry_price;
  const stop  = card.strategy.stop_price;
  const risk  = Math.abs(entry - stop);
  const dir   = card.direction;
  const sign  = dir === 'Bullish' ? 1 : -1;
  // T2/T3 used to be invented here as a flat 2R/3R — not strategy-derived, not
  // validated by any backtest, and invisible to the WFO tuner. They now come
  // from the backend ladder, which is built from each strategy's own exit
  // thesis. The R-step fill survives only as the fallback for a scan result
  // rehydrated from localStorage before `targets` existed (`?.length`, not
  // `??`: an empty array must fall back too).
  const round2 = (v: number) => Math.round(v * 100) / 100;
  const ladder = card.strategy.targets?.length
    ? card.strategy.targets
    : [card.strategy.target_price];
  // Missing rungs are filled by stepping ONE MORE R past the previous rung, not
  // by measuring 2R/3R from entry. Measuring from entry can place T2 nearer than
  // a strategy-derived T1 (a prior swing high 4R away leaves T2 = 2R behind it),
  // and stockPositionLevels() sorts the ladder nearest-first on the way into the
  // portfolio — so the persisted targets[0], which is the ONLY rung TP_HIT
  // fires on, would not be the rung the card showed as T1.
  // ladder is guaranteed non-empty by construction above, so ladder[0] is
  // never undefined — no `?? target_price` fallback needed here.
  const t1    = round2(ladder[0]);
  const t2    = round2(ladder[1] ?? t1 + sign * risk);
  const t3    = round2(ladder[2] ?? t2 + sign * risk);
  const s     = card.shares;
  const s1    = Math.floor(s / 3);
  const s2    = Math.floor(s / 3);
  return { entry, stop, shares: s, t1, t2, t3, sharesT1: s1, sharesT2: s2, sharesT3: s - s1 - s2 };
}

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

export function StockPositionCard({
  card,
  strategyKey,
  afterScanArmed,
  onAfterScanToggle,
}: StockPositionCardProps) {
  const [overlay, setOverlay] = useState<StockEditOverlay>(() => defaultOverlay(card));

  // Reset overlay and per-symbol outcome state when the selected symbol changes.
  // The two on-demand results (estimate, structural stop) are per-SYMBOL and
  // per-overlay, so showing AAPL's numbers under MSFT's header would be worse
  // than showing none. Their in-flight requests are aborted for the same reason:
  // a slow response for the previous symbol must never land on the new one.
  useEffect(() => {
    setOverlay(defaultOverlay(card));
    setAdded(false);
    setErr(null);
    setWarning(null);
    setQueued(false);
    setAdding(false);
    setOrderId(null);
    estimateReq.current?.abort();
    estimateReq.current = null;
    structuralReq.current?.abort();
    structuralReq.current = null;
    planReq.current?.abort();
    planReq.current = null;
    setPlan(null);
    setPlanErr(null);
    setPlanning(false);
    setEstimate(null);
    setEstimateErr(null);
    setEstimating(false);
    setStructural(null);
    setStructuralErr(null);
    setCheckingStructure(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [card.symbol]);

  const patch = useCallback((partial: Partial<StockEditOverlay>) => {
    setOverlay((prev) => {
      const next = { ...prev, ...partial };
      // Each rung's share count is edited independently (one EditableField per
      // T1/T2/T3 row), so nothing stops sharesT1+T2+T3 from exceeding the
      // position's total shares — which would tell the sell-to-close plan
      // (buildPaperStockPosition's contractsToSell) to sell more shares than
      // the position holds.
      const allocated = next.sharesT1 + next.sharesT2 + next.sharesT3;
      if (allocated > next.shares) {
        const shareKeys = ['sharesT1', 'sharesT2', 'sharesT3'] as const;
        const editedShareKeys = shareKeys.filter((k) => k in partial);
        if (editedShareKeys.length > 0) {
          // The rung the user just edited pushed the total over — clamp THAT
          // rung down to what's left after the others, rather than silently
          // shrinking a different rung they didn't touch.
          const othersSum = shareKeys
            .filter((k) => !editedShareKeys.includes(k))
            .reduce((sum, k) => sum + next[k], 0);
          for (const k of editedShareKeys) next[k] = Math.max(0, next.shares - othersSum);
        } else if (allocated > 0) {
          // Total `shares` shrank below the existing allocation — scale every
          // rung down proportionally rather than favoring one arbitrarily.
          const scale = next.shares / allocated;
          next.sharesT1 = Math.floor(next.sharesT1 * scale);
          next.sharesT2 = Math.floor(next.sharesT2 * scale);
          next.sharesT3 = Math.max(0, next.shares - next.sharesT1 - next.sharesT2);
        }
      } else if ('shares' in partial && allocated > 0 && allocated < next.shares) {
        // A fifth independent audit round found the mirror gap: growing total
        // SHARES was never topped up to the sell-to-close plan, silently
        // leaving the added shares with no planned exit rung at all (e.g.
        // 100 shares allocated 33/33/34, SHARES edited up to 250, rungs stay
        // at 33/33/34 — 150 shares reach Add to Portfolio uncovered). Scale
        // every rung UP proportionally, the mirror of the shrink branch
        // above. `allocated > 0` is a pure division-by-zero guard, not a
        // reachable UI state — EditableField.save() requires `p > 0`, so a
        // rung's share count can never actually be edited down to 0.
        const scale = next.shares / allocated;
        next.sharesT1 = Math.floor(next.sharesT1 * scale);
        next.sharesT2 = Math.floor(next.sharesT2 * scale);
        next.sharesT3 = Math.max(0, next.shares - next.sharesT1 - next.sharesT2);
      }
      return next;
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
  }, []);

  // Derived values
  const riskPerShare = Math.abs(overlay.entry - overlay.stop);
  const riskDollars  = overlay.shares * riskPerShare;
  const sizeDollars  = overlay.shares * overlay.entry;
  const rrAt = (t: number) =>
    riskPerShare > 0 ? Math.abs(t - overlay.entry) / riskPerShare : 0;

  // Store selectors
  // Display label like "Swing (5–15d)"; _horizonEnum maps it to the backend enum.
  const scanHorizonLabel = useScanStore((s) => s.context?.horizon ?? null);
  const stockBasket  = useScanStore((s) => s.stockBasket);
  const addToBasket  = useScanStore((s) => s.addToStockBasket);
  const removeBasket = useScanStore((s) => s.removeFromStockBasket);
  const addPosition  = usePortfolioStore((s) => s.addPosition);
  const ibkrPaper    = useSettingsStore((s) => s.ibkrPaper);
  const tradierPaper = useSettingsStore((s) => s.tradierPaper);

  const [execMode, setExecMode]         = useState<ExecMode>('recommendation');
  const [placingType, setPlacingType]   = useState<'LMT' | 'MKT' | null>(null);
  const [orderId, setOrderId]           = useState<string | null>(null);
  const [err, setErr]                   = useState<string | null>(null);
  const [warning, setWarning]           = useState<string | null>(null);
  const [added, setAdded]               = useState(false);
  const [queued, setQueued]             = useState(false);
  const [adding, setAdding]             = useState(false);
  const [alpacaConfigured, setAlpacaConfigured] = useState(false);
  const [tastytradeConfigured, setTastytradeConfigured] = useState(false);

  // ── On-demand analytics (Approach B) ──────────────────────────────────────
  const [estimate, setEstimate]             = useState<StockFirstPassageEstimate | null>(null);
  const [estimating, setEstimating]         = useState(false);
  const [estimateErr, setEstimateErr]       = useState<string | null>(null);
  const [structural, setStructural]         = useState<StructuralStopResult | null>(null);
  const [checkingStructure, setCheckingStructure] = useState(false);
  const [structuralErr, setStructuralErr]   = useState<string | null>(null);
  const [plan, setPlan]                     = useState<StockExitPlan | null>(null);
  const [planning, setPlanning]             = useState(false);
  const [planErr, setPlanErr]               = useState<string | null>(null);
  const estimateReq   = useRef<AbortController | null>(null);
  const structuralReq = useRef<AbortController | null>(null);
  const planReq       = useRef<AbortController | null>(null);

  // Abort anything still in flight when the card unmounts, so a late resolve
  // cannot setState on an unmounted component.
  useEffect(() => () => {
    estimateReq.current?.abort();
    structuralReq.current?.abort();
    planReq.current?.abort();
  }, []);

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
    if (execMode === 'recommendation' || orderId !== null) return;
    setPlacingType(orderType);
    setErr(null);
    setWarning(null);
    try {
      const res = await api.postStockOrder({
        broker: execMode,
        symbol: card.symbol,
        action: card.direction === 'Bullish' ? 'BUY' : 'SELL',
        effect: 'OPEN',
        quantity: overlay.shares,
        order_type: orderType,
        limit_price: orderType === 'LMT' ? overlay.entry : null,
        tif: 'DAY',
      });
      setOrderId(res.order_id);
      try {
        const addRes = await addPosition({
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
          source: 'broker',
          sourceLabel: `${execMode} — ${orderType} (ID: ${res.order_id})`,
          orderedAt: new Date().toISOString(),
        });
        if (addRes.status === 'rejected' || addRes.status === 'pending') {
          setWarning('Order placed but not yet tracked in Portfolio — check there directly.');
        }
      } catch {
        setWarning('Order placed but not yet tracked in Portfolio — check there directly.');
      }
    } catch (e) {
      setErr(String(e));
    } finally {
      setPlacingType(null);
    }
  }

  async function onEstimate() {
    if (estimating) return;
    estimateReq.current?.abort();
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
      if (ctrl.signal.aborted) return;
      setEstimate(res);
    } catch (e) {
      if (ctrl.signal.aborted) return;
      setEstimateErr(String(e));
    } finally {
      if (estimateReq.current === ctrl) {
        estimateReq.current = null;
        setEstimating(false);
      }
    }
  }

  async function onArithmeticPlan() {
    if (planning) return;
    planReq.current?.abort();
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
      if (ctrl.signal.aborted) return;
      setPlan(res);
    } catch (e) {
      if (ctrl.signal.aborted) return;
      setPlanErr(String(e));
    } finally {
      if (planReq.current === ctrl) {
        planReq.current = null;
        setPlanning(false);
      }
    }
  }

  async function onCheckStructure() {
    if (checkingStructure) return;
    structuralReq.current?.abort();
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
      if (ctrl.signal.aborted) return;
      setStructural(
        res.available && res.price != null && res.price > 0
          ? { price: res.price, source: res.source, confidence: res.confidence, distancePct: res.distancePct }
          : null,
      );
      if (!res.available || res.price == null || res.price <= 0) {
        setStructuralErr('No structural level found on recent candles.');
      }
    } catch (e) {
      if (ctrl.signal.aborted) return;
      setStructuralErr(String(e));
    } finally {
      if (structuralReq.current === ctrl) {
        structuralReq.current = null;
        setCheckingStructure(false);
      }
    }
  }

  async function onAddToPortfolio() {
    if (adding || added || queued) return; // guards against a double-click firing two adds
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
    try {
      // The user's EDITED overlay is what gets persisted as the live stop/targets —
      // it is what they intend to trade, and it is what TP_HIT / STOP_REACHED will
      // fire on. The pristine signal rides along inside the snapshot for the audit
      // trail. stockPositionLevels() drops anything non-positive or on the wrong
      // side of entry, so a half-edited overlay can never send a 0 stop.
      const res = await addPosition(
        buildPaperStockPosition(
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
      );
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
      setAdded(true);
    } finally {
      setAdding(false);
    }
  }

  const rrT1 = rrAt(overlay.t1);
  const rrT2 = rrAt(overlay.t2);
  const rrT3 = rrAt(overlay.t3);

  const winTone = card.backtest.win_rate >= 0.5 ? 'pass' : 'caution';

  return (
    <div className={styles.wrap}>

      {/* Section 1 — Sizing grid, Row 1 */}
      <div className={styles.grid4}>
        <EditableField label="ENTRY"    value={overlay.entry} onChange={(v) => patch({ entry: v })} />
        <EditableField label="STOP"     value={overlay.stop}  onChange={(v) => patch({ stop: v })}  tone="reject" />
        <EditableField label="T1 TARGET" value={overlay.t1}  onChange={(v) => patch({ t1: v })}    tone="pass" />
        <div className={styles.editCell}>
          <Text size={10} tone="dim">R:R AT T1</Text>
          <Data size={14} weight={500}>{rrT1.toFixed(1)}×</Data>
        </div>
      </div>

      {/* Section 1 — Sizing grid, Row 2 */}
      <div className={styles.grid4}>
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
      </div>

      {/* Section 2 — Sell-to-Close plan (T1 / T2 / T3) */}
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
          const retPct = profitPct.toFixed(1);
          return (
            <div key={id} className={styles.targetRow}>
              <div className={styles.targetLabel}>
                <Text size={12} weight={500}>{id}</Text>
              </div>
              <div className={styles.targetValues}>
                <EditableField label="" value={price} onChange={onPrice} />
                <Data size={12} tone={rr >= 1.5 ? 'pass' : rr >= 1 ? 'caution' : 'reject'}>
                  {rr.toFixed(1)}×
                </Data>
                <Data size={12} tone={profitPct > 0 ? 'pass' : 'reject'}>
                  {retPct}%
                </Data>
                <EditableField
                  label=""
                  value={sh}
                  onChange={(v) => onShares(Math.max(0, Math.round(v)))}
                  integer
                />
              </div>
            </div>
          );
        })}
      </div>

      {/* Section 2b — On-demand analytics: first-passage estimate + structural stop.
          Both are explicit user actions, never fired by the scan — the Monte
          Carlo is CPU work and the structural lookup is a candle fetch. */}
      <div className={styles.targetsSection}>
        <div className={styles.targetsHeading}>
          <Text size={11} tone="dim">PROBABILITY &amp; STRUCTURE</Text>
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
          <button
            type="button"
            className={styles.actionBtn}
            onClick={onCheckStructure}
            disabled={checkingStructure}
          >
            <Text size={12}>{checkingStructure ? 'Checking…' : 'Check structure'}</Text>
          </button>
        </div>

        {estimateErr && <Text size={11} tone="reject">{estimateErr}</Text>}

        {estimate && (
          <div className={styles.estimateBlock}>
            {/* A probability without its window is meaningless, so the window is
                never optional chrome. Trading days, not calendar days — the
                window comes from confidence_backtest.n_days, which counts bars. */}
            <Text size={11} tone="dim">
              Chance of reaching each target within {estimate.horizonDays} trading days
            </Text>
            {estimate.targets.map((t, i) => (
              <div key={`fp-${i}`} className={styles.estimateRow}>
                <Text size={11} tone="dim">T{i + 1}</Text>
                <Data size={12}>{t.price.toFixed(2)}</Data>
                <Data size={12} tone={t.probability >= 0.5 ? 'pass' : t.probability >= 0.25 ? 'caution' : 'reject'}>
                  {(t.probability * 100).toFixed(0)}%
                </Data>
                <Data size={12} tone="dim">
                  {t.expectedDays != null ? `~${t.expectedDays.toFixed(0)}d` : 'unlikely'}
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
                {estimate.invalidation.expectedDays != null
                  ? `~${estimate.invalidation.expectedDays.toFixed(0)}d`
                  : 'unlikely'}
              </Data>
            </div>
            {estimate.modelCaveat && (
              <Text size={11} tone="caution">{estimate.modelCaveat}</Text>
            )}
          </div>
        )}

        {structuralErr && <Text size={11} tone="caution">{structuralErr}</Text>}

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
        )}
      </div>

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
      <div className={styles.targetsSection}>
        <div className={styles.targetsHeading}>
          <Text size={11} tone="dim">ARITHMETIC PROFIT TARGET</Text>
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

        {planErr && <Text size={11} tone="reject">{planErr}</Text>}

        {plan && (
          <div className={styles.estimateBlock}>
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
                {plan.stop.expectedDays != null
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
                <div className={styles.planRow}>
                  <Text size={11} tone="dim">{t.rrRatio}R</Text>
                  <Data size={13} tone="pass">{t.price.toFixed(2)}</Data>
                  <Data size={12} tone={t.probability >= 0.5 ? 'pass' : t.probability >= 0.25 ? 'caution' : 'reject'}>
                    {(t.probability * 100).toFixed(0)}% reached
                  </Data>
                  <Data size={12} tone="dim">
                    {t.expectedDays != null
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
              <div className={styles.planRace}>
                <Text size={10} tone="dim">
                  Which comes first, over {plan.horizonDays} trading days
                  ({plan.race.nPaths.toLocaleString()} simulated paths). These three
                  add to 100% because every path is counted once — unlike the
                  percentages above, which are each measured on their own.
                </Text>
                {plan.race.outcomes.map((o, i) => (
                  <div key={`race-${i}`} className={styles.planRow}>
                    <Data size={11} tone="dim">{o.targetPrice.toFixed(2)}</Data>
                    {/* The ALLOCATED weights, never the raw p* — they are
                        allocated to hundredths so the three always sum to
                        exactly 100%. Re-rounding the raw values here is how a
                        row ends up printing 18 / 40 / 42 and adding to 99. */}
                    <Data size={12} tone="pass">
                      target {(o.weightTarget * 100).toFixed(0)}%
                      {o.daysTarget != null ? ` (~${o.daysTarget.toFixed(0)}d)` : ''}
                    </Data>
                    <Data size={12} tone="reject">
                      stop {(o.weightStop * 100).toFixed(0)}%
                      {o.daysStop != null ? ` (~${o.daysStop.toFixed(0)}d)` : ''}
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

      <MarketSentiment s={card.sentiment} />

      <FundamentalHealthCard f={card.fundamentals} />

      {/* Section 3 — Action buttons */}
      <div className={styles.actionRow}>
        <a
          href={`/chart?symbol=${encodeURIComponent(card.symbol)}`}
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
        <button
          type="button"
          className={styles.actionBtn}
          onClick={onAddToPortfolio}
          disabled={added || adding || queued}
        >
          <Text size={12}>
            {added ? 'Added to Portfolio' : queued ? 'Queued — will sync' : adding ? 'Adding…' : 'Add to Portfolio'}
          </Text>
        </button>
      </div>

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
            disabled={placingType !== null || orderId !== null}
          >
            <Text size={12}>{placingType === 'LMT' ? 'Placing…' : `Limit @ $${overlay.entry.toFixed(2)}`}</Text>
          </button>
          <button
            type="button"
            className={styles.actionBtn}
            onClick={() => submit('MKT')}
            disabled={placingType !== null || orderId !== null}
          >
            <Text size={12}>{placingType === 'MKT' ? 'Placing…' : 'Market Order'}</Text>
          </button>
        </div>
      )}

      {/* Section 6 — Order result / error */}
      {orderId && <Text size={12} tone="pass">Order placed — ID: {orderId}</Text>}
      {err      && <Text size={12} tone="reject">{err}</Text>}
      {warning  && <Text size={12} tone="caution">{warning}</Text>}
      {queued   && <Text size={12} tone="caution">Queued — backend unreachable, will sync automatically.</Text>}

      {/* Section 7 — Auto-trade arm */}
      <StockAutoTradeArm
        symbol={card.symbol}
        strategyKey={strategyKey}
        direction={card.direction === 'Bullish' ? 'Bullish' : 'Bearish'}
        afterScanArmed={afterScanArmed ?? false}
        onAfterScanToggle={onAfterScanToggle ?? (() => {})}
      />

    </div>
  );
}
