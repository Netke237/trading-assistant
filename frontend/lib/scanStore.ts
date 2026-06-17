// Scan & regime state — Zustand.
// Drives the TopBar content (scan context string, scan state pill, regime dot).

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { Status } from './status';
import type { Direction, OptionContract, TradeCardData } from '@/types/domain';
import type { StockScanResult, PositionCardData } from '@/types/stockDomain';

export type ScanState = 'IDLE' | 'SCANNING' | 'COMPLETED' | 'FAILED' | 'PARTIAL' | 'CANCELLED';

export interface ScanContext {
  universe:  string;       // "SP500" | "NAS100" | ...
  direction: Direction;
  horizon:   string;       // "Swing (5–15d)"
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
  screenerMode:        'options' | 'stocks';
  setScreenerMode:     (m: 'options' | 'stocks') => void;
  stockScanResult:          StockScanResult | null;
  /** Previous stock scan result for delta calculation (rankDelta / scoreDelta). */
  previousStockScanResult:  StockScanResult | null;
  /** ISO-ish local timestamp of the last completed stock scan. */
  stockScanAt:         string | null;
  setStockScanResult:  (r: StockScanResult | null) => void;
  stockBasket:           PositionCardData[];
  addToStockBasket:      (card: PositionCardData) => void;
  removeFromStockBasket: (symbol: string) => void;
  clearStockBasket:      () => void;
  activeStrategy:      string | null;
  setActiveStrategy:   (s: string | null) => void;
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
      setContext:      (c) => set({ context: c }),
      setRegime:       (r) => set({ regime: r }),
      setCombinedRegime: (r) => set({ combinedRegime: r }),
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
      stockBasket:           [],
      activeStrategy:           null,
      setScreenerMode:     (m) => set({ screenerMode: m }),
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
      version: 6,
      migrate: (persistedState, version) => {
        // Branches must accumulate — no early returns — so a store at any old
        // version receives ALL intermediate field additions in one migration pass.
        let s = { ...((persistedState ?? {}) as Record<string, unknown>) };
        if (version < 2) s = { ...s, pickedContracts: {} };
        if (version < 3) s = { ...s, scanDurationMs: null };
        if (version < 4) s = { ...s, screenerMode: 'options', stockScanResult: null, activeStrategy: null };
        if (version < 5) s = { ...s, previousStockScanResult: null, stockBasket: [] };
        if (version < 6) s = { ...s, stockScanAt: null };
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
