/*
 * Chart data types — shared between mock fixtures and CandlestickChart.
 * v5 Lightweight Charts uses `time: string` (YYYY-MM-DD) or UTCTimestamp.
 */

export interface Candle {
  time:   string;   // "YYYY-MM-DD"
  open:   number;
  high:   number;
  low:    number;
  close:  number;
  volume: number;
}
