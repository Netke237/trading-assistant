export const BEARISH_UNVALIDATED_MESSAGE =
  'Bearish setups are Unvalidated: no bearish strategy has passed validation yet '
  + '(decision STOCKS-PARAMS-PER-HORIZON-2026-10-05). Visible for research; '
  + 'no PASS, no auto-trade, no opening order.';

export function isBearishUnvalidated(direction: string | null | undefined): boolean {
  return direction === 'Bearish';
}
