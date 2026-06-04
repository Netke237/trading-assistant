'use client';

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export type Interval = '1min' | '5min' | '15min' | '1h' | '4h' | '1D' | '1W';
export type ChartType = 'candle' | 'bar' | 'line';

export interface IndicatorConfig {
  id: string;           // e.g. 'ema-20'
  type: string;         // 'SMA' | 'EMA' | 'RSI' | 'MACD' | 'BB' | 'ATR' | 'VWAP' | 'VOL'
  params: Record<string, number>;
  pane: 'main' | 'sub';
  color: string;
}

export interface PaneLayout {
  mainHeightPct: number;
  subPanes: { id: string; heightPct: number }[];
}

interface ChartState {
  symbol: string;
  interval: Interval;
  chartType: ChartType;
  activeIndicators: IndicatorConfig[];
  paneLayout: PaneLayout;
  setSymbol: (s: string) => void;
  setInterval: (i: Interval) => void;
  setChartType: (t: ChartType) => void;
  addIndicator: (cfg: IndicatorConfig) => void;
  removeIndicator: (id: string) => void;
  updateIndicator: (id: string, patch: Partial<IndicatorConfig>) => void;
  setPaneLayout: (layout: PaneLayout) => void;
}

const DEFAULT_INDICATORS: IndicatorConfig[] = [
  { id: 'ema-20',  type: 'EMA',  params: { period: 20 },  pane: 'main', color: '#4f8ef7' },
  { id: 'ema-50',  type: 'EMA',  params: { period: 50 },  pane: 'main', color: '#e0a030' },
  { id: 'vol',     type: 'VOL',  params: {},               pane: 'sub',  color: '#4a4a6a' },
  { id: 'rsi-14',  type: 'RSI',  params: { period: 14 },  pane: 'sub',  color: '#70b070' },
];

const DEFAULT_PANE_LAYOUT: PaneLayout = {
  mainHeightPct: 60,
  subPanes: [
    { id: 'vol', heightPct: 15 },
    { id: 'rsi-14', heightPct: 25 },
  ],
};

// Default param sets for the new chart overlays. The IndicatorPanel reads these
// to build toggle entries; ChartWorkspace reads ind.params to render. Every value
// is a user-overwritable default.
export const OVERLAY_DEFAULTS: Record<string, { pane: 'main' | 'sub'; params: Record<string, number>; color: string; label: string }> = {
  MASUITE:   { pane: 'main', label: 'MA Suite (4)',     color: '#4f8ef7', params: { ma1: 9, ma2: 21, ma3: 50, ma4: 200 } },
  XSIGNAL:   { pane: 'main', label: 'EMA/SMA Cross',    color: '#e0a030', params: { emaLen: 9, smaLen: 20 } },
  AVWAP:     { pane: 'main', label: 'Anchored VWAP',    color: '#b070e0', params: { anchorMs: 1735689600000 } },
  KEYLEVELS: { pane: 'main', label: 'Key Levels',       color: '#808080', params: { day: 1, week: 1 } },
  HTFLEVELS: { pane: 'main', label: 'Higher-TF Levels', color: '#30a060', params: { tfMin: 240 } },
  SIGNALS:   { pane: 'main', label: 'Signal Markers',   color: '#26a69a', params: { fast: 9, slow: 21, rsi: 14 } },
  MTF:       { pane: 'main', label: 'MTF Dashboard',    color: '#888888', params: { rsi: 14 } },
  VPROFILE:  { pane: 'main', label: 'Volume Profile',   color: '#5a6acf', params: { lookback: 200, rows: 24 } },
};

export const useChartStore = create<ChartState>()(
  persist(
    (set) => ({
      symbol: 'AAPL',
      interval: '1D',
      chartType: 'candle',
      activeIndicators: DEFAULT_INDICATORS,
      paneLayout: DEFAULT_PANE_LAYOUT,
      setSymbol: (symbol) => set({ symbol }),
      setInterval: (interval) => set({ interval }),
      setChartType: (chartType) => set({ chartType }),
      addIndicator: (cfg) => set(s => ({ activeIndicators: [...s.activeIndicators, cfg] })),
      removeIndicator: (id) => set(s => ({ activeIndicators: s.activeIndicators.filter(i => i.id !== id) })),
      updateIndicator: (id, patch) =>
        set(s => ({ activeIndicators: s.activeIndicators.map(i => (i.id === id ? { ...i, ...patch } : i)) })),
      setPaneLayout: (paneLayout) => set({ paneLayout }),
    }),
    {
      name: 'bamendjou:chart',
      storage: createJSONStorage(() => {
        if (typeof window === 'undefined') return undefined as unknown as Storage;
        return localStorage;
      }),
      skipHydration: true,
      partialize: (state) => ({
        symbol: state.symbol,
        interval: state.interval,
        chartType: state.chartType,
        activeIndicators: state.activeIndicators,
        paneLayout: state.paneLayout,
      }),
      version: 1,
      migrate: (persistedState, version) => {
        const prev = (persistedState as Partial<ChartState> | null) ?? {};
        if (version < 1) {
          return {
            symbol: prev.symbol ?? 'AAPL',
            interval: prev.interval ?? '1D',
            chartType: prev.chartType ?? 'candle',
            activeIndicators: Array.isArray(prev.activeIndicators) ? prev.activeIndicators : DEFAULT_INDICATORS,
            paneLayout: prev.paneLayout ?? DEFAULT_PANE_LAYOUT,
          } as ChartState;
        }
        return prev as ChartState;
      },
    },
  ),
);
