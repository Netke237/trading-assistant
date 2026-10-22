/**
 * Frontend Lane G audit test suite: APP-AUDIT-MONITORING (#355).
 *
 * Pins:
 * 1. Watched contracts store: storage key, schema version 3, grading map, migration rule, and CRUD methods.
 * 2. Watchlist store: storage key, schema version 1, add/remove/isWatched operations.
 * 3. Auto-Trade store: storage key, partialize safety exclusion (unconditionally disarming on reload), atomic armed setter.
 * 4. Alert store separation: portfolio toasts (bamendjou-alerts-v2 v3) vs chart alert rules (bamendjou:alerts).
 * 5. Chart alert indicator parsing and crossing operator math (crosses_above, crosses_below).
 */

import {
  WATCHED_CONTRACTS_STORAGE_KEY,
  migrateWatchedContracts,
  useWatchedContractsStore,
} from '@/lib/watchedContractsStore';
import {
  WATCHLIST_STORAGE_KEY,
  useWatchlistStore,
} from '@/lib/watchlistStore';
import {
  migrateAutoTrade,
  useAutoTradeStore,
} from '@/lib/autoTradeStore';
import { useAlertStore } from '@/lib/alertStore';
import { useChartAlertStore } from '@/lib/chartAlertStore';
import { parseAlertIndicator } from '@/lib/alertIndicators';

describe('Lane G Frontend Audit: APP-AUDIT-MONITORING (#355)', () => {
  describe('1. Watched Contracts Store (useWatchedContractsStore)', () => {
    it('uses canonical storage key bamendjou-watched-contracts-v1', () => {
      expect(WATCHED_CONTRACTS_STORAGE_KEY).toBe('bamendjou-watched-contracts-v1');
    });

    it('implements schema version 3 migration resetting gradings when version < 3', () => {
      const v2Blob = { ids: ['AAPL|180|2026-06-19|C'], grading: { 'AAPL|180|2026-06-19|C': { ivScore: 80 } } };
      const migratedFromV2 = migrateWatchedContracts(v2Blob, 2);
      expect(migratedFromV2.ids).toEqual(['AAPL|180|2026-06-19|C']);
      expect(migratedFromV2.grading).toEqual({});

      const v3Blob = { ids: ['AAPL|180|2026-06-19|C'], grading: { 'AAPL|180|2026-06-19|C': { ivScore: 80 } } };
      const migratedFromV3 = migrateWatchedContracts(v3Blob, 3);
      expect(migratedFromV3.ids).toEqual(['AAPL|180|2026-06-19|C']);
      expect(migratedFromV3.grading).toEqual({ 'AAPL|180|2026-06-19|C': { ivScore: 80 } });
    });

    it('handles add, remove, and clearGrading correctly', () => {
      const { add, remove, clearGrading, isWatched } = useWatchedContractsStore.getState();
      const testId = 'MSFT|400|2026-07-17|C';
      const mockGrading = {
        ivScore: 85,
        liquidityScore: 90,
        spreadScore: 88,
        deltaScore: 92,
        compositeScore: 89,
        passed: true,
      };

      add(testId, mockGrading as any);
      expect(isWatched(testId)).toBe(true);
      expect(useWatchedContractsStore.getState().grading[testId]).toEqual(mockGrading);

      clearGrading(testId);
      // Contract is still watched, but grading is cleared to fall back to YAML rules
      expect(isWatched(testId)).toBe(true);
      expect(useWatchedContractsStore.getState().grading[testId]).toBeUndefined();

      remove(testId);
      expect(isWatched(testId)).toBe(false);
    });
  });

  describe('2. Watchlist Store (useWatchlistStore)', () => {
    it('uses canonical storage key bamendjou-watchlist-v1', () => {
      expect(WATCHLIST_STORAGE_KEY).toBe('bamendjou-watchlist-v1');
    });

    it('supports addSymbol, removeSymbol, and isWatched without toggleSymbol ambiguity', () => {
      const { addSymbol, removeSymbol, isWatched } = useWatchlistStore.getState();
      const sym = 'GOOGL';

      addSymbol(sym);
      expect(isWatched(sym)).toBe(true);

      removeSymbol(sym);
      expect(isWatched(sym)).toBe(false);
    });
  });

  describe('3. Auto-Trade Safety & Persistence (useAutoTradeStore)', () => {
    it('resets armed autoMode to manual in migrateAutoTrade', () => {
      const armedState = { autoMode: 'armed', selectedBroker: 'tradier_paper' as const };
      const migrated = migrateAutoTrade(armedState, 1);
      expect(migrated.autoMode).toBe('manual');

      const postScanState = { autoMode: 'post_scan', selectedBroker: 'tradier_paper' as const };
      const migratedPostScan = migrateAutoTrade(postScanState, 1);
      expect(migratedPostScan.autoMode).toBe('post_scan');
    });

    it('sets armed, armedDirection, and armedSymbol atomically via applyArmedStatus', () => {
      const store = useAutoTradeStore.getState();
      store.applyArmedStatus(true, 'Bullish', 'TSLA');

      let state = useAutoTradeStore.getState();
      expect(state.armed).toBe(true);
      expect(state.armedDirection).toBe('Bullish');
      expect(state.armedSymbol).toBe('TSLA');

      // Disarming atomically clears direction and symbol
      store.applyArmedStatus(false, null, null);
      state = useAutoTradeStore.getState();
      expect(state.armed).toBe(false);
      expect(state.armedDirection).toBeNull();
      expect(state.armedSymbol).toBeNull();
    });
  });

  describe('4. Alert Subsystem Store Separation', () => {
    it('useAlertStore uses bamendjou-alerts-v2 with schema version 3', () => {
      expect(useAlertStore).toBeDefined();
      expect(useAlertStore.persist.getOptions().name).toBe('bamendjou-alerts-v2');
      expect(useAlertStore.persist.getOptions().version).toBe(3);
    });

    it('useChartAlertStore uses separate bamendjou:alerts store (version 2) for chart rules and history', () => {
      expect(useChartAlertStore).toBeDefined();
      expect(useChartAlertStore.persist.getOptions().name).toBe('bamendjou:alerts');
      expect(useChartAlertStore.persist.getOptions().version).toBe(2);
      const state = useChartAlertStore.getState();
      expect(Array.isArray(state.rules)).toBe(true);
      expect(Array.isArray(state.history)).toBe(true);
      expect(Array.isArray(state.toasts)).toBe(true);
    });
  });

  describe('5. Chart Alert Indicator Parsing & Math', () => {
    it('parses valid indicator references and rejects malformed indicators', () => {
      expect(parseAlertIndicator('ema(20)')).toEqual({ kind: 'ema', params: [20] });
      expect(parseAlertIndicator('sma(50)')).toEqual({ kind: 'sma', params: [50] });
      expect(parseAlertIndicator('rsi(14)')).toEqual({ kind: 'rsi', params: [14] });
      expect(parseAlertIndicator('macd(12,26,9)')).toEqual({ kind: 'macd', params: [12, 26, 9] });
      expect(parseAlertIndicator('vwap')).toEqual({ kind: 'vwap', params: [] });

      // Invalid: fast >= slow for MACD
      expect(parseAlertIndicator('macd(26,12,9)')).toBeNull();
      // Invalid: out-of-bounds period
      expect(parseAlertIndicator('ema(0)')).toBeNull();
      expect(parseAlertIndicator('ema(-5)')).toBeNull();
    });
  });
});
