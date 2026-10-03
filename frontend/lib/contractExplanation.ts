/*
 * Pure formatting and view-model helpers for Option Contract Explanations.
 * Evaluates no rules, performs no regrading, and preserves authoritative server numbers.
 */
import type { ContractExplanation, ComponentExplanation, BlockerComparison, OptionContract } from '@/types/domain';
import type { Status } from '@/lib/status';

/** Validates that an untrusted object meets the ContractExplanation shape. */
export function validateExplanation(exp: unknown): exp is ContractExplanation {
  if (!exp || typeof exp !== 'object') return false;
  const e = exp as Record<string, unknown>;
  return (
    typeof e.version === 'number' &&
    typeof e.contract_id === 'string' &&
    typeof e.evaluated_at === 'string' &&
    (e.outcome === 'blocked' || e.outcome === 'aggregate') &&
    typeof e.score === 'number' &&
    Number.isFinite(e.score) &&
    typeof e.pass_threshold === 'number' &&
    Number.isFinite(e.pass_threshold) &&
    typeof e.caution_threshold === 'number' &&
    Number.isFinite(e.caution_threshold) &&
    typeof e.weights === 'object' &&
    e.weights !== null &&
    typeof e.components === 'object' &&
    e.components !== null &&
    Array.isArray(e.largest_losses) &&
    Array.isArray(e.blockers)
  );
}

/** Display names for the five weighted components. */
export function getComponentDisplayName(name: string): string {
  switch (name) {
    case 'liquidity':
      return 'Liquidity';
    case 'spread':
      return 'Bid-Ask Spread';
    case 'delta':
      return 'Delta';
    case 'dte':
    case 'dteFit':
      return 'DTE Fit';
    case 'iv_rank':
    case 'ivAttractiveness':
      return 'IV Attractiveness';
    default:
      return name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  }
}

/** Status classification for an individual 0-100 component sub-score. */
export function getComponentStatus(score: number): Status {
  if (score >= 65) return 'PASS';
  if (score >= 45) return 'CAUTION';
  return 'REJECT';
}

/** Formats an observed metric value with appropriate unit and decimal precision. */
export function formatMetricValue(
  value: number | string | null | undefined,
  unit?: string,
  basis?: string | null
): string {
  if (value == null) return '—';
  if (typeof value === 'string') return value;
  if (!Number.isFinite(value)) return '—';

  if (unit === '%') {
    // Spread observations use ratios at every magnitude; absolute IV uses its basis below.
    return `${(value * 100).toFixed(1)}%`;
  }
  if (unit === 'days') {
    return `${Math.round(value)}d`;
  }
  if (unit === 'contracts') {
    return Math.round(value).toLocaleString('en-US');
  }
  if (basis === 'rank') {
    return `${Math.round(value)} (pctl)`;
  }
  if (basis === 'absolute') {
    return `${value.toFixed(1)}% IV`;
  }
  if (Math.abs(value) < 1 && value !== 0) {
    return value.toFixed(2);
  }
  return Number.isInteger(value) ? value.toLocaleString('en-US') : value.toFixed(2);
}

/** Formats a threshold and operator for human readability. */
export function formatComparison(operator: string, threshold: number | string, unit?: string): string {
  if (!operator && !threshold) return '';
  const opSymbol = operator === '<=' ? '≤' : operator === '>=' ? '≥' : operator;
  let formattedThresh = typeof threshold === 'number' ? threshold.toString() : threshold;
  if (typeof threshold === 'number' && unit === '%') {
    formattedThresh = `${(threshold * 100).toFixed(1)}%`;
  } else if (unit) {
    formattedThresh = `${formattedThresh}${unit === '%' ? '%' : ' ' + unit}`;
  }
  return `${opSymbol} ${formattedThresh}`;
}

/** Summary of blockers and outcome for badges and tooltips. */
export function getBlockingSummary(explanation?: ContractExplanation | null): {
  isBlocked: boolean;
  primaryBlocker: string | null;
  allBlockers: string[];
} {
  if (!explanation || !validateExplanation(explanation)) {
    return { isBlocked: false, primaryBlocker: null, allBlockers: [] };
  }
  if (explanation.outcome === 'blocked' && explanation.blockers.length > 0) {
    const list = explanation.blockers.map((b) => `${b.label} (${b.metric} ${b.operator} ${b.threshold})`);
    return {
      isBlocked: true,
      primaryBlocker: list[0] ?? 'Blocked by rule',
      allBlockers: list,
    };
  }
  return { isBlocked: false, primaryBlocker: null, allBlockers: [] };
}

/** Formats a primary summary line for collapsed view or row badges. */
export function getExplanationSummaryLine(c: OptionContract): string {
  if (!c.explanation) {
    return 'Explanation unavailable for this result';
  }
  const exp = c.explanation;
  if (exp.outcome === 'blocked') {
    const primary = exp.blockers[0];
    if (primary) {
      return `Blocked: ${primary.label} (${primary.metric} ${primary.operator} ${primary.threshold})`;
    }
    return 'Score forced to 0 by blocking rule(s)';
  }
  if (exp.status === 'REJECT') {
    return `Score ${exp.score} below caution threshold (${exp.caution_threshold}) with no hard blockers`;
  }
  if (exp.largest_losses.length > 0 && exp.largest_losses[0].lost_points > 0) {
    const topLoss = exp.largest_losses[0];
    const name = getComponentDisplayName(topLoss.name);
    return `Largest loss: ${name} (−${topLoss.lost_points.toFixed(1)} pts)`;
  }
  return `Score ${exp.score}/100 cleared all rules`;
}
