/*
 * Domain types — shared across pages and components.
 */

import type { Status } from '@/lib/status';

export type Direction = 'Bullish' | 'Bearish';
export type Horizon = 'Intraday' | 'Swing' | 'Position' | 'Custom';
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
  scoreDelta?:  number;        // score pts vs previous scan
  status:       Status;
  breakdown:    ScoreBreakdown;
  nextEventDays?: number;      // days until earnings / fed / etc
  nextEventLabel?: string;     // "Earnings", "FOMC"
}

export interface TargetLevel {
  id?: string;                   // optional — backend doesn't always send it
  stockPrice: number;            // underlying price at this target
  targetPrice?: number;          // new backend field name; optional for backward compat
  estimatedOptionPrice?: number; // model-based or approximation
  pricingMethod?: 'Heston repriced' | 'Delta approximation' | 'Unavailable' | 'heston' | 'delta-approx' | 'manual';
  contractsToSell?: number;      // how many contracts to close here
  status?: string;               // 'PENDING' | 'HIT' | 'MISSED' or undefined
  rrContribution?: number;       // estimated reward / risk contribution
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
  targets:       TargetLevel[];
  status:        Status;
  // Options-specific fields surfaced in the portfolio table.
  ivRank?:       number;       // 0–100, current IV vs 52-week range
  delta?:        number;       // option delta (–1..+1)
  theta?:        number;       // $/day time decay (negative for longs)
  vega?:         number;       // $/vol point
  contracts?:    number;       // number of option contracts held
  /** How the order was placed. Missing = legacy/seed data, treated as broker. */
  source?:       'broker' | 'manual';
  /** ISO timestamp of when the order was created (from Step 7). */
  orderedAt?:    string;
  /** Unique recommendation / position ID. */
  recId:         string;
}

export interface AlertItem {
  id:        string;
  kind:      AlertKind;
  symbol:    string;
  reason:    string;
  timestamp: string;           // "09:42" or ISO
  recId:     string;
  alertType: AlertType;
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
  /** Resolved contract fields for the TradeCard contract-detail block. */
  contractDetails?: {
    strike: number;
    expiry: string;              // YYYY-MM-DD
    right:  'C' | 'P';
    mid:    number;              // premium, $
    delta:  number;
    theta:  number;              // $/day
    ivRank: number;              // 0–100
    ivPercentile?: number;       // 0–100
    dte:    number;
  };
  entry:  { limit: number; maxFill: number; orderType: OrderType };
  exit:   { invalidation: number; premiumStop: number; timeStopDays: number; target: number; targets: TargetLevel[] };
  nextEventDays?:  number;
  nextEventLabel?: string;
  rrRatio:  number;
  rrModel:  'Heston repriced' | 'Delta approximation';
  finalStatus: Status;
}

// --- Option contracts ---

export type OptionRight = 'C' | 'P';

export interface OptionContract {
  id:           string;
  symbol:       string;
  strike:       number;
  expiry:       string;
  right:        OptionRight;
  dte:          number;
  dteTotal:     number;
  price:        number;
  delta:        number;
  theta:        number;
  ivRank:       number;
  ivPercentile: number;
  spread:       number;
  volume:       number;
  score:        number;
}

export function contractId(symbol: string, strike: number, expiry: string, right: OptionRight): string {
  return `${symbol.toUpperCase()}|${strike}|${expiry}|${right}`;
}

/** Short UI label, e.g. "AAPL 190C 05/15". */
export function contractLabel(c: Pick<OptionContract, 'symbol' | 'strike' | 'right' | 'expiry'>): string {
  const [, mm, dd] = c.expiry.split('-');
  return `${c.symbol} ${c.strike}${c.right} ${mm}/${dd}`;
}

// --- Market regime ---

export interface RegimeMetric {
  label:  string;
  value:  string;
  status: Status;
  trend?: 'up' | 'flat' | 'down';
}

export interface MarketRegime {
  overall:  Status;
  headline: string;
  metrics:  RegimeMetric[];
}

// --- Sector heatmap ---

export interface SectorTile {
  key:       string;
  name:      string;
  changePct: number;
  status:    Status;
}

// --- News ---

export type NewsSentiment = 'bull' | 'bear' | 'neutral';

export interface NewsItem {
  id:        string;
  symbol:    string;
  headline:  string;
  source:    string;
  timestamp: string;
  sentiment: NewsSentiment;
}

// --- Alerting & monitoring ---

export interface AlertConfig {
  dedupWindowMinutes: number;      // default 15
  enabledTypes: AlertType[];
  soundEnabled: boolean;
}

export type AlertType =
  | 'TP_HIT'
  | 'STOP_REACHED'
  | 'PREMIUM_STOP'
  | 'TIME_STOP_APPROACHING'
  | 'EARNINGS_APPROACHING'
  | 'EXPIRATION_APPROACHING'
  | 'TIME_STOP'
  | 'EVENT_RISK'
  | 'REGIME_CHANGE'
  | 'SCAN_COMPLETE';

export interface AlertRule {
  type: AlertType;
  label: string;
  threshold?: number;  // e.g. DTE threshold for time-stop
}

export interface ToastItem {
  id: string;
  kind: AlertKind;
  symbol: string;
  reason: string;
  dismissed: boolean;
  recId: string;
  alertType: AlertType;
}

// --- Risk management ---

export interface RiskLimits {
  maxSingleTradeExposurePct: number;  // e.g. 0.05 = 5%
  maxTotalExposurePct: number;        // e.g. 0.25 = 25%
  maxConcurrentPositions: number;     // e.g. 10
  maxDailyRecommendations: number;    // e.g. 5
  portfolioValue: number;             // user's total portfolio value in $
}

export interface RiskCheckResult {
  approved: boolean;
  reasons: string[];
  adjustedContracts?: number;
  singleExposurePct: number;
  totalExposurePct: number;
  capitalAtRisk: number;
}

export interface PortfolioRiskMetrics {
  totalExposurePct: number;
  concurrentPositions: number;
  dailyRecommendations: number;
  largestConcentrationPct: number;
  largestConcentrationSymbol: string;
  status: Status;  // PASS if all within limits, CAUTION if near, REJECT if breached
}
