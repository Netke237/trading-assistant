import { migrateAlerts } from './alertStore';
import { migrateAutoTrade, useAutoTradeStore } from './autoTradeStore';
import { migrateRisk } from './riskStore';
import { migrateStructure } from './structureStore';

// Persisted-state migrations normalize partial nested records before Zustand
// merges them into live defaults (per CLAUDE.md's persistence rule).
describe('persist migrations', () => {
  it('alertStore migration restores default nested state', () => {
    const state = { toasts: [], config: { keepAlertsDays: 30 } };
    expect(migrateAlerts(state, 0)).toMatchObject({
      toasts: [],
      config: { keepAlertsDays: 30, enabledTypes: expect.any(Array) },
    });
  });

  it('alertStore migration handles null persisted state', () => {
    expect(migrateAlerts(null, 0).config?.keepAlertsDays).toBe(30);
  });

  it('alertStore migration backfills STRUCTURAL_STOP_BREACHED into a pre-v3 enabledTypes list, once', () => {
    const preV3 = { config: { enabledTypes: ['TP_HIT', 'STOP_REACHED', 'PREMIUM_STOP'] } };
    expect(migrateAlerts(preV3, 2).config?.enabledTypes).toEqual(
      expect.arrayContaining(['TP_HIT', 'STOP_REACHED', 'PREMIUM_STOP', 'STRUCTURAL_STOP_BREACHED']),
    );

    // Already on v3+ (e.g. the user explicitly unchecked it after the v2->v3
    // migration ran once) -> must NOT be silently re-added.
    const postV3 = { config: { enabledTypes: ['TP_HIT', 'STOP_REACHED', 'PREMIUM_STOP'] } };
    expect(migrateAlerts(postV3, 3).config?.enabledTypes).toEqual(['TP_HIT', 'STOP_REACHED', 'PREMIUM_STOP']);
  });

  it('riskStore migration restores missing nested limits', () => {
    const state = { limits: { maxDailyRecommendations: 5 } };
    expect(migrateRisk(state, 1)).toMatchObject({
      limits: {
        maxDailyRecommendations: 5,
        portfolioValue: 100000,
      },
    });
  });

  it('riskStore migration handles null persisted state', () => {
    expect(migrateRisk(null, 0).limits?.portfolioValue).toBe(100000);
  });

  it('riskStore v2->v3 migration backfills maxLossPerTradePct and portfolioValueUpdatedAt', () => {
    const preV3 = { limits: { maxDailyRecommendations: 5, portfolioValue: 75000 } };
    const migrated = migrateRisk(preV3, 2);
    expect(migrated.limits?.maxLossPerTradePct).toBe(0.0375);
    expect(migrated.portfolioValueUpdatedAt).toBeNull();
  });

  it('riskStore migration preserves an already-migrated maxLossPerTradePct/portfolioValueUpdatedAt', () => {
    const postV3 = {
      limits: { maxDailyRecommendations: 5, portfolioValue: 75000, maxLossPerTradePct: 0.02 },
      portfolioValueUpdatedAt: '2026-04-01T00:00:00.000Z',
    };
    const migrated = migrateRisk(postV3, 3);
    expect(migrated.limits?.maxLossPerTradePct).toBe(0.02);
    expect(migrated.portfolioValueUpdatedAt).toBe('2026-04-01T00:00:00.000Z');
  });

  it('structureStore migration restores missing visibility keys', () => {
    const state = { visibility: { FVG: true }, structureVisible: true };
    expect(migrateStructure(state, 1)).toMatchObject({
      visibility: { FVG: true, BOS: false },
      structureVisible: true,
    });
  });

  it('structureStore migration handles null persisted state', () => {
    expect(migrateStructure(null, 0).visibility?.BOS).toBe(false);
  });

  it('autoTrade migration never restores the armed mode', () => {
    expect(migrateAutoTrade({ autoMode: 'armed' }, 1).autoMode).toBe('manual');
    expect(migrateAutoTrade({ autoMode: 'post_scan' }, 1).autoMode).toBe('post_scan');
  });

  it('autoTrade never persists any armed-window state', () => {
    // The store's own comment treats this exclusion as a SAFETY property: an
    // auto-trade that resumed "armed" across a browser restart would fire on
    // the next scan as a surprise trade. Nothing asserted it, so someone
    // "completing" `partialize` later would resurrect that hazard with the
    // suite green. The armed window is server-owned — /auto-trade/status is
    // the source of truth — which is also why adding `armedDirection` and
    // `armedSymbol` needed no `version` bump under CLAUDE.md's rule: that rule
    // governs new PERSISTED fields, and these are deliberately not persisted.
    const partialize = useAutoTradeStore.persist.getOptions().partialize!;
    const persisted = partialize({
      ...useAutoTradeStore.getState(),
      armed: true,
      armedDirection: 'Bearish',
      armedSymbol: 'NVDA',
      lastOrderId: 'order-123',
      autoMode: 'armed',
    }) as Record<string, unknown>;

    expect(persisted).not.toHaveProperty('armed');
    expect(persisted).not.toHaveProperty('armedDirection');
    expect(persisted).not.toHaveProperty('armedSymbol');
    expect(persisted).not.toHaveProperty('lastOrderId');
    // ...and 'armed' never survives as a mode either, belt and braces with the
    // migration above: partialize guards a live write, migrate guards a read of
    // something already on disk.
    expect(persisted.autoMode).toBe('manual');
  });
});
