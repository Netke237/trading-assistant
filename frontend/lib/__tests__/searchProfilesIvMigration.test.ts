import { useSearchProfilesStore } from '../searchProfilesStore';
import { DEFAULT_SPREADS } from '../settingsStore';

// Reach into the store's persist config for the real migrate() callback — same
// approach as scanStoreIvMigration.test.ts.
const { migrate, version } = (useSearchProfilesStore as unknown as {
  persist: { getOptions: () => {
    migrate: (state: unknown, version: number) => unknown;
    version: number;
  } };
}).persist.getOptions();

type Migrated = {
  profiles: Array<{
    id: string;
    scanSettings?: { spreads?: Record<string, unknown> };
  }>;
};

/** A v1 blob as it was actually written before PHASE-A-SPREAD-BASIS-2026-09-06:
 *  the profile's frozen copy of the settings `spreads` block, carrying the one
 *  pre-split knob and no absolute counterpart. */
function legacyBlob() {
  return {
    profiles: [
      {
        id: 'p-moved-the-knob',
        name: 'Bearish swing',
        scanSettings: {
          confidenceGate: { minWinRate: 0.5 },
          spreads: {
            widthPoints: 5,
            shortLegDelta: 0.3,
            ivRankThreshold: 70,   // the user moved it
            minCredit: 0.5,
            maxDebitPctOfWidth: 40,
          },
        },
      },
      {
        id: 'p-stocks',
        name: 'Stocks pullback',
        // Stocks profiles carry no spreads block at all.
        scanSettings: { confidenceGate: { minWinRate: 0.5 } },
      },
    ],
  };
}

describe('searchProfilesStore v1 → v3 (PHASE-A-SPREAD-BASIS-2026-09-06)', () => {
  it('is registered at the version the migration branch expects', () => {
    expect(version).toBe(5);   // v5: STOCKS-HORIZON-T1 H5 override reset
  });

  it("seeds a profile's absolute threshold from THAT profile's own pre-split knob", () => {
    const out = migrate(legacyBlob(), 1) as Migrated;
    const spreads = out.profiles[0].scanSettings?.spreads;
    // Not the constant 50: whoever moved the single knob to 70 meant it for the
    // chains they actually see, which are the absolute ones. Reading 50 here is
    // the bug — on a Tradier-only chain at 60% IV it flips choose_primary from
    // bear_put (debit, long premium) to bear_call (credit, short premium).
    expect(spreads?.ivAbsThreshold).toBe(70);
    // ...and the percentile knob is left exactly as it was.
    expect(spreads?.ivRankThreshold).toBe(70);
  });

  it('leaves the rest of the spreads block untouched', () => {
    const out = migrate(legacyBlob(), 1) as Migrated;
    expect(out.profiles[0].scanSettings?.spreads).toMatchObject({
      widthPoints: 5, shortLegDelta: 0.3, minCredit: 0.5, maxDebitPctOfWidth: 40,
    });
  });

  it('does not invent a spreads block on a stocks profile', () => {
    const out = migrate(legacyBlob(), 1) as Migrated;
    expect(out.profiles[1].scanSettings).not.toHaveProperty('spreads');
  });

  it('falls back to the default only when the pre-split knob is missing too', () => {
    const blob = legacyBlob();
    delete (blob.profiles[0].scanSettings.spreads as Record<string, unknown>).ivRankThreshold;
    const out = migrate(blob, 1) as Migrated;
    expect(out.profiles[0].scanSettings?.spreads?.ivAbsThreshold)
      .toBe(DEFAULT_SPREADS.ivAbsThreshold);
  });

  it('never overwrites a value a post-split profile already carries', () => {
    // The branch is version-gated, but unlike the scanStore/portfolioStore strips
    // this one is also idempotent by construction — it only fills an absent key.
    // Pinned so a later refactor cannot quietly make it destructive.
    const blob = legacyBlob();
    (blob.profiles[0].scanSettings.spreads as Record<string, unknown>).ivAbsThreshold = 25;
    const out = migrate(blob, 1) as Migrated;
    expect(out.profiles[0].scanSettings?.spreads?.ivAbsThreshold).toBe(25);
  });

  it('survives a blob with no profiles, or a malformed entry', () => {
    expect((migrate({}, 1) as Migrated).profiles).toEqual([]);
    const junk = { profiles: [null, 'nonsense', { id: 'x' }] };
    expect(() => migrate(junk, 1)).not.toThrow();
  });
});
