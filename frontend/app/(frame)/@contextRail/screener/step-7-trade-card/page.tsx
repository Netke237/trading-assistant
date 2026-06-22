'use client';

/*
 * Trade Card right-rail — Pre-trade checklist.
 * Gates are computed from live TradeCardData + WatchlistRow for the
 * candidate currently active in Step 7 (tracked via scanStore.selectedSymbol).
 */

import { RailSection } from '@/components/organisms/ContextRail';
import { RailQuickLook } from '@/components/organisms/ContextRail/QuickLook';
import { Text } from '@/components/primitives';
import { StatusDot } from '@/components/atoms/StatusDot';
import { useScanStore } from '@/lib/scanStore';
import { statusForScore } from '@/lib/status';
import { useIvThresholdsStore, getIvPassMax, getIvCautionMax } from '@/lib/ivThresholdsStore';
import type { TradeCardData, WatchlistRow } from '@/types/domain';
import type { Status } from '@/lib/status';
import styles from './page.module.css';

interface Gate {
  label:  string;
  status: 'PASS' | 'CAUTION' | 'REJECT';
}

function buildChecklist(
  candidate: TradeCardData,
  wlRow: WatchlistRow | undefined,
  regime: Status,
  horizonKey: string,
  ivThresholds: Record<string, { pass_max: number | null; caution_max: number | null }>,
): Gate[] {
  const gates: Gate[] = [];

  // Regime — PENDING/NO_DATA means scan not run yet, show CAUTION not REJECT
  if (regime !== 'PENDING' && regime !== 'NO_DATA') {
    const regimeStatus: 'PASS' | 'CAUTION' | 'REJECT' =
      regime === 'PASS' ? 'PASS' : regime === 'CAUTION' ? 'CAUTION' : 'REJECT';
    gates.push({ label: 'Regime PASS', status: regimeStatus });
  }

  // IV rank acceptable — thresholds from ivThresholdsStore (fetched from backend)
  const ivRank = candidate.contractDetails?.ivRank;
  if (ivRank !== undefined) {
    const ivPassMax    = getIvPassMax(horizonKey, ivThresholds);
    const ivCautionMax = getIvCautionMax(horizonKey, ivThresholds);
    const ivStatus: 'PASS' | 'CAUTION' | 'REJECT' =
      ivPassMax === null    ? 'PASS' :           // Intraday: no IV gate
      ivRank <= ivPassMax   ? 'PASS' :
      ivCautionMax !== null && ivRank <= ivCautionMax ? 'CAUTION' :
      'REJECT';
    gates.push({ label: 'IV rank acceptable', status: ivStatus });
  }

  // Earnings > 7d away
  const days = wlRow?.nextEventDays;
  if (days != null) {
    gates.push({
      label: 'Earnings > 7d away',
      status: days > 7 ? 'PASS' : days >= 3 ? 'CAUTION' : 'REJECT',
    });
  }

  // Score ≥ 55 (both stock and contract) — thresholds from statusForScore()
  const minScore = Math.min(candidate.stockScore, candidate.contractScore);
  gates.push({
    label: 'Score ≥ 55',
    status: statusForScore(minScore) as 'PASS' | 'CAUTION' | 'REJECT',
  });

  // R:R ≥ 2.0
  gates.push({
    label: 'R:R ≥ 2.0',
    status: candidate.rrRatio >= 2.0 ? 'PASS' : candidate.rrRatio >= 1.5 ? 'CAUTION' : 'REJECT',
  });

  // Spread score ≥ 70 (higher = tighter spread)
  const spreadScore = candidate.contractBreakdown.spread;
  gates.push({
    label: 'Spread < 5% of price',
    status: spreadScore >= 70 ? 'PASS' : spreadScore >= 40 ? 'CAUTION' : 'REJECT',
  });

  return gates;
}

export default function TradeCardContextRail() {
  const selectedSymbol      = useScanStore((s) => s.selectedSymbol);
  const regime              = useScanStore((s) => s.combinedRegime);
  const horizon             = useScanStore((s) => s.context?.horizon);
  const scanResultCandidates = useScanStore((s) => s.scanResult?.candidates);
  const candidates          = scanResultCandidates ?? [];
  const ivThresholds        = useIvThresholdsStore((s) => s.thresholds);

  const horizonKey = horizon?.startsWith('Intraday') ? 'Intraday'
    : horizon?.startsWith('Position') ? 'Position'
    : 'Swing';

  const candidate = candidates.find((c) => c.symbol === selectedSymbol) ?? candidates[0];

  // Build a minimal WatchlistRow from candidate for buildChecklist
  const wlRow: WatchlistRow | undefined = candidate
    ? {
        symbol: candidate.symbol,
        company: candidate.company,
        price: candidate.price,
        direction: candidate.direction,
        horizon: 'Swing',
        score: candidate.stockScore,
        rankDelta: 0,
        scoreDelta: 0,
        status: candidate.status,
        breakdown: candidate.stockBreakdown,
        nextEventDays: candidate.nextEventDays,
        nextEventLabel: candidate.nextEventLabel,
      }
    : undefined;

  const gates = candidate ? buildChecklist(candidate, wlRow, regime, horizonKey, ivThresholds) : [];

  return (
    <>
      <RailSection title={selectedSymbol ? `Pre-trade checklist · ${selectedSymbol}` : 'Pre-trade checklist'}>
        {!candidate ? (
          <Text size={12} tone="dim">Run a scan to populate the checklist.</Text>
        ) : (
          <>
            <Text size={11} tone="dim">
              Gates for this candidate. Portfolio-level checks live below.
            </Text>
            <div className={styles.checklistStack}>
              {gates.map((g) => (
                <div key={g.label} className={styles.checklistRow}>
                  <StatusDot tone={g.status} size="sm" />
                  <Text size={12} tone={g.status === 'CAUTION' ? 'caution' : 'secondary'}>
                    {g.label}
                  </Text>
                </div>
              ))}
            </div>
          </>
        )}
      </RailSection>

      <RailSection title="Historical analogs">
        <Text size={12} tone="dim">Not yet available.</Text>
      </RailSection>

      <RailQuickLook />
    </>
  );
}
