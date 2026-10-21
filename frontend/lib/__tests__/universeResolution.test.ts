import {
  parseSymbols,
  isValidUniverse,
  universeDisplayName,
  resolveUniverseSymbols,
  isUniverseEmpty,
  universeEmptyReason,
  universeCaption,
  SECTOR_LABELS,
} from '../universeResolution';

describe('universeResolution', () => {
  describe('parseSymbols', () => {
    it('parses whitespace, comma, semicolon, and newline separated symbols', () => {
      const raw = 'aapl, msft; tsla\n nvda  goog ';
      expect(parseSymbols(raw)).toEqual(['AAPL', 'MSFT', 'TSLA', 'NVDA', 'GOOG']);
    });

    it('deduplicates case-insensitively', () => {
      expect(parseSymbols('aapl AAPL AapL')).toEqual(['AAPL']);
    });

    it('filters out invalid ticker formats', () => {
      expect(parseSymbols('AAPL 123 INVALID_TICKER !@# TSLA')).toEqual(['AAPL', 'TSLA']);
    });

    it('handles symbols with dots and dashes up to 6 characters', () => {
      expect(parseSymbols('BRK.B BF-B MKC')).toEqual(['BRK.B', 'BF-B', 'MKC']);
    });

    it('returns empty array on blank input', () => {
      expect(parseSymbols('   \n\t  ')).toEqual([]);
    });
  });

  describe('isValidUniverse', () => {
    it('recognizes standard index presets and custom/watchlist', () => {
      expect(isValidUniverse('SP500')).toBe(true);
      expect(isValidUniverse('NDX100')).toBe(true);
      expect(isValidUniverse('DOW30')).toBe(true);
      expect(isValidUniverse('SPY')).toBe(true);
      expect(isValidUniverse('Watchlist')).toBe(true);
      expect(isValidUniverse('Custom')).toBe(true);
    });

    it('recognizes sector universes', () => {
      expect(isValidUniverse('SECTOR:XLK')).toBe(true);
      expect(isValidUniverse('SECTOR:XLF')).toBe(true);
    });

    it('rejects unknown universe strings', () => {
      expect(isValidUniverse('UNKNOWN')).toBe(false);
      expect(isValidUniverse('RUSSELL2000')).toBe(false);
      expect(isValidUniverse('')).toBe(false);
    });
  });

  describe('universeDisplayName', () => {
    it('returns friendly name for presets and sectors', () => {
      expect(universeDisplayName('SP500')).toBe('S&P 500');
      expect(universeDisplayName('NDX100')).toBe('Nasdaq 100');
      expect(universeDisplayName('DOW30')).toBe('Dow 30');
      expect(universeDisplayName('SECTOR:XLK')).toBe('Technology');
      expect(universeDisplayName('SECTOR:XLE')).toBe('Energy');
    });

    it('falls back to raw key if not in dictionary', () => {
      expect(universeDisplayName('Custom')).toBe('Custom');
      expect(universeDisplayName('Watchlist')).toBe('Watchlist');
    });
  });

  describe('resolveUniverseSymbols', () => {
    it('resolves Custom pick from customRaw', () => {
      expect(resolveUniverseSymbols('Custom', 'mkc, key, emn')).toEqual(['MKC', 'KEY', 'EMN']);
      expect(resolveUniverseSymbols('Custom', '')).toEqual([]);
    });

    it('resolves Watchlist pick from watchlist symbols list', () => {
      expect(resolveUniverseSymbols('Watchlist', '', ['aapl', 'TSLA', '123'])).toEqual(['AAPL', 'TSLA']);
      expect(resolveUniverseSymbols('Watchlist', '', [])).toEqual([]);
    });

    it('resolves preset picks as single element array', () => {
      expect(resolveUniverseSymbols('SP500', 'ignored')).toEqual(['SP500']);
      expect(resolveUniverseSymbols('NDX100', 'ignored')).toEqual(['NDX100']);
      expect(resolveUniverseSymbols('SECTOR:XLK', 'ignored')).toEqual(['SECTOR:XLK']);
    });
  });

  describe('isUniverseEmpty and universeEmptyReason', () => {
    it('identifies empty and non-empty Custom universe', () => {
      expect(isUniverseEmpty('Custom', '', 5)).toBe(true);
      expect(isUniverseEmpty('Custom', '   ', 5)).toBe(true);
      expect(isUniverseEmpty('Custom', 'AAPL', 5)).toBe(false);
      expect(universeEmptyReason('Custom')).toBe('Custom universe is empty — enter symbols in Step 2 (Universe)');
    });

    it('identifies empty and non-empty Watchlist universe', () => {
      expect(isUniverseEmpty('Watchlist', 'AAPL', 0)).toBe(true);
      expect(isUniverseEmpty('Watchlist', '', 2)).toBe(false);
      expect(universeEmptyReason('Watchlist')).toBe('Watchlist is empty — star symbols before scanning');
    });

    it('preset universes are never empty', () => {
      expect(isUniverseEmpty('SP500', '', 0)).toBe(false);
      expect(isUniverseEmpty('NDX100', '', 0)).toBe(false);
      expect(isUniverseEmpty('SECTOR:XLK', '', 0)).toBe(false);
    });
  });

  describe('universeCaption', () => {
    it('formats preset captions', () => {
      expect(universeCaption('SP500', '', 0)).toBe('Scanning full S&P 500 universe for stock setups');
      expect(universeCaption('NDX100', '', 0)).toBe('Scanning full Nasdaq 100 universe for stock setups');
    });

    it('formats sector captions', () => {
      expect(universeCaption('SECTOR:XLK', '', 0)).toBe('Scanning Technology sector (S&P 500) for stock setups');
    });

    it('formats Custom captions with symbol count and sample', () => {
      expect(universeCaption('Custom', 'MKC, KEY, EMN', 0)).toBe('Scanning 3 custom symbols (MKC, KEY, EMN) for stock setups');
      expect(universeCaption('Custom', 'A B C D E F G', 0)).toBe('Scanning 7 custom symbols (A, B, C, D, E…) for stock setups');
      expect(universeCaption('Custom', '', 0)).toBe('Custom universe is empty — add symbols in Step 2 (Universe)');
    });

    it('formats Watchlist captions', () => {
      expect(universeCaption('Watchlist', '', 4)).toBe('Scanning 4 watchlist symbols for stock setups');
      expect(universeCaption('Watchlist', '', 1)).toBe('Scanning 1 watchlist symbol for stock setups');
      expect(universeCaption('Watchlist', '', 0)).toBe('Watchlist is empty — star symbols before scanning');
    });
  });
});
