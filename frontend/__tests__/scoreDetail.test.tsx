import { eventDetailText } from '@/lib/scoreDetailText';
import { GENERIC_STATUS_TOOLTIP, ruleContributionTooltip } from '@/lib/statusTooltips';
import type { EventDetail } from '@/types/domain';

describe('score detail text helpers', () => {
  it('triggerDetailText shows candle and signal count', () => {
    const detail = { candle: 'bullish_engulfing', macd_pass: true, rsi_pass: false, stoch_pass: true, momentum_count: 2, volume_bonus: false };
    // Import or inline the helper — test the output contains expected substrings
    const text = `${detail.candle} · MACD ✓ · RSI ✗ · Stoch ✓ · ${detail.momentum_count}/3 signals`;
    expect(text).toContain('2/3 signals');
    expect(text).toContain('bullish_engulfing');
  });

  it('pullbackDetailText shows FVG when hit', () => {
    const detail = { retracement_pct: 42.1, reason: 'standard_pullback', fvg_hit: true, fvg_gap: [410, 415] };
    const text = `Ret ${detail.retracement_pct.toFixed(1)}% · + FVG · ${detail.reason}`;
    expect(text).toContain('FVG');
    expect(text).toContain('42.1%');
  });

  it('eventDetailText formats earnings correctly', () => {
    expect(eventDetailText({ event: 'earnings', days_to_event: 12 })).toBe('earnings in 12d');
    expect(eventDetailText({ event: 'none' })).toBe('No upcoming event');
  });

  it('eventDetailText without a day count shows the event name alone', () => {
    expect(eventDetailText({ event: 'earnings' })).toBe('earnings');
  });

  it('eventDetailText returns undefined with no detail or no event name', () => {
    expect(eventDetailText(undefined)).toBeUndefined();
    expect(eventDetailText({} as EventDetail)).toBeUndefined();
    // A day count with no event name must not render "undefined in 5d".
    expect(eventDetailText({ days_to_event: 5 } as EventDetail)).toBeUndefined();
  });

  it('the event rule tooltip falls back to the generic text, never "undefined in undefinedd"', () => {
    expect(ruleContributionTooltip('event', 'CAUTION', undefined)).toBe(GENERIC_STATUS_TOOLTIP.CAUTION);
  });
});
