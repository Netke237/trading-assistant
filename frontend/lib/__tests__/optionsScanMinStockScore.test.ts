/**
 * Step-3 "Min stock score" (P3a) is a Stocks-mode field: its hint says the
 * Options scan does not read it. The options request must not carry it, in
 * `overrides` or at the top level — `min_stock_score` is also a
 * contract_validator override key (backend _CONTRACT_OVERRIDES, hard_reject),
 * so posting it replaced contract_rules.yaml's contract floor (55) with the
 * Step-3 value as soon as the field was edited.
 */
import { buildOptionsScanRequestBody } from '@/lib/resolveOptionsScanRequest';
import type { ConfidenceGate, FundamentalsGate, SpreadsConfig } from '@/lib/settingsStore';

const CONFIDENCE_GATE = {
  enabled: true, cautionBelow: 45, rejectBelow: 30,
  atrMult: {
    intraday: { target: 1.5, stop: 1.0 },
    swing:    { target: 2.0, stop: 1.2 },
    position: { target: 2.5, stop: 1.5 },
  },
} as unknown as ConfidenceGate;
const FUNDAMENTALS_GATE = {
  enabled: true, cautionBelow: 40, rejectBelow: 25, deReject: 3,
} as unknown as FundamentalsGate;
const SPREADS = {
  widthPoints: 5, shortLegDelta: 0.3, ivRankThreshold: 50, ivAbsThreshold: 0.6,
  minCredit: 0.5, maxDebitPctOfWidth: 40,
} as unknown as SpreadsConfig;

const optionsBody = (scanOverrides: Record<string, number | boolean | string>) =>
  buildOptionsScanRequestBody({
    universe: ['AAPL'], direction: 'Bullish', horizon: 'Swing',
    horizonPreset: 'Swing', holdMinDays: 5, holdMaxDays: 15,
    minPriceRaw: '', maxPriceRaw: '', minCapRaw: '', maxCapRaw: '', capUnit: 'B',
    scanOverrides,
    confidenceGate: CONFIDENCE_GATE, fundamentalsGate: FUNDAMENTALS_GATE,
    shortlistMaxCandidates: 10, spreads: SPREADS,
  });

it('strips an edited min_stock_score from the options scan request', () => {
  const b = optionsBody({ min_stock_score: 40, weight_trend: 30 });
  expect(b.overrides).not.toHaveProperty('min_stock_score');
  expect(b).not.toHaveProperty('min_stock_score');
  // Other score overrides still go through.
  expect(b.overrides.weight_trend).toBe(30);
});
