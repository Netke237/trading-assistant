/*
 * Mock TradeCard data — Phase 4 placeholder rendering.
 * Will be replaced by Step-6 output data in Phase 5.
 */

import type { TradeCardData } from '@/types/domain';

export const MOCK_TRADE_CARD: TradeCardData = {
  symbol:  'AAPL',
  company: 'Apple Inc',
  price:   185.20,
  direction: 'Bullish',
  status:  'PASS',

  stockScore:      82,
  stockConfidence: 'PASS',
  stockBreakdown: {
    trend:      88,
    pullback:   78,
    trigger:    85,
    event:      72,
    volatility: 74,
  },

  contract:           'AAPL 220C 05/16',
  contractScore:      76,
  contractConfidence: 'PASS',
  contractBreakdown: {
    dteFit:           80,
    delta:            72,
    ivAttractiveness: 68,
    liquidity:        84,
    spread:           78,
  },

  entry: {
    limit:     4.25,
    maxFill:   4.40,
    orderType: 'Limit',
  },
  exit: {
    invalidation: 180.00,
    premiumStop:  2.95,
    timeStopDays: 10,
    target:       196.00,
  },
  rrRatio: 2.1,
  rrModel: 'Heston repriced',

  finalStatus: 'PASS',
};
