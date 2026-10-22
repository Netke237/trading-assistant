'use client';

import { useState } from 'react';
import { Text, Data } from '@/components/primitives';
import { useScanStore, type RejectedEntry } from '@/lib/scanStore';
import { toneForScore } from '@/lib/status';
import styles from './index.module.css';

// Mirrors backend/config/scoring_rules.yaml weights per horizon
const HORIZON_WEIGHTS: Record<string, Record<string, number>> = {
  Intraday: { trend: 35, pullback: 20, trigger: 30, event: 5,  vol: 10 },
  Swing:    { trend: 30, pullback: 20, trigger: 25, event: 15, vol: 10 },
  Position: { trend: 30, pullback: 20, trigger: 20, event: 20, vol: 10 },
};

function resolveHorizonKey(h: string | undefined): string {
  if (!h) return 'Swing';
  if (h.startsWith('Intraday')) return 'Intraday';
  if (h.startsWith('Position')) return 'Position';
  return 'Swing';
}

// ---------------------------------------------------------------------------
// Category mapping for contract rejection reasons
// ---------------------------------------------------------------------------

export const REASON_CATEGORY: Record<string, 'DATA' | 'GREEKS' | 'PRICE' | 'SOFT'> = {
  no_live_quote: 'DATA',
  no_greeks_data:          'DATA',
  no_iv_data:              'DATA',
  open_interest_too_low:   'DATA',
  volume_too_low:          'DATA',
  delta_too_low_far_otm:   'GREEKS',
  delta_too_high_deep_itm: 'GREEKS',
  spread_too_wide:         'PRICE',
  dte_too_short:           'PRICE',
  dte_too_long:            'PRICE',
  too_many_soft_failures:  'SOFT',
};

const CATEGORY_LABELS: Record<string, string> = {
  DATA:   'DATA: no greeks / no IV / no OI',
  GREEKS: 'GREEKS: delta out of range',
  PRICE:  'PRICE: spread / DTE',
  SOFT:   'SOFT: too many weak signals',
};

function parseContractReasons(reason: string): Record<string, number> {
  const counts: Record<string, number> = {};
  const m = reason.match(/\[(.+)\]/);
  if (!m) return counts;
  for (const part of m[1].split(',')) {
    const p = part.trim().match(/^(.+)×(\d+)$/);
    if (p) counts[p[1].trim()] = Number(p[2]);
  }
  return counts;
}

// ---------------------------------------------------------------------------
// Breakdown rows (P2-2)
// ---------------------------------------------------------------------------

const COMPONENT_ORDER = ['trend', 'pullback', 'trigger', 'event', 'vol'] as const;
const COMPONENT_LABELS: Record<string, string> = {
  trend: 'Trend', pullback: 'Pullback', trigger: 'Trigger', event: 'Event', vol: 'Vol',
};

function BreakdownRows({
  breakdown,
  weights,
}: {
  breakdown: Record<string, number>;
  weights: Record<string, number>;
}) {
  return (
    <div className={styles.breakdown}>
      {COMPONENT_ORDER.map((key) => {
        const raw = breakdown[key] ?? 0;
        const wt  = weights[key] ?? 0;
        const pts = (raw * wt) / 100;
        const tone = toneForScore(raw);
        return (
          <div key={key} className={styles.breakdownRow}>
            <Text size={11} tone="secondary">{COMPONENT_LABELS[key]}</Text>
            <Data size={11} tone={tone}>{raw}/100</Data>
            <Text size={11} tone="dim">{wt}%</Text>
            <div className={styles.breakdownBar}>
              <div className={styles.breakdownFill} style={{ width: `${raw}%` }} />
            </div>
            <Data size={11} tone="dim">{pts.toFixed(1)}</Data>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stock rejection row (P2-1)
// ---------------------------------------------------------------------------

function StockRejRow({
  score,
  count,
  breakdown,
  weights,
}: {
  score: number;
  count: number;
  breakdown?: Record<string, number>;
  weights: Record<string, number>;
}) {
  const [open, setOpen] = useState(false);
  const hasBreakdown = !!breakdown && Object.keys(breakdown).length > 0;

  return (
    <div>
      <div
        className={`${styles.row} ${hasBreakdown ? styles.rowClickable : ''}`}
        onClick={() => hasBreakdown && setOpen((o) => !o)}
        role={hasBreakdown ? 'button' : undefined}
        tabIndex={hasBreakdown ? 0 : undefined}
        onKeyDown={(e) => {
          if (hasBreakdown && (e.key === 'Enter' || e.key === ' ')) setOpen((o) => !o);
        }}
      >
        <div className={styles.rowLabel}>
          {hasBreakdown && (
            <span className={`${styles.chevron} ${open ? styles.chevronOpen : ''}`}>›</span>
          )}
          <Text size={12} tone="reject" weight={500}>STOCK REJECT</Text>
          <Text size={12} tone="secondary">score</Text>
          <Data size={12} weight={500}>{score}</Data>
        </div>
        <div className={styles.rowCount}>
          <Data size={11} tone="dim">{count} ×</Data>
        </div>
      </div>
      {open && hasBreakdown && (
        <BreakdownRows breakdown={breakdown!} weights={weights} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stock rejection section
// ---------------------------------------------------------------------------

function StockRejectionSection({
  rejected,
  weights,
}: {
  rejected: RejectedEntry[];
  weights: Record<string, number>;
}) {
  const stockRej = rejected.filter((r) => r.reason.startsWith('stock REJECT'));
  if (stockRej.length === 0) return null;

  // Group by reason (same score → same row, aggregated count)
  const groups = new Map<string, { count: number; score: number; breakdown?: Record<string, number> }>();
  for (const r of stockRej) {
    const m = r.reason.match(/score (\d+)/);
    const score = m ? Number(m[1]) : 0;
    const existing = groups.get(r.reason);
    if (existing) {
      existing.count += 1;
    } else {
      groups.set(r.reason, { count: 1, score, breakdown: r.breakdown });
    }
  }

  return (
    <div className={styles.section}>
      <div className={styles.sectionLabel}>
        <Text size={10} tone="dim" weight={500}>
          STOCK REJECTIONS — {stockRej.length} symbols
        </Text>
      </div>
      {Array.from(groups.entries()).map(([reason, { count, score, breakdown }]) => (
        <StockRejRow
          key={reason}
          score={score}
          count={count}
          breakdown={breakdown}
          weights={weights}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Contract rejection section (P2-3)
// ---------------------------------------------------------------------------

function ContractRejectionSection({ rejected }: { rejected: RejectedEntry[] }) {
  const [open, setOpen] = useState(false);

  const contractRej = rejected.filter(
    (r) => r.reason.startsWith('all contracts') || r.reason === 'no option chain',
  );
  if (contractRej.length === 0) return null;

  const catCounts: Record<string, number> = { DATA: 0, GREEKS: 0, PRICE: 0, SOFT: 0 };
  let totalContracts = 0;
  for (const r of contractRej) {
    const reasons = parseContractReasons(r.reason);
    for (const [rk, n] of Object.entries(reasons)) {
      totalContracts += n;
      const cat = REASON_CATEGORY[rk] ?? 'SOFT';
      catCounts[cat] = (catCounts[cat] ?? 0) + n;
    }
  }

  return (
    <div className={styles.section}>
      <div className={styles.sectionLabel}>
        <Text size={10} tone="dim" weight={500}>
          CONTRACT REJECTIONS — {contractRej.length} symbols
        </Text>
      </div>
      <div
        className={`${styles.row} ${styles.rowClickable}`}
        onClick={() => setOpen((o) => !o)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setOpen((o) => !o); }}
      >
        <div className={styles.rowLabel}>
          <span className={`${styles.chevron} ${open ? styles.chevronOpen : ''}`}>›</span>
          <Text size={12} tone="reject" weight={500}>ALL CONTRACTS REJECTED</Text>
        </div>
        {totalContracts > 0 && (
          <Data size={11} tone="dim">{totalContracts} contracts</Data>
        )}
      </div>
      {open && (
        <div className={styles.breakdown}>
          {(Object.keys(catCounts) as Array<keyof typeof catCounts>)
            .filter((c) => catCounts[c] > 0)
            .map((cat) => (
              <div key={cat} className={styles.categoryRow}>
                <span className={styles.categoryLabel}><Text size={11} tone="secondary">{CATEGORY_LABELS[cat]}</Text></span>
                <Data size={11} tone="dim">{catCounts[cat]}</Data>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Root export
// ---------------------------------------------------------------------------

export function ScanLog() {
  const context = useScanStore((s) => s.context);
  const result  = useScanStore((s) => s.scanResult);

  if (!result || !context) return null;

  const rejected = result.rejected ?? [];
  if (rejected.length === 0) {
    const n = result.candidates.length;
    return (
      <div className={styles.logEmpty}>
        <Text size={12} tone="secondary">
          {n} stock{n !== 1 ? 's' : ''} scanned · all passed
        </Text>
      </div>
    );
  }

  const hKey    = resolveHorizonKey(context.horizon);
  const weights = HORIZON_WEIGHTS[hKey];
  const wLabel  = Object.entries(weights)
    .map(([k, v]) => `${COMPONENT_LABELS[k] ?? k} ${v}%`)
    .join(' · ');

  return (
    <div className={styles.root}>
      {/* P2-7: Scan context + horizon weights header */}
      <div className={styles.header}>
        <Text size={11} tone="dim">
          Scan: {context.universe} · {context.direction} · {context.horizon} — weights: {wLabel}
        </Text>
      </div>

      <StockRejectionSection rejected={rejected} weights={weights} />
      <ContractRejectionSection rejected={rejected} />
    </div>
  );
}
