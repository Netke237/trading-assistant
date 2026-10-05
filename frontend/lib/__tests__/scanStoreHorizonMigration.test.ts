import { useScanStore } from '../scanStore';

// Reach into the store's persist config to get the real migrate() callback.
// zustand's `persist` middleware exposes it via the store's persist API.
const migrate = (useScanStore as unknown as {
  persist: { getOptions: () => { migrate: (state: unknown, version: number) => unknown } };
}).persist.getOptions().migrate;

describe('scanStore persisted migrate(): v9 -> v10', () => {
  it('preserves the typed custom range that v9 discarded, and recomputes horizon', () => {
    const v9State = {
      context: { universe: 'SP500', direction: 'Bullish', horizon: 'Custom (60–185d)' },
    };
    const migrated = migrate(v9State, 9) as { context: Record<string, unknown> };
    expect(migrated.context).toEqual({
      universe: 'SP500',
      direction: 'Bullish',
      // NOT the stale 'Custom (60–185d)' — recomputed from the migrated fields via
      // scoringHorizonForHold(185) === 'Position'. A stale 'Custom (...)' string
      // would break lib/stockScan.ts's `.split(' ')[0]` (see Task 9 Step 3 note).
      horizon: 'Position (60–185d)',
      horizonPreset: 'Custom',
      holdMin: 60,
      holdMax: 185,
    });
  });

  it('handles a null context without throwing', () => {
    const v9State = { context: null };
    const migrated = migrate(v9State, 9) as { context: unknown };
    expect(migrated.context).toBeNull();
  });

  it('handles a missing context key without throwing', () => {
    const migrated = migrate({}, 9) as { context: unknown };
    expect(migrated.context).toBeNull();
  });
});

describe('scanStore persisted migrate(): legacy pricing methods', () => {
  it('normalizes legacy target pricing codes in persisted scan results', () => {
    const migrated = migrate({
      scanResult: {
        candidates: [{ exit: { targets: [{ pricingMethod: 'delta-approx' }], rrRiskBasis: 'full_premium' } }],
      },
      previousRun: {
        candidates: [{ exit: { targets: [{ pricingMethod: 'heston' }], rrRiskBasis: 'full_premium' } }],
      },
    }, 11) as {
      scanResult: { candidates: Array<{ exit: { targets: Array<{ pricingMethod: string }> } }> };
      previousRun: { candidates: Array<{ exit: { targets: Array<{ pricingMethod: string }> } }> };
    };

    expect(migrated.scanResult.candidates[0].exit.targets[0].pricingMethod)
      .toBe('BS repriced (IV-derived)');
    expect(migrated.previousRun.candidates[0].exit.targets[0].pricingMethod)
      .toBe('Heston repriced');
  });
});
