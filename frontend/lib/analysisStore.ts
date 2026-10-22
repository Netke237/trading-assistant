import { create } from 'zustand';
import { api, type AnalyzeStockRequest, type StockAnalysis } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { buildStockScanRequestBody, type StockScanRequestBody } from '@/lib/resolveStockScanRequest';
import { tunedParamsHorizon } from '@/lib/horizonPresets';
import { scanSizingFromRisk } from '@/lib/stockScan';
import { useUniverseStore } from '@/lib/universeStore';

export type HorizonEnum = 'Intraday' | 'Swing' | 'Position';

/** ScanContext.horizon is a display label like "Swing (5–15d)" — map to the backend enum. */
export function _horizonEnum(label: string | undefined): HorizonEnum {
  const l = (label ?? '').toLowerCase();
  if (l.startsWith('intraday')) return 'Intraday';
  if (l.startsWith('position')) return 'Position';
  return 'Swing';
}

/** What the Analysis request was built from (A5). 'last-scan' — the exact
 *  request of the stock scan result on record; 'current-settings' — no such
 *  request is known, so the live Step-3 / saved settings, and the page says so. */
export type AnalysisBasis = 'last-scan' | 'current-settings';

/** A5 (decisions A5-ANALYSIS-MIRRORS-SCAN / A5-MIRROR-LAST-SCAN-RUN,
 *  2026-09-24): Analysis mirrors the last stock scan RUN. Replays that scan's
 *  own request with `symbol` in place of `universe`, so every param, Step-3
 *  override, gate threshold and the Step-4 panel's unsaved edits match what
 *  produced the rows on screen. Only when no request is on record does it
 *  build one from the live stores exactly as `runStockScan(activeStrategy)`
 *  would, and it reports that basis rather than passing it off as the scan's. */
export function analysisRequestFor(symbol: string): { req: AnalyzeStockRequest; basis: AnalysisBasis } {
  const scan = useScanStore.getState();
  const snapshot = scan.stockScanRequest;
  if (snapshot) {
    // `symbols` can arrive on a request recovered from the backend's record.
    const { universe: _u, symbols: _s, ...rest } =
      snapshot as StockScanRequestBody & { symbols?: unknown };
    return {
      req: { ...rest, symbol, horizon: _horizonEnum(snapshot.horizon) },
      basis: 'last-scan',
    };
  }
  const ctx = scan.context;
  const u = useUniverseStore.getState();
  // The user's sizing (P3a); throws ScanSizingError on 0%, which `analyze`
  // shows as its error.
  const sizing = scanSizingFromRisk();
  const { universe: _u, ...rest } = buildStockScanRequestBody({
    universe: [],
    direction: ctx?.direction ?? 'Bullish',
    horizon: (ctx?.horizon ?? 'Swing (5–15d)').split(' ')[0],
    strategy: scan.activeStrategy ?? 'pullback_ema',
    params: useScanParamsStore.getState(),
    // The params horizon runStockScan would send (STOCKS-HORIZON-T1 H5).
    paramsHorizon: ctx ? tunedParamsHorizon(ctx.horizonPreset, ctx.holdMax) : null,
    requireReversal: (scan.scanOverrides.pullback_require_reversal as boolean | undefined) ?? false,
    scanOverrides: scan.scanOverrides,
    confidenceGate: useSettingsStore.getState().confidenceGate,
    accountSize: sizing.accountSize,
    riskPct: sizing.riskPct,
    // The scan context's hold, as runStockScan sends it (B6).
    holdMinDays: ctx?.holdMin,
    holdMaxDays: ctx?.holdMax,
    minPriceRaw: u.minPriceRaw,
    maxPriceRaw: u.maxPriceRaw,
    minCapRaw: u.minCapRaw,
    maxCapRaw: u.maxCapRaw,
    capUnit: u.capUnit,
  });
  return { req: { ...rest, symbol, horizon: _horizonEnum(ctx?.horizon) }, basis: 'current-settings' };
}

interface AnalysisState {
  symbol: string;
  result: StockAnalysis | null;
  /** Basis of the request behind `result` (null before the first analysis). */
  basis: AnalysisBasis | null;
  loading: boolean;
  error: string | null;
  analyze: (symbol: string) => Promise<void>;
}

export const useAnalysisStore = create<AnalysisState>((set) => ({
  symbol: '',
  result: null,
  basis: null,
  loading: false,
  error: null,
  analyze: async (raw: string) => {
    const symbol = raw.trim().toUpperCase();
    if (!symbol) return;
    set({ loading: true, error: null, symbol });
    try {
      const { req, basis } = analysisRequestFor(symbol);
      const result = await api.analyzeStock(req);
      set({ result, basis, loading: false });
    } catch (e) {
      set({ result: null, basis: null, loading: false, error: e instanceof Error ? e.message : 'Analysis failed' });
    }
  },
}));
