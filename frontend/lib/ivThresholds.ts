// Compatibility shims — consumers should migrate to useIvThresholdsStore directly.
export { getIvPassMax, getIvCautionMax, FALLBACK } from '@/lib/ivThresholdsStore';

export const IV_PASS_MAX: Record<string, number | null> = {
  Intraday: null, Swing: 34, Position: 44,
};
export const IV_CAUTION_MAX: Record<string, number | null> = {
  Intraday: null, Swing: 55, Position: 65,
};
