import type { Status } from '@/lib/status';

export interface StrategySignalData {
  strategy: string; entry_price: number; stop_price: number;
  target_price: number; rr_ratio: number; atr: number; detail: Record<string, unknown>;
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
}
export interface StockScanResult {
  scan_id: string; timestamp: string;
  candidates: PositionCardData[]; rejected: Array<{symbol: string; reason: string}>;
}
