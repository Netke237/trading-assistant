import { useScanStore } from './scanStore';
import { useUniverseStore } from './universeStore';
import { useWatchlistStore } from './watchlistStore';
import { useSettingsStore } from './settingsStore';
import { useScanParamsStore } from './scanParamsStore';
import { useRiskStore } from './riskStore';
import { buildOptionsScanRequestBody } from './resolveOptionsScanRequest';
import { buildStockScanRequestBody } from './resolveStockScanRequest';
import { presetByKey, resolveParamsHorizon, tunedParamsHorizon } from './horizonPresets';
import type { ScanReportCategory } from './scanReports';
/** Read controls through the same pure request builders used at dispatch. Never mutates trading state. */
export function useCurrentScanReportInputs(category: ScanReportCategory): Record<string, unknown> | undefined {
    const scan = useScanStore();
    const universe = useUniverseStore();
    const watch = useWatchlistStore();
    const settings = useSettingsStore();
    const params = useScanParamsStore();
    const risk = useRiskStore();
    const context = scan.context;
    // Comparison is read-only: malformed saved settings must not prevent
    // durable report inspection or bypass the scan path's own refusal.
    try {
        if (category === 'options') {
            const preset = context?.horizonPreset ?? 'Swing';
            const holdMax = context?.holdMax ?? presetByKey('Swing').holdMax;
            return { ...buildOptionsScanRequestBody({ universe: universe.pick === 'Custom' ? Array.from(new Set(universe.customRaw.split(/[\s,;\n]+/).map(s => s.trim().toUpperCase()).filter(s => /^[A-Z][A-Z0-9.\-]{0,5}$/.test(s)))) : universe.pick === 'Watchlist' ? watch.added : [universe.pick], direction: context?.direction ?? 'Bullish', horizon: presetByKey(resolveParamsHorizon(preset, holdMax)).scoringHorizon, horizonPreset: preset, holdMinDays: context?.holdMin ?? presetByKey('Swing').holdMin, holdMaxDays: holdMax, minPriceRaw: universe.minPriceRaw, maxPriceRaw: universe.maxPriceRaw, minCapRaw: universe.minCapRaw, maxCapRaw: universe.maxCapRaw, capUnit: universe.capUnit, scanOverrides: scan.scanOverrides, confidenceGate: settings.confidenceGate, fundamentalsGate: settings.fundamentalsGate, shortlistMaxCandidates: settings.shortlistMaxCandidates, spreads: settings.spreads }) };
        }
        if (category === 'stocks')
            return { ...buildStockScanRequestBody({ universe: [context?.universe ?? 'SP500'], direction: context?.direction ?? 'Bullish', horizon: (context?.horizon ?? 'Swing').split(' ')[0], strategy: scan.activeStrategy ?? 'pullback_ema', params, paramsHorizon: context ? tunedParamsHorizon(context.horizonPreset, context.holdMax) : null, requireReversal: (scan.scanOverrides.pullback_require_reversal as boolean | undefined) ?? false, scanOverrides: scan.scanOverrides, confidenceGate: settings.confidenceGate, accountSize: risk.limits.portfolioValue, riskPct: risk.limits.maxLossPerTradePct, holdMinDays: context?.holdMin, holdMaxDays: context?.holdMax, minPriceRaw: universe.minPriceRaw, maxPriceRaw: universe.maxPriceRaw, minCapRaw: universe.minCapRaw, maxCapRaw: universe.maxCapRaw, capUnit: universe.capUnit }) };
    }
    catch {
        return undefined;
    }
    return undefined;
}
