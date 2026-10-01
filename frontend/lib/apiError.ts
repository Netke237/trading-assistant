/*
 * Reading the errors `api.ts` throws. `apiError` there throws
 * `API ${path} → ${status}: ${detail}` with no status field, so callers that
 * branch on the status parse the message. Moved out of `directOrder.ts`
 * (WATCHLIST-SCAN-CONTRACT-RULES) so ContractStar can read a 422 too.
 */

/** `api.ts`'s `apiError` throws `API ${path} → ${status}: ${detail}`. */
export function parseApiError(e: unknown): { status: number | null; detail: string | null; text: string } {
  const text = String(e);
  const msg = e instanceof Error ? e.message : text;
  const m = /→ (\d{3})(?:: ([\s\S]*))?$/.exec(msg);
  if (!m) return { status: null, detail: null, text };
  return { status: Number(m[1]), detail: m[2] ?? null, text };
}

/** The HTTP status of a thrown `api.ts` error, or null (network failure, other). */
export function statusOf(e: unknown): number | null {
  return parseApiError(e).status;
}
