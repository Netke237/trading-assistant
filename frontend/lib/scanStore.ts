// Scan & regime state — Zustand.
// Drives the TopBar content (scan context string, scan state pill, regime dot).

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { Status } from './status';
import type { Direction, OptionContract, TradeCardData } from '@/types/domain';
import type { StockScanResult } from '@/types/stockDomain';

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

export interface ScanResult {
  scan_id: string;
  timestamp: string;
  candidates: TradeCardData[];
  rejected: RejectedEntry[];
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
  stockScanResult:     StockScanResult | null;
  setStockScanResult:  (r: StockScanResult | null) => void;
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
      screenerMode:        'options',
      stockScanResult:     null,
      activeStrategy:      null,
      setScreenerMode:     (m) => set({ screenerMode: m }),
      setStockScanResult:  (r) => set({ stockScanResult: r }),
      setActiveStrategy:   (s) => set({ activeStrategy: s }),
    }),
    {
      name: 'bamendjou-scan-store',
      storage: createJSONStorage(() => {
        if (typeof window === 'undefined') return undefined as unknown as Storage;
        return localStorage;
      }),
      skipHydration: true,
      version: 4,
      migrate: (persistedState, version) => {
        const prev = (persistedState ?? {}) as any;
        if (version < 2) return { ...prev, pickedContracts: {} };
        if (version < 3) return { ...prev, scanDurationMs: null };
        if (version < 4) return { ...prev, screenerMode: 'options', stockScanResult: null, activeStrategy: null };
        return prev;
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
        screenerMode:    state.screenerMode,
        activeStrategy:  state.activeStrategy,
        stockScanResult: state.stockScanResult,
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
