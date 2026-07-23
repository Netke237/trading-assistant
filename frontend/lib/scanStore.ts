// Scan & regime state — Zustand.
// Drives the TopBar content (scan context string, scan state pill, regime dot).

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { Status } from './status';
import type { Direction, OptionContract, TradeCardData, DteWindow } from '@/types/domain';
import type { StockScanResult, PositionCardData } from '@/types/stockDomain';
import type { HorizonKey } from './horizonPresets';
import { migrateLegacyHorizon, presetByKey, horizonDisplayString, resolveParamsHorizon } from './horizonPresets';

export type ScanState = 'IDLE' | 'SCANNING' | 'COMPLETED' | 'FAILED' | 'PARTIAL' | 'CANCELLED';

export interface ScanContext {
  universe:      string;      // "SP500" | "NAS100" | ...
  direction:     Direction;
  /**
   * Derived display string, e.g. "Position (90–105d)" — kept for the ~15
   * existing consumers (TopBar, dashboard, ScanLog, stock-mode scan/analyze
   * requests) that parse or display this directly. Always starts with one of
   * 'Intraday' | 'Swing' | 'Position' (the scoring horizon), even for the
   * Position-scored long-dated presets — see horizonDisplayString().
   */
  horizon:       string;
  horizonPreset: HorizonKey;  // 'Swing' | 'Quarterly' | 'Custom' | ...
  holdMin:       number;      // calendar days
  holdMax:       number;      // calendar days
}

export interface RejectedEntry {
  symbol: string;
  reason: string;
  breakdown?: Record<string, number>;
}

export interface OptionsPipeline {
  scanned:           number;
  failed_data:       number;
  failed_pre_screen: number;
  no_chain:          number;
  failed_score:      number;
  failed_contracts:  number;
  candidates:        number;
}

export interface ScanResult {
  scan_id: string;
  timestamp: string;
  candidates: TradeCardData[];
  rejected: RejectedEntry[];
  pipeline?: OptionsPipeline;
  direction_banner?: string;
  dte_window?: DteWindow;
}

interface ScanStoreState {
  scanState:  ScanState;
  /** ISO-ish local timestamp, e.g. "2026-04-21T09:42:00" (no TZ suffix). */
  scanAt:          string | null;
  /** Elapsed milliseconds for the last completed/failed scan. Not persisted. */
  scanDurationMs:  number | null;
  context:         ScanContext | null;
  regime:          Status;
  combinedRegime:  Status;
  scanResult:      ScanResult | null;
  /** Previous scan result for delta calculation (rankDelta / scoreDelta). */
  previousRun:     ScanResult | null;
  selectedSymbol:  string | null;
  conflictedSymbols: string[];
  rejectedLog: { symbol: string; reason: string }[];
  scanOverrides: Record<string, number | boolean | string>;
  pickedContracts:    Record<string, string>;
  contractsBySymbol:  Record<string, OptionContract[]>;
  setScanState:    (s: ScanState, at?: string, durationMs?: number) => void;
  setContext:      (c: ScanContext | null) => void;
  setRegime:       (r: Status) => void;
  setCombinedRegime: (r: Status) => void;
  setScanResult:   (r: ScanResult | null) => void;
  setPreviousRun:  (r: ScanResult | null) => void;
  setSelectedSymbol: (s: string) => void;
  setConflictedSymbols: (symbols: string[]) => void;
  setRejectedLog:  (entries: { symbol: string; reason: string }[]) => void;
  setScanOverrides: (o: Record<string, number | boolean | string>) => void;
  setPickedContract:    (symbol: string, contractId: string) => void;
  clearPickedContracts: () => void;
  setContractsBySymbol: (map: Record<string, OptionContract[]>) => void;
  screenerMode:        'options' | 'stocks' | 'prebreakout';
  setScreenerMode:     (m: 'options' | 'stocks' | 'prebreakout') => void;
  stockScanResult:          StockScanResult | null;
  /** Previous stock scan result for delta calculation (rankDelta / scoreDelta). */
  previousStockScanResult:  StockScanResult | null;
  /** ISO-ish local timestamp of the last completed stock scan. */
  stockScanAt:         string | null;
  /** ISO-ish local timestamp of the last completed options scan. */
  optionsScanAt:       string | null;
  setOptionsScanAt:    (at: string) => void;
  setStockScanResult:  (r: StockScanResult | null) => void;
  stockBasket:           PositionCardData[];
  addToStockBasket:      (card: PositionCardData) => void;
  removeFromStockBasket: (symbol: string) => void;
  clearStockBasket:      () => void;
  activeStrategy:      string | null;
  setActiveStrategy:   (s: string | null) => void;
  /** Session-only — not persisted; cleared on page load. */
  regimeDirection:    'BULL' | 'BEAR' | 'MIXED' | null;
  setRegimeDirection: (d: 'BULL' | 'BEAR' | 'MIXED' | null) => void;
  preBreakoutResults: Array<{ symbol: string; confidence: number; direction: string; metrics: Record<string, number> }>;
  setPreBreakoutResults: (results: Array<{ symbol: string; confidence: number; direction: string; metrics: Record<string, number> }>) => void;
  fibPullbackResults: Array<{
    symbol: string;
    direction: string;
    fib_level_hit: string;
    fib_dist_pct: number | null;
    at_level: boolean;
    confidence: number;
  }>;
  setFibPullbackResults: (results: Array<{
    symbol: string;
    direction: string;
    fib_level_hit: string;
    fib_dist_pct: number | null;
    at_level: boolean;
    confidence: number;
  }>) => void;
}

export const useScanStore = create<ScanStoreState>()(
  persist(
    (set) => ({
      scanState:       'IDLE',
      scanAt:          null,
      scanDurationMs:  null,
      context:         null,
      regime:          'PENDING',
      combinedRegime:  'PENDING',
      scanResult:      null,
      previousRun:     null,
      selectedSymbol:  null,
      conflictedSymbols: [],
      rejectedLog: [],
      scanOverrides:   {},
      pickedContracts:    {},
      contractsBySymbol:  {},
      setScanState:    (s, at, durationMs) => set({ scanState: s, scanAt: at ?? null, scanDurationMs: durationMs ?? null }),
      setContext:      (c) => set((state) => {
        if (c === null) return { context: null };
        const prev = state.context;
        const contextChanged = !prev
          || prev.universe  !== c.universe
          || prev.direction !== c.direction
          || prev.horizon   !== c.horizon;
        return {
          context: c,
          ...(contextChanged ? { previousRun: null, previousStockScanResult: null } : {}),
        };
      }),
      setRegime:       (r) => set({ regime: r }),
      setCombinedRegime: (r) => set({ combinedRegime: r }),
      regimeDirection:    null,
      setRegimeDirection: (d) => set({ regimeDirection: d }),
      preBreakoutResults: [],
      setPreBreakoutResults: (results) => set({ preBreakoutResults: results }),
      fibPullbackResults: [],
      setFibPullbackResults: (results) => set({ fibPullbackResults: results }),
      setScanResult:   (r) => set((state) => ({
        scanResult: r,
        previousRun: r !== null ? state.scanResult : state.previousRun,
      })),
      setPreviousRun:  (r) => set({ previousRun: r }),
      setSelectedSymbol: (s) => set({ selectedSymbol: s }),
      setConflictedSymbols: (symbols) => set({ conflictedSymbols: symbols }),
      setRejectedLog: (entries) => set({ rejectedLog: entries }),
      setScanOverrides: (o) => set({ scanOverrides: o }),
      setPickedContract:    (symbol, contractId) => set(s => ({ pickedContracts: { ...s.pickedContracts, [symbol]: contractId } })),
      clearPickedContracts: () => set({ pickedContracts: {} }),
      setContractsBySymbol: (map) => set({ contractsBySymbol: map }),
      screenerMode:             'options',
      stockScanResult:          null,
      previousStockScanResult:  null,
      stockScanAt:              null,
      optionsScanAt:            null,
      stockBasket:           [],
      activeStrategy:           null,
      setScreenerMode:     (m) => set({ screenerMode: m }),
      setOptionsScanAt:    (at) => set({ optionsScanAt: at }),
      setStockScanResult:  (r) => set((state) => ({
        stockScanResult: r,
        previousStockScanResult: r !== null ? state.stockScanResult : state.previousStockScanResult,
        stockScanAt: r !== null ? new Date().toISOString().slice(0, 19) : state.stockScanAt,
      })),
      addToStockBasket:      (card) => set((s) => ({
        stockBasket: [...s.stockBasket.filter((c) => c.symbol !== card.symbol), card],
      })),
      removeFromStockBasket: (symbol) => set((s) => ({
        stockBasket: s.stockBasket.filter((c) => c.symbol !== symbol),
      })),
      clearStockBasket:      () => set({ stockBasket: [] }),
      setActiveStrategy:   (s) => set({ activeStrategy: s }),
    }),
    {
      name: 'bamendjou-scan-store',
      storage: createJSONStorage(() => {
        if (typeof window === 'undefined') return undefined as unknown as Storage;
        return localStorage;
      }),
      skipHydration: true,
      version: 10,
      migrate: (persistedState, version) => {
        // Branches must accumulate — no early returns — so a store at any old
        // version receives ALL intermediate field additions in one migration pass.
        let s = { ...((persistedState ?? {}) as Record<string, unknown>) };
        if (version < 2) s = { ...s, pickedContracts: {} };
        if (version < 3) s = { ...s, scanDurationMs: null };
        if (version < 4) s = { ...s, screenerMode: 'options', stockScanResult: null, activeStrategy: null };
        if (version < 5) s = { ...s, previousStockScanResult: null, stockBasket: [] };
        if (version < 6) s = { ...s, stockScanAt: null };
        if (version < 7) s = { ...s, optionsScanAt: null };
        if (version < 8) s = { ...s, preBreakoutResults: [] };
        if (version < 9) s = { ...s, fibPullbackResults: [] };
        if (version < 10) {
          const ctx = s.context as { universe?: string; direction?: string; horizon?: string } | null | undefined;
          s = {
            ...s,
            context: ctx
              ? (() => {
                  const legacy = migrateLegacyHorizon(ctx.horizon);
                  // Equivalent to the old ternary for every horizonPreset value (same
                  // reasoning as page.tsx's weightsKey/scoringHz and RunScanButton's horizon).
                  const scoringHz = presetByKey(resolveParamsHorizon(legacy.horizonPreset, legacy.holdMax)).scoringHorizon;
                  return {
                    universe:  ctx.universe  ?? 'SP500',
                    direction: ctx.direction ?? 'Bullish',
                    ...legacy,
                    horizon: horizonDisplayString(scoringHz, legacy.holdMin, legacy.holdMax),
                  };
                })()
              : null,
          };
        }
        return s;
      },
      partialize: (state) => ({
        scanResult:      state.scanResult,
        previousRun:     state.previousRun,
        context:         state.context,
        scanAt:          state.scanAt,
        scanDurationMs:  state.scanDurationMs,
        pickedContracts: state.pickedContracts,
        // Persist terminal states so the COMPLETED/FAILED pill survives a restart.
        // SCANNING / IDLE are never persisted — they'd be stale after reload.
        scanState:       state.scanState,
        screenerMode:             state.screenerMode,
        activeStrategy:           state.activeStrategy,
        stockScanResult:          state.stockScanResult,
        previousStockScanResult:  state.previousStockScanResult,
        stockScanAt:              state.stockScanAt,
        optionsScanAt:            state.optionsScanAt,
        stockBasket:     state.stockBasket,
      }),
      merge: (persisted, current) => {
        const p = persisted as Partial<ScanStoreState>;
        const lastState = p.scanState;
        // Restore only terminal states; an in-progress state from before a crash
        // or server restart is meaningless — reset to IDLE.
        const restoredState: ScanState =
          lastState === 'COMPLETED' || lastState === 'PARTIAL' || lastState === 'FAILED'
            ? lastState
            : 'IDLE';
        return { ...current, ...p, scanState: restoredState };
      },
    },
  ),
);
