export type SignalKind = 'FVG' | 'BOS' | 'CHoCH' | 'OrderBlock' | 'Divergence' | 'Fibonacci' | 'Confluence';
export type Direction = 'bullish' | 'bearish';

export interface ZoneSignal {
  kind: 'FVG' | 'OrderBlock';
  direction: Direction;
  time_start: string;
  time_end: string | null;
  price_high: number;
  price_low: number;
  mitigated: boolean;
  confidence: number;
  mtf_aligned: boolean;
  multi_tf?: boolean;
}

export interface LineSignal {
  kind: 'BOS' | 'CHoCH';
  direction: Direction;
  time: string;
  price: number;
  confidence: number;
  mtf_aligned: boolean;
  time_end?: string | null;
  multi_tf?: boolean;
}

export interface DivergenceSignal {
  kind: 'Divergence';
  direction: Direction;
  indicator: 'RSI' | 'MACD';
  divergence_type: 'regular' | 'hidden';
  time_start: string;
  time_end: string;
  price_start: number;
  price_end: number;
  confidence: number;
  mtf_aligned: boolean;
}

export interface FibonacciSignal {
  kind: 'Fibonacci';
  swing_high_time: string;
  swing_high_price: number;
  swing_low_time: string;
  swing_low_price: number;
  levels: { pct: number; price: number }[];
}

export interface ConfluenceSignal {
  kind: 'Confluence';
  price_high: number;
  price_low: number;
  score: number;
  components: SignalKind[];
}

export type StructureSignal = ZoneSignal | LineSignal | DivergenceSignal | FibonacciSignal | ConfluenceSignal;
