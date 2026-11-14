import type { IChartApi, ISeriesApi, MouseEventParams, IRange, SeriesType, Time, UTCTimestamp } from 'lightweight-charts';

export interface LinkedPane {
 chart: IChartApi;
 element: HTMLElement;
 /** Whether the pane holds data; an empty pane is never given a range. */
 hasData: () => boolean;
 /** The exact recorded value at a timestamp, or null. Never the nearest session. */
 sampleAt: (time: number) => {value: number; series: ISeriesApi<SeriesType>} | null;
}

/**
 * Links panes by actual UTC timestamp, never by logical bar index. Only the pane the pointer is
 * in broadcasts its visible range and crosshair, so programmatic updates to the other panes can
 * never echo back (no feedback loops). Returns the cleanup that removes every subscription.
 */
export function linkPanes(panes: LinkedPane[], onHover: (time: number | null) => void): () => void {
 let active: LinkedPane | null = null;
 let release: (() => void) | null = null;
 const others = (source: LinkedPane) => panes.filter(pane => pane !== source);
 const deactivate = (pane: LinkedPane) => {
  if (active !== pane) return;
  active = null;
  for (const other of others(pane)) other.chart.clearCrosshairPosition();
  onHover(null);
 };
 const cleanups = panes.map(pane => {
  const enter = () => { active = pane; };
  const leave = (event: PointerEvent) => {
   if (release) { window.removeEventListener('pointerup', release); release = null; }
   // A drag that leaves the pane keeps broadcasting until the button is released.
   if (event.buttons) {
    const done = () => { window.removeEventListener('pointerup', done); release = null; deactivate(pane); };
    release = done; window.addEventListener('pointerup', done);
   } else deactivate(pane);
  };
  const onRange = (range: IRange<Time> | null) => {
   if (active !== pane || !range) return;
   for (const other of others(pane)) if (other.hasData()) other.chart.timeScale().setVisibleRange(range);
  };
  const onCross = (param: MouseEventParams<Time>) => {
   if (active !== pane) return;
   const time = typeof param.time === 'number' && Number.isFinite(param.time) ? param.time : null;
   onHover(time);
   for (const other of others(pane)) {
    const sample = time === null ? null : other.sampleAt(time);
    if (sample) other.chart.setCrosshairPosition(sample.value, time as UTCTimestamp, sample.series);
    else other.chart.clearCrosshairPosition();
   }
  };
  pane.element.addEventListener('pointerenter', enter);
  pane.element.addEventListener('pointerdown', enter);
  pane.element.addEventListener('pointerleave', leave);
  pane.chart.timeScale().subscribeVisibleTimeRangeChange(onRange);
  pane.chart.subscribeCrosshairMove(onCross);
  return () => {
   pane.element.removeEventListener('pointerenter', enter);
   pane.element.removeEventListener('pointerdown', enter);
   pane.element.removeEventListener('pointerleave', leave);
   pane.chart.timeScale().unsubscribeVisibleTimeRangeChange(onRange);
   pane.chart.unsubscribeCrosshairMove(onCross);
  };
 });
 return () => {
  if (release) window.removeEventListener('pointerup', release);
  release = null; active = null;
  for (const cleanup of cleanups) cleanup();
 };
}
