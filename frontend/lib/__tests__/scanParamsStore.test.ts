import { migrateScanParams, SCAN_PARAM_DEFAULTS, OVERRIDE_FIELDS } from '@/lib/scanParamsStore';

describe('scanParamsStore — migrate is cumulative (H7)', () => {
  it('migrating from v2 includes every field added through v12', () => {
    const result = migrateScanParams({}, 2);
    expect(result.eventFilter).toBe('include');
    expect(result.stockShortlistMax).toBe(10);
    // v12 (STOCKS-HORIZON-T1 H5): every strategy field follows the backend
    // horizon profile, so the values v4-v11 seeded end as null.
    for (const f of OVERRIDE_FIELDS) expect(result[f]).toBeNull();
  });

  it('migrating from v2 leaves btMinWinRate at the current default (never entered the v7/v8 bug window)', () => {
    const result = migrateScanParams({}, 2);
    expect(result.btMinWinRate).toBe(SCAN_PARAM_DEFAULTS.btMinWinRate);
  });

  it('forces btMinWinRate to 0.30 when migrating from exactly v7 (matches the original early-return behavior for a single v7->v11 hop)', () => {
    const result = migrateScanParams({}, 7);
    expect(result.btMinWinRate).toBe(0.30);
  });

  it('corrects a persisted 0.30 to 0.45 when migrating from exactly v8', () => {
    const result = migrateScanParams({ btMinWinRate: 0.30 }, 8);
    expect(result.btMinWinRate).toBe(0.45);
  });

  it('does not touch a genuinely-set btMinWinRate of 0.30 when migrating from v9+', () => {
    const result = migrateScanParams({ btMinWinRate: 0.30 }, 9);
    expect(result.btMinWinRate).toBe(0.30);
  });

  it('preserves an explicit persisted value alongside newly-added fields', () => {
    // A non-strategy setting: strategy fields reset to the profile at v12.
    const result = migrateScanParams({ btMinWinRate: 0.5 }, 3);
    expect(result.btMinWinRate).toBe(0.5);
    expect(result.eventFilter).toBe('include'); // still added
  });

  it('migrating from the current version (12) is a no-op passthrough plus defaults merge', () => {
    const result = migrateScanParams({ rsiPeriod: 21 }, 12);
    expect(result.rsiPeriod).toBe(21);
    expect(result.btMinWinRate).toBe(SCAN_PARAM_DEFAULTS.btMinWinRate);
  });
});
