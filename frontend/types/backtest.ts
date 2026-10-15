/** Server-side original evidence. These payloads belong in component memory, never persisted scan stores. */
export type BacktestArtifactStatus = 'available' | 'unsupported' | 'insufficient_history' | 'invalid_input' | 'failed' | 'invalid_evidence' | 'storage_unavailable' | 'capture_unavailable' | 'original_unavailable';
export type CandidateChartSource = 'stocks' | 'pullback' | 'prebreakout' | 'fib';
export interface CandidateChartContext {
  source: CandidateChartSource | 'unknown';
  symbol: string;
  artifactId: string | null;
  status: BacktestArtifactStatus;
}
export interface BacktestArtifactReference {
  backtest_artifact_id?: string | null;
  backtest_artifact_status?: BacktestArtifactStatus | null;
}
export interface BacktestCandle { time: number; open: number; high: number; low: number; close: number; volume: number; }
export interface BacktestEquitySample { time: number; equity: number; strategy_index: number; benchmark_index: number; }
export interface BacktestTrade {
  id: string; direction: string; entry_time: number; exit_time: number;
  entry_price: number; exit_price: number; size: number; net_return_pct: number;
  commission: number; exit_reason: 'time' | 'unknown';
}
export interface BacktestOpenPosition {
  id: string; direction: string; entry_time: number; entry_price: number; size: number; unrealized_pnl: number;
}
export interface BacktestSummary {
  strategy: string; direction: string; n_trades: number; win_rate: number;
  total_return_pct: number; max_drawdown_pct: number; expectancy: number; sharpe: number;
  confidence: number | null; passes_gate: boolean; summary_text: string; n_time_exits: number;
}
export interface BacktestConfiguration {
  initial_cash: number; commission: number; commission_basis: string; order_size: number;
  sizing: string; margin: number; spread: number; exclusive_orders: boolean;
  trade_on_close: boolean; finalize_trades: boolean; hold_max_days: number | null;
  entry_start: string | null; entry_end: string | null;
  min_trades?: number; min_win_rate?: number; min_expectancy?: number; signal_window_bars?: number;
}
export interface DetailedBacktestResult {
  summary: BacktestSummary; status: 'success'; reason: null;
  input_candles: BacktestCandle[]; candles: BacktestCandle[]; equity: BacktestEquitySample[];
  trades: BacktestTrade[]; open_positions: BacktestOpenPosition[]; initial_equity: number;
  configuration: BacktestConfiguration; effective_params: Record<string, unknown>;
  engine_contract_version: string; time_basis: string;
}
export interface BacktestArtifact {
  schema_version: 1; artifact_id: string; provenance: 'original' | 'fresh';
  identity: {
    scan_id: string; report_run_id: string | null; symbol: string; strategy: string;
    direction: string; horizon: string; interval: '1d' | '15m'; bars_basis_version: string;
    input_hash: string; engine_contract_version: string;
  };
  created_at: number; expires_at: number; currency: null; detail: DetailedBacktestResult;
}
export type OriginalBacktestUnavailableReason = Exclude<BacktestArtifactStatus, 'available'> | 'missing' | 'expired' | 'context_mismatch';
export type OriginalBacktestState = {status: 'idle'} | {status: 'loading'} |
  {status: 'ready'; artifact: BacktestArtifact} | {status: 'unavailable'; reason: OriginalBacktestUnavailableReason};

export interface FreshBacktestConfiguration {
  strategies: string[];
  parameters: Record<string, Record<string, string>>;
  multi_fields: string[];
}
export interface FreshBacktestRequest {
  symbol: string; strategy: string; direction: 'Bullish' | 'Bearish';
  params: Record<string, unknown>; start: string; end: string; commission: number;
  hold_max_days: number | null; min_trades: number; min_win_rate: number;
  initial_cash: 100000; order_size: 0.9999999999999998; margin: 1; spread: 0;
  exclusive_orders: true; trade_on_close: false; finalize_trades: false;
  sizing: 'fraction of available equity; whole units'; confirmed: true;
}
export interface FreshBacktestResponse {
  status: 'success' | 'insufficient_history' | 'invalid_input' | 'unsupported' | 'failed' | 'invalid_evidence' | 'storage_unavailable';
  artifact: BacktestArtifact | null;
}
