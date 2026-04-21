/*
 * Domain types — shared across pages and components.
 *
 * v1 is mocks-only (see /mocks/). These types are the contract the future
 * FastAPI backend needs to satisfy.
 */

import type { Status } from '@/lib/status';

export type Direction = 'Bullish' | 'Bearish';
export type Horizon = 'Swing' | 'Position';
export type AlertKind = 'Info' | 'Action' | 'Critical';
export type OrderType = 'Limit' | 'Market' | 'Stop';

export interface ScoreBreakdown {
  trend:       number;
  pullback:    number;
  trigger:     number;
  event:       number;
  volatility:  number;
}

export interface ContractScoreBreakdown {
  dteFit:           number;
  delta:            number;
  ivAttractiveness: number;
  liquidity:        number;
  spread:           number;
}

export interface WatchlistRow {
  symbol:       string;        // e.g. "AAPL"
  company:      string;        // e.g. "Apple Inc"
  price:        number;        // e.g. 185.20
  direction:    Direction;
  horizon:      Horizon;
  score:        number;        // 0–100
  rankDelta:    number;        // +2 / -1 / 0
  status:       Status;
  breakdown:    ScoreBreakdown;
  nextEventDays?: number;      // days until earnings / fed / etc
  nextEventLabel?: string;     // "Earnings", "FOMC"
}

export interface PortfolioPosition {
  symbol:        string;
  contract:      string;       // "AAPL 220C 05/16"
  direction:     Direction;
  entryDate:     string;       // ISO date
  expiry:        string;       // ISO date
  dteRemaining:  number;
  dteTotal:      number;
  entryPrice:    number;
  currentPrice: number;
  pnlDollar:     number;
  pnlPct:        number;
  stop:          number;
  target:        number;
  status:        Status;
  // Options-specific fields surfaced in the portfolio table.
  ivRank?:       number;       // 0–100, current IV vs 52-week range
  delta?:        number;       // option delta (–1..+1)
  theta?:        number;       // $/day time decay (negative for longs)
  vega?:         number;       // $/vol point
  contracts?:    number;       // number of option contracts held
}

export interface AlertItem {
  id:        string;
  kind:      AlertKind;
  symbol:    string;
  reason:    string;
  timestamp: string;           // "09:42" or ISO
}

export interface UpcomingEvent {
  date:    string;             // ISO date
  symbol:  string;
  label:   string;             // "Earnings" / "FOMC" / ...
  status:  Status;
}

export interface TradeCardData {
  symbol:        string;
  company:       string;
  price:         number;
  direction:     Direction;
  status:        Status;
  stockScore:    number;
  stockConfidence: Status;
  stockBreakdown:  ScoreBreakdown;
  contract:      string;
  contractScore: number;
  contractConfidence: Status;
  contractBreakdown: ContractScoreBreakdown;
  entry:  { limit: number; maxFill: number; orderType: OrderType };
  exit:   { invalidation: number; premiumStop: number; timeStopDays: number; target: number };
  rrRatio:  number;
  rrModel:  'Heston repriced' | 'Delta approximation';
  finalStatus: Status;
}
