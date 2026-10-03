/*
 * Pure formatting and view-model helpers for Option Contract Explanations.
 * Evaluates no rules, performs no regrading, and preserves authoritative server numbers.
 */
import type { ContractExplanation, ComponentExplanation, BlockerComparison, OptionContract } from '@/types/domain';
import type { Status } from '@/lib/status';

const componentKeys = ['liquidity', 'spread', 'delta', 'dte', 'iv_rank'] as const;
const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every(x => typeof x === 'string');
const optionalNumber = (n: unknown) => n == null || finite(n);

/** Reject unsupported or incomplete snapshots instead of fabricating numbers. */
export function validateExplanation(exp: unknown, contractId?: string): exp is ContractExplanation {
  if (!record(exp)) return false;
  const e = exp;
  if (e.version !== 1 || typeof e.contract_id !== 'string' ||
      (contractId != null && e.contract_id !== contractId) || typeof e.evaluated_at !== 'string' ||
      !['blocked', 'aggregate'].includes(String(e.outcome)) ||
      !['PASS', 'CAUTION', 'REJECT'].includes(String(e.status)) ||
      !finite(e.score) || !finite(e.pass_threshold) || !finite(e.caution_threshold) ||
      !optionalNumber(e.unrounded_score) || !optionalNumber(e.rounded_score) ||
      !finite(e.soft_fail_count) || !finite(e.max_soft_fail_count) ||
      !strings(e.reject_reasons) || !strings(e.soft_flags) ||
      !record(e.weights) || !record(e.components)) return false;
  const validComponent = (c: unknown) => record(c) && typeof c.name === 'string' &&
    typeof c.wire_name === 'string' && ['raw_score', 'weight', 'contribution', 'lost_points'].every(k => finite(c[k])) &&
    ['observed', 'preferred_min', 'preferred_max', 'volume', 'open_interest', 'preferred_volume_min', 'preferred_oi_min'].every(k => optionalNumber(c[k])) &&
    (c.basis == null || ['rank', 'absolute', 'none'].includes(String(c.basis))) && strings(c.flags);
  const weights = e.weights; const components = e.components;
  if (!componentKeys.every(k => finite(weights[k]) && validComponent(components[k]))) return false;
  if (!Array.isArray(e.largest_losses) || !e.largest_losses.every(validComponent) ||
      !Array.isArray(e.blockers) || !e.blockers.every(b => record(b) &&
        ['code', 'label', 'metric', 'operator'].every(k => typeof b[k] === 'string') &&
        (b.observed == null || typeof b.observed === 'string' || finite(b.observed)) &&
        (typeof b.threshold === 'string' || finite(b.threshold)))) return false;
  if (e.hard_bounds != null && (!record(e.hard_bounds) || !Object.values(e.hard_bounds).every(finite))) return false;
  if (e.raw_inputs != null && (!record(e.raw_inputs) || !Object.values(e.raw_inputs).every(optionalNumber))) return false;
  return true;
}

/** Keep all significant boundary digits; integer percentages retain one decimal. */
export function formatPercentRatio(value: number): string {
  if (value === 0) return '0.0%';
  const [mantissa, exponent = '0'] = String(value).split('e');
  const negative = mantissa.startsWith('-');
  const [whole, fraction = ''] = mantissa.replace('-', '').split('.');
  const decimals = fraction.length - Number(exponent) - 2;
  let digits = (whole + fraction).replace(/^0+(?=\d)/, '');
  let percent: string;
  if (decimals <= 0) percent = digits + '0'.repeat(-decimals) + '.0';
  else {
    digits = digits.padStart(decimals + 1, '0');
    percent = digits.slice(0, -decimals) + '.' + digits.slice(-decimals);
    percent = percent.replace(/0+$/, '').replace(/\.$/, '.0');
  }
  return `${negative ? '-' : ''}${percent}%`;
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
    return formatPercentRatio(value);
  }
  if (unit === 'days') {
    return `${Math.round(value)}d`;
  }
  if (unit === 'contracts') {
    return Math.round(value).toLocaleString('en-US');
  }
  if (basis === 'rank') {
    return `${value} (pctl)`;
  }
  if (basis === 'absolute') {
    return `${Number.isInteger(value) ? value.toFixed(1) : String(value)}% IV`;
  }
  return String(value);
}

/** Formats a threshold and operator for human readability. */
export function formatComparison(operator: string, threshold: number | string, unit?: string): string {
  if (!operator && !threshold) return '';
  const opSymbol = operator === '<=' ? '≤' : operator === '>=' ? '≥' : operator;
  let formattedThresh = typeof threshold === 'number' ? threshold.toString() : threshold;
  if (typeof threshold === 'number' && unit === '%') {
    formattedThresh = formatPercentRatio(threshold);
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
  if (!validateExplanation(c.explanation, c.id)) {
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
  return `Score ${exp.score} (${exp.status}); no hard blockers recorded`;
}
