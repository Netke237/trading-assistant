/*
 * Option contract mocks. Swapped for a live chain feed once the backend exists.
 * Keyed by canonical id `SYMBOL|STRIKE|YYYY-MM-DD|C|P` so the Watchlist tab
 * can resolve a starred id back to its contract row.
 */

export type OptionRight = 'C' | 'P';

export interface OptionContract {
  id:           string;
  symbol:       string;
  strike:       number;
  expiry:       string;       // YYYY-MM-DD
  right:        OptionRight;
  dte:          number;
  dteTotal:     number;       // days from open → expiry
  price:        number;       // mid premium, $
  delta:        number;
  theta:        number;       // $/day (negative for long)
  ivRank:       number;       // 0–100
  ivPercentile: number;       // 0–100
  spread:       number;       // bid/ask width, $
  volume:       number;       // contracts traded today
  score:        number;
}

export function contractId(
  symbol: string,
  strike: number,
  expiry: string,
  right: OptionRight
): string {
  return `${symbol.toUpperCase()}|${strike}|${expiry}|${right}`;
}

/** Short UI label, e.g. "AAPL 190C 05/15". */
export function contractLabel(c: Pick<OptionContract, 'symbol' | 'strike' | 'right' | 'expiry'>): string {
  const [, mm, dd] = c.expiry.split('-');
  return `${c.symbol} ${c.strike}${c.right} ${mm}/${dd}`;
}

function mk(
  symbol: string,
  strike: number,
  expiry: string,
  right: OptionRight,
  extra: Omit<OptionContract, 'id' | 'symbol' | 'strike' | 'expiry' | 'right'>
): OptionContract {
  return {
    id: contractId(symbol, strike, expiry, right),
    symbol,
    strike,
    expiry,
    right,
    ...extra,
  };
}

// DTE values computed against today ≈ 2026-04-21. Expiries are Friday monthlies.
export const MOCK_CONTRACTS: OptionContract[] = [
  mk('AAPL', 190, '2026-05-15', 'C', {
    dte: 24, dteTotal: 38, price: 4.85, delta: 0.45, theta: -0.11,
    ivRank: 42, ivPercentile: 51, spread: 0.05, volume: 8420, score: 82,
  }),
  mk('AAPL', 195, '2026-05-15', 'C', {
    dte: 24, dteTotal: 38, price: 3.10, delta: 0.38, theta: -0.10,
    ivRank: 45, ivPercentile: 54, spread: 0.06, volume: 6180, score: 78,
  }),
  mk('AAPL', 190, '2026-06-19', 'C', {
    dte: 59, dteTotal: 71, price: 7.90, delta: 0.48, theta: -0.07,
    ivRank: 38, ivPercentile: 46, spread: 0.08, volume: 3250, score: 73,
  }),
  mk('AAPL', 200, '2026-05-15', 'C', {
    dte: 24, dteTotal: 38, price: 1.85, delta: 0.32, theta: -0.09,
    ivRank: 48, ivPercentile: 58, spread: 0.07, volume: 4710, score: 67,
  }),
  mk('AAPL', 185, '2026-04-24', 'C', {
    dte:  3, dteTotal: 17, price: 1.20, delta: 0.58, theta: -0.25,
    ivRank: 61, ivPercentile: 68, spread: 0.04, volume: 11850, score: 54,
  }),
  mk('AAPL', 210, '2026-05-15', 'C', {
    dte: 24, dteTotal: 38, price: 0.72, delta: 0.22, theta: -0.08,
    ivRank: 52, ivPercentile: 62, spread: 0.12, volume: 1940, score: 42,
  }),
];

export const MOCK_CONTRACT_INDEX: Record<string, OptionContract> =
  Object.fromEntries(MOCK_CONTRACTS.map((c) => [c.id, c]));
