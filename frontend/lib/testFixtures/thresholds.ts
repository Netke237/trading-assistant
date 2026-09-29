// Test fixtures ONLY — the shipped scoring_rules.yaml values as typed records.
// These are NOT a fallback: no production module may import this file
// (decision DOCC-3-THRESHOLD-STORES-REFUSE-2026-09-29). It sits outside
// __tests__ so jest does not collect it as a suite.
import type { ThresholdHorizon, HorizonEventThresholds } from '@/lib/eventThresholdsStore';
import type { HorizonIvThresholds } from '@/lib/ivThresholdsStore';

export const EVENT_SHIPPED: Record<ThresholdHorizon, HorizonEventThresholds> = {
  Intraday: { reject_days: 1,  caution_days: 3  },
  Swing:    { reject_days: 21, caution_days: 45 },
  Position: { reject_days: 30, caution_days: 60 },
};

export const IV_SHIPPED: Record<ThresholdHorizon, HorizonIvThresholds> = {
  Intraday: { abs_pass_max: null, abs_caution_max: null, rank_pass_max: null, rank_caution_max: null },
  Swing:    { abs_pass_max: 34,   abs_caution_max: 55,   rank_pass_max: 34,   rank_caution_max: 55   },
  Position: { abs_pass_max: 44,   abs_caution_max: 65,   rank_pass_max: 44,   rank_caution_max: 65   },
};
