/*
 * Chart data types — shared between mock fixtures and CandlestickChart.
 * v5 Lightweight Charts: daily bars use YYYY-MM-DD string; intraday uses
 * UTCTimestamp (Unix seconds as number).
 */

export interface Candle {
  time:   number | string;  // UTCTimestamp (seconds) for intraday; "YYYY-MM-DD" for daily
  open:   number;
  high:   number;
  low:    number;
  close:  number;
  volume: number;
}

export type IndicatorType = 'volume' | 'rsi' | 'macd';

export interface RsiPoint {
  time: string;
  value: number;
}

export interface MacdPoint {
  time: string;
  macd: number;
  signal: number;
  histogram: number;
}

export interface VolumePoint {
  time: string;
  value: number;
  color: string;
}

export type IndicatorData =
  | { type: 'rsi'; data: RsiPoint[] }
  | { type: 'macd'; data: MacdPoint[] }
  | { type: 'volume'; data: VolumePoint[] };
