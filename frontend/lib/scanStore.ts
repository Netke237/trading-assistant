/*
 * Scan & regime state — Zustand.
 *
 * Drives the TopBar content (scan context string, scan state pill, regime dot).
 * v1 is not persisted because scan runs are ephemeral — they come from the
 * backend. In v1 we seed with plausible mock data so the UI is populated.
 */

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
  scanAt:     string | null;
  context:    ScanContext | null;
  regime:     Status;
  scanResult: { scan_id: string; timestamp: string; candidates: TradeCardData[] } | null;
  setScanState: (s: ScanState, at?: string) => void;
  setContext:   (c: ScanContext | null) => void;
  setRegime:    (r: Status) => void;
  setScanResult: (r: { scan_id: string; timestamp: string; candidates: TradeCardData[] } | null) => void;
}

export const useScanStore = create<ScanStoreState>((set) => ({
  scanState:  'COMPLETED',
  // Seeded as yesterday so the TopBar date-prefix behaviour is visible on load.
  scanAt:     '2026-04-20T09:42:00',
  context:    { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)' },
  regime:     'PASS',
  setScanState: (s, at) => set({ scanState: s, scanAt: at ?? null }),
  setContext:   (c) => set({ context: c }),
  setRegime:    (r) => set({ regime: r }),
  scanResult: null,
  setScanResult: (r) => set({ scanResult: r }),
}));
