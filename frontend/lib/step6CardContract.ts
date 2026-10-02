/*
 * Step 6 always lists the trade card's own contract (STEP3-PARAM-REACH,
 * STEP6-SCAN-CONTRACT-RULES deferred item 3).
 *
 * GET /api/contracts applies `max_price` (Settings' max contract price) and
 * `limit` (max contracts per chain); the scan applies neither. So the contract
 * the scan put on the card -- the one Step 7 shows and sends unless the user
 * picks another -- could be missing from Step 6's table: too expensive for the
 * price cap, or ranked past the limit. Those rows are fetched again by their
 * own expiry and strike, a request the backend exempts from both cuts, and
 * appended.
 */
import type { OptionContract, TradeCardData } from '@/types/domain';

export interface CardContractRequest {
  /** Index into the candidates array the table rows were fetched for. */
  index: number;
  id: string;
  expiry: string;
  /** Truncated as the backend truncates OptionContract.strike. */
  strike: number;
}

/** The candidates whose card contract is absent from their fetched rows.
 *  Only a contract of the table's own right is asked for: a bear-call
 *  spread's call on a puts table would be a row of the wrong right. */
export function missingCardContracts(
  candidates: readonly TradeCardData[],
  rows: readonly (readonly OptionContract[] | undefined)[],
  right: 'C' | 'P',
): CardContractRequest[] {
  const out: CardContractRequest[] = [];
  candidates.forEach((c, index) => {
    const cd = c.contractDetails;
    if (!cd || cd.right !== right || !c.contract) return;
    // A real date only: the scan writes 'TBD' when it had none, and asking
    // for that expiry is a chain fetch that can only fail.
    if (typeof cd.expiry !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(cd.expiry)) return;
    if (!Number.isFinite(cd.strike) || cd.strike < 0) return;
    if ((rows[index] ?? []).some((r) => r.id === c.contract)) return;
    out.push({ index, id: c.contract, expiry: cd.expiry, strike: Math.trunc(cd.strike) });
  });
  return out;
}

/** Append the card's own row to `rows` (a new array; `rows` untouched). Only a
 *  returned row whose id IS the card's contract is taken. NOTE: ids carry
 *  int(strike) (backend market.py), so a 182 and a 182.5 strike share one id
 *  and cannot be told apart here or anywhere else that matches on id -- a
 *  pre-existing limit of the contract id, logged, not fixed by this change. */
export function withCardContract(
  rows: readonly OptionContract[],
  fetched: readonly OptionContract[],
  id: string,
): OptionContract[] {
  if (rows.some((r) => r.id === id)) return [...rows];
  const own = fetched.find((r) => r.id === id);
  return own ? [...rows, own] : [...rows];
}
