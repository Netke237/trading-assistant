/** Age is trailing input bars. The average is transition strides, not days. */

export function formatRegimeAge(ageBars: number): string {
  return `${ageBars} bars`;
}

export function formatRegimeAverage(avgStrides: number, strideBars?: number | null): string {
  if (!Number.isFinite(avgStrides)) return '';
  const shown = avgStrides.toFixed(1).replace(/\.0$/, '');
  const sized = typeof strideBars === 'number' && Number.isInteger(strideBars) && strideBars >= 1;
  return sized ? `≈${shown} strides of ${strideBars} bars` : `≈${shown} strides`;
}
