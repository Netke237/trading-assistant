'use client';

/*
 * Trade Card right-rail — Pre-trade checklist.
 * Gates are computed from the card Step 7 is SHOWING, published by that page
 * into tradeCardUiStore -- the Step-6 pick applied and its recomputed plan
 * merged. Never from the raw scan candidate: after a pick that is the
 * auto-picked contract, and the rail graded its IV, score, spread and R:R
 * beside a card showing another one (A8, open_questions[64]).
 *
 * IV thresholds are fetched on mount and read as the EFFECTIVE record (fetched
 * + Settings' session override), the same effectiveIvThresholds Step 5 uses.
 * No record in hand -> the IV item is CAUTION, never PASS (decision
 * DOCC-3-THRESHOLD-STORES-REFUSE-2026-09-29).
 */

import { useEffect, useMemo } from 'react';
import { RailSection } from '@/components/organisms/ContextRail';
import { RailQuickLook } from '@/components/organisms/ContextRail/QuickLook';
import { Text } from '@/components/primitives';
import { StatusDot } from '@/components/atoms/StatusDot';
import { useScanStore } from '@/lib/scanStore';
import { useTradeCardUiStore } from '@/lib/tradeCardUiStore';
import { statusForScore } from '@/lib/status';
import {
  useIvThresholdsStore, getIvPassMax, getIvCautionMax, effectiveIvThresholds, ivOverrideFor,
  type HorizonIvThresholds,
} from '@/lib/ivThresholdsStore';
import type { ThresholdHorizon } from '@/lib/eventThresholdsStore';
import { resolveIv, formatIv } from '@/lib/ivBasis';
import { ScreenerStepGate } from '@/components/organisms/ScreenerStepGate';
import type { TradeCardData, WatchlistRow } from '@/types/domain';
import type { Status } from '@/lib/status';
import styles from './page.module.css';

interface Gate {
  label:  string;
  status: 'PASS' | 'CAUTION' | 'REJECT';
  /** Non-redundant hover detail — the actual value behind the gate, not a
   *  repeat of `label`. */
  detail: string;
}

function buildChecklist(
  candidate: TradeCardData,
  wlRow: WatchlistRow | undefined,
  regime: Status,
  horizonKey: ThresholdHorizon,
  ivThresholds: Record<ThresholdHorizon, HorizonIvThresholds> | null,
  rrPending: boolean,
  ivOverride: { value: number; yaml: number } | null = null,
  eventWindow: { reject_days: number; caution_days: number } | undefined = undefined,
): Gate[] {
  const gates: Gate[] = [];

  // Regime — PENDING/NO_DATA means scan not run yet, show CAUTION not REJECT
  if (regime !== 'PENDING' && regime !== 'NO_DATA') {
    const regimeStatus: 'PASS' | 'CAUTION' | 'REJECT' =
      regime === 'PASS' ? 'PASS' : regime === 'CAUTION' ? 'CAUTION' : 'REJECT';
    gates.push({ label: 'Regime PASS', status: regimeStatus, detail: `Current market regime: ${regime}.` });
  }

  // IV acceptable — thresholds from ivThresholdsStore (fetched from backend).
  // The figure may be a percentile or an absolute IV, and each is judged by
  // its own threshold set (PHASE-A-NULL-IVRANK-2026-09-06). With no figure at
  // all the gate is CAUTION, not PASS: an unknown IV is not a clean read, and
  // silently passing it is how a gate stops being a gate.
  const iv = resolveIv(candidate.contractDetails);
  // ROUND 4 finding 14. The gate-disabled test has to come FIRST. Ordered the
  // other way, an Intraday contract with no IV reading showed "CAUTION: the IV
  // gate could not be applied" on a horizon where the IV gate is disabled by
  // design — cautioning about the absence of a check that was never going to
  // run. Nothing is missing there, so nothing is flagged.
  // DOCC-3: before even that, an UNKNOWN config. No record in hand is not a
  // disabled gate, so it is checked ahead of `gateDisabled` and never PASS.
  const gateDisabled = ivThresholds !== null
    && getIvPassMax(horizonKey, ivThresholds, iv.basis === 'none' ? 'absolute' : iv.basis) === null;
  if (ivThresholds === null) {
    gates.push({
      label: 'IV acceptable',
      status: 'CAUTION',
      detail: 'IV thresholds could not be loaded from scoring_rules.yaml — the IV gate was not applied.',
    });
  } else if (gateDisabled) {
    gates.push({
      label: 'IV acceptable',
      status: 'PASS',
      detail: `No IV gate for ${horizonKey}.`,
    });
  } else if (iv.basis === 'none') {
    gates.push({
      label: 'IV acceptable',
      status: 'CAUTION',
      detail: 'No implied-volatility data for this contract — the IV gate could not be applied.',
    });
  } else {
    const ivValue      = iv.value as number;
    const shown        = formatIv(iv, candidate.symbol);
    const ivPassMax    = getIvPassMax(horizonKey, ivThresholds, iv.basis);
    const ivCautionMax = getIvCautionMax(horizonKey, ivThresholds, iv.basis);
    const noun         = iv.basis === 'rank' ? 'IV rank' : 'IV';
    const ivStatus: 'PASS' | 'CAUTION' | 'REJECT' =
      ivPassMax === null    ? 'PASS' :           // Intraday: no IV gate
      ivValue <= ivPassMax  ? 'PASS' :
      ivCautionMax !== null && ivValue <= ivCautionMax ? 'CAUTION' :
      'REJECT';
    gates.push({
      label: 'IV acceptable',
      status: ivStatus,
      detail: ivPassMax === null
        ? `${noun} ${shown.text} — no IV gate for ${horizonKey}.`
        : `${noun} ${shown.text} vs. pass ≤${ivPassMax}${ivCautionMax != null ? ` / caution ≤${ivCautionMax}` : ''}.`
          // The override replaces the ABSOLUTE pass ceiling only.
          + (ivOverride !== null && iv.basis === 'absolute'
            ? ` (session override from Settings; scoring_rules.yaml: ${ivOverride.yaml})` : ''),
    });
  }

  // Fix #3: the scan's own event window (echoed on the scan result), never a
  // fixed 7/3d. With no window in hand the gate is CAUTION, not PASS -- an
  // unknown window is not a clean read (same rule as the IV gate above).
  //
  // D4 amended 2026-10-03 (Kenneth): an unknown earnings date caps a SINGLE
  // STOCK's card at CAUTION and blocks its auto-fire (backend). An ETF has no
  // earnings, so it passes. A card without `isEtf` (pre-deploy scan) reads as
  // a stock -- the same safe direction the backend takes.
  if (candidate.earningsUnknown) {
    gates.push(candidate.isEtf
      ? {
          label: 'Earnings date',
          status: 'PASS',
          detail: 'ETF — no earnings date to check.',
        }
      : {
          label: 'Earnings date',
          status: 'CAUTION',
          detail: 'No earnings date on file — the card is capped at CAUTION and auto-trade will not fire a single stock. Check the calendar before sending.',
        });
  }
  // Graded on EARNINGS distance only. nextEventDays is the nearer of earnings
  // and dividend, and only earnings veto (D3): a dividend inside the window
  // must not read as an "Earnings" REJECT. Unknown earnings is the CAUTION
  // gate above.
  const days = candidate.earningsDays;
  if (days != null) {
    gates.push(eventWindow
      ? {
          label: 'Earnings outside reject window',
          status: days < eventWindow.reject_days ? 'REJECT' : days < eventWindow.caution_days ? 'CAUTION' : 'PASS',
          detail: `Next event in ${days}d — reject <${eventWindow.reject_days}d, caution <${eventWindow.caution_days}d (this scan's window).`,
        }
      : {
          label: 'Earnings outside reject window',
          status: 'CAUTION',
          detail: `Next event in ${days}d — this scan carried no event window; re-run the scan.`,
        });
  }

  // Score ≥ 55 (both stock and contract) — thresholds from statusForScore()
  const minScore = Math.min(candidate.stockScore, candidate.contractScore);
  gates.push({
    label: 'Score ≥ 55',
    status: statusForScore(minScore) as 'PASS' | 'CAUTION' | 'REJECT',
    detail: `Lower of stock score (${candidate.stockScore}) and contract score (${candidate.contractScore}) = ${minScore}.`,
  });

  // R:R ≥ 2.0. While the picked contract's plan is loading (or failed) the
  // card's rrRatio is still the auto-pick's -- CAUTION, never that figure.
  if (rrPending) {
    gates.push({
      label: 'R:R ≥ 2.0',
      status: 'CAUTION',
      detail: 'R:R not yet recomputed for the contract picked in Step 6.',
    });
  } else gates.push({
    label: 'R:R ≥ 2.0',
    status: candidate.rrRatio >= 2.0 ? 'PASS' : candidate.rrRatio >= 1.5 ? 'CAUTION' : 'REJECT',
    detail: `Projected reward:risk is ${candidate.rrRatio.toFixed(1)}× — pass ≥2.0×, caution 1.5-2.0×.`,
  });

  // Spread score ≥ 70 (higher = tighter spread)
  const spreadScore = candidate.contractBreakdown.spread;
  gates.push({
    label: 'Spread < 5% of price',
    status: spreadScore >= 70 ? 'PASS' : spreadScore >= 40 ? 'CAUTION' : 'REJECT',
    detail: `Spread quality sub-score ${spreadScore}/100 — pass ≥70, caution 40-69.`,
  });

  return gates;
}

export default function TradeCardContextRail() {
  const published           = useTradeCardUiStore((s) => s.activeCard);
  const regime              = useScanStore((s) => s.combinedRegime);
  const horizon             = useScanStore((s) => s.context?.horizon);
  // Fix #3: the scan's own earnings window, echoed on its result.
  const eventWindow         = useScanStore((s) => s.scanResult?.event_window);
  // Two selectors (Zustand v5: never one returning a fresh object).
  const ivFetched           = useIvThresholdsStore((s) => s.thresholds);
  const ivOverrides         = useIvThresholdsStore((s) => s.overrides);
  const ivThresholds = useMemo(
    () => effectiveIvThresholds(ivFetched, ivOverrides),
    [ivFetched, ivOverrides],
  );
  useEffect(() => { void useIvThresholdsStore.getState().fetch(); }, []);

  const horizonKey: ThresholdHorizon = horizon?.startsWith('Intraday') ? 'Intraday'
    : horizon?.startsWith('Position') ? 'Position'
    : 'Swing';

  const candidate = published?.card;

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

  const gates = candidate ? buildChecklist(
    candidate, wlRow, regime, horizonKey, ivThresholds, published?.rrPending ?? false,
    ivOverrideFor(horizonKey, ivFetched, ivOverrides),
    eventWindow,
  ) : [];

  return (
    <ScreenerStepGate>
      <>
      <RailSection title={candidate ? `Pre-trade checklist · ${candidate.symbol}` : 'Pre-trade checklist'}>
        {!candidate ? (
          <Text size={12} tone="dim">Run a scan to populate the checklist.</Text>
        ) : (
          <>
            <Text size={11} tone="dim">
              Gates for this candidate. Portfolio-level checks live below.
            </Text>
            <div className={styles.checklistStack}>
              {gates.map((g) => (
                <div key={g.label} className={styles.checklistRow} data-gate-label={g.label} data-status={g.status}>
                  <StatusDot tone={g.status} size="sm" title={g.detail} />
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
    </ScreenerStepGate>
  );
}
