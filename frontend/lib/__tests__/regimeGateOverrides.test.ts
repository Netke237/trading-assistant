/**
 * The Step-3 Regime Gate controls must reach the same place, with the same
 * value, on both scan paths that carry them: the options scan and the stocks
 * scan. The auto-trade arm reads the CARD's resolved snapshot instead
 * (`regimeGateFromCard`, pinned at the bottom of this file).
 *
 * Piece 2 round 1 finding 3, in one sentence: "Headwind reject %" has been on
 * the shared Step-3 panel in every screener mode since it was built, and only
 * the STOCK scan request ever carried it. Setting it and running an options
 * scan did nothing at all — and the options scan is the only one whose cards
 * can be armed, so the value never reached a fire either.
 *
 * These pin the wire contract. backend/tests/test_regime_gate_resolver.py pins
 * what the backend does with it once it arrives.
 */
import { buildOptionsScanRequestBody } from '@/lib/resolveOptionsScanRequest';
import { buildStockScanRequestBody } from '@/lib/resolveStockScanRequest';
import { regimeGateOverridesFrom, regimeGateFromCard } from '@/lib/regimeGateOverrides';
import type { ConfidenceGate, FundamentalsGate, SpreadsConfig } from '@/lib/settingsStore';
import type { ScanParams } from '@/lib/scanParamsStore';

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
const PARAMS = {
  pullbackTolerancePct: 0.08, pullbackEmaPeriod: 50, pullbackTrendEma: 100,
  pullbackMaType: 'EMA', maCrossoverFast: 20, maCrossoverSlow: 50,
  maCrossoverLookback: 10, breakoutVolumeMult: 1.1, rsiPeriod: 14,
  rsiOversold: 30, rsiTrendSma: 200, requireChoppyRegime: false,
  btMinTrades: 5, btMinWinRate: 0.45, eventFilter: 'include',
  stockShortlistMax: 10, meanReversionVariants: [], meanReversionMinConfirm: 2,
  vwapLookback: 20, vwapDeviationPct: 0.02,
} as unknown as ScanParams;

type Ov = Record<string, number | boolean | string>;

const optionsBody = (scanOverrides: Ov) => buildOptionsScanRequestBody({
  universe: ['AAPL'], direction: 'Bullish', horizon: 'Swing',
  horizonPreset: 'Swing', holdMinDays: 5, holdMaxDays: 15,
  minPriceRaw: '', maxPriceRaw: '', minCapRaw: '', maxCapRaw: '', capUnit: 'B',
  scanOverrides,
  confidenceGate: CONFIDENCE_GATE, fundamentalsGate: FUNDAMENTALS_GATE,
  shortlistMaxCandidates: 10, spreads: SPREADS,
});

const stocksBody = (scanOverrides: Ov) => buildStockScanRequestBody({
  universe: ['AAPL'], direction: 'Bullish', horizon: 'Swing',
  strategy: 'pullback_ema', params: PARAMS, requireReversal: false,
  scanOverrides, confidenceGate: CONFIDENCE_GATE,
  accountSize: 50_000, riskPct: 0.01, holdMinDays: 5, holdMaxDays: 15, paramsHorizon: null,
});

describe('regimeGateOverridesFrom', () => {
  it('passes numbers through and leaves anything else undefined', () => {
    expect(regimeGateOverridesFrom({
      regime_headwind_caution_pct: -25, regime_headwind_reject_pct: -80,
    })).toEqual({ regime_headwind_caution_pct: -25, regime_headwind_reject_pct: -80 });

    // A store written before these keys existed, and a store that somehow
    // carries a string — both mean "not set", not "0".
    expect(regimeGateOverridesFrom({})).toEqual({
      regime_headwind_caution_pct: undefined, regime_headwind_reject_pct: undefined,
    });
    expect(regimeGateOverridesFrom({ regime_headwind_reject_pct: '-80' })
      .regime_headwind_reject_pct).toBeUndefined();
  });

  it('keeps zero, which is inside the control\'s own -100..0 range', () => {
    // A truthiness test here would drop it and let the backend fall back to
    // the YAML -40 — 40 points looser than the trader asked for.
    expect(regimeGateOverridesFrom({
      regime_headwind_caution_pct: 0, regime_headwind_reject_pct: 0,
    })).toEqual({ regime_headwind_caution_pct: 0, regime_headwind_reject_pct: 0 });
  });

  it('tolerates a null/undefined override map rather than throwing', () => {
    expect(regimeGateOverridesFrom(null).regime_headwind_reject_pct).toBeUndefined();
    expect(regimeGateOverridesFrom(undefined).regime_headwind_reject_pct).toBeUndefined();
  });
});

describe('both scan requests carry the Step-3 Regime Gate controls', () => {
  const set: Ov = { regime_headwind_caution_pct: -25, regime_headwind_reject_pct: -80 };

  it('options scan sends them as TOP-LEVEL fields', () => {
    const body = optionsBody(set);
    expect(body.regime_headwind_caution_pct).toBe(-25);
    expect(body.regime_headwind_reject_pct).toBe(-80);
  });

  it('stocks scan sends the same two, from the same reader', () => {
    const body = stocksBody(set);
    expect(body.regime_headwind_caution_pct).toBe(-25);
    expect(body.regime_headwind_reject_pct).toBe(-80);
  });

  it('the two scans agree field-for-field on what the controls said', () => {
    // The point of the shared reader: not that each is right today, but that
    // they cannot be edited apart.
    const o = optionsBody(set);
    const s = stocksBody(set);
    expect(o.regime_headwind_caution_pct).toBe(s.regime_headwind_caution_pct);
    expect(o.regime_headwind_reject_pct).toBe(s.regime_headwind_reject_pct);
  });

  it('options scan keeps them OUT of the score-overrides dict', () => {
    // They are top-level request fields. `stock_scorer` ignores keys it does
    // not know, so a leak here is silent — it just means the value is posted
    // somewhere nothing reads, which is exactly how it went unnoticed.
    expect(optionsBody(set).overrides).not.toHaveProperty('regime_headwind_reject_pct');
    expect(optionsBody(set).overrides).not.toHaveProperty('regime_headwind_caution_pct');
  });

  it('omits both when Step 3 never set them, so the backend reads its YAML', () => {
    expect(optionsBody({}).regime_headwind_reject_pct).toBeUndefined();
    expect(stocksBody({}).regime_headwind_reject_pct).toBeUndefined();
  });
});

describe('regimeGateFromCard — the arm path reads the CARD, not Step 3', () => {
  it('returns null when the card carries no snapshot (absent or null)', () => {
    expect(regimeGateFromCard({})).toBeNull();
    expect(regimeGateFromCard({ regimeGate: null })).toBeNull();
  });

  it('maps the resolved thresholds onto the arm payload keys', () => {
    expect(regimeGateFromCard({ regimeGate: { headwindCautionPct: -15, headwindRejectPct: -40 } }))
      .toEqual({ regime_headwind_caution_pct: -15, regime_headwind_reject_pct: -40 });
  });

  it('keeps a zero and turns a null value into an omitted key', () => {
    const g = regimeGateFromCard({ regimeGate: { headwindCautionPct: null, headwindRejectPct: 0 } });
    expect(g).toEqual({ regime_headwind_caution_pct: undefined, regime_headwind_reject_pct: 0 });
  });
});
