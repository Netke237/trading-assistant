// Scan & regime state — Zustand.
// Drives the TopBar content (scan context string, scan state pill, regime dot).

import { create } from 'zustand';
import type { Status } from './status';
import type { Direction, TradeCardData } from '@/types/domain';

export type ScanState = 'IDLE' | 'SCANNING' | 'COMPLETED' | 'FAILED';

export interface ScanContext {
  universe:  string;       // "SP500" | "NAS100" | ...
  direction: Direction;
  horizon:   string;       // "Swing (5–15d)"
}

interface ScanStoreState {
  scanState:  ScanState;
  /** ISO-ish local timestamp, e.g. "2026-04-21T09:42:00" (no TZ suffix). */
  scanAt:          string | null;
  context:         ScanContext | null;
  regime:          Status;
  scanResult:      { scan_id: string; timestamp: string; candidates: TradeCardData[] } | null;
  selectedSymbol:  string | null;
  setScanState:    (s: ScanState, at?: string) => void;
  setContext:      (c: ScanContext | null) => void;
  setRegime:       (r: Status) => void;
  setScanResult:   (r: { scan_id: string; timestamp: string; candidates: TradeCardData[] } | null) => void;
  setSelectedSymbol: (s: string) => void;
}

export const useScanStore = create<ScanStoreState>((set) => ({
  scanState:       'IDLE',
  scanAt:          null,
  context:         null,
  regime:          'PENDING',
  scanResult:      null,
  selectedSymbol:  null,
  setScanState:    (s, at) => set({ scanState: s, scanAt: at ?? null }),
  setContext:      (c) => set({ context: c }),
  setRegime:       (r) => set({ regime: r }),
  setScanResult:   (r) => set({ scanResult: r }),
  setSelectedSymbol: (s) => set({ selectedSymbol: s }),
}));
