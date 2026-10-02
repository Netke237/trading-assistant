/*
 * Universe store — Zustand (no persistence).
 *
 * Holds Step 1 universe selection and filter state so it survives
 * navigation between screener steps.
 */

import { create } from 'zustand';

export type Universe =
  | 'SP500'
  | 'NDX100'
  | 'DOW30'
  | 'SPY'
  | 'Watchlist'
  | 'Custom'
  | 'SECTOR:XLK'
  | 'SECTOR:XLC'
  | 'SECTOR:XLY'
  | 'SECTOR:XLI'
  | 'SECTOR:XLF'
  | 'SECTOR:XLP'
  | 'SECTOR:XLV'
  | 'SECTOR:XLB'
  | 'SECTOR:XLRE'
  | 'SECTOR:XLU'
  | 'SECTOR:XLE';

export type CapUnit = 'M' | 'B';

interface UniverseState {
  pick:        Universe;
  customRaw:   string;
  minPriceRaw: string;
  maxPriceRaw: string;
  minCapRaw:   string;
  maxCapRaw:   string;
  capUnit:     CapUnit;
  setPick:        (v: Universe) => void;
  setCustomRaw:   (v: string)   => void;
  setMinPriceRaw: (v: string)   => void;
  setMaxPriceRaw: (v: string)   => void;
  setMinCapRaw:   (v: string)   => void;
  setMaxCapRaw:   (v: string)   => void;
  setCapUnit:     (v: CapUnit)  => void;
  clearFilters:   ()            => void;
}

export const useUniverseStore = create<UniverseState>((set) => ({
  pick:        'SP500',
  customRaw:   '',
  minPriceRaw: '',
  maxPriceRaw: '',
  minCapRaw:   '',
  maxCapRaw:   '',
  capUnit:     'B',
  setPick:        (v) => set({ pick: v }),
  setCustomRaw:   (v) => set({ customRaw: v }),
  setMinPriceRaw: (v) => set({ minPriceRaw: v }),
  setMaxPriceRaw: (v) => set({ maxPriceRaw: v }),
  setMinCapRaw:   (v) => set({ minCapRaw: v }),
  setMaxCapRaw:   (v) => set({ maxCapRaw: v }),
  setCapUnit:     (v) => set({ capUnit: v }),
  clearFilters:   ()  => set({ minPriceRaw: '', maxPriceRaw: '', minCapRaw: '', maxCapRaw: '' }),
}));
