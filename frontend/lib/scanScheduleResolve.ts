/*
 * Part 3 (profile-based scan scheduling) — client-side resolution of a
 * SearchProfile into a fully-resolved ScanRequest/StockScanRequest body,
 * reusing the SAME pure builders RunScanButton/runStockScan use
 * (resolveOptionsScanRequest.ts / resolveStockScanRequest.ts), sourced from
 * the profile's own captured fields instead of live store state — so a
 * schedule entry's resolved_request always reflects exactly what running
 * that profile manually would have produced at save time.
 *
 * Universe/price/cap unit conversion and horizon resolution are NOT
 * reimplemented here — they're the same parseSymbols()/presetByKey()/
 * resolveParamsHorizon() helpers applySearchProfile() already uses, just
 * reading from `profile` instead of a live Zustand store.
 *
 * Decision P3C-SCHEDULE-ZERO-RISK-WARNS-2026-09-25: a stocks entry saved with
 * risk_pct 0 keeps sending 0 (the backend runs it at the 1% default); the
 * Settings row warns via scheduleRiskIgnored() below.
 */
import type { SearchProfile } from '@/types/searchProfile';
import { presetByKey, resolveParamsHorizon, tunedParamsHorizon } from '@/lib/horizonPresets';
import { SCAN_PARAM_DEFAULTS } from '@/lib/scanParamsStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { useRiskStore } from '@/lib/riskStore';
import { buildOptionsScanRequestBody } from '@/lib/resolveOptionsScanRequest';
import { buildStockScanRequestBody } from '@/lib/resolveStockScanRequest';
import type { OptionsScanRequestBody } from '@/lib/resolveOptionsScanRequest';
import type { StockScanRequestBody } from '@/lib/resolveStockScanRequest';

function parseSymbols(raw: string): string[] {
  return Array.from(
    new Set(
      raw
        .split(/[\s,;\n]+/)
        .map((s) => s.trim().toUpperCase())
        .filter((s) => /^[A-Z][A-Z0-9.\-]{0,5}$/.test(s)),
    ),
  );
}

/**
 * Resolve a profile's raw universe pick ('Custom'/'Watchlist'/a preset name)
 * into an actual symbol list — shared by both options and stocks mode.
 *
 * Fixed by post-implementation adversarial review: this used to be
 * options-mode-only (resolveOptionsUniverse), and the stocks-mode branch
 * below just wrapped `profile.universe.pick` in an array directly. Since
 * the backend's expand_universe() passes any non-preset string through
 * unchanged as "an individual ticker," a stocks-mode schedule entry saved
 * from a profile whose universe pick was literally 'Custom' or 'Watchlist'
 * would fire on schedule forever, "successfully" scan a single nonexistent
 * ticker named CUSTOM/WATCHLIST, find 0 candidates, and give no indication
 * anywhere that the schedule was broken.
 */
function resolveUniversePick(profile: SearchProfile): string[] {
  const u = profile.universe;
  if (u.pick === 'Custom') return parseSymbols(u.customRaw);
  if (u.pick === 'Watchlist') return useWatchlistStore.getState().added;
  return [u.pick];
}

/**
 * Resolve a saved SearchProfile into the request body a schedule entry
 * should carry as `resolved_request`. Throws if `profile.mode === 'options'`
 * but `scanSettings.fundamentalsGate`/`spreads` are somehow missing (should
 * never happen — captureCurrentSnapshot always populates them for
 * options-mode profiles) or if a stocks-mode profile has no `strategy`
 * (Step 5 never visited) — surface that as a clear error rather than
 * silently posting a request the backend's own Pydantic model will reject
 * anyway (ScanScheduleEntry's resolved_request validator, backend-side).
 */
export function resolveProfileToScanRequest(
  profile: SearchProfile,
): OptionsScanRequestBody | StockScanRequestBody {
  if (profile.mode === 'options') {
    if (!profile.scanSettings.fundamentalsGate || !profile.scanSettings.spreads) {
      throw new Error(
        `Profile "${profile.name}" is missing fundamentalsGate/spreads — cannot resolve an options scan request.`,
      );
    }
    const scoringHz = presetByKey(resolveParamsHorizon(profile.horizonPreset, profile.holdMax)).scoringHorizon;
    return buildOptionsScanRequestBody({
      universe: resolveUniversePick(profile),
      direction: profile.direction,
      horizon: scoringHz,
      horizonPreset: profile.horizonPreset,
      holdMinDays: profile.holdMin,
      holdMaxDays: profile.holdMax,
      minPriceRaw: profile.universe.minPriceRaw,
      maxPriceRaw: profile.universe.maxPriceRaw,
      minCapRaw: profile.universe.minCapRaw,
      maxCapRaw: profile.universe.maxCapRaw,
      capUnit: profile.universe.capUnit,
      scanOverrides: profile.scanOverrides,
      confidenceGate: profile.scanSettings.confidenceGate,
      fundamentalsGate: profile.scanSettings.fundamentalsGate,
      shortlistMaxCandidates: profile.scanSettings.shortlistMaxCandidates ?? 10,
      spreads: profile.scanSettings.spreads,
    });
  }

  // Stocks mode.
  if (!profile.strategy || !profile.strategyParams) {
    throw new Error(
      `Profile "${profile.name}" has no strategy selected (Step 5 was never visited) — ` +
      `cannot resolve a stock scan request. Visit Step 5 and re-save the profile first.`,
    );
  }
  const scoringHz = presetByKey(resolveParamsHorizon(profile.horizonPreset, profile.holdMax)).scoringHorizon;
  const requireReversal = (profile.scanOverrides.pullback_require_reversal as boolean | undefined) ?? false;

  // Real fix for the risk-fields gap the plan's audit rounds 2/3 found: the
  // manual path's runStockScan() hardcodes account_size/risk_pct ($50k/1%)
  // and never reads riskStore — a schedule entry firing unattended for
  // months must not silently inherit that stale default once the user has
  // actually set their real position sizing. risk_fixed_usd has no
  // frontend source anywhere today (confirmed by the plan's own audit) and
  // is left at its backend default (None) — not mapped here.
  const risk = useRiskStore.getState().limits;

  return buildStockScanRequestBody({
    universe: resolveUniversePick(profile),
    direction: profile.direction,
    horizon: scoringHz,
    strategy: profile.strategy,
    // Saved overrides only (absent = follow the profile), STOCKS-HORIZON-T1 H5.
    params: { ...SCAN_PARAM_DEFAULTS, ...profile.strategyParams },
    paramsHorizon: tunedParamsHorizon(profile.horizonPreset, profile.holdMax),
    requireReversal,
    scanOverrides: profile.scanOverrides,
    confidenceGate: profile.scanSettings.confidenceGate,
    accountSize: risk.portfolioValue,
    riskPct: risk.maxLossPerTradePct,
    // The profile's own hold, Custom included, as the options branch (B6).
    holdMinDays: profile.holdMin,
    holdMaxDays: profile.holdMax,
    minPriceRaw: profile.universe.minPriceRaw,
    maxPriceRaw: profile.universe.maxPriceRaw,
    minCapRaw: profile.universe.minCapRaw,
    maxCapRaw: profile.universe.maxCapRaw,
    capUnit: profile.universe.capUnit,
  });
}

/**
 * True when a schedule entry's saved request carries `risk_pct: 0` — which the
 * backend's StockScanRequest (`_stored_zero_is_unset`) maps to the 1% default
 * (conviction-adjusted), so the 0% the user saved is silently ignored.
 * Decision P3C-SCHEDULE-ZERO-RISK-WARNS-2026-09-25. Options entries never
 * carry `risk_pct` and are never flagged.
 */
export function scheduleRiskIgnored(entry: { mode: string; resolved_request: unknown }): boolean {
  const req = entry.resolved_request;
  return (
    entry.mode === 'stocks' &&
    typeof req === 'object' &&
    req !== null &&
    'risk_pct' in req &&
    (req as { risk_pct: unknown }).risk_pct === 0
  );
}
