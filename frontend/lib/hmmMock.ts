import type { Candle } from '@/types/chart';
import type { HmmState } from '@/types/domain';
import type { MarkovConfig } from '@/lib/settingsStore';

/**
 * Deterministic mock HMM state — replaced by backend computation when FastAPI is connected.
 * Uses smoothed average return over a lookback window to classify regime state.
 */
export function computeHmmState(
  candles: Candle[],
  cfg: MarkovConfig,
): { state: HmmState; confidence: number } {
  if (candles.length < cfg.lookback) return { state: 'Choppy', confidence: 0.5 };

  const slice = candles.slice(-cfg.lookback);
  const returns = slice
    .slice(1)
    .map((c, i) => (c.close - slice[i].close) / slice[i].close);
  const avg = returns.reduce((a, b) => a + b, 0) / returns.length;
  const last = returns[returns.length - 1] ?? 0;
  const smoothed = avg * cfg.smoothing + last * (1 - cfg.smoothing);

  const confidence = Math.min(0.95, Math.abs(smoothed) / cfg.threshold);
  if (smoothed > cfg.threshold)  return { state: 'Bull',   confidence };
  if (smoothed < -cfg.threshold) return { state: 'Bear',   confidence };
  return { state: 'Choppy', confidence: Math.max(0.05, 1 - confidence) };
}
