import type { Status } from '@/lib/status';
import type { SentimentData, FundamentalsOut } from '@/types/domain';

export interface StrategySignalData {
  strategy: string; entry_price: number; stop_price: number;
  target_price: number; rr_ratio: number; atr: number; detail: Record<string, unknown>;
  /** Backend-computed nearest-first exit ladder; `targets[0] === target_price`.
   *  OPTIONAL, and it must stay optional: `scanStore` persists `stockScanResult`
   *  to localStorage, so a result saved before this field existed rehydrates
   *  without it. Every read site falls back to `[target_price]`, which is why no
   *  store version bump / `migrate()` branch is needed here. Read sites must use
   *  `targets?.length ? … : …` rather than `?? …` — an empty array is also a
   *  "no ladder" case and `??` would not catch it. */
  targets?: number[];
}
export interface BacktestData {
  n_trades: number; win_rate: number; total_return_pct: number;
  max_drawdown_pct: number; expectancy: number; sharpe: number;
  confidence: number | null; passes_gate: boolean; summary_text: string;
}
export interface PositionCardData {
  symbol: string; company: string; price: number; direction: string;
  strategy: StrategySignalData; backtest: BacktestData;
  stock_score: number; stock_status: Status;
  shares: number; dollar_risk: number; dollar_size: number;
  confidence: number | null; confidence_text: string | null;
  sector_rs_pct?: number | null;
  next_event_days?: number | null;
  next_event_label?: string | null;
  sentiment?: SentimentData | null;
  fundamentals?: FundamentalsOut | null;
}
export interface StockPipeline {
  scanned:         number;
  failed_history:  number;
  failed_score:    number;
  failed_signal:   number;
  failed_backtest: number;
  failed_regime?:  number;
  other_rejected:  number;
  candidates:      number;
}

export interface StockScanResult {
  scan_id: string; timestamp: string;
  candidates: PositionCardData[]; rejected: Array<{symbol: string; reason: string}>;
  pipeline?: StockPipeline;
  original_count?: number;
  shortlist_truncated?: boolean;
  direction_banner?: string;
}

export interface StockFirstPassageTarget {
  price:        number;
  probability:  number;         // 0-1
  expectedDays: number | null;  // median TRADING days to hit; null if probability is 0
}

export interface StockFirstPassageEstimate {
  targets:      StockFirstPassageTarget[];
  invalidation: { probability: number; expectedDays: number | null };
  /** Length of the simulated holding window, in TRADING days — from
   *  scoring_rules.yaml's `confidence_backtest.<horizon>.n_days`. A probability
   *  without its window is meaningless, so this is always rendered alongside. */
  horizonDays:  number;
  /** Non-null when the model is a poor fit for this strategy (mean_reversion_*).
   *  Rendered verbatim; the decision of WHEN to set it lives in the backend. */
  modelCaveat:  string | null;
}

// ─── Stocks arithmetic plan (piece 6) ────────────────────────────────────────
//
// The response of `POST /api/stocks/exit-plan` — the options exit plan with the
// premium half removed. There is deliberately NO stop-cost field, no premium,
// no strike, no DTE, no IV and no delta: a stock's stop cost is exact
// (`riskPerShare` x shares), so the options gate's question does not exist here
// and a badge that looked like it would answer a different one. A backend test
// asserts on the response's key set that none of those fields can leak back in.

export interface StockExitPlanStop {
  price:                number;
  source:               'structural' | 'atr_widened';
  structuralSource:     'order_block' | 'swing_low' | 'swing_high' | null;
  structuralConfidence: number | null;
  structuralPrice:      number | null;
  atrFloorPrice:        number;
  /** |structural − ATR floor| — how far apart the two candidate levels were.
   *  null when no structural level was found to compare against. */
  distanceDollar:       number | null;
  /** |entry − stop|. The whole "cost of the stop" for a stock, exactly. */
  riskPerShare:         number;
  /** 0–1, from the same Monte Carlo the targets use. The options card has no
   *  equivalent — it never reported a probability for its stop row. */
  probability:          number;
  /** Median TRADING days to reach the stop; null when no path reached it. */
  expectedDays:         number | null;
}

export interface StockExitPlanTargetRow {
  rrRatio:         number;
  /** entry ± rrRatio × riskPerShare, exactly — the backend quantizes the stop
   *  to cents before building this, so the chain reconciles on screen. */
  arithmeticPrice: number;
  /** The price actually used: `arithmeticPrice`, or the structural level it
   *  snapped onto. */
  price:           number;
  tpSource:        'arithmetic' | 'structural_snap';
  structuralPrice: number | null;
  /** |structural − arithmetic|; null when no structural level lies ahead. */
  distanceDollar:  number | null;
  /** The snap band (0.3 × ATR). Always computable, even with nothing to
   *  compare against. */
  toleranceDollar: number;
  /** |target − entry|, measured to `price` — the level actually used, not the
   *  arithmetic one, or the R:R printed beside it describes a different trade. */
  rewardPerShare:  number;
  probability:     number;
  expectedDays:    number | null;
  qualityGood:     boolean;
  qualityReasons:  string[];
}

/** One target's row of the two-barrier stock race. The three probabilities are
 *  an ATTRIBUTION — every simulated path lands in exactly one — so they sum to
 *  100%, unlike `stop.probability` and `targets[].probability`, which are each
 *  measured on their own and routinely sum past it. */
export interface StockRaceOutcome {
  targetPrice:   number;
  pTargetFirst:  number;
  pStopFirst:    number;
  pNeither:      number;
  /** CONDITIONAL medians — the median day of the paths that resolved THAT way,
   *  not of all paths. They therefore differ from the unconditional
   *  `expectedDays` on the rows above. */
  daysTarget:    number | null;
  daysStop:      number | null;
  /** Allocated to hundredths so the three always sum to exactly 1.00. RENDER
   *  THESE, never the raw p* above: re-rounding the raw values in JavaScript is
   *  how a row ends up printing 18% / 40% / 42% and adding to 99%. */
  weightTarget:  number;
  weightStop:    number;
  weightNeither: number;
  /** Mean price at the end of the window over the `pNeither` paths. A stock
   *  that reached no barrier is still an open position at a knowable average
   *  price. null when no path landed in the bucket. */
  terminalMean:  number | null;
}

export interface StockBarrierRace {
  outcomes:  StockRaceOutcome[];
  /** Echo of the barrier actually used, for auditability against `stop.price`. */
  stopPrice: number;
  nPaths:    number;
}

export interface StockExitPlan {
  stop:              StockExitPlanStop;
  targets:           StockExitPlanTargetRow[];
  atr:               number;
  /** floor(riskBudget / riskPerShare); null when either input is non-positive. */
  recommendedShares: number | null;
  /** portfolioValue × maxLossPerTradePct, from the backend's risk_rules.yaml —
   *  surfaced so the division above is checkable rather than trusted. */
  riskBudget:        number;
  /** Always 'trading'. The options card counts CALENDAR days; this one counts
   *  trading days, and the difference is disclosed rather than unified because
   *  each basis is correct for its own instrument. The card renders the word. */
  daysBasis:         'trading';
  horizonDays:       number;
  modelCaveat:       string | null;
  race:              StockBarrierRace | null;
}
