import { useUniverseStore } from './universeStore';
import { useScanStore } from './scanStore';
import { useScanParamsStore, OVERRIDE_FIELDS } from './scanParamsStore';
import { useSettingsStore } from './settingsStore';
import { horizonDisplayString, presetByKey, resolveParamsHorizon } from './horizonPresets';
import { assertStrategyScanOverrides } from './strategyScanValidation';
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
  // chosen this session (activeStrategy set on Step 4). Saving a stocks
  // profile straight from Step 3 — before ever visiting Step 4 — must NOT
  // bake in whatever scanParamsStore happens to hold left over from an
  // unrelated prior session; that would silently masquerade as this
  // profile's intentional strategy tuning.
  if (mode !== 'stocks' || !s.activeStrategy) return base;

  const p = useScanParamsStore.getState();
  return {
    ...base,
    strategy: s.activeStrategy,
    // STOCKS-HORIZON-T1 H5: only the overrides the user set; every other
    // strategy field follows the backend horizon profile when the saved
    // profile is loaded or scheduled.
    strategyParams: {
      btMinTrades:       p.btMinTrades,
      btMinWinRate:      p.btMinWinRate,
      eventFilter:       p.eventFilter,
      stockShortlistMax: p.stockShortlistMax,
      ...Object.fromEntries(
        OVERRIDE_FIELDS.filter((f) => p[f] !== null).map((f) => [f, p[f]]),
      ),
    },
  };
}

export function applySearchProfile(profile: SearchProfile): void {
  if (profile.strategyParams) {
    assertStrategyScanOverrides({
      pullbackTolerancePct: profile.strategyParams.pullbackTolerancePct,
      maCrossoverLookback: profile.strategyParams.maCrossoverLookback,
      breakoutVolumeMult: profile.strategyParams.breakoutVolumeMult,
    });
  }

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
    // stockScan.ts (runStockScan, which step-4-stocks runs) reads context.universe directly
    // for the actual Stocks scan request (not useUniverseStore) — reusing the
    // OLD context.universe here would silently leave a Stocks scan pointed at
    // whatever universe was previously selected, defeating the whole point of
    // restoring a profile. Use the profile's captured pick instead.
    universe:      profile.universe.pick,
    direction:     profile.direction,
    horizon:       horizonDisplayString(scoringHz, profile.holdMin, profile.holdMax),
    horizonPreset: profile.horizonPreset,
    holdMin:       profile.holdMin,
    holdMax:       profile.holdMax,
  });
  useScanStore.getState().setScanOverrides({ ...profile.scanOverrides });

  if (profile.mode === 'stocks') {
    // A strategy-less profile (saved from Step 3 before ever visiting Step 4)
    // must explicitly clear activeStrategy — otherwise a strategy left over
    // from an earlier session survives untouched, can silently run via
    // RunScanButton's Stocks path, and can get baked into this profile on a
    // later "Update" as if it were intentional.
    useScanStore.getState().setActiveStrategy(profile.strategyParams ? (profile.strategy ?? null) : null);
    if (profile.strategyParams) useScanParamsStore.getState().loadParams(profile.strategyParams);
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
