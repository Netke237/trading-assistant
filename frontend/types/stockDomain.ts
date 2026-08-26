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
