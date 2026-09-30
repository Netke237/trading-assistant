// Test fixtures ONLY — the shipped scoring_rules.yaml values as typed records.
// These are NOT a fallback: no production module may import this file
// (decision DOCC-3-THRESHOLD-STORES-REFUSE-2026-09-29). It sits outside
// __tests__ so jest does not collect it as a suite.
import {
  useEventThresholdsStore, type ThresholdHorizon, type HorizonEventThresholds,
} from '@/lib/eventThresholdsStore';
import { useIvThresholdsStore, type HorizonIvThresholds } from '@/lib/ivThresholdsStore';

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

/** The stores' fetch() answers, for a test file that does
 *  `jest.mock('@/lib/api', () => ({ api: { getIvThresholds: jest.fn(), getEventThresholds: jest.fn() } }))`.
 *  Each call answers with the record the test put in the store, so the fetch a
 *  page fires on mount re-sets the test's values instead of clearing them. A
 *  test that put no full record there (null, or a partial one) gets a refusal,
 *  exactly as a malformed backend payload would. */
export function echoStoredThresholds(api: {
  getIvThresholds: jest.Mock;
  getEventThresholds: jest.Mock;
}): void {
  api.getIvThresholds.mockImplementation(async () => useIvThresholdsStore.getState().thresholds);
  api.getEventThresholds.mockImplementation(async () => useEventThresholdsStore.getState().thresholds);
}
