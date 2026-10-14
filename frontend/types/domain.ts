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
  /** Which quantity `iv_rank` holds — the STOCK score's volatility rule carries
   *  the same ambiguous figure the contract rule does. Absent on a response
   *  predating the split, which carried an absolute level, so 'absolute' is the
   *  default. See lib/ivBasis.ts. */
  iv_basis?: 'rank' | 'absolute' | 'none';
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
  /** Which quantity `iv_rank` holds — see lib/ivBasis.ts. Absent on responses
   *  predating the split, which were all carrying an absolute IV. */
  iv_basis?:     'rank' | 'absolute' | 'none';
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
  duration_stride_bars?: number | null;
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
  /** 1-based position in the scan's own ranking (the backend orders options
   *  candidates by finalStatus, then stock score, then contract score).
   *  Optional because only Step 4's cardToRow knows it. */
  rank?:        number;
  scoreDelta?:  number;        // score pts vs previous scan
  status:       Status;
  breakdown:    ScoreBreakdown;
  nextEventDays?: number | null;   // days until earnings / dividend / etc; null = no event known
  nextEventLabel?: string | null;
  confidence?: number | null;      // signal confidence 0–100; null = thin history
  confidenceText?: string | null;  // plain-English interpretation
  /** The scan-time stop-vs-premium gate (Phase B3). Copied verbatim from the
   *  candidate by `cardToRow`; see `TradeCardData.stopCostPct` for why it is
   *  two fields and what null means. Optional because a row rebuilt from a
   *  scan session persisted before B3 has neither. */
  stopCostPct?: number | null;
  stopCostStatus?: 'PASS' | 'CAUTION' | null;
}

/** The stop-vs-premium gate as the endpoints that produce a stop return it —
 *  `/contracts/structural-stop` and `/contracts/exit-plan`. Mirrors
 *  `StopCostOut` in backend/app/routers/contracts.py; rendered by
 *  `stopPremiumRisk` in lib/risk.ts, which computes nothing.
 *
 *  Lives here rather than in lib/risk.ts because it is a WIRE shape, and
 *  `StructuralStop` / `ExitPlan` below embed it. Every figure is per share and
 *  quantized to cents server-side, so `premium − valueAtStop === lossDollar`
 *  holds on the printed values.
 *
 *  ABSENT means "not computed" and must never render as a PASS: no contract
 *  was sent, no structural level was found, the IV would not invert, or the
 *  block predates B2 in a restored `ExitPlan`. */
export interface StopCostOut {
  /** premium − valueAtStop, per share. */
  lossDollar:      number;
  /** BS(stop, K, today's dte, r, iv), per share — printed, so the input shows. */
  valueAtStop:     number;
  /** lossDollar / premium, clamped to [0, 1]. The number `status` was decided on. */
  fraction:        number;
  status:          'PASS' | 'CAUTION';
  /** The threshold applied, echoed for auditability — it moved with the basis. */
  passMaxFraction: number;
  /** Echoed input: the premium the gate priced, per share. */
  premium:         number;
  /** Echoed input: the stop it priced to. */
  stopPrice:       number;
  basis:           'bs_today';
}

export interface StructuralStop {
  price:       number;
  source:      'order_block' | 'swing_low' | 'swing_high';
  confidence:  number;
  distancePct: number;
  /** What this stop costs the contract, when one was sent with the request.
   *  Absent for the stocks-mode card, which calls the same endpoint with no
   *  contract at all. */
  stopCost?:   StopCostOut | null;
}

export interface FirstPassageTarget {
  pct:          number;          // profit target as a fraction of premium (0.20 = 20%)
  stockPrice:   number | null;   // display-only Stage-1 approximation; null if unreachable
  optionPrice:  number;          // premium * (1 + pct)
  probability:  number;          // 0-1, hit probability before expiry
  expectedDays: number | null;   // median days to hit; null if probability is 0
}

/** One target's row of the barrier race. The four `p*` fields are an
 *  ATTRIBUTION, not four independent probabilities: every simulated path is
 *  counted exactly once, so they sum to 1. `FirstPassageTarget.probability` and
 *  `invalidation.probability` are each measured on their own and can sum past
 *  100% — that difference is the whole reason this exists.
 *
 *  Every `days*` is a CONDITIONAL median: the median day of the paths that
 *  resolved to that outcome, not of all paths. */
export interface BarrierRaceOutcome {
  targetPct:            number;
  targetOptionPrice:    number;

  pTargetFirst:         number;
  pStockStopFirst:      number;
  pPremiumStopFirst:    number;
  pNeither:             number;

  daysTarget:           number | null;
  daysStockStop:        number | null;
  daysPremiumStop:      number | null;
  /** The UNCONDITIONAL median day any path reaches the stock stop — the basis
   *  of `repriceDaysStockStop`. Different from `daysStockStop`, which is
   *  conditional on the stop winning the race, so the two legitimately differ;
   *  `null` means no path reached the stop and the horizon came from the preset
   *  table instead. */
  daysAnyPathReachedStop: number | null;

  /** The four shares allocated to hundredths by the backend, summing to
   *  exactly 1.00. Print THESE in the edge chain and derive the whole-percent
   *  labels from them: they are the weights the edge was actually computed
   *  with, so the terms, the labels and the total cannot disagree.
   *
   *  Do not re-round `pTargetFirst` and friends for display. That is what these
   *  replace: the backend weighted the edge with a Python imitation of
   *  `toFixed`, which disagrees with the real one on 44 of the 2001 shares
   *  reachable at 2000 paths, and the printed chain stopped adding up. The raw
   *  p* fields are for the bars, which are continuous. */
  weightTargetFirst:      number;
  weightStockStopFirst:   number;
  weightPremiumStopFirst: number;
  weightNeither:          number;
  /** Mean option value at expiry over the `pNeither` paths — the input to the
   *  edge's fourth term, which is SIGNED: those paths can end above the premium
   *  paid, so it is not always a loss. */
  terminalMean:         number | null;

  // The card prints every term of the risk / R:R / edge chains, so the payload
  // carries the inputs, not just the results.
  rewardDollar:         number;
  repriceDaysStockStop: number;
  stopRepricedValue:    number | null;
  riskStockStop:        number | null;
  riskPremiumStop:      number;
  /** THE measurement. Its risk leg is `premium - BS(stop, ...)`, which is not
   *  proportional to premium, so premium does not cancel and this genuinely
   *  varies by contract. `null` when the risk leg is <= 0 (possible on a
   *  deep-ITM contract with a tight stop) — render an em dash, never a negative
   *  or infinite ratio. */
  rrStockStop:          number | null;
  /** Constant by construction: exactly `targetPct / premiumStopPct`. Its risk
   *  leg IS proportional to premium, so premium cancels. Shown for completeness
   *  and explicitly labelled as not a measurement.
   *
   *  Taken from that definition rather than by dividing the two rounded dollar
   *  legs — dividing them does not reproduce it once the money is quantized to
   *  cents (at a $1.03 premium the legs give 0.34x and at $1.07 they give
   *  0.33x), which would make the "on every contract" claim printed beside it
   *  false by up to 14% on sub-$1 premiums. `null` only when `premiumStopPct`
   *  is non-positive, which the endpoint rejects. */
  rrPremiumStop:        number | null;
  edgePerContract:      number | null;
}

export interface BarrierRace {
  outcomes:         BarrierRaceOutcome[];
  premiumStopPrice: number;   // the option-value barrier actually used
  premiumStopPct:   number;
  stockStopPrice:   number;   // echo of the invalidation price, for auditability
  /** The premium every printed chain subtracts, already quantized to cents by
   *  the backend. Print THIS rather than re-rounding a local copy: Python's
   *  round() is banker's rounding and JavaScript's toFixed() is not, so the two
   *  disagree on an exact half-cent and the chain stops adding up. */
  premiumUsed:      number;
  /** False when the contract's own IV could not be backed out of its quote, so
   *  the simulation ran on a generic fallback volatility. Every number on the
   *  card is then about a contract the market is not pricing that way — the
   *  card caveats them rather than showing a confident dollar edge. */
  ivSolved:         boolean;
  nPaths:           number;
}

export interface FirstPassageEstimate {
  targets:      FirstPassageTarget[];
  invalidation: { probability: number; expectedDays: number | null };
  /** `null`/absent when the simulation was refused (dte < 1). The card renders
   *  "not simulated" in that case, never four zeroes. */
  race?:        BarrierRace | null;
  /** ISO timestamp of when this estimate was computed — client-set on
   *  receipt, the same way `ExitPlan.computedAt` works (the backend endpoint
   *  is stateless/fresh on every call, so this isn't returned by it). Feature
   *  8 (Final Recommendation) compares this against `ExitPlan.computedAt` to
   *  show whichever method — Arithmetic or Monte Carlo — ran most recently. */
  computedAt?: string;
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
  /** |structuralPrice - arithmeticPrice|; null when no structural candidate
   *  was found ahead of entry. */
  distanceDollar:  number | null;
  /** The snap band (snap_atr_multiplier * ATR) — always computable, whether
   *  or not this row actually snapped. */
  toleranceDollar: number;
}

/** The scan's own resolved stock stop, with its provenance. Mirrors
 *  `FinalStopOut` in backend/app/schemas — see `TradeCardData.exit.finalStop`.
 *
 *  Deliberately NOT an `ExitPlan['stop']`, though it reports the same levels:
 *  that block carries `contractPrice` and `rrModel`, which price the contract
 *  AT the stop, and the scan cannot supply them. A stop is a question about the
 *  STOCK; what it costs is a question about a contract, and the auto-pick does
 *  not settle it (a Step 6 override replaces the contract without moving the
 *  stop). The contract-priced sub-cells and the risk-derived size render "—"
 *  until an Arithmetic Plan is computed. */
export interface FinalStop {
  /** The stop itself, in dollars. Always equal to `exit.invalidation` — the
   *  provenance row and the Invalidation field sit inches apart on one card. */
  price: number;
  /** Which branch decided it. Always 'final_stop' on the wire today: the
   *  backend sends no block at all on the flat-percentage fallback, because a
   *  block of nulls would read as "we looked and found nothing" rather than
   *  "we could not look at all". Kept explicit so a future fallback block
   *  cannot arrive undetected. */
  source: 'final_stop' | 'flat_fallback';
  /** 'structural' = a real level that already cleared the ATR floor unassisted;
   *  'atr_widened' = the level was tighter than the floor (or absent) and was
   *  widened out to it. */
  stopSource?: 'structural' | 'atr_widened' | null;
  structuralSource?: 'order_block' | 'swing_low' | 'swing_high' | null;
  /** The structural candidate's raw price, whether or not it decided `price`
   *  (i.e. populated even when stopSource === 'atr_widened'). */
  structuralPrice?: number | null;
  /** The ATR-floor price, whether or not it decided `price`. */
  atrFloorPrice?: number | null;
  /** |structuralPrice - atrFloorPrice|; null when no structural candidate was
   *  found at all. */
  distanceDollar?: number | null;
  /** ATR(14) the floor was built on. */
  atr: number;
  /** ISO-8601, SERVER-set — unlike `ExitPlan.computedAt`, which the client
   *  stamps on receipt. This block rides on a scan result that IS persisted and
   *  replayed, so a restored card has to be able to say how old its stop is. */
  computedAt: string;
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
    /** The structural stop candidate's raw price, whether or not it decided
     *  the final stop (i.e. populated even when source === 'atr_widened'). */
    structuralPrice:      number | null;
    /** The ATR-floor price, whether or not it decided the final stop. */
    atrFloorPrice:        number;
    /** The same gate as `StructuralStop.stopCost`, priced against THIS stop —
     *  the wider of the structural level and the ATR floor. The two endpoints
     *  disagreeing is the model working, not a bug: a wider stop costs more of
     *  the premium (spec §2.2).
     *
     *  OPTIONAL because `ExitPlan` is persisted (`PortfolioPosition.exitPlan`,
     *  `TradeCardData.exit.exitPlan`) and a plan computed before B2 carries no
     *  block. That restores as "not computed", which is the honest reading —
     *  so no store migration is needed to avoid a wrong number. */
    stopCost?:            StopCostOut | null;
    /** |structuralPrice - atrFloorPrice|; null when no structural candidate
     *  was found at all. No toleranceDollar counterpart here — the stop
     *  comparison is a strict "whichever is further from entry wins", not a
     *  tolerance band (that concept only applies on the target side). */
    distanceDollar:       number | null;
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
  /** True when the last GET /api/portfolio had no quote for this position
   *  (NO-LIVE-QUOTE NLQ-1). `currentPrice`/`pnlDollar`/`pnlPct` then hold 0
   *  defaults, not a price: the table shows "—" and the totals leave the row
   *  out. Absent on a row that never synced. */
  quoteUnavailable?: boolean;
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
  /** Per-trade override of the global `maxLossPerTradePct` warning threshold
   *  (Feature C). `null`/absent inherits the global default. */
  maxLossOverride?: MaxLossOverride | null;
  /** Per-position premium stop as a fraction of entry premium (piece 4).
   *  `null`/absent means this position INHERITS the global
   *  (`settingsStore.premiumStopPct` / `reward_risk.premium_stop_pct`) and keeps
   *  tracking it as it changes — a distinct state from being set to the same
   *  number. Always read through `resolvePremiumStopPct` in lib/premiumStop.ts;
   *  never compare it directly. */
  premiumStopPct?: number | null;
  /** The DOLLAR premium stop as typed on the trade card, carried on the create
   *  path only. The backend derives `premiumStopPct` from it against the
   *  entry price it actually persists — which it may replace with a live quote
   *  — so the fraction is never computed client-side against a price the
   *  server is about to change. */
  premiumStopDollar?: number | null;
  /** Which TP computation drives this position's TP_HIT alert (Feature D).
   *  Absent = 'ladder', matching the backend column's server-side default —
   *  every position predating this field keeps today's behavior. */
  activeTpMethod?: TpMethod;
  /** Stock price the active TP method resolved to, snapshotted at selection /
   *  re-compute time rather than recomputed per alert tick. Null for 'ladder',
   *  which reads `targets[0].stockPrice` live instead — see alertEngine.ts.
   *  This is what BOTH alert paths compare the live price against, exactly as
   *  they already do for `structuralStop`. */
  resolvedTpPrice?: number | null;
  /** ISO timestamp of the last `resolvedTpPrice` refresh, for an "as of" hint
   *  next to a snapshot that is deliberately never auto-refreshed. */
  resolvedTpUpdatedAt?: string | null;
  /** Phase G (piece 5, D4/D5) — the RAW pick the trader made, carried on the
   *  create path only and otherwise immutable. Distinct from `activeTpMethod`/
   *  `resolvedTpPrice` above: those are SERVER-DERIVED from this pick via the
   *  spec's §4.3 mapping table (`picked_method.py`), this is the input to that
   *  mapping. NULL is a real state on every one of the five fields — it means
   *  "opened before G, or opened by a path with no human in it" (the S5
   *  after-scan auto-executor is deliberately exempt from the send gate and
   *  creates positions with all five NULL, §7.3) — never "missing/legacy" the
   *  way an absent `activeTpMethod` is. Use `lib/cardEdits.ts`'s
   *  `pickedFieldsFrom` to build these five from a `MethodPick` at a send site
   *  rather than mapping the fields ad hoc. */
  pickedMethod?: PickedMethod | null;
  /** Underlying-space only — the ONLY field of the five that may ever seed
   *  `resolvedTpPrice`. See `MethodPick.rowStockPrice`'s own doc for why a
   *  premium landing here instead fires TP_HIT instantly on the first tick. */
  pickedRowStockPrice?: number | null;
  /** Premium-space — record-only, never seeds `resolvedTpPrice`, never alerts. */
  pickedRowOptionPrice?: number | null;
  pickedStopBasis?: PickedStopBasis | null;
  /** ISO. The vintage of the numbers the pick was made against — see
   *  `MethodPick.pickedAt`'s own doc. */
  pickedAt?: string | null;
  /** STOCKS-HORIZON-T1 H6 -- the scan's hold in calendar days, written by the
   *  stock sends (`ScanContext.holdMax` through `sanitizeHoldDays`). A stock
   *  position raises TIME_STOP once held this many days. `null`/absent = no
   *  hold (options rows, rows opened before H6), never a stock time stop. */
  holdMaxDays?: number | null;
  /** Per-position alert-type overrides — absent key inherits the global
   *  `AlertConfig.enabledTypes` decision (Feature D). */
  alertOverrides?: AlertOverrides;
  targets:       TargetLevel[];
  status:        Status;
  // Options-specific fields surfaced in the portfolio table.
  /** An IV RANK (today's IV vs this name's own 52-week range), or
   *  absent when no rank source answered — which is the common case. The
   *  absolute level lives in `iv`. Resolve the two via lib/ivBasis.ts;
   *  never print one under the other's label. */
  ivRank?:       number | null;
  /** ABSOLUTE implied volatility, 0–100, for this contract. */
  iv?:           number | null;
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
  /** True when `stop` is a level the USER TYPED on the trade card, as an
   *  absolute price against today's quote, rather than one the plan derived.
   *  Sent to the backend, which re-anchors a plan-derived stop by
   *  (live price − `scanStockPrice`) and must leave a typed one alone: the
   *  user chose that number while looking at the live price, so shifting it
   *  stores a stop they never picked. Absent/false keeps the re-anchor, which
   *  is right for every plan-derived stop and for legacy rows. */
  stopIsUserSet?: boolean;
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
  noLiveQuote?: boolean;
  symbol:        string;
  company:       string;
  price:         number;
  direction:     Direction;
  status:        Status;
  unvalidatedReason?: string | null;
  stockScore:    number;
  stockConfidence: Status;
  stockBreakdown:  ScoreBreakdown;
  /** Scan-time evidence. Missing/null means not captured; re-run the scan. */
  stockExplanation?: StockExplanation | null;
  contract:      string;
  contractScore: number;
  contractConfidence: Status;
  contractBreakdown: ContractScoreBreakdown;
  /** Authoritative evaluation explanation for the picked contract, if available */
  contractExplanation?: ContractExplanation | null;
  /** Alternative contracts (FR-28) — zero to N alternatives to the best contract. */
  alternatives?: AlternativeContract[];
  alternativesCount?: number;
  /** Resolved contract fields for the TradeCard contract-detail block. */
  contractDetails?: {
    strike: number;
    expiry: string;              // YYYY-MM-DD
    right:  'C' | 'P';
    spread?: number;
    mid:    number;              // premium, $
    delta:  number;
    theta:  number;              // $/day
    /** IV RANK, or null when no rank source answered. See lib/ivBasis.ts. */
    ivRank: number | null;
    /** ABSOLUTE implied volatility 0–100, or null. See lib/ivBasis.ts. */
    iv?:    number | null;
    ivPercentile?: number | null;  // 0–100
    dte:    number;
  };
  entry:  { limit: number; maxFill: number; orderType: OrderType };
  exit:   {
    /** The stock stop this card is built around: the wider of the structural
     *  level and a 2xATR floor, resolved server-side at scan time (piece 3).
     *  It used to be a flat percentage move off the stock price -- the same
     *  -3% on every symbol in the universe.
     *
     *  NULL means "not computed -- re-run the scan", and comes from exactly one
     *  place: the scanStore v15 migration, which strips it from every candidate
     *  persisted before piece 3 because that stored value is a flat percentage
     *  wearing the resolved stop's name. It must never be seeded into the
     *  editable field or sent: `checkInvalidation` in lib/risk.ts reports
     *  `missing_invalidation` and the card cannot be ordered from until a fresh
     *  scan refills it. The backend never sends null. */
    invalidation: number | null;
    premiumStop: number; timeStopDays: number; target: number; targets: TargetLevel[];
    stockStopLoss?: number | null;
    stockStopLossAt?: number | null;
    rrRiskBasis?: 'premium_stop' | 'stock_stop' | 'full_premium';
    targetSource?: 'structural_snap' | 'arithmetic' | 'flat_fallback' | 'capped';
    /** Where `invalidation` came from — rendered by the "Bottom (final stop)"
     *  row before the user has pressed Compute Arithmetic Plan. Sent by the
     *  scan and echoed by /contracts/recompute-plan so a Step 6 contract
     *  override cannot drop it.
     *
     *  ABSENT means "not computed": the card predates piece 3, the bar feed
     *  could not form a single true range (so the flat percentage fallback
     *  decided the stop and there is no structural level or ATR floor to
     *  report), or the resolution raised. Never render an absent block as a
     *  computed stop. */
    finalStop?: FinalStop | null;
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
  /** Fix #3: earnings inside the horizon reject window -> finalStatus REJECT, no send. */
  earningsVeto?: boolean;
  /** No known next earnings date (none on file, or only a past one). D4
   *  amended 2026-10-03: on a single stock the backend caps finalStatus at
   *  CAUTION; an ETF is unaffected. The cap does not stop an auto-fire by
   *  itself -- the auto-trader re-looks the date up at fire time and refuses
   *  on that (audit round 1, F7). Step 7 refuses the Arm for it (F8). */
  earningsUnknown?: boolean;
  /** In the backend's curated ETF set (app/data/etfs.py). Absent on pre-deploy
   *  scans -- read as false, i.e. a single stock (the safe direction). */
  isEtf?: boolean;
  /** Days to earnings alone; nextEventDays is the nearer of earnings/dividend. */
  earningsDays?: number | null;
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
  /** The stop-vs-premium gate, priced at SCAN time against a structural/ATR
   *  stop (Phase B3, gate-basis spec §2.3). Mirrors `TradeCardData.stopCostPct`
   *  / `stopCostStatus` in backend/app/schemas.
   *
   *  TWO fields, not the whole `StopCostOut`. `WatchlistRow` carries no
   *  contract data, and shipping strike/dte/premium/iv down so the ranking
   *  table could price the gate itself would be the rejected
   *  "Black-Scholes in TypeScript" decision arriving by the back door. The
   *  card's own badge — which DOES render a full `StopCostOut` — is a
   *  different, later reading against a stop the user has refreshed.
   *
   *  They describe the AUTO-PICKED contract. A Step 6 override replaces the
   *  contract without recomputing these, so the ranking table must say what
   *  they describe rather than implying they follow the pick.
   *
   *  null/absent means NOT COMPUTED and must never render as a PASS: no stop
   *  could be formed, the IV would not invert, or the row was restored from a
   *  scan session persisted before B3 shipped. */
  stopCostPct?:    number | null;
  stopCostStatus?: 'PASS' | 'CAUTION' | null;
  /** The two regime-gate headwind thresholds THIS card's scan resolved
   *  (scoring_rules.yaml overlaid by the Step-3 controls it was run with).
   *  Mirrors `TradeCardData.regimeGate` in backend/app/schemas.
   *
   *  The auto-trade arm payload reads its thresholds from HERE, not from the
   *  live Step-3 store: an armed trade is judged by the rule its own scan ran
   *  under (AUTOTRADE-ARMED-TRADE-JUDGED-BY-ITS-SCANS-RULE-2026-09-21).
   *
   *  Absent means the card predates the field (an older persisted or restored
   *  scan), and Arm refuses it rather than guess. A null VALUE inside means the
   *  resolved block carried no such key -- the scan read the YAML, and so will
   *  the fire path. */
  regimeGate?: {
    headwindCautionPct?: number | null;
    headwindRejectPct?:  number | null;
  } | null;
  /**
   * Set locally (never sent by the backend) when the user has picked a
   * different contract than the scan's top recommendation via the contract
   * picker (Step 6 / ContractStar). Drives the "User-selected" badge on
   * Step 7. See step-7-trade-card/page.tsx effectiveCard.
   */
  _userOverride?: boolean;
}

export interface BlockerComparison {
  code: string;
  label: string;
  metric: string;
  observed: number | string | null;
  threshold: number | string;
  operator: string;
}

export interface ComponentExplanation {
  name: string;
  wire_name: string;
  raw_score: number;
  weight: number;
  contribution: number;
  lost_points: number;
  observed?: number | null;
  observed_unit?: string;
  basis?: 'rank' | 'absolute' | 'none' | null;
  preferred_min?: number | null;
  preferred_max?: number | null;
  flags: string[];
  volume?: number | null;
  open_interest?: number | null;
  preferred_volume_min?: number | null;
  preferred_oi_min?: number | null;
}

export interface ContractExplanation {
  version: number;
  contract_id: string;
  evaluated_at: string;
  outcome: 'blocked' | 'aggregate';
  score: number;
  status: Status;
  unrounded_score: number | null;
  rounded_score: number | null;
  pass_threshold: number;
  caution_threshold: number;
  weights: Record<string, number>;
  components: Record<string, ComponentExplanation>;
  largest_losses: ComponentExplanation[];
  blockers: BlockerComparison[];
  reject_reasons: string[];
  soft_flags: string[];
  soft_fail_count: number;
  max_soft_fail_count: number;
  hard_bounds?: Record<string, number>;
  raw_inputs?: Record<string, number | null>;
}

export type ScoreEvidenceValue = string | number | boolean | null | ScoreEvidenceValue[] | { [key: string]: ScoreEvidenceValue };

export interface StockComponentEvidence {
  name: string;
  wire_name: string;
  raw_score: number;
  status: Status;
  measured: boolean;
  weight: number;
  contribution: number;
  detail: Record<string, ScoreEvidenceValue>;
  config: Record<string, ScoreEvidenceValue>;
}

export interface StockCapEvidence {
  name: string;
  status: Status;
  before: Status;
  after: Status;
  detail: Record<string, ScoreEvidenceValue>;
  config: Record<string, ScoreEvidenceValue>;
}

export interface StockExplanation {
  version: 1;
  symbol: string;
  direction: Direction;
  horizon: Horizon;
  scoring_mode: 'stock' | 'options';
  iv_basis: string;
  evaluated_at: string;
  score: number;
  status: Status;
  raw_status: Status;
  unrounded_score: number;
  rounding: 'python_round_ties_to_even';
  pass_threshold: number;
  caution_threshold: number;
  weights: Record<string, number>;
  components: Record<string, StockComponentEvidence>;
  caps: StockCapEvidence[];
  gate_config: Record<string, Record<string, ScoreEvidenceValue> | null>;
}

// --- Option contracts ---

export type OptionRight = 'C' | 'P';

export interface OptionContract {
  noLiveQuote?: boolean;
  quoteState?: string | null;
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
  /** IV RANK, or null when no rank source answered — the common case.
   *  The absolute level is in `iv`. Resolve via lib/ivBasis.ts. */
  ivRank:       number | null;
  /** ABSOLUTE implied volatility, 0–100, for this strike, or null. */
  iv?:          number | null;
  ivPercentile: number | null;
  spread:       number;
  volume:       number;
  score:        number;
  contractConfidence: Status;
  /** Per-component breakdown for THIS contract, when the backend supplied it
   *  (/api/contracts does). Optional because older cached responses and the
   *  scan's own chain rows do not carry it. See applyPickedContract. */
  breakdown?: ContractScoreBreakdown;
  /** Authoritative evaluation breakdown and blocking causes for THIS contract */
  explanation?: ContractExplanation;
}

/** The grading inputs Step 6 sent to `/api/contracts` for a row when it was
 *  starred, stored with the star so the Watchlist grades it the same way
 *  (WATCHLIST-SCAN-CONTRACT-RULES). Both rule forms are deltas on the live
 *  contract_rules.yaml: `{}` = the scan overrode nothing, `null` = the scan's
 *  rules are unknown (older result / unrecordable). */
export interface ContractGrading {
  contract_rules: Record<string, number> | null;
  /** Both set or both null. */
  hold_min_days:  number | null;
  hold_max_days:  number | null;
  /** 0-100 int; null -> the backend default 70. */
  stock_score:    number | null;
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
  /** IV RANK or null; absolute level in `iv`. See lib/ivBasis.ts. */
  ivRank:       number | null;
  iv?:          number | null;
  score:        number;
  contractConfidence: Status;
  contractBreakdown:  ContractScoreBreakdown;
  contractExplanation?: ContractExplanation | null;
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
  avg_regime_duration:  number;   // transition strides, not days
  duration_stride_bars?: number | null;
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

/** Portfolio-position-scoped alert types — the subset of `AlertType` that a
 *  single open position can actually raise, and therefore the only ones a
 *  per-position override can meaningfully switch. REGIME_CHANGE and the
 *  SCAN_* lifecycle types are account-wide and stay global-only. */
export const POSITION_ALERT_TYPES = [
  'TP_HIT',
  'STOP_REACHED',
  'STRUCTURAL_STOP_BREACHED',
  'PREMIUM_STOP',
  'TIME_STOP',
  'EVENT_RISK',
] as const;

export type PositionAlertType = (typeof POSITION_ALERT_TYPES)[number];

/** Per-position alert-type overrides (Feature D).
 *
 *  Tri-state by design, encoded as key presence: an ABSENT key inherits the
 *  global `AlertConfig.enabledTypes` decision, an explicit `true`/`false`
 *  wins over it. `Partial<Record<...>>` (not `Record<..., boolean>`) is what
 *  makes "absent" representable at all — do not "tidy" it into a full record
 *  or the inherit state disappears. Mirrors the backend's `alert_overrides`
 *  JSON column 1:1. */
export type AlertOverrides = Partial<Record<PositionAlertType, boolean>>;

/** Which take-profit computation drives a position's TP_HIT alert (Feature D).
 *  Exactly one is active per position — these are not independent alerts.
 *    ladder        — today's Sell-to-Close ladder, i.e. `targets[0].stockPrice`
 *    monte_carlo   — the Monte Carlo estimate's target
 *    exit_plan_2r  — the exit-plan pipeline's 2R row
 *    exit_plan_3r  — the exit-plan pipeline's 3R row
 *  Mirrors the backend `TpMethod` literal / `active_tp_method` column. */
export type TpMethod = 'ladder' | 'monte_carlo' | 'exit_plan_2r' | 'exit_plan_3r';

/** Phase G (piece 5, D4/D5) — which exit method the trader EXPLICITLY picked
 *  for THIS trade.
 *
 *  Three names in this codebase sound alike and are not:
 *    `rrModel`        — the PRICER (Heston / BS / delta). G does not touch it.
 *    `lastRunMethod`  — "whichever ran most recently", which is what this
 *                       replaces as the thing the card treats as chosen.
 *    `PickedMethod`   — a decision a human made.
 *
 *  `barrier_race` has no `lastRunMethod` counterpart BY CONSTRUCTION: the race
 *  shares Monte Carlo's `computedAt`, so no clock can tell the two apart. An
 *  explicit pick can, which is the fourth value's whole reason for existing.
 *
 *  Named after `scanStore.pickedContracts` — the existing word here for "the
 *  one the user chose over the auto-pick". */
export type PickedMethod = 'arithmetic' | 'monte_carlo' | 'ladder' | 'barrier_race';

/** Which stop the trade was judged on. A RECORD only — it does NOT re-point
 *  any alert (spec §9.2). */
export type PickedStopBasis = 'stock' | 'premium';

export interface MethodPick {
  method: PickedMethod;
  /** D5's second leg, split across the next TWO fields — as PRICES, not a row
   *  index, because a price survives an `rr_ratios` change and `exit_plan_2r`
   *  does not.
   *
   *  THE SPLIT IS LOAD-BEARING; DO NOT COLLAPSE THESE INTO ONE `rowPrice`.
   *  The four methods do not quote their target rows in the same space, and
   *  the only thing this can seed — `resolved_tp_price` — is compared against
   *  the UNDERLYING (`alertEngine.ts:152`, `alert_generator.py:181`):
   *
   *    Ladder       -> stock only  (`exit.targets[].targetPrice ?? stockPrice`)
   *    Arithmetic   -> stock only  (`exitPlan.targets[].price`)
   *    Monte Carlo  -> BOTH        (`FirstPassageTarget.stockPrice`, NULLABLE
   *                                 and documented "display-only Stage-1
   *                                 approximation; null if unreachable", plus
   *                                 `optionPrice` = premium * (1 + pct), which
   *                                 is what the card RENDERS)
   *    Barrier Race -> option only (`BarrierRaceOutcome.targetOptionPrice`;
   *                                 it carries no stock level at all)
   *
   *  One shared field would put a PREMIUM in a STOCK-price column. A $6.24
   *  premium stamped as a stock target makes `price >= 6.24` true on the first
   *  tick, so TP_HIT fires instantly on every bullish option position. The
   *  codebase already knows this: `EditDrawer.tsx:287` maps these very rows
   *  with `price: t.stockPrice ?? 0`, never `optionPrice`. */
  rowStockPrice: number | null;   // underlying space. The ONLY field that may seed resolvedTpPrice.
  rowOptionPrice: number | null;  // premium space. RECORD ONLY — never seeds, never alerts.
  /** D5's third leg. See `PickedStopBasis` — a record, not a re-pointing. */
  stopBasis: PickedStopBasis;
  /** ISO. The vintage of the numbers the pick was made against, so a pick can
   *  be told apart from a stale one the same way the card already tells a
   *  stale estimate apart (`estimateIsFresh`). */
  pickedAt: string;
}

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
  /** PREMIUM_STOP only — the premium-stop fraction this alert ACTUALLY fired
   *  at, stamped at fire time (ALERT-THRESHOLD-STAMP-2026-09-05).
   *
   *  The Alerts page used to resolve this live off the position on every
   *  render, so editing a position's stop afterwards silently relabelled its
   *  historical rows with a threshold those alerts never used: a row reading
   *  "Premium stop (-60%)" for an alert that fired at 30%. `referenceValue`
   *  already stamped the threshold PRICE; this is the percentage beside it.
   *
   *  OPTIONAL, and absent is meaningful: rows persisted before this field
   *  existed carry no stamp and the page falls back to live resolution for
   *  them, which is the best answer available for a row that was never
   *  stamped. That is also why this needs no store migration -- there is no
   *  shape to convert, and bumping ALERT_STORE_VERSION would re-fire
   *  migrateAlerts' one-time enabledTypes backfill (see the comment above that
   *  constant). A FRACTION (0.30), not a percentage (30), matching
   *  `resolvePremiumStopPct` and the backend's `thresholdPct`. */
  premiumStopPct?: number;
  /** PREMIUM_STOP only — the side rule this alert FIRED under
   *  (STOP-SEMANTICS-2026-10-02): 'short-stock' fires on a RISE above entry,
   *  'long-stock' and 'option' on a fall. Stamped at fire time, like
   *  `premiumStopPct`, and part of the alert store's dedup key (`alertKey`), so
   *  a short's rise-side fire never inherits state written under the old
   *  fall-side rule. ABSENT on every pre-deploy row, which fired under that
   *  old rule -- the Alerts page then keeps the legacy label. Needs no store
   *  migration for the same reason `premiumStopPct` needs none. Mirrors
   *  `PremiumStopSide` in lib/premiumStop.ts (types/ does not import lib/). */
  stopSide?: 'short-stock' | 'long-stock' | 'option';
}

// --- Risk management ---

export interface RiskLimits {
  maxSingleTradeExposurePct: number;  // e.g. 0.05 = 5%
  maxTotalExposurePct: number;        // e.g. 0.25 = 25%
  maxConcurrentPositions: number;     // e.g. 10
  maxDailyRecommendations: number;    // e.g. 5
  portfolioValue: number;             // user's total portfolio value in $
  /** Max acceptable $ loss at the exit-plan pipeline's final stop, as a
   *  fraction of portfolioValue (e.g. 0.0375 = 3.75%). The stop-based check
   *  is warning-only and never auto-clamps. It ALSO caps option premium
   *  (review fix #4, D5): an option order has no protective order, so the
   *  effective single-position cap is min(maxSingleTradeExposurePct, this),
   *  enforced server-side in `check_position_risk` and mirrored in
   *  `checkTradeRisk`. See docs/superpowers/plans/
   *  2026-08-26-exit-plan-pipeline.md Feature C. */
  maxLossPerTradePct: number;
  /** STOCK-SENDS (decision STOCK-SENDS-STOCK-CAPS-2026-09-27): the STOCK caps, on
   *  price x shares as a fraction of portfolioValue. The two caps above judge
   *  OPTIONS only, and each kind's total counts only its own rows. */
  maxSingleStockPositionPct: number;  // e.g. 0.20 = 20%
  maxTotalStockExposurePct: number;   // e.g. 1.00 = 100%
}

export interface RiskCheckResult {
  approved: boolean;
  reasons: string[];
  adjustedContracts?: number;
  singleExposurePct: number;
  totalExposurePct: number;
  capitalAtRisk: number;
  /** $ loss projected at the exit-plan final stop (entry premium minus the
   *  stop-repriced contract price, floored at 0, times contracts). Undefined
   *  when no exit plan has been computed yet — there is nothing to check. */
  maxLossAtStop?: number;
  /** The $ threshold `maxLossAtStop` was compared against — either the global
   *  `maxLossPerTradePct * portfolioValue` default, or an active per-trade
   *  override (Feature 5, resolved via `resolveMaxLossLimitDollar`) — set
   *  pre-trade on the Arithmetic Profit Target card, or post-trade via
   *  `PortfolioPosition.maxLossOverride` from the Portfolio editor. */
  maxLossLimitDollar?: number;
}

/** Per-trade override for the max-loss-per-trade warning — either a fixed
 *  dollar figure or a percent of portfolioValue. `null`/absent means
 *  "inherit the global `maxLossPerTradePct` default". Settable in TWO places
 *  now (Feature 5): pre-trade on the TradeCard's Arithmetic Profit Target
 *  card (threaded through `initialMaxLossOverride`/`onMaxLossOverrideChange`,
 *  cached per symbol at the page level, and carried onto the created
 *  `PortfolioPosition` at send time), and post-trade from the Portfolio
 *  editor (`PortfolioPosition.maxLossOverride` directly) — same shape, same
 *  resolution function (`resolveMaxLossLimitDollar`), just set at different
 *  points in the trade's lifecycle. */
export interface MaxLossOverride {
  mode:  'dollar' | 'percent';
  value: number;
}

export interface PortfolioRiskMetrics {
  /** OPTION rows only (STOCK-SENDS: each kind has its own caps). */
  totalExposurePct: number;
  concurrentPositions: number;
  dailyRecommendations: number;
  /** Largest OPTION position (per symbol). */
  largestConcentrationPct: number;
  largestConcentrationSymbol: string;
  /** STOCK rows only, against maxTotalStockExposurePct. */
  stockExposurePct: number;
  /** Largest STOCK position (per symbol), against maxSingleStockPositionPct. */
  largestStockConcentrationPct: number;
  largestStockConcentrationSymbol: string;
  status: Status;  // PASS if all within limits, CAUTION if near, REJECT if breached
}

// --- Holding-horizon DTE window ---

export interface DteWindow {
  min_dte:    number;
  max_dte:    number;
  multiplier: number;
}
