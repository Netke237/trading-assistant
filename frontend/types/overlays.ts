// frontend/types/overlays.ts
// Shared types for the new chart overlays and user drawings.

import type { Interval } from '@/lib/chartStore';

/** New overlay kinds added on top of the existing indicator types. */
export type OverlayType =
  | 'MASUITE'    // up to 4 configurable MAs
  | 'XSIGNAL'    // EMA/SMA crossover markers
  | 'AVWAP'      // anchored VWAP
  | 'KEYLEVELS'  // PDH/PDL/PWH/PWL
  | 'HTFLEVELS'  // higher-timeframe H/L/C
  | 'SIGNALS'    // buy/sell markers (EMA cross + RSI)
  | 'MTF'        // multi-timeframe dashboard table
  | 'VPROFILE';  // volume profile + POC

export interface MarkerPoint {
  time: string | number;
  position: 'aboveBar' | 'belowBar';
  color: string;
  shape: 'arrowUp' | 'arrowDown';
  text: string;
}

export interface KeyLevels {
  pdh: number | null; pdl: number | null;
  pwh: number | null; pwl: number | null;
}

export interface VolumeProfileBin { price: number; volume: number; }
export interface VolumeProfile {
  bins: VolumeProfileBin[];
  poc: number | null;   // point of control price
  vah: number | null;   // value-area high
  val: number | null;   // value-area low
}

export interface MtfRow {
  tf: Interval;
  trendUp: boolean;
  rsi: number;
  changePct: number;
}

export type DrawingKind = 'trendline' | 'hline' | 'rect';
export interface DrawingPoint { time: number; price: number; }
export interface Drawing {
  id: string;
  symbol: string;
  interval: Interval;
  kind: DrawingKind;
  points: DrawingPoint[];   // hline: 1 pt; trendline/rect: 2 pts
  color: string;
  width: number;
  createdAt: string;
}
