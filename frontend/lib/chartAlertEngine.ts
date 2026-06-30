import type { AlertRule, Condition, AlertHistory, RegimeCondition } from '@/types/alerts';
import type { Candle } from '@/lib/indicators';
import type { StructureSignal } from '@/types/structure';
import type { Interval } from '@/lib/chartStore';

export interface RegimeSnapshot {
  state: string;
  conviction?: number;
  model?: 'OMM' | 'HMM';
}

interface Point {
  time: string | number;
  value: number;
}

function isCooldownPassed(rule: AlertRule, now: Date): boolean {
  if (!rule.last_triggered_at) return true;
  const lastMs = new Date(rule.last_triggered_at).getTime();
  return now.getTime() - lastMs >= rule.cooldown_minutes * 60 * 1000;
}

function isExpired(rule: AlertRule, now: Date): boolean {
  if (!rule.expiry_date) return false;
  return now > new Date(rule.expiry_date);
}

function comparePrice(op: string, a: number, b: number): boolean {
  switch (op) {
    case '>': return a > b;
    case '<': return a < b;
    case '>=': return a >= b;
    case '<=': return a <= b;
    default: return false;
  }
}

function evaluateRegimeCondition(
  condition: RegimeCondition,
  regime: RegimeSnapshot | null,
): { met: boolean; triggerValues: Record<string, number> } {
  if (!regime) return { met: false, triggerValues: {} };
  const modelMatch = condition.model === 'any' || !regime.model || regime.model === condition.model;
  const stateMatch = condition.state === 'any' || regime.state === condition.state;
  const convictionMatch =
    condition.min_conviction == null ||
    (regime.conviction != null && regime.conviction >= condition.min_conviction);
  const met = modelMatch && stateMatch && convictionMatch;
  return { met, triggerValues: met ? { regime_state: 1 } : {} };
}

function evaluateCondition(
  condition: Condition,
  closedCandle: Candle,
  indicators: Record<string, Point[]>,
  signals: StructureSignal[],
  candleTime: string | number,
  regime: RegimeSnapshot | null,
): { met: boolean; triggerValues: Record<string, number> } {
  const triggerValues: Record<string, number> = {};

  if (condition.kind === 'regime') {
    return evaluateRegimeCondition(condition, regime);
  }

  if (condition.kind === 'price') {
    triggerValues.close = closedCandle.close;
    return { met: comparePrice(condition.operator, closedCandle.close, condition.value), triggerValues };
  }

  if (condition.kind === 'indicator') {
    const series = indicators[condition.indicator];
    if (!series) return { met: false, triggerValues };
    const idx = series.findIndex((p) => p.time === candleTime);
    if (idx === -1) return { met: false, triggerValues };
    const currentValue = series[idx].value;
    triggerValues[condition.indicator] = currentValue;

    if (condition.operator === 'crosses_above') {
      if (idx <= 0) return { met: false, triggerValues };
      const prevValue = series[idx - 1].value;
      return { met: currentValue > condition.value && prevValue <= condition.value, triggerValues };
    }
    if (condition.operator === 'crosses_below') {
      if (idx <= 0) return { met: false, triggerValues };
      const prevValue = series[idx - 1].value;
      return { met: currentValue < condition.value && prevValue >= condition.value, triggerValues };
    }
    return { met: comparePrice(condition.operator, currentValue, condition.value), triggerValues };
  }

  if (condition.kind === 'structure') {
    const matchingSignal = signals.find((s) => {
      if (s.kind !== condition.signal_kind) return false;
      if (condition.direction) {
        if ('direction' in s && s.direction !== condition.direction) return false;
      }
      if (condition.min_confidence != null) {
        if ('confidence' in s && (s.confidence ?? 0) < condition.min_confidence) return false;
      }
      const signalTime = 'time' in s ? s.time : 'time_start' in s ? s.time_start : '';
      return String(signalTime) >= String(candleTime);
    });
    if (matchingSignal) {
      triggerValues[condition.signal_kind] = 1;
      return { met: true, triggerValues };
    }
    return { met: false, triggerValues };
  }

  return { met: false, triggerValues };
}

function buildReason(rule: AlertRule, triggerValues: Record<string, number>): string {
  if (rule.group.conditions.length === 0) return '';
  const sep = rule.group.logic === 'N_OF_M'
    ? ` (${rule.group.n_of_m_threshold ?? 1}-of-${rule.group.conditions.length}) `
    : ` ${rule.group.logic} `;
  return rule.group.conditions
    .map((c) => {
      if (c.kind === 'price') return `Price ${c.operator} ${c.value}`;
      if (c.kind === 'indicator') {
        const val = triggerValues[c.indicator];
        const valStr = ` (was ${val != null ? val.toFixed(2) : 'N/A'})`;
        return `${c.indicator} ${c.operator} ${c.value}${valStr}`;
      }
      if (c.kind === 'structure') {
        return `${c.signal_kind} ${c.direction ?? ''} detected`.trim();
      }
      if (c.kind === 'regime') {
        return `Regime ${c.model === 'any' ? '' : c.model + ' '}state = ${c.state}${c.min_conviction != null ? ` (conv≥${c.min_conviction}%)` : ''}`.trim();
      }
      return '';
    })
    .filter(Boolean)
    .join(sep);
}

export function evaluateRules(
  rules: AlertRule[],
  closedCandle: Candle,
  _allCandles: Candle[],
  indicators: Record<string, Point[]>,
  signals: StructureSignal[],
  now: Date,
  activeSymbol: string,
  activeInterval: Interval,
  regime?: RegimeSnapshot | null,
): AlertHistory[] {
  const results: AlertHistory[] = [];

  for (const rule of rules) {
    if (!rule.enabled) continue;
    if (rule.symbol !== activeSymbol) continue;
    if (rule.interval !== activeInterval) continue;
    if (rule.group.conditions.length === 0) continue;
    if (isExpired(rule, now)) continue;
    if (!isCooldownPassed(rule, now)) continue;

    const accumulatedTriggerValues: Record<string, number> = {};
    const evaluations = rule.group.conditions.map((c) => {
      const ev = evaluateCondition(c, closedCandle, indicators, signals, closedCandle.time, regime ?? null);
      Object.assign(accumulatedTriggerValues, ev.triggerValues);
      return ev.met;
    });

    const threshold = rule.group.n_of_m_threshold ?? 1;
    const triggered =
      rule.group.logic === 'AND'   ? evaluations.every(Boolean) :
      rule.group.logic === 'OR'    ? evaluations.some(Boolean) :
      /* N_OF_M */                   evaluations.filter(Boolean).length >= threshold;

    if (triggered) {
      const id = now.getTime().toString(36) + Math.random().toString(36).slice(2, 6);
      results.push({
        id,
        rule_id: rule.id,
        symbol: rule.symbol,
        interval: rule.interval,
        triggered_at: now.toISOString(),
        candle: { ...closedCandle },
        trigger_values: accumulatedTriggerValues,
        reason: buildReason(rule, accumulatedTriggerValues),
      });
    }
  }

  return results;
}
