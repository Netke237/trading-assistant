import type { Universe } from './universeStore';

export const SECTOR_LABELS: Record<string, string> = {
  'SECTOR:XLK': 'Technology',
  'SECTOR:XLC': 'Communication Services',
  'SECTOR:XLY': 'Consumer Discretionary',
  'SECTOR:XLI': 'Industrials',
  'SECTOR:XLF': 'Financials',
  'SECTOR:XLP': 'Consumer Staples',
  'SECTOR:XLV': 'Health Care',
  'SECTOR:XLB': 'Materials',
  'SECTOR:XLRE': 'Real Estate',
  'SECTOR:XLU': 'Utilities',
  'SECTOR:XLE': 'Energy',
  'SP500': 'S&P 500',
  'NDX100': 'Nasdaq 100',
  'DOW30': 'Dow 30',
  'SPY': 'SPY ETF',
};

const TICKER_RE = /^[A-Z][A-Z0-9.\-]{0,5}$/;

/** Parse raw textarea/input -> unique uppercase tickers (1-6 chars). */
export function parseSymbols(raw: string): string[] {
  return Array.from(
    new Set(
      raw
        .split(/[\s,;\n]+/)
        .map((s) => s.trim().toUpperCase())
        .filter((s) => TICKER_RE.test(s)),
    ),
  );
}

/** Check if string matches a known Universe type. */
export function isValidUniverse(val: string): val is Universe {
  if (val === 'SP500' || val === 'NDX100' || val === 'DOW30' || val === 'SPY' || val === 'Watchlist' || val === 'Custom') {
    return true;
  }
  return val.startsWith('SECTOR:');
}

/** Human-readable display name for a universe key. */
export function universeDisplayName(pick: string): string {
  return SECTOR_LABELS[pick] ?? pick;
}

/**
 * Pure resolution of a universe pick ('Custom' / 'Watchlist' / preset) into an
 * actual string array of symbols or preset keys for API requests.
 */
export function resolveUniverseSymbols(
  pick: Universe | string,
  customRaw: string,
  watchlistSymbols: string[] = [],
): string[] {
  if (pick === 'Custom') {
    return parseSymbols(customRaw);
  }
  if (pick === 'Watchlist') {
    return Array.from(
      new Set(
        watchlistSymbols
          .map((s) => s.trim().toUpperCase())
          .filter((s) => TICKER_RE.test(s)),
      ),
    );
  }
  return [pick];
}

/** Returns true if a universe selection resolves to an empty symbol set. */
export function isUniverseEmpty(
  pick: Universe | string,
  customRaw: string,
  watchlistCount: number,
): boolean {
  if (pick === 'Custom') {
    return parseSymbols(customRaw).length === 0;
  }
  if (pick === 'Watchlist') {
    return watchlistCount === 0;
  }
  return false;
}

/** Human-readable reason why a universe cannot be scanned when empty. */
export function universeEmptyReason(pick: Universe | string): string {
  if (pick === 'Custom') {
    return 'Custom universe is empty — enter symbols in Step 2 (Universe)';
  }
  if (pick === 'Watchlist') {
    return 'Watchlist is empty — star symbols before scanning';
  }
  return 'Universe is empty';
}

/**
 * Format human-readable UI caption describing the exact scan scope.
 */
export function universeCaption(
  pick: Universe | string,
  customRaw: string,
  watchlistCount: number,
  customSymbolsList?: string[],
): string {
  if (pick === 'Custom') {
    const syms = customSymbolsList ?? parseSymbols(customRaw);
    if (syms.length === 0) {
      return 'Custom universe is empty — add symbols in Step 2 (Universe)';
    }
    const sample = syms.slice(0, 5).join(', ') + (syms.length > 5 ? '…' : '');
    return `Scanning ${syms.length} custom ${syms.length === 1 ? 'symbol' : 'symbols'} (${sample}) for stock setups`;
  }

  if (pick === 'Watchlist') {
    if (watchlistCount === 0) {
      return 'Watchlist is empty — star symbols before scanning';
    }
    return `Scanning ${watchlistCount} watchlist ${watchlistCount === 1 ? 'symbol' : 'symbols'} for stock setups`;
  }

  if (pick.startsWith('SECTOR:')) {
    const name = SECTOR_LABELS[pick] ?? pick;
    return `Scanning ${name} sector (S&P 500) for stock setups`;
  }

  const name = SECTOR_LABELS[pick] ?? pick;
  return `Scanning full ${name} universe for stock setups`;
}
