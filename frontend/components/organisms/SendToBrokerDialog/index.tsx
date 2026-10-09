'use client';

/*
 * SendToBrokerDialog — modal launched from Step 7 Send button.
 *
 * Lists every pinned basket item with a per-row quantity. Fix #5 (review, D6):
 * the basket places NO broker order. Every row is saved to the Portfolio as a
 * tracked position with source='manual'; to trade one, send it from its own
 * card. It used to offer an "Auto-send" checkbox and store 'broker' rows, which
 * made phantom positions that looked like fills.
 */

import { contractKeyFor } from '@/lib/tradeCardOverride';
import { quoteWarning } from '@/lib/quoteWarning';
import { useMemo, useState } from 'react';
import { Text, Data } from '@/components/primitives';
import { useRiskStore } from '@/lib/riskStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import {
  checkTradeRisk,
  MISSING_INVALIDATION_MESSAGE, MISSING_INVALIDATION_TITLE,
  MISSING_METHOD_PICK_MESSAGE, MISSING_METHOD_PICK_TITLE,
} from '@/lib/risk';
import type { TradeCardData, RiskCheckResult, MaxLossOverride, MethodPick } from '@/types/domain';
import styles from './SendToBrokerDialog.module.css';

export interface DraftOrder {
  card:      TradeCardData;
  contracts: number;
}

interface Props {
  cards:    TradeCardData[];
  quoteWarningsByContract?: Record<string, string | null>;
  /** Feature 7 — the page-level shared per-symbol contracts map (same one fed
   *  into TradeCard's `contracts` prop and read by the quick-order/auto-trade
   *  paths), used only to SEED this dialog's row state. Editing the quantity
   *  inside this dialog is a one-off override for that submission only — it
   *  deliberately does NOT write back to the shared map; the dialog reviews/
   *  finalizes a snapshot right before sending, not a place for live pre-trade
   *  state the rest of the page also reads from. */
  contractsBySymbol: Record<string, number>;
  /** Feature 5 — the page-level shared per-symbol max-loss override cache,
   *  sourced from the same `maxLossOverrideBySymbol` state TradeCard's
   *  Arithmetic card writes to. Read directly into `checkTradeRisk` below so
   *  this dialog's own risk check knows about an active override and doesn't
   *  force a spurious extra confirmation click for a trade the user already
   *  explicitly sized up under a raised budget. */
  overridesBySymbol: Record<string, MaxLossOverride | null>;
  /** PIECE 3 — the stop each card is actually SHOWING, resolved by the page
   *  through `invalidationFor` (the user's typed value when the Invalidation
   *  field is touched, else the card's own). Fed straight into
   *  `checkTradeRisk` so `missing_invalidation` judges the level that would be
   *  stored as `PortfolioPosition.stop`, not the card's stale one — which on a
   *  candidate restored from a pre-piece-3 scan session is null, and which the
   *  user can fix by typing. A symbol absent from the map falls back to the
   *  card. */
  invalidationBySymbol: Record<string, number | null>;
  /** Phase G piece 5, build step 4 (§7.1) — the trader's explicit method pick
   *  for each basket card, sourced from step 7's `methodPickFor` (keyed by
   *  contract through `editKeyFor`, looked up here per symbol since one
   *  basket card is one contract). Fed into `checkTradeRisk` so `.some(...)`
   *  below applies the same rule §7.1 states in words: one unpicked card
   *  blocks the whole basket, the same rule `missing_invalidation` already
   *  applies. A symbol absent from the map means no pick, same as `null`. */
  methodPickBySymbol: Record<string, MethodPick | null | undefined>;
  onClose:  () => void;
  onSubmit: (orders: DraftOrder[], riskOverridden: boolean) => void;
}

interface RowState {
  contracts: number;
}

export function SendToBrokerDialog({ cards, quoteWarningsByContract, contractsBySymbol, overridesBySymbol, invalidationBySymbol, methodPickBySymbol, onClose, onSubmit }: Props) {
  const [rows, setRows] = useState<Record<string, RowState>>(() =>
    Object.fromEntries(cards.map((c) => [c.symbol, { contracts: contractsBySymbol[c.symbol] ?? 1 }])),
  );
  const [overrideReady, setOverrideReady] = useState(false);

  const limits = useRiskStore((s) => s.limits);
  const dailyRecommendations = useRiskStore((s) => s.dailyRecommendations);
  const positions = usePortfolioStore((s) => s.positions);

  const estTotal = useMemo(() => {
    let t = 0;
    for (const c of cards) {
      const r = rows[c.symbol] ?? { contracts: 1 };
      const mid = c.contractDetails?.mid ?? 0;
      t += mid * 100 * r.contracts;
    }
    return t;
  }, [cards, rows]);

  const riskChecks = useMemo(() => {
    const checks: Record<string, RiskCheckResult> = {};
    for (const c of cards) {
      const r = rows[c.symbol] ?? { contracts: 1 };
      checks[c.symbol] = checkTradeRisk(
        c, Math.max(1, Math.round(r.contracts)), limits, positions, dailyRecommendations,
        overridesBySymbol[c.symbol] ?? null,
        invalidationBySymbol[c.symbol] ?? c.exit.invalidation,
        methodPickBySymbol[c.symbol] ?? null,
      );
    }
    return checks;
  }, [cards, rows, limits, positions, dailyRecommendations, overridesBySymbol, invalidationBySymbol, methodPickBySymbol]);

  const hasMissingInvalidation = useMemo(
    () => Object.values(riskChecks).some((rc) => rc.reasons.includes('missing_invalidation')),
    [riskChecks],
  );

  const hasMissingMethodPick = useMemo(
    () => Object.values(riskChecks).some((rc) => rc.reasons.includes('missing_method_pick')),
    [riskChecks],
  );

  const hasWarnings = useMemo(
    () => Object.values(riskChecks).some((rc) =>
      !rc.approved
      && !rc.reasons.includes('missing_invalidation')
      && !rc.reasons.includes('missing_method_pick'),
    ),
    [riskChecks],
  );

  const allClean = useMemo(
    () => Object.values(riskChecks).every((rc) => rc.approved),
    [riskChecks],
  );

  const patch = (sym: string, p: Partial<RowState>) => {
    setOverrideReady(false);
    setRows((r) => ({ ...r, [sym]: { ...(r[sym] ?? { contracts: 1 }), ...p } }));
  };

  const submit = () => {
    if (hasMissingInvalidation) return;
    if (hasMissingMethodPick) return;
    if (hasWarnings && !overrideReady) {
      setOverrideReady(true);
      return;
    }
    const orders: DraftOrder[] = cards.map((c) => {
      const r = rows[c.symbol] ?? { contracts: 1 };
      return { card: c, contracts: Math.max(1, Math.round(r.contracts)) };
    });
    onSubmit(orders, overrideReady);
  };

  return (
    <div className={styles.backdrop} onClick={onClose} role="presentation">
      <div
        className={styles.dialog}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Track basket in Portfolio"
      >
        <header className={styles.header}>
          <div>
            <Text size={14} weight={600}>Track basket in Portfolio</Text>
            <Text size={11} tone="secondary">
              Adds these to Portfolio as tracked rows — no broker order is placed. A tracked row reserves
              its contract and symbol: to trade it instead, send from the card.
            </Text>
          </div>
          <button
            type="button"
            className={styles.close}
            onClick={onClose}
            aria-label="Close dialog"
          >
            ×
          </button>
        </header>

        <div className={styles.tableHead}>
          <Text size={10} tone="dim">SYMBOL</Text>
          <Text size={10} tone="dim">CONTRACT</Text>
          <Text size={10} tone="dim" className={styles.right}>MID</Text>
          <Text size={10} tone="dim">QTY</Text>
          <Text size={10} tone="dim" className={styles.right}>EST $</Text>
        </div>

        <div className={styles.tableBody}>
          {cards.map((c) => {
            const r      = rows[c.symbol] ?? { contracts: 1 };
            const isSpread = c.spreadType && c.spreadType !== 'single' && c.legs && c.legs.length > 0;
            const mid    = c.contractDetails?.mid ?? 0;
            const est    = mid * 100 * r.contracts;

            if (isSpread) {
              // Spread: one row per leg, all sharing the same qty control in the first leg row.
              return (
                <div key={c.symbol}>
                  {c.legs!.map((leg, i) => {
                    const legMid = (leg.bid + leg.ask) / 2;
                    return (
                      <div key={i} className={`${styles.row} ${i > 0 ? styles.legSubRow : ''}`}>
                        {i === 0 ? (
                          <Data size={13} weight={500}>{c.symbol}</Data>
                        ) : (
                          <span />
                        )}
                        <Text size={12}>
                          {leg.action} {leg.qty}× {c.symbol} ${leg.strike}{leg.right} {leg.expiry}
                        </Text>
                        <Data size={12} className={styles.right}>
                          {legMid > 0 ? `$${legMid.toFixed(2)}` : '—'}
                        </Data>
                        {i === 0 ? (
                          <>
                            <input
                              type="number"
                              min={1}
                              step={1}
                              value={r.contracts}
                              className={styles.qtyInput}
                              onChange={(e) => patch(c.symbol, { contracts: Math.max(1, Number(e.target.value) || 1) })}
                              aria-label={`Contracts for ${c.symbol}`}
                            />
                            <Data size={12} className={styles.right}>${Math.round(est).toLocaleString()}</Data>
                          </>
                        ) : (
                          <>
                            <span />
                            <span />
                          </>
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            }

            // Single-leg (original path)
            return (
              <div key={c.symbol} className={styles.row}>
                <Data size={13} weight={500}>{c.symbol}</Data>
                <div><Text size={12}>{c.contract}</Text><Text size={11} tone="caution">{quoteWarningsByContract?.[contractKeyFor(c) ?? c.contract] ?? (quoteWarningsByContract && (contractKeyFor(c) ?? c.contract) in quoteWarningsByContract ? null : quoteWarning(null))}</Text></div>
                <Data size={12} className={styles.right}>${mid.toFixed(2)}</Data>
                <input
                  type="number"
                  min={1}
                  step={1}
                  value={r.contracts}
                  className={styles.qtyInput}
                  onChange={(e) => patch(c.symbol, { contracts: Math.max(1, Number(e.target.value) || 1) })}
                  aria-label={`Contracts for ${c.symbol}`}
                />
                <Data size={12} className={styles.right}>${Math.round(est).toLocaleString()}</Data>
              </div>
            );
          })}
        </div>

        <div className={styles.riskSummaryWrap}>
          <RiskSummary
            hasMissingInvalidation={hasMissingInvalidation}
            hasMissingMethodPick={hasMissingMethodPick}
            hasWarnings={hasWarnings}
            allClean={allClean}
            overrideReady={overrideReady}
            riskChecks={riskChecks}
          />
        </div>

        <footer className={styles.footer}>
          <Text size={12} tone="secondary">
            {cards.length} to track · Est total ${Math.round(estTotal).toLocaleString()}
          </Text>
          <div className={styles.actions}>
            <button type="button" className={styles.btn} onClick={onClose}>Cancel</button>
            <button
              type="button"
              className={`${styles.btn} ${styles.btnPrimary}`}
              onClick={submit}
              disabled={cards.length === 0 || hasMissingInvalidation || hasMissingMethodPick}
              title={
                hasMissingInvalidation ? MISSING_INVALIDATION_TITLE
                : hasMissingMethodPick ? MISSING_METHOD_PICK_TITLE
                : undefined
              }
            >
              {overrideReady && hasWarnings
                ? 'Override & Submit'
                : `Add ${cards.length} to Portfolio`}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}

function RiskSummary({
  hasMissingInvalidation,
  hasMissingMethodPick,
  hasWarnings,
  allClean,
  overrideReady,
  riskChecks,
}: {
  hasMissingInvalidation: boolean;
  hasMissingMethodPick: boolean;
  hasWarnings: boolean;
  allClean: boolean;
  overrideReady: boolean;
  riskChecks: Record<string, RiskCheckResult>;
}) {
  if (hasMissingInvalidation) {
    return (
      <Text size={12} tone="reject">
        {MISSING_INVALIDATION_MESSAGE}
      </Text>
    );
  }

  if (hasMissingMethodPick) {
    return (
      <Text size={12} tone="reject">
        {MISSING_METHOD_PICK_MESSAGE}
      </Text>
    );
  }

  if (allClean) {
    return (
      <Text size={12} tone="pass">
        Within risk limits.
      </Text>
    );
  }

  const reasons = new Set<string>();
  for (const rc of Object.values(riskChecks)) {
    for (const r of rc.reasons) {
      reasons.add(r);
    }
  }

  const reasonLabels: Record<string, string> = {
    single_trade_exposure_too_high: 'Single trade exposure too high',
    total_exposure_limit_reached: 'Total exposure limit reached',
    max_concurrent_positions_reached: 'Max concurrent positions reached',
    duplicate_symbol: 'Duplicate symbol in portfolio',
    max_daily_recommendations_reached: 'Max daily recommendations reached',
    max_loss_per_trade_exceeded: 'Max loss at stop exceeds per-trade limit',
  };

  return (
    <div className={styles.riskReasonsStack}>
      {Array.from(reasons).map((r) => (
        <Text key={r} size={12} tone="caution">
          {reasonLabels[r] ?? r}
        </Text>
      ))}
      {reasons.has('max_loss_per_trade_exceeded') && (() => {
        // The actual worst offender, not just the first match in basket order —
        // a symbol pinned first with a barely-over loss must never mask a
        // later symbol whose loss is wildly over the same limit.
        let worst: { symbol: string; rc: RiskCheckResult } | null = null;
        for (const [symbol, rc] of Object.entries(riskChecks)) {
          if (!rc.reasons.includes('max_loss_per_trade_exceeded') || rc.maxLossAtStop == null) continue;
          if (!worst || rc.maxLossAtStop > worst.rc.maxLossAtStop!) worst = { symbol, rc };
        }
        if (!worst || worst.rc.maxLossLimitDollar == null) return null;
        return (
          <Text size={11} tone="dim">
            Max loss at stop ({worst.symbol}) ≈ ${Math.round(worst.rc.maxLossAtStop!).toLocaleString('en-US')}
            {' '}(limit ${Math.round(worst.rc.maxLossLimitDollar).toLocaleString('en-US')})
          </Text>
        );
      })()}
      {!overrideReady && (
        <Text size={12} tone="secondary">
          Click Submit again to override.
        </Text>
      )}
    </div>
  );
}
