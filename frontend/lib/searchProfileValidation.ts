import type { SearchProfile } from '@/types/searchProfile';

function isFiniteNumber(val: unknown): val is number {
  return typeof val === 'number' && Number.isFinite(val);
}

function isValidAtrMultPair(val: unknown): boolean {
  if (typeof val !== 'object' || val === null || Array.isArray(val)) return false;
  const pair = val as Record<string, unknown>;
  return isFiniteNumber(pair.target) && isFiniteNumber(pair.stop);
}

function isValidAtrMult(val: unknown): boolean {
  if (typeof val !== 'object' || val === null || Array.isArray(val)) return false;
  const m = val as Record<string, unknown>;
  return (
    isValidAtrMultPair(m.intraday) &&
    isValidAtrMultPair(m.swing) &&
    isValidAtrMultPair(m.position)
  );
}

/**
 * Strict runtime shape guard for SearchProfile.
 * Rejects malformed objects, null/corrupt timestamps, invalid modes, missing required
 * string primitives in universe bounds, and corrupt confidence gate structures.
 */
export function isValidSearchProfile(p: unknown): p is SearchProfile {
  if (typeof p !== 'object' || p === null || Array.isArray(p)) return false;
  const obj = p as Record<string, unknown>;

  // Identifiers: non-empty strings required
  if (typeof obj.id !== 'string' || obj.id.trim().length === 0) return false;
  if (typeof obj.name !== 'string' || obj.name.trim().length === 0) return false;

  // Timestamps: must not be null, boolean, number, empty, or unparseable date strings
  if (obj.createdAt === null || typeof obj.createdAt === 'boolean' || typeof obj.createdAt === 'number') {
    return false;
  }
  if (typeof obj.createdAt === 'string' && (obj.createdAt.trim().length === 0 || Number.isNaN(Date.parse(obj.createdAt)))) {
    return false;
  }

  if (obj.updatedAt === null || typeof obj.updatedAt === 'boolean' || typeof obj.updatedAt === 'number') {
    return false;
  }
  if (typeof obj.updatedAt === 'string' && (obj.updatedAt.trim().length === 0 || Number.isNaN(Date.parse(obj.updatedAt)))) {
    return false;
  }

  // Mode: if specified, must be 'options' or 'stocks'
  if (obj.mode !== undefined && obj.mode !== 'options' && obj.mode !== 'stocks') {
    return false;
  }

  // Direction: if specified, must be 'Bullish' or 'Bearish'
  if (obj.direction !== undefined && obj.direction !== 'Bullish' && obj.direction !== 'Bearish') {
    return false;
  }

  // Horizon & Hold bounds
  if (obj.horizonPreset !== undefined && (typeof obj.horizonPreset !== 'string' || obj.horizonPreset.trim().length === 0)) {
    return false;
  }
  if (obj.holdMin !== undefined && !isFiniteNumber(obj.holdMin)) return false;
  if (obj.holdMax !== undefined && !isFiniteNumber(obj.holdMax)) return false;

  // Universe (Finding F-5): if universe object is present, all 4 price/cap fields must be string primitives
  if (obj.universe !== undefined) {
    if (typeof obj.universe !== 'object' || obj.universe === null || Array.isArray(obj.universe)) return false;
    const u = obj.universe as Record<string, unknown>;
    if (u.pick !== undefined && (typeof u.pick !== 'string' || u.pick.trim().length === 0)) return false;
    if (u.customRaw !== undefined && typeof u.customRaw !== 'string') return false;
    if (u.capUnit !== undefined && u.capUnit !== 'M' && u.capUnit !== 'B') return false;
    // Price/cap filters must be string primitives (can be empty string, never null/undefined/number/boolean)
    if (
      typeof u.minPriceRaw !== 'string' ||
      typeof u.maxPriceRaw !== 'string' ||
      typeof u.minCapRaw !== 'string' ||
      typeof u.maxCapRaw !== 'string'
    ) {
      return false;
    }
  }

  // Scan overrides
  if (obj.scanOverrides !== undefined && (typeof obj.scanOverrides !== 'object' || obj.scanOverrides === null || Array.isArray(obj.scanOverrides))) {
    return false;
  }

  // Scan settings & confidence gate (Finding F-6)
  if (obj.scanSettings !== undefined) {
    if (typeof obj.scanSettings !== 'object' || obj.scanSettings === null || Array.isArray(obj.scanSettings)) return false;
    const ss = obj.scanSettings as Record<string, unknown>;
    if (ss.confidenceGate !== undefined) {
      if (typeof ss.confidenceGate !== 'object' || ss.confidenceGate === null || Array.isArray(ss.confidenceGate)) return false;
      const cg = ss.confidenceGate as Record<string, unknown>;
      if (cg.enabled !== undefined && typeof cg.enabled !== 'boolean') return false;
      if (cg.cautionBelow !== undefined && !isFiniteNumber(cg.cautionBelow)) return false;
      if (cg.rejectBelow !== undefined && !isFiniteNumber(cg.rejectBelow)) return false;
      // atrMult must be non-null object with intraday, swing, position numeric pairs
      if (typeof cg.atrMult !== 'object' || cg.atrMult === null || !isValidAtrMult(cg.atrMult)) return false;
    }
  }

  // Strategy & StrategyParams co-presence (Finding F-7)
  if (obj.mode === 'stocks') {
    const hasStrategy = obj.strategy !== undefined;
    const hasParams = obj.strategyParams !== undefined;
    if (hasStrategy !== hasParams) return false;
    if (hasStrategy) {
      if (typeof obj.strategy !== 'string' || obj.strategy.trim().length === 0) return false;
      if (typeof obj.strategyParams !== 'object' || obj.strategyParams === null || Array.isArray(obj.strategyParams)) {
        return false;
      }
    }
  } else if (obj.mode === 'options') {
    // Options mode profiles must not define stocks strategy fields
    if (obj.strategy !== undefined || obj.strategyParams !== undefined) return false;
  }

  return true;
}

/**
 * Filter an arbitrary unknown array or value, returning only structurally valid SearchProfile entries.
 */
export function sanitizeSearchProfiles(profiles: unknown): SearchProfile[] {
  if (!Array.isArray(profiles)) return [];
  return profiles.filter(isValidSearchProfile);
}

/**
 * Pure descending timestamp comparator: safe against null/undefined timestamps.
 */
export function safeCompareTimestamps(a?: string | null, b?: string | null): number {
  return (b || '').localeCompare(a || '');
}
