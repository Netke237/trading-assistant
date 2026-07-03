import type { Interval } from '@/lib/chartStore';
import type { SignalKind } from '@/types/structure';
import type { Candle } from '@/lib/indicators';

export type ConditionOperator = '>' | '<' | '>=' | '<=' | 'crosses_above' | 'crosses_below';
export type LogicOperator = 'AND' | 'OR' | 'N_OF_M';
export type RegimeState = 'Bull' | 'Bear' | 'Choppy' | 'Sideways' | 'Trending' | 'Mean-reverting' | 'any';
export type RegimeModel = 'OMM' | 'HMM' | 'HMM_directional' | 'any';

export interface PriceCondition {
  kind: 'price';
  operator: ConditionOperator;
  value: number;
}

export interface IndicatorCondition {
  kind: 'indicator';
  indicator: string;
  operator: ConditionOperator;
  value: number;
}

export interface StructureCondition {
  kind: 'structure';
  signal_kind: SignalKind;
  direction?: 'bullish' | 'bearish';
  min_confidence?: number;
}

export interface RegimeCondition {
  kind: 'regime';
  model: RegimeModel;
  state: RegimeState;
  min_conviction?: number;
}

export type Condition = PriceCondition | IndicatorCondition | StructureCondition | RegimeCondition;

export interface ConditionGroup {
  logic: LogicOperator;
  n_of_m_threshold?: number;
  conditions: Condition[];
}

export interface AlertRule {
  id: string;
  name: string;
  symbol: string;
  interval: Interval;
  enabled: boolean;
  group: ConditionGroup;
  cooldown_minutes: number;
  expiry_date: string | null;
  created_at: string;
  last_triggered_at: string | null;
}

export interface AlertHistory {
  id: string;
  rule_id: string;
  symbol: string;
  interval: Interval;
  triggered_at: string;
  candle: Candle;
  trigger_values: Record<string, number>;
  reason: string;
}
