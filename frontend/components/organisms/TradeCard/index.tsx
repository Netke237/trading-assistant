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
import type { TradeCardData, TargetLevel, StructuralStop, TriggerDetail, PullbackDetail, TrendDetail, EventDetail, VolDetail, DteDetail, DeltaDetail, IvRankDetail, LiquidityDetail, SpreadDetail } from '@/types/domain';
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
  const risk = overlay.entryLimit;
  if (risk <= 0) return { rr: 0, model: 'Edit (delta approx)' };
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
  const estOptionPrice = Math.max(0.01, risk + delta * priceMove);
  const reward = estOptionPrice - risk;
  const rr = reward > 0 ? Math.round((reward / risk) * 100) / 100 : 0;

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
  targetStockPrice: number,
  estOptionPrice: number,
  entryLimit: number,
): number {
  const risk = entryLimit;
  const reward = estOptionPrice - risk;
  if (risk <= 0 || reward <= 0) return 0;
  return Math.round((reward / risk) * 10) / 10;
}

function triggerDetailText(d?: TriggerDetail): string | undefined {
  if (!d) return undefined;
  const checks = [
    d.macd_pass  ? 'MACD ✓'  : 'MACD ✗',
    d.rsi_pass   ? 'RSI ✓'   : 'RSI ✗',
    d.stoch_pass ? 'Stoch ✓' : 'Stoch ✗',
  ].join(' · ');
  const candle = d.candle !== 'none' ? d.candle : '';
  const vol = d.volume_bonus ? ' + vol' : '';
  return [candle, `${checks} · ${d.momentum_count}/3 signals${vol}`].filter(Boolean).join(' · ');
}

function pullbackDetailText(d?: PullbackDetail): string | undefined {
  if (!d) return undefined;
  const ret = d.retracement_pct != null ? `Ret ${d.retracement_pct.toFixed(1)}%` : '';
  const fvg = d.fvg_hit ? '+ FVG' : '';
  return [ret, fvg, d.reason].filter(Boolean).join(' · ');
}

function trendDetailText(d?: TrendDetail): string | undefined {
  if (!d) return undefined;
  if (d.adx_val != null) return `ADX ${d.adx_val.toFixed(0)} · ${d.method}`;
  if (d.stock_roc != null) return `RS ${d.stock_roc.toFixed(1)}% vs bench ${d.bench_roc?.toFixed(1)}%`;
  return d.method;
}

function eventDetailText(d?: EventDetail): string | undefined {
  if (!d) return undefined;
  if (d.event === 'none') return 'No upcoming event';
  return `${d.event} in ${d.days_to_event}d`;
}

function volDetailText(d?: VolDetail): string | undefined {
  if (!d) return undefined;
  const parts = [];
  if (d.iv_rank != null) parts.push(`IV Rank ${d.iv_rank.toFixed(0)}`);
  if (d.reason) parts.push(d.reason);
  return parts.join(' · ') || undefined;
}

function dteDetailText(d?: DteDetail): string | undefined {
  if (!d) return undefined;
  return `${d.dte}d · target ${d.preferred_min}-${d.preferred_max}d`;
}

function deltaDetailText(d?: DeltaDetail): string | undefined {
  if (!d) return undefined;
  return `Δ${d.delta.toFixed(2)} · target ${d.preferred_min.toFixed(2)}-${d.preferred_max.toFixed(2)}`;
}

function ivDetailText(d?: IvRankDetail): string | undefined {
  if (!d) return undefined;
  if (d.iv_rank == null) return 'No IV rank data';
  return `IV Rank ${d.iv_rank.toFixed(0)} · pref ≤${d.preferred_max.toFixed(0)}`;
}

function liquidityDetailText(d?: LiquidityDetail): string | undefined {
  if (!d) return undefined;
  return `Vol ${d.volume.toLocaleString()} · OI ${d.open_interest.toLocaleString()} · pref ≥${d.preferred_volume_min.toLocaleString()}/${d.preferred_oi_min.toLocaleString()}`;
}

function spreadDetailText(d?: SpreadDetail): string | undefined {
  if (!d) return undefined;
  return `Spread ${(d.spread_pct * 100).toFixed(1)}% · pref ≤${(d.preferred_max_pct * 100).toFixed(0)}%`;
}

interface TradeCardProps {
  data: TradeCardData;
  recId?: string;
  onSendToBroker?: () => void;
  sendLabel?: string;
  sendDisabled?: boolean;
  contracts?: number;
  onEditsChange?: (overlay: EditOverlay) => void;
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
  // Tracks the in-flight "Check structure" request (if any) so a stale response
  // for a contract the user has since navigated away from (via CandidateNav
  // Prev/Next) can never overwrite the display for the new one — same class of
  // race step-7-trade-card/page.tsx's recomputePlan effects guard against.
  const structuralRequestRef = useRef<AbortController | null>(null);

  const prevSymbolRef = useRef(data.symbol);
  const prevContractRef = useRef(data.contract);
  useEffect(() => {
    if (data.symbol !== prevSymbolRef.current || data.contract !== prevContractRef.current) {
      structuralRequestRef.current?.abort();
      setOverlay({ ...defaultOverlay(data), contracts: initialContracts });
      setStructuralStop(data.exit.structuralStop);
      setStructuralError(false);
      setStructuralLoading(false);
      prevSymbolRef.current = data.symbol;
      prevContractRef.current = data.contract;
    }
  }, [data.symbol, data.contract, initialContracts]);

  // Cancel any outstanding request on unmount.
  useEffect(() => () => structuralRequestRef.current?.abort(), []);

  const checkStructure = useCallback(async () => {
    structuralRequestRef.current?.abort();
    const controller = new AbortController();
    structuralRequestRef.current = controller;
    setStructuralLoading(true);
    setStructuralError(false);
    setStructuralStop(undefined);
    try {
      const res = await api.getStructuralStop({
        symbol: data.symbol,
        direction: data.direction,
        stock_price: data.price,
      }, controller.signal);
      if (controller.signal.aborted) return;
      setStructuralStop(
        res.available && res.price != null && res.source != null
          && res.confidence != null && res.distancePct != null
          ? { price: res.price, source: res.source, confidence: res.confidence, distancePct: res.distancePct }
          : null,
      );
    } catch {
      if (controller.signal.aborted) return;
      setStructuralError(true);
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

        {/* 5b. Sell-to-close plan */}
        <section className={`${styles.planCard} ${styles.targetsCard}`}>
          <Text size={14} weight={600}>Sell-to-Close Plan</Text>
          <div className={styles.targetsTable}>
            {data.exit.targets.map((t, i) => (
              <EditableTargetRow
                key={t.id ?? i}
                target={t}
                index={i}
                editedStockPrice={overlay.targets[i] ?? t.targetPrice ?? t.stockPrice}
                entryLimit={overlay.entryLimit}
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
            <LabeledStatusBadge label="Final Status" status={data.finalStatus} />
          </div>
          <div className={styles.scoreCardBody}>
            <div className={styles.scoreRow}>
              <Text size={12} tone="secondary">Historical accuracy (3×ATR exit)</Text>
              <StatusBadge status={data.stockConfidence} />
            </div>
            <div className={styles.scoreRow}>
              <Text size={12} tone="secondary">Contract confidence</Text>
              <StatusBadge status={data.contractConfidence} />
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

      <div
        style={{
          borderTop: '1px solid var(--border-subtle)',
          paddingTop: 'var(--space-2)',
          marginTop: 'var(--space-2)',
        }}
      >
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
  data,
  onStockPriceChange,
  totalContracts,
}: {
  target: TargetLevel;
  index: number;
  editedStockPrice: number;
  entryLimit: number;
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

  const rr = rrContribution(editedStockPrice, estOptionPrice, entryLimit);

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
          {statusVal && <StatusBadge status={badgeStatus as 'PENDING' | 'PASS' | 'REJECT'} />}
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
          {rr > 0 && <KV label="R:R" value={`${rr.toFixed(1)}x`} mono />}
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
          {statusVal && <StatusBadge status={badgeStatus as 'PENDING' | 'PASS' | 'REJECT'} />}
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