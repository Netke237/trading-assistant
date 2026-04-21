/*
 * Scan & regime state — Zustand.
 *
 * Drives the TopBar content (scan context string, scan state pill, regime dot).
 * v1 is not persisted because scan runs are ephemeral — they come from the
 * backend. In v1 we seed with plausible mock data so the UI is populated.
 */

import { create } from 'zustand';
import type { Status } from './status';
import type { Direction } from '@/types/domain';

export type ScanState = 'IDLE' | 'SCANNING' | 'COMPLETED' | 'FAILED';

export interface ScanContext {
  universe:  string;       // "SP500" | "NAS100" | ...
  direction: Direction;
  horizon:   string;       // "Swing (5–15d)"
}

interface ScanStoreState {
  scanState:  ScanState;
  scanTime:   string | null;    // e.g. "09:42" — set when state becomes COMPLETED
  context:    ScanContext | null;
  regime:     Status;
  setScanState: (s: ScanState, time?: string) => void;
  setContext:   (c: ScanContext | null) => void;
  setRegime:    (r: Status) => void;
}

export const useScanStore = create<ScanStoreState>((set) => ({
  scanState:  'COMPLETED',
  scanTime:   '09:42',
  context:    { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)' },
  regime:     'PASS',
  setScanState: (s, time) => set({ scanState: s, scanTime: time ?? null }),
  setContext:   (c) => set({ context: c }),
  setRegime:    (r) => set({ regime: r }),
}));
