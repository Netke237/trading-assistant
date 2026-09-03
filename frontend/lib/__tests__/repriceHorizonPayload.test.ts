/**
 * The Monte Carlo card and the Fixed % Ladder must be told the same horizon.
 *
 * The backend resolves the repricing horizon from a dict keyed by EXACT string
 * and, on a miss, falls through to Swing's 7 days without complaining
 * (backend/app/scoring/reprice_horizon.py's `_fallback_days`). So a frontend
 * that sends "Position" on one path and "Quarterly" on the other does not get
 * an error — it gets two cards on one screen quietly repricing 25 days apart.
 *
 * The specific mistake this guards against is real and was live until the
 * ladder was wired: `/scan` carried `presetByKey(...).scoringHorizon`, which
 * collapses Quarterly, SemiAnnual and Annual all into "Position", while
 * `/first-passage` carried the uncollapsed preset key. Reusing the scan's
 * `horizon` field for repricing would have looked like a one-line win and
 * silently given a 200-day hold and a 20-day hold the same repricing time.
 *
 * backend/tests/test_reprice_horizon_agreement.py pins the other half: that
 * equal inputs produce equal horizons. This file pins that the inputs are
 * equal in the first place.
 */
import { buildOptionsScanRequestBody } from '@/lib/resolveOptionsScanRequest';
import { horizonFieldsFrom } from '@/lib/tradeCardOverride';
import { HORIZON_PRESETS, presetByKey, resolveParamsHorizon } from '@/lib/horizonPresets';
import type { HorizonKey } from '@/lib/horizonPresets';
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
  widthPoints: 5, shortLegDelta: 0.3, ivRankThreshold: 50,
  minCredit: 0.5, maxDebitPctOfWidth: 40,
} as unknown as SpreadsConfig;

function scanBody(presetKey: HorizonKey, holdMin: number, holdMax: number) {
  return buildOptionsScanRequestBody({
    universe: ['AAPL'],
    direction: 'Bullish',
    horizon: presetByKey(resolveParamsHorizon(presetKey, holdMax)).scoringHorizon,
    horizonPreset: presetKey,
    holdMinDays: holdMin,
    holdMaxDays: holdMax,
    minPriceRaw: '', maxPriceRaw: '', minCapRaw: '', maxCapRaw: '', capUnit: 'B',
    scanOverrides: {},
    confidenceGate: CONFIDENCE_GATE,
    fundamentalsGate: FUNDAMENTALS_GATE,
    shortlistMaxCandidates: 10,
    spreads: SPREADS,
  });
}

describe('repricing-horizon payload agreement', () => {
  it.each(HORIZON_PRESETS.map((p) => [p.key, p.holdMin, p.holdMax] as const))(
    '/scan and /first-passage carry the same preset key for %s',
    (key, holdMin, holdMax) => {
      const scan = scanBody(key, holdMin, holdMax);
      const card = horizonFieldsFrom({ horizonPreset: key, holdMin, holdMax });

      expect(scan.horizon_preset).toBe(card.horizon_preset);
      expect(scan.hold_min_days).toBe(card.hold_min);
      expect(scan.hold_max_days).toBe(card.hold_max);
    },
  );

  it('sends the preset key, NOT the collapsed scoring horizon', () => {
    // The whole trap in one assertion: these three all score as "Position" and
    // must NOT reprice as it. If horizon_preset is ever wired to `horizon`,
    // every one of these becomes "Position" and this fails.
    for (const key of ['Quarterly', 'SemiAnnual', 'Annual'] as const) {
      const preset = presetByKey(key);
      const body = scanBody(key, preset.holdMin, preset.holdMax);
      expect(body.horizon).toBe('Position');
      expect(body.horizon_preset).toBe(key);
      expect(body.horizon_preset).not.toBe(body.horizon);
    }
  });

  it('keeps the scoring horizon and the preset key as separate fields', () => {
    // Swing is the one preset where the two spellings coincide, so a wiring
    // mistake hides here. Assert both fields exist independently anyway.
    const body = scanBody('Swing', 5, 15);
    expect(body.horizon).toBe('Swing');
    expect(body.horizon_preset).toBe('Swing');
    expect(Object.keys(body)).toEqual(expect.arrayContaining(['horizon', 'horizon_preset']));
  });

  it('Custom carries the typed range, which is the only thing it can derive from', () => {
    const body = scanBody('Custom', 30, 40);
    const card = horizonFieldsFrom({ horizonPreset: 'Custom', holdMin: 30, holdMax: 40 });
    expect(body.horizon_preset).toBe('Custom');
    expect(card.horizon_preset).toBe('Custom');
    // "Custom" with no range reaching one path and not the other diverges the
    // same way a spelling mismatch does — the backend derives from mean(lo, hi).
    expect(body.hold_min_days).toBe(30);
    expect(body.hold_max_days).toBe(40);
    expect(card.hold_min).toBe(30);
    expect(card.hold_max).toBe(40);
  });

  it('horizonFieldsFrom omits rather than invents when the context is absent', () => {
    // Omitted is a real answer the backend documents as "Swing". Sending
    // `undefined` explicitly, or a made-up 0-day range, is not.
    expect(horizonFieldsFrom(null)).toEqual({});
    expect(horizonFieldsFrom(undefined)).toEqual({});
    expect(horizonFieldsFrom({})).toEqual({});
    expect(horizonFieldsFrom({ horizonPreset: 'Annual' })).toEqual({ horizon_preset: 'Annual' });
    expect(horizonFieldsFrom({ holdMin: 0, holdMax: 2 })).toEqual({ hold_min: 0, hold_max: 2 });
  });
});
