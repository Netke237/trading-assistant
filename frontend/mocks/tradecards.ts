/*
 * Per-candidate TradeCardData synthesis for Step 7.
 *
 * Step 4 ranks MOCK_WATCHLIST. Step 6 scores contracts for the picked stock.
 * Until the backend wires real output through Steps 1–6, this helper
 * fabricates a plausible TradeCardData for every ranked symbol so the Step 7
 * Prev/Next navigation and basket have something to cycle through.
 *
 * AAPL pulls its top-scoring option from MOCK_CONTRACTS. Everything else gets
 * a deterministic ATM call/put ~24 DTE derived from the watchlist row.
 */

import type { TradeCardData } from '@/types/domain';
import { MOCK_WATCHLIST } from './watchlist';
import {
  MOCK_CONTRACTS,
  contractLabel,
  type OptionContract,
  type OptionRight,
} from './contracts';

function pickContract(symbol: string, price: number, bullish: boolean): OptionContract {
  const matches = MOCK_CONTRACTS.filter((c) => c.symbol === symbol);
  if (matches.length > 0) {
    return [...matches].sort((a, b) => b.score - a.score)[0]!;
  }
  const right: OptionRight = bullish ? 'C' : 'P';
  // Deterministic strike just off ATM.
  const strike = Math.round(price * (bullish ? 1.02 : 0.98));
  return {
    id: `${symbol}|${strike}|2026-05-15|${right}`,
    symbol,
    strike,
    expiry:       '2026-05-15',
    right,
    dte:          24,
    dteTotal:     38,
    price:        Math.max(0.40, +(price * 0.022).toFixed(2)),
    delta:        bullish ? 0.44 : -0.44,
    theta:        -0.09,
    ivRank:       45,
    ivPercentile: 55,
    spread:       0.08,
    volume:       4200,
    score:        70,
  };
}

function tradeCardFor(row: typeof MOCK_WATCHLIST[number]): TradeCardData {
  const bullish  = row.direction === 'Bullish';
  const contract = pickContract(row.symbol, row.price, bullish);

  // Entry / exit anchored on the stock price + contract mid.
  const invalidation = +(row.price * (bullish ? 0.97 : 1.03)).toFixed(2);
  const target       = +(row.price * (bullish ? 1.08 : 0.92)).toFixed(2);

  return {
    symbol:    row.symbol,
    company:   row.company,
    price:     row.price,
    direction: row.direction,
    status:    row.status,

    stockScore:      row.score,
    stockConfidence: row.status,
    stockBreakdown:  row.breakdown,

    contract:           contractLabel(contract),
    contractScore:      contract.score,
    contractConfidence: row.status,
    contractBreakdown: {
      dteFit:           Math.min(100, 100 - Math.abs(30 - contract.dte) * 2),
      delta:            Math.round(Math.abs(contract.delta) * 150),
      ivAttractiveness: contract.ivRank,
      liquidity:        Math.min(100, 40 + Math.round(contract.volume / 200)),
      spread:           Math.max(0, 100 - Math.round(contract.spread * 400)),
    },
    contractDetails: {
      strike: contract.strike,
      expiry: contract.expiry,
      right:  contract.right,
      mid:    contract.price,
      delta:  contract.delta,
      theta:  contract.theta,
      ivRank: contract.ivRank,
      dte:    contract.dte,
    },

    entry: {
      limit:     contract.price,
      maxFill:   +(contract.price * 1.05).toFixed(2),
      orderType: 'Limit',
    },
    exit: {
      invalidation,
      premiumStop:  +(contract.price * 0.6).toFixed(2),
      timeStopDays: Math.max(3, Math.round(contract.dte * 0.4)),
      target,
    },
    rrRatio:  +((Math.abs(target - row.price)) / (Math.abs(row.price - invalidation) || 1)).toFixed(1),
    rrModel:  'Heston repriced',

    finalStatus: row.status,
  };
}

export const MOCK_CANDIDATE_CARDS: TradeCardData[] =
  MOCK_WATCHLIST.map(tradeCardFor);

export const MOCK_CANDIDATE_INDEX: Record<string, TradeCardData> =
  Object.fromEntries(MOCK_CANDIDATE_CARDS.map((c) => [c.symbol, c]));
