/*
 * scoreDetailText — human-readable one-liners for the per-component score
 * breakdown detail objects (TrendDetail, PullbackDetail, ..., SpreadDetail).
 * Moved out of TradeCard so lib/statusTooltips.ts (and anything else that
 * needs to explain a score component on hover) can reuse them without
 * creating a component -> lib -> component import cycle.
 */
import type {
  TriggerDetail,
  PullbackDetail,
  TrendDetail,
  EventDetail,
  VolDetail,
  DteDetail,
  DeltaDetail,
  IvRankDetail,
  LiquidityDetail,
  SpreadDetail,
} from '@/types/domain';

export function triggerDetailText(d?: TriggerDetail): string | undefined {
  if (!d) return undefined;
  const checks = [
    d.macd_pass  ? 'MACD ✓'  : 'MACD ✗',
    d.rsi_pass   ? 'RSI ✓'   : 'RSI ✗',
    d.stoch_pass ? 'Stoch ✓' : 'Stoch ✗',
  ].join(' · ');
  const candle = d.candle !== 'none' ? d.candle : '';
  const vol = d.volume_bonus ? ' + vol' : '';
  return [candle, `${checks} · ${d.momentum_count}/3 signals${vol}`].filter(Boolean).join(' · ') || undefined;
}

export function pullbackDetailText(d?: PullbackDetail): string | undefined {
  if (!d) return undefined;
  const ret = d.retracement_pct != null ? `Ret ${d.retracement_pct.toFixed(1)}%` : '';
  const fvg = d.fvg_hit ? '+ FVG' : '';
  // d.reason is typed as required, but the un-validated /api/analyze-stock path can
  // forward a raw dict missing it (e.g. the atr_fallback branch of _rule_pullback) —
  // `|| undefined` (not just relying on filter(Boolean)) ensures an all-empty result
  // falls back to the caller's generic status copy instead of silently rendering no
  // tooltip at all.
  return [ret, fvg, d.reason].filter(Boolean).join(' · ') || undefined;
}

export function trendDetailText(d?: TrendDetail): string | undefined {
  if (!d) return undefined;
  if (d.adx_val != null) return `ADX ${d.adx_val.toFixed(0)} · ${d.method}`;
  if (d.stock_roc != null) return `RS ${d.stock_roc.toFixed(1)}% vs bench ${d.bench_roc?.toFixed(1)}%`;
  return d.method;
}

export function eventDetailText(d?: EventDetail): string | undefined {
  if (!d) return undefined;
  if (d.event === 'none') return 'No upcoming event';
  return `${d.event} in ${d.days_to_event}d`;
}

export function volDetailText(d?: VolDetail): string | undefined {
  if (!d) return undefined;
  const parts = [];
  if (d.iv_rank != null) {
    // Same rule as ivDetailText above, and for the same reason: the STOCK
    // score's volatility figure is a percentile ONLY when a rank source
    // answered, which is the minority of chains. Labelling it "IV Rank"
    // unconditionally asserted that every scanned name sat at that percentile
    // of its own 52-week range — a claim nothing measured, on the default path
    // (PHASE-A-NULL-IVRANK-2026-09-06). Responses predating the split carried
    // an absolute level, so that is the default.
    const label = d.iv_basis === 'rank' ? 'IV Rank' : 'IV';
    const unit  = d.iv_basis === 'rank' ? '' : '%';
    parts.push(`${label} ${d.iv_rank.toFixed(0)}${unit}`);
  }
  if (d.reason) parts.push(d.reason);
  return parts.join(' · ') || undefined;
}

export function dteDetailText(d?: DteDetail): string | undefined {
  if (!d) return undefined;
  return `${d.dte}d · target ${d.preferred_min}-${d.preferred_max}d`;
}

export function deltaDetailText(d?: DeltaDetail): string | undefined {
  if (!d) return undefined;
  return `Δ${d.delta.toFixed(2)} · target ${d.preferred_min.toFixed(2)}-${d.preferred_max.toFixed(2)}`;
}

export function ivDetailText(d?: IvRankDetail): string | undefined {
  if (!d) return undefined;
  if (d.iv_rank == null) return 'No implied-volatility data';
  // `iv_rank` may hold a percentile OR an absolute IV, and only `iv_basis`
  // says which — printing an absolute level as "IV Rank" is the exact defect
  // Phase A exists to fix (PHASE-A-NULL-IVRANK-2026-09-06). Responses
  // predating the split carried an absolute level, so that is the default.
  const label = d.iv_basis === 'rank' ? 'IV Rank' : 'IV';
  const unit  = d.iv_basis === 'rank' ? '' : '%';
  return `${label} ${d.iv_rank.toFixed(0)}${unit} · pref ≤${d.preferred_max.toFixed(0)}${unit}`;
}

export function liquidityDetailText(d?: LiquidityDetail): string | undefined {
  if (!d) return undefined;
  return `Vol ${d.volume.toLocaleString()} · OI ${d.open_interest.toLocaleString()} · pref ≥${d.preferred_volume_min.toLocaleString()}/${d.preferred_oi_min.toLocaleString()}`;
}

export function spreadDetailText(d?: SpreadDetail): string | undefined {
  if (!d) return undefined;
  return `Spread ${(d.spread_pct * 100).toFixed(1)}% · pref ≤${(d.preferred_max_pct * 100).toFixed(0)}%`;
}
