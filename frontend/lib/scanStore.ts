// Scan & regime state — Zustand.
// Drives the TopBar content (scan context string, scan state pill, regime dot).

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { Status } from './status';
import type { Direction, TradeCardData } from '@/types/domain';

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
  context:         ScanContext | null;
  regime:          Status;
  scanResult:      ScanResult | null;
  /** Previous scan result for delta calculation (rankDelta / scoreDelta). */
  previousRun:     ScanResult | null;
  selectedSymbol:  string | null;
  conflictedSymbols: string[];
  rejectedLog: { symbol: string; reason: string }[];
  scanOverrides: Record<string, number | boolean>;
  setScanState:    (s: ScanState, at?: string) => void;
  setContext:      (c: ScanContext | null) => void;
  setRegime:       (r: Status) => void;
  setScanResult:   (r: ScanResult | null) => void;
  setPreviousRun:  (r: ScanResult | null) => void;
  setSelectedSymbol: (s: string) => void;
  setConflictedSymbols: (symbols: string[]) => void;
  setRejectedLog:  (entries: { symbol: string; reason: string }[]) => void;
  setScanOverrides: (o: Record<string, number | boolean>) => void;
}

export const useScanStore = create<ScanStoreState>()(
  persist(
    (set) => ({
      scanState:       'IDLE',
      scanAt:          null,
      context:         null,
      regime:          'PENDING',
      scanResult:      null,
      previousRun:     null,
      selectedSymbol:  null,
      conflictedSymbols: [],
      rejectedLog: [],
      scanOverrides:   {},
      setScanState:    (s, at) => set({ scanState: s, scanAt: at ?? null }),
      setContext:      (c) => set({ context: c }),
      setRegime:       (r) => set({ regime: r }),
      setScanResult:   (r) => set((state) => ({
        scanResult: r,
        previousRun: r !== null ? state.scanResult : state.previousRun,
      })),
      setPreviousRun:  (r) => set({ previousRun: r }),
      setSelectedSymbol: (s) => set({ selectedSymbol: s }),
      setConflictedSymbols: (symbols) => set({ conflictedSymbols: symbols }),
      setRejectedLog: (entries) => set({ rejectedLog: entries }),
      setScanOverrides: (o) => set({ scanOverrides: o }),
    }),
    {
      name: 'bamendjou-scan-store',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        scanResult:  state.scanResult,
        previousRun: state.previousRun,
        context:     state.context,
        scanAt:      state.scanAt,
      }),
      merge: (persisted, current) => ({
        ...current,
        ...(persisted as Partial<ScanStoreState>),
        scanState: 'IDLE',
      }),
    },
  ),
);
