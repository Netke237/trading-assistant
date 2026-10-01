/**
 * Step-3 "Min stock score" (P3a) is a Stocks-mode field: its hint says the
 * Options scan does not read it. The options request must not carry it, in
 * `overrides` or at the top level — `min_stock_score` is also a
 * contract_validator override key (backend _CONTRACT_OVERRIDES, hard_reject),
 * so posting it replaced contract_rules.yaml's contract floor (55) with the
 * Step-3 value as soon as the field was edited.
 */
import { buildOptionsScanRequestBody } from '@/lib/resolveOptionsScanRequest';
import { DEFAULT_CONFIDENCE_GATE, DEFAULT_FUNDAMENTALS_GATE, DEFAULT_SPREADS } from '@/lib/settingsStore';

const optionsBody = (scanOverrides: Record<string, number | boolean | string>) =>
  buildOptionsScanRequestBody({
    universe: ['AAPL'], direction: 'Bullish', horizon: 'Swing',
    horizonPreset: 'Swing', holdMinDays: 5, holdMaxDays: 15,
    minPriceRaw: '', maxPriceRaw: '', minCapRaw: '', maxCapRaw: '', capUnit: 'B',
    scanOverrides,
    confidenceGate: DEFAULT_CONFIDENCE_GATE, fundamentalsGate: DEFAULT_FUNDAMENTALS_GATE,
    shortlistMaxCandidates: 10, spreads: DEFAULT_SPREADS,
  });

it('strips an edited min_stock_score from the options scan overrides', () => {
  const b = optionsBody({ min_stock_score: 40, weight_trend: 30 });
  expect(b.overrides).not.toHaveProperty('min_stock_score');
  // Other score overrides still go through.
  expect(b.overrides.weight_trend).toBe(30);
});
