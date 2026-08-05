import { useUniverseStore } from './universeStore';
import { useScanStore } from './scanStore';
import { useScanParamsStore } from './scanParamsStore';
import { useSettingsStore } from './settingsStore';
import { horizonDisplayString, presetByKey, resolveParamsHorizon } from './horizonPresets';
import type { SearchProfile, SearchProfileSnapshot } from '@/types/searchProfile';

export function captureCurrentSnapshot(mode: 'options' | 'stocks'): SearchProfileSnapshot {
  const u = useUniverseStore.getState();
  const s = useScanStore.getState();
  const settings = useSettingsStore.getState();
  const base: SearchProfileSnapshot = {
    mode,
    universe: {
      pick: u.pick, customRaw: u.customRaw,
      minPriceRaw: u.minPriceRaw, maxPriceRaw: u.maxPriceRaw,
      minCapRaw: u.minCapRaw, maxCapRaw: u.maxCapRaw, capUnit: u.capUnit,
    },
    direction:     s.context?.direction     ?? 'Bullish',
    horizonPreset: s.context?.horizonPreset ?? 'Swing',
    holdMin:       s.context?.holdMin       ?? presetByKey('Swing').holdMin,
    holdMax:       s.context?.holdMax       ?? presetByKey('Swing').holdMax,
    scanOverrides: { ...s.scanOverrides },
    // confidenceGate is read by both scan paths — always captured. The other
    // three are Options-only in practice (RunScanButton's Options path reads
    // them; the Stocks scan path reads its own equivalents from
    // scanOverrides/scanParamsStore instead) — only captured for
    // mode === 'options', so a Stocks profile can't bake in a snapshot of
    // settings it has no bearing on.
    scanSettings: {
      confidenceGate: { ...settings.confidenceGate },
      ...(mode === 'options' ? {
        fundamentalsGate:       { ...settings.fundamentalsGate },
        shortlistMaxCandidates: settings.shortlistMaxCandidates,
        spreads:                { ...settings.spreads },
      } : {}),
    },
  };
  // Only attach strategy/strategyParams when a strategy has actually been
  // chosen this session (activeStrategy set on Step 5). Saving a stocks
  // profile straight from Step 3 — before ever visiting Step 5 — must NOT
  // bake in whatever scanParamsStore happens to hold left over from an
  // unrelated prior session; that would silently masquerade as this
  // profile's intentional strategy tuning.
  if (mode !== 'stocks' || !s.activeStrategy) return base;

  const p = useScanParamsStore.getState();
  return {
    ...base,
    strategy: s.activeStrategy,
    strategyParams: {
      pullbackTolerancePct: p.pullbackTolerancePct, pullbackEmaPeriod: p.pullbackEmaPeriod,
      pullbackTrendEma:     p.pullbackTrendEma,     pullbackMaType:    p.pullbackMaType,
      maCrossoverFast:      p.maCrossoverFast,       maCrossoverSlow:  p.maCrossoverSlow,
      maCrossoverLookback:  p.maCrossoverLookback,   breakoutVolumeMult: p.breakoutVolumeMult,
      rsiPeriod:            p.rsiPeriod,             rsiOversold:      p.rsiOversold,
      rsiTrendSma:          p.rsiTrendSma,            requireChoppyRegime: p.requireChoppyRegime,
      btMinTrades:          p.btMinTrades,            btMinWinRate:     p.btMinWinRate,
      eventFilter:          p.eventFilter,            stockShortlistMax: p.stockShortlistMax,
      meanReversionVariants:   p.meanReversionVariants,
      meanReversionMinConfirm: p.meanReversionMinConfirm,
      vwapLookback:            p.vwapLookback,
      vwapDeviationPct:        p.vwapDeviationPct,
    },
  };
}

export function applySearchProfile(profile: SearchProfile): void {
  const u = useUniverseStore.getState();
  u.setPick(profile.universe.pick);
  u.setCustomRaw(profile.universe.customRaw);
  u.setMinPriceRaw(profile.universe.minPriceRaw);
  u.setMaxPriceRaw(profile.universe.maxPriceRaw);
  u.setMinCapRaw(profile.universe.minCapRaw);
  u.setMaxCapRaw(profile.universe.maxCapRaw);
  u.setCapUnit(profile.universe.capUnit);

  const scoringHz = presetByKey(resolveParamsHorizon(profile.horizonPreset, profile.holdMax)).scoringHorizon;
  useScanStore.getState().setContext({
    universe:      useScanStore.getState().context?.universe ?? 'SP500',
    direction:     profile.direction,
    horizon:       horizonDisplayString(scoringHz, profile.holdMin, profile.holdMax),
    horizonPreset: profile.horizonPreset,
    holdMin:       profile.holdMin,
    holdMax:       profile.holdMax,
  });
  useScanStore.getState().setScanOverrides({ ...profile.scanOverrides });

  if (profile.mode === 'stocks' && profile.strategyParams) {
    useScanStore.getState().setActiveStrategy(profile.strategy ?? null);
    useScanParamsStore.getState().loadParams(profile.strategyParams);
  }

  const settings = useSettingsStore.getState();
  settings.setConfidenceGate(profile.scanSettings.confidenceGate);
  if (profile.mode === 'options') {
    if (profile.scanSettings.fundamentalsGate) settings.setFundamentalsGate(profile.scanSettings.fundamentalsGate);
    if (profile.scanSettings.shortlistMaxCandidates !== undefined) settings.setShortlistMaxCandidates(profile.scanSettings.shortlistMaxCandidates);
    if (profile.scanSettings.spreads) settings.setSpreads(profile.scanSettings.spreads);
  }

  // setContext()'s own contextChanged check (scanStore.ts) only compares
  // universe/direction/horizon, so a profile switch that changes only
  // scanOverrides/universe-filters/strategyParams would leave a stale
  // previousRun/previousStockScanResult in place, corrupting the next scan's
  // rank/score delta against a completely different configuration. Force the
  // reset unconditionally — applying any profile is a fresh setup, never a
  // delta baseline.
  useScanStore.setState({ previousRun: null, previousStockScanResult: null });
}

/** Key-order-insensitive JSON stringify, used for snapshot equality checks —
 *  scanOverrides gets keys re-inserted (delete + spread) on every edit, which
 *  moves the touched key to the end of the object, so plain JSON.stringify
 *  would flag a no-op toggle as a change. */
export function stableStringify(value: unknown): string {
  return JSON.stringify(value, (_key, val) => {
    if (val && typeof val === 'object' && !Array.isArray(val)) {
      return Object.keys(val).sort().reduce((acc, k) => {
        acc[k] = val[k];
        return acc;
      }, {} as Record<string, unknown>);
    }
    return val;
  });
}
