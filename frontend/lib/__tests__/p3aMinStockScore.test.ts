/** P3a item 2 (decision Q5): the Step-3 "Min stock score" default and body field. */
import { PARAM_DEFAULTS_POSITION, PARAM_DEFAULTS_PER_HORIZON } from '@/lib/executionParamDefaults';
import { SCORE_BAND } from '@/lib/status';
import { buildStockScanRequestBody } from '@/lib/resolveStockScanRequest';
import { buildOptionsScanRequestBody } from '@/lib/resolveOptionsScanRequest';
import { DEFAULT_CONFIDENCE_GATE, DEFAULT_FUNDAMENTALS_GATE, DEFAULT_SPREADS } from '@/lib/settingsStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';

it('defaults to the REJECT line on every horizon, so an untouched field changes nothing', () => {
  expect(PARAM_DEFAULTS_POSITION.min_stock_score).toBe(SCORE_BAND.cautionAt);
  for (const [h, d] of Object.entries(PARAM_DEFAULTS_PER_HORIZON)) {
    expect([h, d.min_stock_score]).toEqual([h, SCORE_BAND.cautionAt]);
  }
});

function body(scanOverrides: Record<string, number | boolean | string>) {
  return buildStockScanRequestBody({
    universe: ['SP500'], direction: 'Bullish', horizon: 'Swing', strategy: 'pullback_ema',
    params: useScanParamsStore.getState(), requireReversal: false, scanOverrides,
    confidenceGate: DEFAULT_CONFIDENCE_GATE, accountSize: 50_000, riskPct: 0.01,
    holdMinDays: 5, holdMaxDays: 15, paramsHorizon: null,
  });
}

it('is sent only when set, as a top-level field (not a scorer override)', () => {
  expect(body({}).min_stock_score).toBeUndefined();
  const b = body({ min_stock_score: 60 });
  expect(b.min_stock_score).toBe(60);
  expect(b.overrides).not.toHaveProperty('min_stock_score');
});

// Open question #57: the field is Stocks-mode only (its hint says so), but the
// options resolver forwarded every unrecognised Step-3 key into `overrides`,
// where contract_validator's _CONTRACT_OVERRIDES['min_stock_score'] replaced
// contract_rules.yaml's hard_reject floor (55) with the edited value.
it('is never posted by an options scan, so the contract floor stays contract_rules.yaml\'s', () => {
  const b = buildOptionsScanRequestBody({
    universe: ['SP500'], direction: 'Bullish', horizon: 'Swing',
    horizonPreset: 'Swing', holdMinDays: 5, holdMaxDays: 15,
    minPriceRaw: '', maxPriceRaw: '', minCapRaw: '', maxCapRaw: '', capUnit: 'B',
    scanOverrides: { min_stock_score: 40, weight_trend: 30 },
    confidenceGate: DEFAULT_CONFIDENCE_GATE, fundamentalsGate: DEFAULT_FUNDAMENTALS_GATE,
    shortlistMaxCandidates: 10, spreads: DEFAULT_SPREADS,
  });
  expect(b.overrides).not.toHaveProperty('min_stock_score');
  expect(b).not.toHaveProperty('min_stock_score');
  // Everything else still goes through.
  expect(b.overrides.weight_trend).toBe(0.3);
});
