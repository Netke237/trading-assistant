import { evaluateRules, conditionLabel } from '@/lib/chartAlertEngine';
import type { AlertRule, PriceCondition, IndicatorCondition, RegimeCondition, StructureCondition } from '@/types/alerts';
import type { Candle } from '@/lib/indicators';
import type { StructureSignal } from '@/types/structure';
import type { Interval } from '@/lib/chartStore';

const SYM = 'AAPL';
const INT: Interval = '1D';

function candles(): Candle[] {
  return [
    { time: '2024-01-02', open: 181, high: 184, low: 180, close: 183, volume: 1000 },
    { time: '2024-01-03', open: 183, high: 186, low: 182, close: 184, volume: 1200 },
    { time: '2024-01-04', open: 184, high: 190, low: 183, close: 188, volume: 1500 },
    { time: '2024-01-05', open: 188, high: 192, low: 187, close: 190, volume: 2000 },
  ];
}

const closedCandle: Candle = candles()[3];

const indicators = {
  'RSI(14)': [
    { time: '2024-01-02', value: 45 },
    { time: '2024-01-03', value: 48 },
    { time: '2024-01-04', value: 52 },
    { time: '2024-01-05', value: 55 },
  ],
  'EMA(20)': [
    { time: '2024-01-02', value: 180 },
    { time: '2024-01-03', value: 182 },
    { time: '2024-01-04', value: 184 },
    { time: '2024-01-05', value: 186 },
  ],
};

const now = new Date('2024-01-05T16:00:00Z');

describe('evaluateRules', () => {
  it('test_price_condition_gt_triggers — price > 185 triggers when close = 190', () => {
    const rule: AlertRule = {
      id: 'r1', name: 'P>185', symbol: SYM, interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [{ kind: 'price', operator: '>', value: 185 }] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(1);
    expect(result[0].trigger_values.close).toBe(190);
    expect(result[0].reason).toBe('Price > 185');
  });

  it('test_price_condition_lt_does_not_trigger — price < 170 does not trigger when close = 190', () => {
    const rule: AlertRule = {
      id: 'r1', name: 'P<170', symbol: SYM, interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [{ kind: 'price', operator: '<', value: 170 }] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(0);
  });

  it('test_price_condition_gte_triggers — price >= 190 triggers when close = 190', () => {
    const rule: AlertRule = {
      id: 'r1', name: 'P>=190', symbol: SYM, interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [{ kind: 'price', operator: '>=', value: 190 }] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(1);
  });

  it('test_price_condition_lte_triggers — price <= 190 triggers when close = 190', () => {
    const rule: AlertRule = {
      id: 'r1', name: 'P<=190', symbol: SYM, interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [{ kind: 'price', operator: '<=', value: 190 }] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(1);
  });

  it('test_indicator_crosses_above — RSI crosses above 50', () => {
    const ind = {
      'RSI(14)': [
        { time: '2024-01-02', value: 45 },
        { time: '2024-01-03', value: 48 },
        { time: '2024-01-04', value: 49 },
        { time: '2024-01-05', value: 55 },
      ],
    };
    const rule: AlertRule = {
      id: 'r2', name: 'RSI X>50', symbol: SYM, interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [{ kind: 'indicator', indicator: 'RSI(14)', operator: 'crosses_above', value: 50 }] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), ind, [], now, SYM, INT);
    expect(result).toHaveLength(1);
    expect(result[0].reason).toContain('RSI(14)');
    expect(result[0].trigger_values['RSI(14)']).toBe(55);
  });

  it('test_indicator_crosses_below — RSI crosses below 50', () => {
    const ind = {
      'RSI(14)': [
        { time: '2024-01-02', value: 55 },
        { time: '2024-01-03', value: 52 },
        { time: '2024-01-04', value: 51 },
        { time: '2024-01-05', value: 45 },
      ],
    };
    const rule: AlertRule = {
      id: 'r2b', name: 'RSI X<50', symbol: SYM, interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [{ kind: 'indicator', indicator: 'RSI(14)', operator: 'crosses_below', value: 50 }] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), ind, [], now, SYM, INT);
    expect(result).toHaveLength(1);
  });

  it('test_indicator_simple_gt — RSI > 50 triggers', () => {
    const rule: AlertRule = {
      id: 'r2c', name: 'RSI>50', symbol: SYM, interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [{ kind: 'indicator', indicator: 'RSI(14)', operator: '>', value: 50 }] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(1);
  });

  it('test_structure_condition_matches — BOS bullish signal triggers', () => {
    const signals: StructureSignal[] = [
      { kind: 'BOS', direction: 'bullish', time: '2024-01-05', price: 189, confidence: 80, mtf_aligned: false },
    ];
    const rule: AlertRule = {
      id: 'r3', name: 'BOS Bull', symbol: SYM, interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [{ kind: 'structure', signal_kind: 'BOS', direction: 'bullish' }] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, signals, now, SYM, INT);
    expect(result).toHaveLength(1);
    expect(result[0].reason).toContain('BOS');
  });

  it('test_structure_min_confidence_filters — confidence 50 below threshold 70 skipped', () => {
    const signals: StructureSignal[] = [
      { kind: 'BOS', direction: 'bullish', time: '2024-01-05', price: 189, confidence: 50, mtf_aligned: false },
    ];
    const rule: AlertRule = {
      id: 'r3b', name: 'BOS Conf', symbol: SYM, interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [{ kind: 'structure', signal_kind: 'BOS', direction: 'bullish', min_confidence: 70 }] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, signals, now, SYM, INT);
    expect(result).toHaveLength(0);
  });

  it('test_and_logic_requires_all — AND: both conditions must pass', () => {
    const rule: AlertRule = {
      id: 'r4', name: 'AND', symbol: SYM, interval: INT, enabled: true,
      group: {
        logic: 'AND',
        conditions: [
          { kind: 'price', operator: '>', value: 185 },
          { kind: 'price', operator: '<', value: 200 },
        ],
      },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(1);
  });

  it('test_and_logic_fails_if_one_false — AND: one false = no trigger', () => {
    const rule: AlertRule = {
      id: 'r4b', name: 'AND fail', symbol: SYM, interval: INT, enabled: true,
      group: {
        logic: 'AND',
        conditions: [
          { kind: 'price', operator: '>', value: 185 },
          { kind: 'price', operator: '<', value: 189 },
        ],
      },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(0);
  });

  it('test_or_logic_requires_one — OR: one condition sufficient', () => {
    const rule: AlertRule = {
      id: 'r5', name: 'OR', symbol: SYM, interval: INT, enabled: true,
      group: {
        logic: 'OR',
        conditions: [
          { kind: 'price', operator: '>', value: 200 },
          { kind: 'price', operator: '>', value: 185 },
        ],
      },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(1);
  });

  it('test_cooldown_blocks_retrigger — triggered 30 min ago, cooldown 60 min', () => {
    const triggeredAt = new Date('2024-01-05T15:30:00Z');
    const rule: AlertRule = {
      id: 'r6', name: 'Cooldown', symbol: SYM, interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [{ kind: 'price', operator: '>', value: 185 }] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: triggeredAt.toISOString(),
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(0);
  });

  it('test_expired_rule_skipped — expiry Jan 4, now Jan 5', () => {
    const rule: AlertRule = {
      id: 'r7', name: 'Expired', symbol: SYM, interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [{ kind: 'price', operator: '>', value: 185 }] },
      cooldown_minutes: 60, expiry_date: '2024-01-04T00:00:00Z', created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(0);
  });

  it('test_disabled_rule_skipped', () => {
    const rule: AlertRule = {
      id: 'r9', name: 'Disabled', symbol: SYM, interval: INT, enabled: false,
      group: { logic: 'AND', conditions: [{ kind: 'price', operator: '>', value: 185 }] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(0);
  });

  it('test_rule_mismatched_symbol_skipped — engine filters by activeSymbol', () => {
    const rule: AlertRule = {
      id: 'r10', name: 'MSFT', symbol: 'MSFT', interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [{ kind: 'price', operator: '>', value: 185 }] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(0);
  });

  it('test_empty_conditions_skipped', () => {
    const rule: AlertRule = {
      id: 'r11', name: 'Empty', symbol: SYM, interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(0);
  });
});

describe('conditionLabel', () => {
  it('price: includes live value when available', () => {
    const c: PriceCondition = { kind: 'price', operator: '>', value: 119 };
    expect(conditionLabel(c, { close: 128.68 })).toBe('Price above 119 (was 128.68)');
  });

  it('price: omits value when not available', () => {
    const c: PriceCondition = { kind: 'price', operator: '>', value: 119 };
    expect(conditionLabel(c, {})).toBe('Price above 119');
  });

  it('indicator: includes live reading', () => {
    const c: IndicatorCondition = { kind: 'indicator', indicator: 'RSI(14)', operator: '>', value: 70 };
    expect(conditionLabel(c, { 'RSI(14)': 62.4 })).toBe('RSI(14) above 70 (was 62.40)');
  });

  it('regime: distinguishes model and conviction', () => {
    const omm: RegimeCondition = { kind: 'regime', model: 'OMM', state: 'Bull' };
    const hmm: RegimeCondition = { kind: 'regime', model: 'HMM', state: 'Bull' };
    expect(conditionLabel(omm, {})).toBe('Trend regime: Bull');
    expect(conditionLabel(hmm, {})).toBe('Trend regime: Bull (HMM model)');
    expect(conditionLabel(omm, {})).not.toBe(conditionLabel(hmm, {}));
  });

  it('regime: shows conviction threshold when set', () => {
    const c: RegimeCondition = { kind: 'regime', model: 'OMM', state: 'Bull', min_conviction: 70 };
    expect(conditionLabel(c, {})).toBe('Trend regime: Bull, conviction ≥70%');
  });

  it('structure: maps known signal kinds to plain labels', () => {
    const c: StructureCondition = { kind: 'structure', signal_kind: 'BOS', direction: 'bullish' };
    expect(conditionLabel(c, {})).toBe('Breakout structure (BOS, bullish)');
  });

  it('structure: falls back to the raw kind for unmapped signal kinds', () => {
    const c: StructureCondition = { kind: 'structure', signal_kind: 'Fibonacci' };
    expect(conditionLabel(c, {})).toBe('Fibonacci (Fibonacci)');
  });

  it('structure: distinguishes direction', () => {
    const bull: StructureCondition = { kind: 'structure', signal_kind: 'BOS', direction: 'bullish' };
    const bear: StructureCondition = { kind: 'structure', signal_kind: 'BOS', direction: 'bearish' };
    expect(conditionLabel(bull, {})).not.toBe(conditionLabel(bear, {}));
    expect(conditionLabel(bull, {})).toContain('bullish');
    expect(conditionLabel(bear, {})).toContain('bearish');
  });

  it('regime: the explicit "any" literal renders as "any state"', () => {
    const c: RegimeCondition = { kind: 'regime', model: 'OMM', state: 'any' };
    expect(conditionLabel(c, {})).toBe('Trend regime: any state');
  });

  // The next five tests simulate a rule fetched from the backend whose stored
  // rule_json is missing a field entirely, or has it as an explicit JSON
  // null -- GET /alerts/rules returns the raw stored JSON (see _rule_to_dict
  // in chart_alerts.py), not run through Python's own c.get(key, default)
  // defaulting, so these are real runtime shapes despite the Condition types
  // declaring these fields as required. Each test isolates exactly one null
  // field so a regression in a single `||`/`&&` guard condition is caught,
  // mirroring TestConditionLabel's null-guard tests in
  // backend/tests/test_chart_alerts_notification_text.py one-for-one.

  it('regime: null model AND null state together do not leak "null" and still read "any state"', () => {
    const c = JSON.parse('{"kind":"regime","model":null,"state":null}') as RegimeCondition;
    const label = conditionLabel(c, {});
    expect(label).not.toContain('null');
    expect(label).toBe('Trend regime: any state');
  });

  it('structure: null signal_kind falls back to "Structure signal" without leaking "null"', () => {
    const c = JSON.parse('{"kind":"structure","signal_kind":null}') as StructureCondition;
    const label = conditionLabel(c, {});
    expect(label).not.toContain('null');
    expect(label).toBe('Structure signal');
  });

  it('price: null operator alone falls back to "Price condition"', () => {
    const c = JSON.parse('{"kind":"price","operator":null,"value":119}') as PriceCondition;
    expect(conditionLabel(c, {})).toBe('Price condition');
  });

  it('price: null value alone falls back to "Price condition"', () => {
    const c = JSON.parse('{"kind":"price","operator":">","value":null}') as PriceCondition;
    expect(conditionLabel(c, {})).toBe('Price condition');
  });

  it('indicator: null indicator alone (operator/value present) falls back to "Indicator condition"', () => {
    const c = JSON.parse('{"kind":"indicator","indicator":null,"operator":">","value":70}') as IndicatorCondition;
    expect(conditionLabel(c, {})).toBe('Indicator condition');
  });

  it('indicator: null operator alone (indicator present) falls back to "Indicator condition"', () => {
    const c = JSON.parse('{"kind":"indicator","indicator":"RSI(14)","operator":null,"value":70}') as IndicatorCondition;
    expect(conditionLabel(c, {})).toBe('Indicator condition');
  });
});

describe('evaluateRules checklist', () => {
  it('attaches a checklist entry per condition with correct met flags', () => {
    const rule: AlertRule = {
      id: 'r1', name: 'N of M', symbol: SYM, interval: INT, enabled: true,
      group: {
        logic: 'N_OF_M', n_of_m_threshold: 1,
        conditions: [
          { kind: 'price', operator: '>', value: 185 },
          { kind: 'price', operator: '<', value: 100 },
        ],
      },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(1);
    expect(result[0].checklist).toEqual([
      { label: 'Price above 185 (was 190.00)', met: true },
      { label: 'Price below 100 (was 190.00)', met: false },
    ]);
  });
});
