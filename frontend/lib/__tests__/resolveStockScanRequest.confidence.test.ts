import { buildStockScanRequestBody, type ResolvedStockScanContext } from '@/lib/resolveStockScanRequest';
import { resolveProfileToScanRequest } from '@/lib/scanScheduleResolve';
import { SCAN_PARAM_DEFAULTS } from '@/lib/scanParamsStore';
import type { SearchProfile } from '@/types/searchProfile';

const baseContext: ResolvedStockScanContext = {
  universe: ['SP500'],
  direction: 'Bullish',
  horizon: 'Swing',
  strategy: 'pullback_ema',
  params: { ...SCAN_PARAM_DEFAULTS },
  paramsHorizon: null,
  requireReversal: false,
  scanOverrides: {},
  confidenceGate: {
    enabled: true,
    cautionBelow: 50,
    rejectBelow: 35,
    atrMult: {
      intraday: { target: 2, stop: 1.5 },
      swing: { target: 3, stop: 1.5 },
      position: { target: 2.5, stop: 1.5 },
    },
  },
  accountSize: 50_000,
  riskPct: 0.01,
  holdMinDays: 5,
  holdMaxDays: 15,
};

describe('buildStockScanRequestBody — confidence threshold overrides (#383)', () => {
  describe('when confidenceGate is enabled', () => {
    it('uses explicit numeric overrides when provided', () => {
      const body = buildStockScanRequestBody({
        ...baseContext,
        scanOverrides: {
          confidence_caution_below: 65,
          confidence_reject_below: 45,
        },
      });

      expect(body.confidence_caution_below).toBe(65);
      expect(body.confidence_reject_below).toBe(45);
    });

    it('preserves explicit 0 overrides (finding C5)', () => {
      const body = buildStockScanRequestBody({
        ...baseContext,
        scanOverrides: {
          confidence_caution_below: 0,
          confidence_reject_below: 0,
        },
      });

      expect(body.confidence_caution_below).toBe(0);
      expect(body.confidence_reject_below).toBe(0);
    });

    it('falls back to settings thresholds when overrides are absent', () => {
      const body = buildStockScanRequestBody({
        ...baseContext,
        scanOverrides: {},
      });

      expect(body.confidence_caution_below).toBe(50);
      expect(body.confidence_reject_below).toBe(35);
    });

    it('falls back independently when only one override is provided', () => {
      const body = buildStockScanRequestBody({
        ...baseContext,
        scanOverrides: {
          confidence_caution_below: 62,
        },
      });

      expect(body.confidence_caution_below).toBe(62);
      expect(body.confidence_reject_below).toBe(35);
    });

    it('falls back when override is null, undefined, or non-finite', () => {
      const body = buildStockScanRequestBody({
        ...baseContext,
        scanOverrides: {
          confidence_caution_below: null as unknown as number,
          confidence_reject_below: NaN,
        },
      });

      expect(body.confidence_caution_below).toBe(50);
      expect(body.confidence_reject_below).toBe(35);
    });
  });

  describe('when confidenceGate is disabled', () => {
    it('sends undefined thresholds regardless of overrides', () => {
      const body = buildStockScanRequestBody({
        ...baseContext,
        confidenceGate: {
          ...baseContext.confidenceGate,
          enabled: false,
        },
        scanOverrides: {
          confidence_caution_below: 65,
          confidence_reject_below: 45,
        },
      });

      expect(body.confidence_caution_below).toBeUndefined();
      expect(body.confidence_reject_below).toBeUndefined();
    });

    it('sends undefined thresholds when overrides are absent', () => {
      const body = buildStockScanRequestBody({
        ...baseContext,
        confidenceGate: {
          ...baseContext.confidenceGate,
          enabled: false,
        },
        scanOverrides: {},
      });

      expect(body.confidence_caution_below).toBeUndefined();
      expect(body.confidence_reject_below).toBeUndefined();
    });
  });

  describe('SearchProfile / Scheduled Scan resolution parity', () => {
    const baseProfile: SearchProfile = {
      id: 'test-profile',
      name: 'Test Profile',
      createdAt: '2026-10-20T00:00:00.000Z',
      updatedAt: '2026-10-20T00:00:00.000Z',
      mode: 'stocks',
      direction: 'Bullish',
      horizonPreset: 'Swing',
      holdMin: 5,
      holdMax: 15,
      strategy: 'pullback_ema',
      strategyParams: { ...SCAN_PARAM_DEFAULTS },
      universe: {
        pick: 'SP500',
        customRaw: '',
        minPriceRaw: '',
        maxPriceRaw: '',
        minCapRaw: '',
        maxCapRaw: '',
        capUnit: 'B',
      },
      scanSettings: {
        confidenceGate: {
          enabled: true,
          cautionBelow: 50,
          rejectBelow: 35,
          atrMult: {
            intraday: { target: 2, stop: 1.5 },
            swing: { target: 3, stop: 1.5 },
            position: { target: 2.5, stop: 1.5 },
          },
        },
        fundamentalsGate: {
          enabled: false,
          cautionBelow: 45,
          rejectBelow: 30,
          deReject: 3,
        },
        shortlistMaxCandidates: 10,
        spreads: {
          shortLegDelta: 0.3,
          widthPoints: 5,
          ivRankThreshold: 50,
          ivAbsThreshold: 50,
          minCredit: 0.5,
          maxDebitPctOfWidth: 40,
        },
      },
      scanOverrides: {},
    };

    it('resolves explicit zero overrides from saved search profile', () => {
      const profile: SearchProfile = {
        ...baseProfile,
        scanOverrides: {
          confidence_caution_below: 0,
          confidence_reject_below: 0,
        },
      };

      const req = resolveProfileToScanRequest(profile);
      expect(req.confidence_caution_below).toBe(0);
      expect(req.confidence_reject_below).toBe(0);
    });

    it('resolves custom non-zero overrides from saved search profile', () => {
      const profile: SearchProfile = {
        ...baseProfile,
        scanOverrides: {
          confidence_caution_below: 58,
          confidence_reject_below: 42,
        },
      };

      const req = resolveProfileToScanRequest(profile);
      expect(req.confidence_caution_below).toBe(58);
      expect(req.confidence_reject_below).toBe(42);
    });

    it('omits thresholds when profile gate is disabled', () => {
      const profile: SearchProfile = {
        ...baseProfile,
        scanSettings: {
          ...baseProfile.scanSettings,
          confidenceGate: {
            ...baseProfile.scanSettings.confidenceGate,
            enabled: false,
          },
        },
        scanOverrides: {
          confidence_caution_below: 58,
          confidence_reject_below: 42,
        },
      };

      const req = resolveProfileToScanRequest(profile);
      expect(req.confidence_caution_below).toBeUndefined();
      expect(req.confidence_reject_below).toBeUndefined();
    });
  });
});
