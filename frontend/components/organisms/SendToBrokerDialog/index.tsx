'use client';

/*
 * SendToBrokerDialog — modal launched from Step 7 Send button.
 *
 * Lists every pinned basket item with per-row quantity + an "Auto-send"
 * checkbox. Checked rows are sent to the (mock) broker; unchecked rows go
 * straight into the portfolio with source='manual'.
 */

import { useMemo, useState } from 'react';
import { Text, Data } from '@/components/primitives';
import { useRiskStore } from '@/lib/riskStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { checkTradeRisk } from '@/lib/risk';
import type { TradeCardData, RiskCheckResult } from '@/types/domain';
import styles from './SendToBrokerDialog.module.css';

export interface DraftOrder {
  card:      TradeCardData;
  contracts: number;
  autoSend:  boolean;
}

interface Props {
  cards:    TradeCardData[];
  onClose:  () => void;
  onSubmit: (orders: DraftOrder[], riskOverridden: boolean) => void;
}

interface RowState {
  contracts: number;
  autoSend:  boolean;
}

export function SendToBrokerDialog({ cards, onClose, onSubmit }: Props) {
  const [rows, setRows] = useState<Record<string, RowState>>(() =>
    Object.fromEntries(cards.map((c) => [c.symbol, { contracts: 1, autoSend: true }])),
  );
  const [overrideReady, setOverrideReady] = useState(false);

  const limits = useRiskStore((s) => s.limits);
  const dailyRecommendations = useRiskStore((s) => s.dailyRecommendations);
  const positions = usePortfolioStore((s) => s.positions);

  const { autoCount, manualCount, estTotal } = useMemo(() => {
    let a = 0, m = 0, t = 0;
    for (const c of cards) {
      const r = rows[c.symbol] ?? { contracts: 1, autoSend: true };
      if (r.autoSend) a++; else m++;
      const mid = c.contractDetails?.mid ?? 0;
      t += mid * 100 * r.contracts;
    }
    return { autoCount: a, manualCount: m, estTotal: t };
  }, [cards, rows]);

  const riskChecks = useMemo(() => {
    const checks: Record<string, RiskCheckResult> = {};
    for (const c of cards) {
      const r = rows[c.symbol] ?? { contracts: 1, autoSend: true };
      checks[c.symbol] = checkTradeRisk(c, Math.max(1, Math.round(r.contracts)), limits, positions, dailyRecommendations);
    }
    return checks;
  }, [cards, rows, limits, positions, dailyRecommendations]);

  const hasMissingInvalidation = useMemo(
    () => Object.values(riskChecks).some((rc) => rc.reasons.includes('missing_invalidation')),
    [riskChecks],
  );

  const hasWarnings = useMemo(
    () => Object.values(riskChecks).some((rc) => !rc.approved && !rc.reasons.includes('missing_invalidation')),
    [riskChecks],
  );

  const allClean = useMemo(
    () => Object.values(riskChecks).every((rc) => rc.approved),
    [riskChecks],
  );

  const patch = (sym: string, p: Partial<RowState>) => {
    setOverrideReady(false);
    setRows((r) => ({ ...r, [sym]: { ...(r[sym] ?? { contracts: 1, autoSend: true }), ...p } }));
  };

  const submit = () => {
    if (hasMissingInvalidation) return;
    if (hasWarnings && !overrideReady) {
      setOverrideReady(true);
      return;
    }
    const orders: DraftOrder[] = cards.map((c) => {
      const r = rows[c.symbol] ?? { contracts: 1, autoSend: true };
      return { card: c, contracts: Math.max(1, Math.round(r.contracts)), autoSend: r.autoSend };
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
        aria-label="Send basket to broker"
      >
        <header className={styles.header}>
          <div>
            <Text size={14} weight={600}>Send basket to broker</Text>
            <Text size={11} tone="secondary">
              Uncheck Auto-send for any contract you&apos;d rather place manually. Unchecked orders
              are still added to the portfolio, tagged MANUAL.
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
          <Text size={10} tone="dim">AUTO-SEND</Text>
        </div>

        <div className={styles.tableBody}>
          {cards.map((c) => {
            const r      = rows[c.symbol] ?? { contracts: 1, autoSend: true };
            const isSpread = c.spreadType && c.spreadType !== 'single' && c.legs && c.legs.length > 0;
            const mid    = c.contractDetails?.mid ?? 0;
            const est    = mid * 100 * r.contracts;

            if (isSpread) {
              // Spread: one row per leg, all sharing the same qty/auto-send controls in the first leg row.
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
                            <label className={styles.autoCell}>
                              <input
                                type="checkbox"
                                checked={r.autoSend}
                                onChange={(e) => patch(c.symbol, { autoSend: e.target.checked })}
                                aria-label={`Auto-send ${c.symbol} to broker`}
                              />
                              <Text size={11} tone={r.autoSend ? 'pass' : 'caution'}>
                                {r.autoSend ? 'Auto' : 'Manual'}
                              </Text>
                            </label>
                          </>
                        ) : (
                          <>
                            <span />
                            <span />
                            <Text size={11} tone="dim" className={styles.ibkrNote}>Copy manually — IBKR multi-leg not routed</Text>
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
                <Text size={12}>{c.contract}</Text>
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
                <label className={styles.autoCell}>
                  <input
                    type="checkbox"
                    checked={r.autoSend}
                    onChange={(e) => patch(c.symbol, { autoSend: e.target.checked })}
                    aria-label={`Auto-send ${c.symbol} to broker`}
                  />
                  <Text size={11} tone={r.autoSend ? 'pass' : 'caution'}>
                    {r.autoSend ? 'Auto' : 'Manual'}
                  </Text>
                </label>
              </div>
            );
          })}
        </div>

        <div style={{ padding: 'var(--space-3) var(--space-4)', borderTop: '1px solid var(--border-subtle)' }}>
          <RiskSummary
            hasMissingInvalidation={hasMissingInvalidation}
            hasWarnings={hasWarnings}
            allClean={allClean}
            overrideReady={overrideReady}
            riskChecks={riskChecks}
          />
        </div>

        <footer className={styles.footer}>
          <Text size={12} tone="secondary">
            {autoCount} auto · {manualCount} manual · Est total ${Math.round(estTotal).toLocaleString()}
          </Text>
          <div className={styles.actions}>
            <button type="button" className={styles.btn} onClick={onClose}>Cancel</button>
            <button
              type="button"
              className={`${styles.btn} ${styles.btnPrimary}`}
              onClick={submit}
              disabled={cards.length === 0 || hasMissingInvalidation}
              title={hasMissingInvalidation ? 'Invalidation stop required' : undefined}
            >
              {overrideReady && hasWarnings
                ? 'Override & Submit'
                : `Submit ${cards.length} order${cards.length === 1 ? '' : 's'}`}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}

function RiskSummary({
  hasMissingInvalidation,
  hasWarnings,
  allClean,
  overrideReady,
  riskChecks,
}: {
  hasMissingInvalidation: boolean;
  hasWarnings: boolean;
  allClean: boolean;
  overrideReady: boolean;
  riskChecks: Record<string, RiskCheckResult>;
}) {
  if (hasMissingInvalidation) {
    return (
      <Text size={12} tone="reject">
        Invalidation stop required — define an invalidation level before submitting.
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
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
      {Array.from(reasons).map((r) => (
        <Text key={r} size={12} tone="caution">
          {reasonLabels[r] ?? r}
        </Text>
      ))}
      {!overrideReady && (
        <Text size={12} tone="secondary">
          Click Submit again to override.
        </Text>
      )}
    </div>
  );
}
