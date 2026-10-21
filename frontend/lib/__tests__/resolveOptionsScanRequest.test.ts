import { buildOptionsScanRequestBody, type ResolvedScanContext } from '@/lib/resolveOptionsScanRequest';
import { DEFAULT_CONFIDENCE_GATE, DEFAULT_FUNDAMENTALS_GATE, DEFAULT_SPREADS } from '@/lib/settingsStore';

it.each([
  ['M', '25', 25_000_000], ['B', '2', 2_000_000_000],
  ['M', '0.5', 500_000], ['B', '0.25', 250_000_000],
  ['M', '0', 0], ['B', '0', 0],
  ['M', '', undefined], ['B', '', undefined],
  ['M', 'NaN', undefined], ['B', 'Infinity', undefined],
] as const)('Options builder converts %s %s into %s USD', (capUnit, raw, usd) => {
  const ctx: ResolvedScanContext = {
    universe: ['AAPL'], direction: 'Bullish', horizon: 'Swing', horizonPreset: 'Swing',
    holdMinDays: 5, holdMaxDays: 15, minPriceRaw: '10', maxPriceRaw: '200',
    minCapRaw: raw, maxCapRaw: raw, capUnit, scanOverrides: {},
    confidenceGate: DEFAULT_CONFIDENCE_GATE, fundamentalsGate: DEFAULT_FUNDAMENTALS_GATE,
    spreads: DEFAULT_SPREADS, shortlistMaxCandidates: 10,
  };
  const req = buildOptionsScanRequestBody(ctx);
  expect(req.min_cap_usd).toBe(usd);
  expect(req.max_cap_usd).toBe(usd);
  expect(req).toMatchObject({ cap_filter_units_version: 1, min_price: 10, max_price: 200 });
  if (usd === undefined) {
    expect(req).not.toHaveProperty('min_cap_usd');
    expect(req).not.toHaveProperty('max_cap_usd');
  }
});
