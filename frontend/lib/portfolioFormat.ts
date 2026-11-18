/*
 * PORTFOLIO-NUMBERS (#657): one money / percent / contract format for the
 * Portfolio page and its right rail. Pure, no React.
 *
 * Money: Unicode minus (U+2212), `$` after the sign, optional `+` for
 * positives, and `$0` for anything that rounds to zero (never `−$0` / `+$0`).
 * Grouping is fixed to en-US so the output does not depend on the browser or
 * Jest locale. Rounding is `Math.round` (half toward +infinity), the same as
 * the page's previous whole-dollar figures.
 */

import { parseContractId } from './contractGrading';

export const MINUS = '−';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function roundTo(value: number, decimals: number): number {
  const f = 10 ** decimals;
  return Math.round(value * f) / f;
}

/** `−$2,595`, `+$89` (with `plus`), `$0`, `−$1.10` (decimals 2); `—` when not finite. */
export function formatMoney(value: number, opts?: { decimals?: 0 | 2; plus?: boolean }): string {
  if (!Number.isFinite(value)) return '—';
  const d = opts?.decimals ?? 0;
  const r = roundTo(value, d);
  const body = Math.abs(r).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  if (r < 0) return MINUS + '$' + body;
  if (r > 0 && opts?.plus) return '+$' + body;
  return '$' + body;
}

/** `+4.5%`, `−7.0%`, `0.0%` when it rounds to zero; `—` when not finite. */
export function formatSignedPct(value: number, decimals = 1): string {
  if (!Number.isFinite(value)) return '—';
  const s = Math.abs(value).toFixed(decimals);
  const n = Number(value.toFixed(decimals));
  if (n > 0) return '+' + s + '%';
  if (n < 0) return MINUS + s + '%';
  return (0).toFixed(decimals) + '%';
}

/** The tone of a money figure, from the value as `formatMoney` rounds it, so
 *  a figure printed `$0` is never coloured. Components call this rather than
 *  re-deriving the rule. */
export function moneyTone(value: number, decimals: 0 | 2 = 0): 'pass' | 'reject' | undefined {
  if (!Number.isFinite(value)) return undefined;
  const r = roundTo(value, decimals);
  if (r < 0) return 'reject';
  if (r > 0) return 'pass';
  return undefined;
}

/** `CMG|40|2027-06-17|C` → `40C · 17 Jun 27`; `XYZ|STOCK` → `Stock`; any key
 *  `parseContractId` rejects (or with an impossible month) → the key unchanged. */
export function readableContract(key: string): string {
  if (key.endsWith('|STOCK')) return 'Stock';
  const parsed = parseContractId(key);
  if (!parsed) return key;
  const [yyyy, mm, dd] = parsed.expiry.split('-') as [string, string, string];
  const month = MONTHS[Number(mm) - 1];
  if (!month) return key;
  return `${String(parsed.strike)}${parsed.right} · ${String(Number(dd))} ${month} ${yyyy.slice(2)}`;
}
