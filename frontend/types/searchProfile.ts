import type { Direction } from './domain';
import type { Universe, CapUnit } from '@/lib/universeStore';
import type { HorizonKey } from '@/lib/horizonPresets';
import type { SavedScanParams } from '@/lib/scanParamsStore';
import type { ConfidenceGate, FundamentalsGate, SpreadsConfig } from '@/lib/settingsStore';

export interface SearchProfileUniverse {
  pick:        Universe;
  customRaw:   string;
  minPriceRaw: string;
  maxPriceRaw: string;
  minCapRaw:   string;
  maxCapRaw:   string;
  capUnit:     CapUnit;
}

// Scan-affecting Settings-tab fields. `confidenceGate` is read by BOTH scan
// paths (RunScanButton for Options, stockScan.ts for Stocks) so it's always
// present. The other three are read only by the Options path — Stocks reads
// its own equivalents from scanOverrides/scanParamsStore instead (already
// captured elsewhere) — so they're only present on `mode: 'options'`
// profiles, mirroring the Stocks-only strategy fields below but for the
// opposite mode.
export interface SearchProfileScanSettings {
  confidenceGate:          ConfidenceGate;
  fundamentalsGate?:       FundamentalsGate;
  shortlistMaxCandidates?: number;
  spreads?:                SpreadsConfig;
}

export interface SearchProfile {
  id:        string;
  name:      string;
  mode:      'options' | 'stocks';
  createdAt: string;   // ISO
  updatedAt: string;   // ISO
  universe:      SearchProfileUniverse;
  direction:     Direction;
  horizonPreset: HorizonKey;
  holdMin:       number;
  holdMax:       number;
  scanOverrides: Record<string, number | boolean | string>;
  scanSettings:  SearchProfileScanSettings;
  // Stocks-mode profiles only — present only when a strategy has actually
  // been chosen this session (see captureCurrentSnapshot); both fields are
  // always present together or both absent, never one alone.
  strategy?:       string;
  // Plain settings plus only the strategy overrides that were set; an absent
  // override follows the backend horizon profile (STOCKS-HORIZON-T1 H5).
  strategyParams?: SavedScanParams;
}

export type SearchProfileSnapshot = Omit<SearchProfile, 'id' | 'name' | 'createdAt' | 'updatedAt'>;
