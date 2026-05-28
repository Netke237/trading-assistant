import { evaluateRules } from '@/lib/chartAlertEngine';
import type { AlertRule } from '@/types/alerts';
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
