export type QuoteLiveness = { quoteLive?: boolean | null; quoteState?: string | null };
/** Only a quote returned for this visit's exact contract proves liveness. */
export function quoteWarning(q: QuoteLiveness | null | undefined): string | null {
  if (q?.quoteLive === true) return null;
  const state = q?.quoteState;
  const detail = state === 'session_closed' ? 'market closed' : state === 'one_sided' ? 'no bid' : state === 'stale' ? 'stale quote' : state;
  return q ? `No live quote${detail ? ` (${detail})` : ''} — the entry premium is not a live price. Entry quality may reflect the last quote.` : 'Live quote unavailable — the entry premium is the scan-time mid. Entry quality may reflect the scan-time quote.';
}
