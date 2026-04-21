/*
 * Sector heatmap — Phase 6 / Round 2.
 * 11 GICS sectors + their 1-day change. Used on Step 3 Market Regime.
 * `status` is derived from change magnitude (±0.4% threshold).
 */

import type { Status } from '@/lib/status';

export interface SectorTile {
  key:     string;          // "XLK"
  name:    string;          // "Technology"
  changePct: number;        // -3.2 .. +3.2
  status:  Status;
}

function statusFromChange(pct: number): Status {
  if (pct >=  0.4) return 'PASS';
  if (pct <= -0.4) return 'REJECT';
  return 'CAUTION';
}

function tile(key: string, name: string, changePct: number): SectorTile {
  return { key, name, changePct, status: statusFromChange(changePct) };
}

export const MOCK_SECTORS: SectorTile[] = [
  tile('XLK',  'Technology',              +1.24),
  tile('XLC',  'Comm. Services',          +0.86),
  tile('XLY',  'Consumer Discretionary',  +0.42),
  tile('XLI',  'Industrials',             +0.18),
  tile('XLF',  'Financials',              +0.05),
  tile('XLP',  'Consumer Staples',        -0.08),
  tile('XLV',  'Health Care',             -0.22),
  tile('XLB',  'Materials',               -0.41),
  tile('XLRE', 'Real Estate',             -0.68),
  tile('XLU',  'Utilities',               -0.94),
  tile('XLE',  'Energy',                  -1.18),
];
