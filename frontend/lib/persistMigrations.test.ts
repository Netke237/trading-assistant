import { migrateAlerts } from './alertStore';
import { migrateAutoTrade } from './autoTradeStore';
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
});
