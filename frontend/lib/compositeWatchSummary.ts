/** Human-readable one-liner for a composite trigger_def. Never throws. */
export function compositeWatchSummary(def: Record<string, unknown> | null | undefined): string {
  if (!def || typeof def !== 'object') return '—';
  const primary = (def.primary ?? {}) as Record<string, unknown>;
  const model = typeof primary.model === 'string' ? primary.model : 'any';
  const modelText = model === 'any' ? 'any model' : model;
  const state = typeof primary.to_state === 'string' && primary.to_state ? primary.to_state : null;
  const stateText = state ?? 'any state';

  const parts = [`${modelText} → ${stateText}`];

  const confirmations = Array.isArray(def.confirmations) ? def.confirmations.length : 0;
  if (confirmations > 0) parts.push(`${confirmations} confirmation${confirmations === 1 ? '' : 's'}`);

  const strategies = Array.isArray(def.strategy_confirmations) ? def.strategy_confirmations.length : 0;
  if (strategies > 0) parts.push(`${strategies} strateg${strategies === 1 ? 'y' : 'ies'}`);

  return parts.join(' · ');
}
