// A GET /api/config/strategy-profiles payload shaped like the backend's
// (backend/app/routers/config.py get_strategy_profiles, STOCKS-HORIZON-T1 H4):
// every horizon reads the direction baseline ("baseline") unless a test
// overlays a tuned profile with `withTuned`.
const BASELINES: Record<string, Record<string, unknown>> = {
  pullback_ema: { ema_period: 50, trend_ema: 100, atr_stop_mult: 1.5, rr_target_mult: 2.0, tolerance: 0.04, exit_swing_lookback: 20 },
  breakout_base: { base_lookback: 20, atr_tight_max: 4.0, volume_mult: 1.5, rr_target_mult: 2.0, measured_move_mult: 1.0 },
  ma_crossover: { fast: 20, slow: 50, lookback: 10, atr_target_mult: 3.0 },
  mean_reversion_rsi: { rsi_period: 14, rsi_oversold: 30, trend_sma: 200, require_choppy_regime: false, exit_sma_period: 20, atr_target_mult: 2.5 },
  mean_reversion_bb: { bb_period: 20, bb_std: 2.0, trend_sma: 200, stop_atr_mult: 0.5, rr_target_mult: 2.0, require_choppy_regime: false },
  mean_reversion_multi: {
    variants: ['mean_reversion_rsi', 'mean_reversion_bb', 'mean_reversion_vwap_daily'],
    min_confirmations: 2,
    variant_params: { mean_reversion_vwap_daily: { vwap_lookback: 20, vwap_deviation_pct: 0.02 } },
  },
};

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

const HORIZONS = ['Swing', 'Position', 'Quarterly', 'SemiAnnual', 'Annual'];

type Payload = Record<string, Record<string, {
  baseline: Record<string, unknown>;
  horizons: Record<string, { params: Record<string, unknown>; source: 'tuned' | 'baseline' }>;
}>>;

export function profilesPayload(): Payload {
  const out: Payload = {};
  for (const [strategy, base] of Object.entries(BASELINES)) {
    out[strategy] = {};
    for (const direction of ['Bullish', 'Bearish']) {
      const horizons: Payload[string][string]['horizons'] = {};
      for (const h of HORIZONS) horizons[h] = { params: clone(base), source: 'baseline' };
      out[strategy][direction] = { baseline: clone(base), horizons };
    }
  }
  return out;
}

/** The payload with one tuned profile overlaid on the baseline. */
export function withTuned(
  payload: Payload, strategy: string, direction: string, horizon: string, params: Record<string, unknown>,
): Payload {
  const p = clone(payload);
  const d = p[strategy][direction];
  d.horizons[horizon] = { params: { ...d.baseline, ...params }, source: 'tuned' };
  return p;
}
