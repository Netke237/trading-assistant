/** P3a item 2 (decision Q5): the Step-3 "Min stock score" default and body field. */
import { PARAM_DEFAULTS_POSITION, PARAM_DEFAULTS_PER_HORIZON } from '@/lib/executionParamDefaults';
import { SCORE_BAND } from '@/lib/status';
import { buildStockScanRequestBody } from '@/lib/resolveStockScanRequest';
import { DEFAULT_CONFIDENCE_GATE } from '@/lib/settingsStore';
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
  });
}

it('is sent only when set, as a top-level field (not a scorer override)', () => {
  expect(body({}).min_stock_score).toBeUndefined();
  const b = body({ min_stock_score: 60 });
  expect(b.min_stock_score).toBe(60);
  expect(b.overrides).not.toHaveProperty('min_stock_score');
});
