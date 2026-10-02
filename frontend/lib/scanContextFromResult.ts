/*
 * Rebuild a ScanContext from the request a scan result records
 * (ScanResult.request_context, STEP3-PARAM-REACH).
 *
 * A result restored from GET /api/scan/last into a browser with no persisted
 * ScanContext used to leave `context` null, and Steps 5-7 then read the
 * defaults: Bullish (so Step 6 fetched CALLS for a bearish scan's puts), Swing,
 * and no hold days (so Step 6 graded without the scan's DTE widening). The
 * result now says what it was produced from, and this turns that into the
 * same ScanContext Step 3's syncToStore would have written.
 */
import type { Direction } from '@/types/domain';
import type { ScanContext, ScanRequestContext } from './scanStore';
import { HORIZON_PRESETS, horizonDisplayString, type HorizonKey, type ScoringHorizon } from './horizonPresets';
import { NAMED_UNIVERSES } from './universeStore';

const NAMED = new Set<string>(NAMED_UNIVERSES);
const SCORING: readonly ScoringHorizon[] = ['Intraday', 'Swing', 'Position'];

/** The universe label a null context resolves to at every reader
 *  (`context?.universe ?? 'SP500'`). */
const DEFAULT_UNIVERSE = 'SP500';

function isWholeDay(v: unknown): v is number {
  return typeof v === 'number' && Number.isInteger(v) && v >= 0;
}

/** null when the record is missing or unusable -- the caller then leaves the
 *  context as it is (null), exactly as before the scan recorded it. */
export function contextFromScanRequest(rc: ScanRequestContext | null | undefined): ScanContext | null {
  if (!rc || typeof rc !== 'object') return null;
  if (rc.direction !== 'Bullish' && rc.direction !== 'Bearish') return null;
  if (!SCORING.includes(rc.horizon as ScoringHorizon)) return null;
  const scoring = rc.horizon as ScoringHorizon;

  // Hold days are required: Step 6 widens its DTE grading by them, so a
  // context with invented hold days would grade differently from a scan that
  // had none. Every UI scan sends them (RunScanButton, schedules replay it).
  if (!(isWholeDay(rc.hold_min_days) && isWholeDay(rc.hold_max_days)
        && rc.hold_max_days >= rc.hold_min_days)) return null;
  // So is a known preset key: Step 7 sends it to recompute-plan and
  // first-passage as horizon_preset, and a guessed one would reprice at a
  // horizon the scan never used. Every UI scan sends one.
  if (!HORIZON_PRESETS.some((p) => p.key === rc.horizon_preset)) return null;
  const horizonPreset = rc.horizon_preset as HorizonKey;
  const holdMin = rc.hold_min_days;
  const holdMax = rc.hold_max_days;

  // Only a universe the scan posted BY NAME is restored. A symbol list
  // (Custom or Watchlist) cannot be named: the context's universe is not a
  // label only -- the Stocks scan posts `[context.universe]` -- so 'Custom'
  // would scan a ticker called "Custom". It gets the label a null context
  // already resolves to. Steps 5-7 of the Options path do not read it.
  const list = Array.isArray(rc.universe) ? rc.universe : [];
  const universe = list.length === 1 && NAMED.has(list[0]!) ? list[0]! : DEFAULT_UNIVERSE;

  return {
    universe,
    direction: rc.direction as Direction,
    horizon: horizonDisplayString(scoring, holdMin, holdMax),
    horizonPreset,
    holdMin,
    holdMax,
  };
}

/** False when a context and a recorded request disagree on anything Steps
 *  5-7 read from the context: direction, preset, or hold days. The universe
 *  is deliberately not compared: Step 2 never writes context.universe (it
 *  stays 'SP500' from Step 3's syncToStore whatever was picked), so it is no
 *  record of what was scanned. Used to keep a
 *  result restored from the backend from sitting under a context it was not
 *  produced for -- the rule setContext enforces by clearing the result. A
 *  result without a record (from before 2026-10-02) cannot be checked and
 *  counts as matching, which is how it was treated before. */
export function resultMatchesContext(
  rc: ScanRequestContext | null | undefined,
  ctx: Pick<ScanContext, 'direction' | 'horizonPreset' | 'holdMin' | 'holdMax'> | null | undefined,
): boolean {
  if (!rc || !ctx) return true;
  if (rc.direction !== ctx.direction) return false;
  if (rc.horizon_preset != null && ctx.horizonPreset != null && rc.horizon_preset !== ctx.horizonPreset) return false;
  if (rc.hold_min_days != null && rc.hold_min_days !== ctx.holdMin) return false;
  if (rc.hold_max_days != null && rc.hold_max_days !== ctx.holdMax) return false;
  return true;
}
