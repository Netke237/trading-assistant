import type { ChartType } from '@/lib/chartStore';

// The id prefix that marks a chart series as THE main price series (as
// opposed to a main-pane indicator overlay — EMA, SMA, BB, MASUITE, AVWAP,
// KEYLEVELS, HTFLEVELS... — which can share the same series render `type`,
// e.g. Line when chartType is 'line'). ChartWorkspace's buildMainSeries is
// the only place that constructs this id (via mainSeriesId(chartType)
// below); ChartPane's series-creation loop and ChartRightPanel (which
// filters the main series out of the crosshair indicator-values list) are
// its only readers. All three go through mainSeriesId()/isMainSeriesId
// instead of a bare `'candles-'` string literal, so they can't drift apart.
//
// Why this matters: whichever pane-0 series shares a render type with the
// main series and is created LAST would otherwise silently become
// ChartWorkspace's `mainSeries`. VolumeProfilePrimitive (and other things
// that attach to mainSeries) then call priceToCoordinate() on it — if
// mainSeries ends up pointing at an indicator that's later removed,
// priceToCoordinate returns null for a detached series and the primitive
// silently draws nothing.
const MAIN_SERIES_ID_PREFIX = 'candles-';

export function mainSeriesId(chartType: ChartType): string {
  return `${MAIN_SERIES_ID_PREFIX}${chartType}`;
}

export function isMainSeriesId(id: string): boolean {
  return id.startsWith(MAIN_SERIES_ID_PREFIX);
}
