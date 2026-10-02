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
import {
  HORIZON_PRESETS, horizonDisplayString,
  type HorizonKey, type ScoringHorizon,
} from './horizonPresets';

/** Named universes RunScanButton posts as a one-element list (`[pick]`).
 *  'Custom' and 'Watchlist' post their symbols instead, so they cannot be
 *  told apart from each other on the wire. */
const NAMED_UNIVERSES = new Set([
  'SP500', 'NDX100', 'DOW30', 'SPY',
  'SECTOR:XLK', 'SECTOR:XLC', 'SECTOR:XLY', 'SECTOR:XLI', 'SECTOR:XLF', 'SECTOR:XLP',
  'SECTOR:XLV', 'SECTOR:XLB', 'SECTOR:XLRE', 'SECTOR:XLU', 'SECTOR:XLE',
]);

const SCORING: readonly ScoringHorizon[] = ['Intraday', 'Swing', 'Position'];

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
  const holdMin = rc.hold_min_days;
  const holdMax = rc.hold_max_days;
  // An unknown (or absent) preset key with explicit hold days is Custom: it
  // is the only preset whose hold days are free.
  const horizonPreset: HorizonKey = HORIZON_PRESETS.some((p) => p.key === rc.horizon_preset)
    ? (rc.horizon_preset as HorizonKey)
    : 'Custom';

  const list = Array.isArray(rc.universe) ? rc.universe : [];
  const universe = list.length === 1 && NAMED_UNIVERSES.has(list[0]!) ? list[0]! : 'Custom';

  return {
    universe,
    direction: rc.direction as Direction,
    horizon: horizonDisplayString(scoring, holdMin, holdMax),
    horizonPreset,
    holdMin,
    holdMax,
  };
}
