import fs from 'fs';
import path from 'path';
import { isValidSearchProfile } from '@/lib/searchProfileValidation';
import { resolveProfileToScanRequest } from '@/lib/scanScheduleResolve';
import type { OptionsScanRequestBody } from '@/lib/resolveOptionsScanRequest';
import type { SearchProfile } from '@/types/searchProfile';

const EXPORT_PATH = path.resolve(__dirname, '../../../docs/search-profiles/search-profiles-export.json');

const EXPECTED_PROFILE_IDS = [
  'mu2n6u2bxt11', // Intraday_Baseline_Bullish
  'mu2n6u8qlkqx', // Intraday_Restrictive_Bullish
  'mu2n6uh2o5iy', // Intraday_Loose_Bullish
  'mu2n6us7zsyl', // Intraday_Baseline_Bearish
  'mu2n6uz5ciqd', // Intraday_Restrictive_Bearish
  'mu2n6v7g9r4p', // Intraday_Loose_Bearish
  'mu2n6vi56pd4', // Swing_Baseline_Bullish
  'mu2n6vokoroy', // Swing_Restrictive_Bullish
  'mu2n6vvzvia6', // Swing_Loose_Bullish
  'mu2n6w3ghw31', // Swing_Baseline_Bearish
  'mu2n6wdkphqe', // Swing_Restrictive_Bearish
  'mu2n6wlgp0oc', // Swing_Loose_Bearish
  'mu2n6wtt37o9', // SemiAnnual_Baseline_Bullish
  'mu2n6x4w0gb9', // SemiAnnual_Restrictive_Bullish
  'mu2n6xcbasfh', // SemiAnnual_Loose_Bullish
  'mu2n6xjqcewd', // SemiAnnual_Baseline_Bearish
  'mu2n6xtffvnn', // SemiAnnual_Restrictive_Bearish
  'mu2n6y1r5fyf', // SemiAnnual_Loose_Bearish
];

describe('Options Search Profiles Recalibration (#187)', () => {
  let exportData: { state: { profiles: unknown[] }; version: number };
  let profiles: SearchProfile[];

  beforeAll(() => {
    expect(fs.existsSync(EXPORT_PATH)).toBe(true);
    const raw = fs.readFileSync(EXPORT_PATH, 'utf-8');
    exportData = JSON.parse(raw);
    profiles = exportData.state.profiles as SearchProfile[];
  });

  it('exports Schema Version 5 envelope with exactly 18 options profiles', () => {
    expect(exportData.version).toBe(5);
    expect(Array.isArray(profiles)).toBe(true);
    expect(profiles).toHaveLength(18);
  });

  it('preserves all 18 stable profile IDs without drift or regeneration', () => {
    const ids = profiles.map((p) => p.id);
    expect(ids).toEqual(EXPECTED_PROFILE_IDS);
  });

  it('passes strict Schema Version 5 runtime validation (isValidSearchProfile) on every profile', () => {
    for (const p of profiles) {
      expect(isValidSearchProfile(p)).toBe(true);
      expect(p.mode).toBe('options');
      expect(p.strategy).toBeUndefined();
      expect(p.strategyParams).toBeUndefined();

      // Universe primitive string bounds
      expect(typeof p.universe.minPriceRaw).toBe('string');
      expect(typeof p.universe.maxPriceRaw).toBe('string');
      expect(typeof p.universe.minCapRaw).toBe('string');
      expect(typeof p.universe.maxCapRaw).toBe('string');
      expect(typeof p.universe.customRaw).toBe('string');
      expect(p.universe.capUnit).toBe('B');

      // Confidence gate full atrMult structure
      const cg = p.scanSettings.confidenceGate;
      expect(cg.enabled).toBe(true);
      expect(cg.atrMult.intraday).toBeDefined();
      expect(cg.atrMult.swing).toBeDefined();
      expect(cg.atrMult.position).toBeDefined();
    }
  });

  it('enforces 3x3x2 parameter matrix invariants across horizons, tiers, and directions', () => {
    for (const p of profiles) {
      const isBullish = p.direction === 'Bullish';
      const isBearish = p.direction === 'Bearish';
      expect(isBullish || isBearish).toBe(true);

      // Fundamentals D/E gate: Bullish 3, Bearish 10
      expect(p.scanSettings.fundamentalsGate?.deReject).toBe(isBullish ? 3 : 10);

      const isSemiAnnual = p.horizonPreset === 'SemiAnnual';
      const isIntraday = p.horizonPreset === 'Intraday';
      const isSwing = p.horizonPreset === 'Swing';
      expect(isIntraday || isSwing || isSemiAnnual).toBe(true);

      // Event overrides on SemiAnnual
      if (isSemiAnnual) {
        expect(p.scanOverrides.event_reject_days).toBe(7);
        expect(p.scanOverrides.event_caution_days).toBe(30);
      } else {
        expect(p.scanOverrides.event_reject_days).toBeUndefined();
        expect(p.scanOverrides.event_caution_days).toBeUndefined();
      }

      // Tier-specific liquidity overrides
      if (p.name.includes('_Baseline_')) {
        expect(p.scanSettings.shortlistMaxCandidates).toBe(10);
        if (!isSemiAnnual) {
          expect(Object.keys(p.scanOverrides)).toHaveLength(0);
        } else {
          expect(p.scanOverrides).toEqual({ event_reject_days: 7, event_caution_days: 30 });
        }
      } else if (p.name.includes('_Restrictive_')) {
        expect(p.scanSettings.shortlistMaxCandidates).toBe(10);
        expect(p.scanOverrides.max_bid_ask_spread_pct).toBe(0.08);
        expect(p.scanOverrides.min_open_interest).toBe(1000);
        expect(p.scanOverrides.min_volume).toBe(isSemiAnnual ? 50 : 200);
      } else if (p.name.includes('_Loose_')) {
        expect(p.scanSettings.shortlistMaxCandidates).toBe(20);
        expect(p.scanOverrides.max_bid_ask_spread_pct).toBe(0.3);
        expect(p.scanOverrides.preferred_spread_pct_max).toBe(0.3);
        expect(p.scanOverrides.min_volume).toBe(0);
        expect(p.scanOverrides.preferred_volume_min).toBe(20);
        expect(p.scanOverrides.min_open_interest).toBe(75);
        expect(p.scanOverrides.preferred_oi_min).toBe(75);
      }
    }
  });

  it('successfully resolves every profile to an OptionsScanRequestBody via resolveProfileToScanRequest', () => {
    for (const p of profiles) {
      const req = resolveProfileToScanRequest(p) as OptionsScanRequestBody;
      expect(req.direction).toBe(p.direction);
      expect(req.horizon_preset).toBe(p.horizonPreset);
      expect(req.universe).toEqual(['SP500']);
      expect(typeof req.overrides).toBe('object');
      expect(req.overrides?.shortlist_max_candidates).toBe(p.scanSettings.shortlistMaxCandidates);
    }
  });
});
