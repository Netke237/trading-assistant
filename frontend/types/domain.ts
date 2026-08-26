/*
 * Domain types — shared across pages and components.
 */

import type { Status } from '@/lib/status';

export type Direction = 'Bullish' | 'Bearish';
export type Horizon = 'Intraday' | 'Swing' | 'Position' | 'Custom';
export type AlertKind = 'Info' | 'Action' | 'Critical';
export type OrderType = 'Limit' | 'Market' | 'Stop';

export type SpreadType = 'single' | 'bear_put' | 'bear_call';

export interface OptionLeg {
  right:  'C' | 'P';
  strike: number;
  expiry: string;
  action: 'BUY' | 'SELL';
  qty:    number;
  bid:    number;
  ask:    number;
}

export interface TriggerDetail {
  candle:         string;
  macd_pass:      boolean;
  rsi_pass:       boolean;
  stoch_pass:     boolean;
  momentum_count: number;
  volume_bonus:   boolean;
}
export interface PullbackDetail {
  retracement_pct: number | null;
  reason:          string;
  fvg_hit:         boolean;
  fvg_gap:         [number, number] | null;
}
export interface TrendDetail {
  method:     string;
  adx_val?:   number;
  price_pts?: number;
  slope_pts?: number;
  stock_roc?: number;
  bench_roc?: number;
}
export interface EventDetail {
  event:          string;
  days_to_event?: number;
}
export interface VolDetail {
  iv_rank?: number;
  reason?:  string;
}

export interface DteDetail {
  dte:           number;
  preferred_min: number;
  preferred_max: number;
}
export interface DeltaDetail {
  delta:         number;
  preferred_min: number;
  preferred_max: number;
}
export interface IvRankDetail {
  iv_rank:       number | null;
  preferred_max: number;
}
export interface LiquidityDetail {
  volume:               number;
  open_interest:        number;
  preferred_volume_min: number;
  preferred_oi_min:     number;
}
export interface SpreadDetail {
  spread_pct:       number;
  preferred_max_pct: number;
}

export interface FundamentalsOut {
  score: number;
  quality_label: 'Strong' | 'Neutral' | 'Weak';
  risk_label: 'Low' | 'Medium' | 'High';
  growth_score: number;
  quality_score: number;
  risk_score: number;
  safety_flags: string[];
  detail: Record<string, unknown>;
}

export interface SentimentData {
  horizon: string;
  timeframe: string;
  state: string;
  p_stay: number;
  stability: string;
  regime_age_days: number;
  avg_regime_duration: number;
  conviction_pct: number;
  conviction_label: string;
  interpretation: string;
  hmm_state?: string | null;
  alignment: 'Aligned' | 'Diverging' | 'Unavailable';
  insufficient_data?: boolean;
}

export interface ScoreBreakdown {
  trend:       number;
  pullback:    number;
  trigger:     number;
  event:       number;
  volatility:  number;
  trendDetail?:    TrendDetail;
  pullbackDetail?: PullbackDetail;
  triggerDetail?:  TriggerDetail;
  eventDetail?:    EventDetail;
  volDetail?:      VolDetail;
  sentiment?: SentimentData | null;
}

export interface ContractScoreBreakdown {
  dteFit:           number;
  delta:            number;
  ivAttractiveness: number;
  liquidity:        number;
  spread:           number;
  dteDetail?:       DteDetail;
  deltaDetail?:     DeltaDetail;
  ivDetail?:        IvRankDetail;
  liquidityDetail?: LiquidityDetail;
  spreadDetail?:    SpreadDetail;
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
  nextEventDays?: number | null;   // days until earnings / dividend / etc; null = no event known
  nextEventLabel?: string | null;
  confidence?: number | null;      // signal confidence 0–100; null = thin history
  confidenceText?: string | null;  // plain-English interpretation
}

export interface StructuralStop {
  price:       number;
  source:      'order_block' | 'swing_low' | 'swing_high';
  confidence:  number;
  distancePct: number;
}

export interface FirstPassageTarget {
  pct:          number;          // profit target as a fraction of premium (0.20 = 20%)
  stockPrice:   number | null;   // display-only Stage-1 approximation; null if unreachable
  optionPrice:  number;          // premium * (1 + pct)
  probability:  number;          // 0-1, hit probability before expiry
  expectedDays: number | null;   // median days to hit; null if probability is 0
}

export interface FirstPassageEstimate {
  targets:      FirstPassageTarget[];
  invalidation: { probability: number; expectedDays: number | null };
}

/** The inputs a `FirstPassageEstimate` was actually computed against — captured
 *  at request time, not re-read afterwards. `premium`/`delta` are the FRESH
 *  quote values (not `contractDetails.mid`/`.delta`, which are scan-time
 *  snapshots), so a later R:R-vs-structural-stop calc subtracts the matching
 *  baseline; `targetPct` is the T1/T2/T3 fraction trio the request carried, so
 *  a restored estimate's rows and its % inputs can never disagree.
 *  `targetPct`'s shape is written structurally rather than importing
 *  `TargetProfitPct` from `lib/settingsStore` — this module must not depend on
 *  a Zustand store. The two shapes are structurally identical, so values flow
 *  both ways without a cast. */
export interface FirstPassageContext {
  premium:   number;
  delta:     number;
  targetPct: { t1: number; t2: number; t3: number };
}

/** One R:R row from the exit-plan pipeline (backend
 *  backend/app/scoring/exit_plan.py) — see docs/superpowers/plans/
 *  2026-08-26-exit-plan-pipeline.md. `price` is the row's effective target
 *  (== `arithmeticPrice` unless `tpSource === 'structural_snap'`, in which
 *  case it's the real structural level snapped onto). */
export interface ExitPlanTargetRow {
  rrRatio:         number;
  arithmeticPrice: number;
  price:           number;
  tpSource:        'arithmetic' | 'structural_snap';
  structuralPrice: number | null;
  contractPrice:   number;
  rrModel:         'Heston repriced' | 'BS repriced (IV-derived)' | 'Delta approximation';
  probability:     number;
  expectedDays:    number | null;
  qualityGood:     boolean;
  qualityReasons:  string[];
}

/** Result of POST /api/contracts/exit-plan — final stop (wider of the
 *  structural stop and an ATR floor) plus one target row per configured R:R
 *  ratio. Persisted verbatim as `PortfolioPosition.exitPlan`/
 *  `TradeCardData.exit.exitPlan` on manual "Compute Exit Plan" clicks only —
 *  never recomputed automatically. */
export interface ExitPlan {
  /** ISO timestamp of when this result was computed (client-set on receipt,
   *  not returned by the backend — the endpoint itself is stateless/fresh on
   *  every call). Lets the UI show "as of" staleness next to a persisted,
   *  never-auto-refreshed plan. */
  computedAt: string;
  stop: {
    price:                number;
    source:               'structural' | 'atr_widened';
    contractPrice:        number;
    rrModel:              'Heston repriced' | 'BS repriced (IV-derived)' | 'Delta approximation';
    structuralSource:     'order_block' | 'swing_low' | 'swing_high' | null;
    structuralConfidence: number | null;
  };
  targets: ExitPlanTargetRow[];
  atr:     number;
}

export interface TargetLevel {
  id?: string;                   // optional — backend doesn't always send it
  stockPrice: number;            // underlying price at this target
  targetPrice?: number;          // new backend field name; optional for backward compat
  estimatedOptionPrice?: number; // model-based or approximation
  // Backend PricingMethod enum values (backend/app/schemas/__init__.py). Legacy
  // lowercase codes ('heston' / 'delta-approx' / 'manual') may still appear in
  // old persisted scan sessions; they're rendered as raw strings, so the narrowed
  // type only affects compile-time checking, not runtime display.
  pricingMethod?: 'Heston repriced' | 'BS repriced (IV-derived)' | 'Delta approximation' | 'Unavailable';
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
  /** Live underlying stock price, refreshed on every portfolio sync — distinct from
   *  `scanStockPrice` (the one-time anchor captured when the position was opened).
   *  For a stock position this always mirrors `currentPrice` (including its 0.0
   *  fallback on a failed quote fetch — unchanged pre-existing behavior for stock
   *  legs). For an option position it's fetched separately since `currentPrice`
   *  there is the option premium; undefined there on stale/pre-fix cached data or
   *  when the live underlying-price fetch specifically failed. */
  currentStockPrice?: number;
  pnlDollar:     number;
  pnlPct:        number;
  stop:          number | null;
  /** Structural (order-block/swing) stop level — set only when "Check structure"
   *  was run on the trade card before sending to broker. Optional/opt-in, unlike
   *  `stop` (the premium-based invalidation). */
  structuralStop?: number | null;
  /** Full exit-plan pipeline result — set only after "Compute Exit Plan" was run
   *  (on the trade card pre-trade, or the Portfolio editor post-trade). Persisted
   *  verbatim, refreshed only on manual re-click, mirrors the backend's
   *  `exit_plan` JSON column 1:1. */
  exitPlan?:     ExitPlan | null;
  targets:       TargetLevel[];
  status:        Status;
  // Options-specific fields surfaced in the portfolio table.
  ivRank?:       number;       // 0–100, current IV vs 52-week range
  delta?:        number;       // option delta (–1..+1)
  theta?:        number;       // $/day time decay (negative for longs)
  vega?:         number;       // $/vol point
  contracts?:    number;       // number of option contracts held
  /** How the order was placed. Missing = legacy/seed data, treated as broker. */
  source?:       'broker' | 'manual' | 'paper' | 'auto-trade';
  /** Human-readable execution label, e.g. "Tradier Paper — Limit". */
  sourceLabel?:  string;
  /** ISO timestamp of when the order was created (from Step 7). */
  orderedAt?:    string;
  /** Unique recommendation / position ID. */
  recId:         string;
  /** Underlying stock price at scan time — used to re-anchor stop/targets to fill price. */
  scanStockPrice?: number;
  /** Full trade-card/score-breakdown snapshot at buy time — sent once on create
   *  so the backend can permanently attach it (audit_events via log_approval)
   *  answering "why was this bought". Stored on the position object itself
   *  (not passed only as a one-off call argument) so addPosition's pending-
   *  retry path — which re-POSTs from this stored object — carries it too. */
  tradeCardSnapshot?: Record<string, unknown>;
  /** Local-only sync state vs the backend. Never sent to the backend.
   *  'pending'  — optimistically added, POST in flight or retrying.
   *  'synced'   — confirmed present on the backend. */
  syncStatus?: 'pending' | 'synced';
  /** Epoch ms when this row entered 'pending' (for an "unsynced since" hint). */
  syncPendingSince?: number;
  /** Epoch ms when the backend last confirmed this row. Used by the reconcile
   *  to avoid dropping a row confirmed after the current GET's snapshot. */
  syncedAt?: number;
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
  /** Alternative contracts (FR-28) — zero to N alternatives to the best contract. */
  alternatives?: AlternativeContract[];
  alternativesCount?: number;
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
  exit:   {
    invalidation: number; premiumStop: number; timeStopDays: number; target: number; targets: TargetLevel[];
    /** Populated only after the user presses "Check structure" — never set by the scan itself. */
    structuralStop?: StructuralStop | null;
    /** Populated only after the user presses "Estimate" — never set by the scan itself. */
    firstPassage?: FirstPassageEstimate | null;
    /** Populated only after the user presses "Compute Exit Plan" — never set by the scan itself. */
    exitPlan?: ExitPlan | null;
    /** The fresh underlying price `structuralStop` above was derived from, at the time
     *  it was fetched. Client-only, like `structuralStop` itself. A value RESTORED here
     *  (spliced in by step-7-trade-card/page.tsx on candidate re-navigation) is inert —
     *  TradeCard's R:R-vs-structural-stop calc requires the structural stop and the
     *  estimate independently reconfirmed fresh in the same mount before it will use
     *  either (see the plan's round 5 audit notes), so a restored value here is only
     *  ever overwritten by a live fetch, never read. Kept for shape symmetry with
     *  `structuralStop` and because a future consumer may legitimately want it.
     *  Never sent by the backend. */
    structuralStopStockPrice?: number | null;
    /** The inputs `firstPassage` above was computed against. Client-only, same
     *  restore-on-re-navigation path as `structuralStopStockPrice`. Never sent by
     *  the backend. */
    firstPassageContext?: FirstPassageContext | null;
  };
  nextEventDays?:  number | null;
  nextEventLabel?: string | null;
  rrRatio:  number;
  rrModel:  'Heston repriced' | 'BS repriced (IV-derived)' | 'Delta approximation';
  finalStatus: Status;
  /** Signal confidence 0–100 (null when history is too thin to judge). */
  confidence?: number | null;
  confidenceText?: string | null;
  sentiment?: SentimentData | null;
  fundamentals?: FundamentalsOut | null;
  spreadType?:     SpreadType;
  legs?:           OptionLeg[];
  netDebitCredit?: number;
  maxProfit?:      number;
  maxLoss?:        number;
  breakeven?:      number;
  /**
   * Set locally (never sent by the backend) when the user has picked a
   * different contract than the scan's top recommendation via the contract
   * picker (Step 6 / ContractStar). Drives the "User-selected" badge on
   * Step 7. See step-7-trade-card/page.tsx effectiveCard.
   */
  _userOverride?: boolean;
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
  contractConfidence: Status;
}

export function contractId(symbol: string, strike: number, expiry: string, right: OptionRight): string {
  return `${symbol.toUpperCase()}|${strike}|${expiry}|${right}`;
}

/** Short UI label, e.g. "AAPL 190C 05/15/27". Includes a 2-digit year so
 *  contracts across different expiry years are never ambiguous. */
export function contractLabel(c: Pick<OptionContract, 'symbol' | 'strike' | 'right' | 'expiry'>): string {
  const parts = (c.expiry ?? '').split('-');
  const yyyy = parts[0] ?? '';
  const mm = parts[1] ?? '--';
  const dd = parts[2] ?? '--';
  const yy = yyyy.length === 4 ? yyyy.slice(2) : '--';
  return `${c.symbol} ${c.strike}${c.right} ${mm}/${dd}/${yy}`;
}

// --- Alternative contracts (FR-28) ---

export interface AlternativeContract {
  symbol:       string;
  strike:       number;
  expiry:       string;
  right:        OptionRight;
  dte:          number;
  mid:          number;
  delta:        number;
  theta:        number;
  ivRank:       number;
  score:        number;
  contractConfidence: Status;
  contractBreakdown:  ContractScoreBreakdown;
  rrRatio:      number;
  rrModel:      'Heston repriced' | 'BS repriced (IV-derived)' | 'Delta approximation';
  reason:       string;
  spreadType?:     SpreadType;
  legs?:           OptionLeg[];
  netDebitCredit?: number;
  maxProfit?:      number;
  maxLoss?:        number;
  breakeven?:      number;
}

// --- Market regime ---

export interface RegimeMetric {
  label:  string;
  value:  string;
  status: Status;
  trend?: 'up' | 'flat' | 'down';
}

export type HmmState = 'Bull' | 'Bear' | 'Choppy';

export interface OmmData {
  state:                'Bull' | 'Bear' | 'Choppy';
  p_stay:               number;   // 0–1
  stability:            'Stable' | 'Fragile';
  regime_age_days:      number;
  avg_regime_duration:  number;   // days
  transition_row:       number[]; // [P(Bull), P(Bear), P(Choppy)]
  state_order:          string[]; // ['Bull', 'Bear', 'Choppy']
  conviction_pct?: number | null;
  conviction_label?: string | null;
}

export interface IntraHmmTransition {
  to:   string;
  prob: number;
}

export interface IntraHmmData {
  state:        'Trending' | 'Choppy' | 'Mean-reverting';
  p_stay:       number;
  p_transition: IntraHmmTransition[];
}

export interface MarketRegime {
  overall:              Status;
  headline:             string;
  metrics:              RegimeMetric[];
  omm?:                 OmmData | null;
  intraday_hmm?:        IntraHmmData | null;
  intraday_hmm_status?: 'ok' | 'insufficient_data' | 'unavailable';
  intraday_omm?:        OmmData | null;
  vix_pct_30d?:         number | null;
  vix_pct_252d?:        number | null;
  /** Legacy client-side field — kept for backward compat, not populated by backend. */
  hmm?: { state: HmmState; confidence: number };
  conviction_pct?: number | null;
  conviction_label?: string | null;
  hmm_state?: string | null;
  alignment?: 'Aligned' | 'Diverging' | 'Unavailable' | null;
  regime_direction?: 'BULL' | 'BEAR' | 'MIXED' | null;
}

// --- Sector heatmap ---

export interface SectorTile {
  key:         string;
  name:        string;
  changePct:   number;
  status:      Status;
  symbolCount?: number;
}

export interface IndexChangeTile {
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
  dedupWindowMinutes: number;      // default 15 — min spacing before re-reporting to backend
  reminderIntervalHours: number;   // default 4 — email/Telegram reminder gap while a condition stays true
  checkIntervalSeconds: number;    // default 60 — how often background monitors re-check conditions
  enabledTypes: AlertType[];
  soundEnabled: boolean;
  keepAlertsDays: number;          // default 30 — auto-purge after N days
  retentionDays: number;           // default 30 — backend sent-message log retention (days)
  // default 0 — portfolio position (TP/stop/premium) sustain-minutes filter.
  // No dedicated UI control yet (deferred) — round-tripped here so saving any
  // other Alerts-page setting doesn't silently reset it back to 0 on the backend.
  positionSustainMinutes: number;
  // default 30 — position_alert_history retention window (days). No dedicated
  // UI control yet — round-tripped for the same reason as positionSustainMinutes
  // above: the Alerts page POSTs the whole alert_delivery block, so any field
  // missing here gets silently reset to the backend's Pydantic default on save.
  positionAlertRetentionDays: number;
}

export type AlertType =
  | 'TP_HIT'
  | 'STOP_REACHED'
  | 'STRUCTURAL_STOP_BREACHED'
  | 'PREMIUM_STOP'
  | 'TIME_STOP_APPROACHING'
  | 'EARNINGS_APPROACHING'
  | 'EXPIRATION_APPROACHING'
  | 'TIME_STOP'
  | 'EVENT_RISK'
  | 'REGIME_CHANGE'
  | 'SCAN_COMPLETE'
  | 'SCAN_FAILED';

export interface ToastItem {
  id: string;
  kind: AlertKind;
  symbol: string;
  reason: string;
  dismissed: boolean;
  acknowledged: boolean;   // permanently suppress re-fire; dims row in history
  firedAt: string;         // ISO timestamp when the alert fired
  recId: string;
  alertType: AlertType;
  // Structured fire data, forwarded to POST /api/alerts/notify for
  // position_alert_history — see lib/alertEngine.ts AlertReason.
  price?: number;
  referenceValue?: number;
  direction?: Direction;
  contract?: string;
  note?: string;
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

// --- Holding-horizon DTE window ---

export interface DteWindow {
  min_dte:    number;
  max_dte:    number;
  multiplier: number;
}
