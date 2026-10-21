import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { PersistStorage, StorageValue } from 'zustand/middleware';
import type { SearchProfile, SearchProfileSnapshot } from '@/types/searchProfile';
import { api } from '@/lib/api';
import { DEFAULT_SPREADS } from '@/lib/settingsStore';
import { resolveProfileToScanRequest } from '@/lib/scanScheduleResolve';
import { OVERRIDE_FIELDS } from '@/lib/scanParamsStore';
import { assertStrategyScanOverrides } from '@/lib/strategyScanValidation';
import { sanitizeSearchProfiles } from '@/lib/searchProfileValidation';

function genId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
}

export const CURRENT_SEARCH_PROFILES_SCHEMA_VERSION = 5;

export type PersistedSearchProfiles = Pick<SearchProfilesState, 'profiles' | 'legacyTargetPctDropped'>;

/**
 * Storage adapter with future-version write barrier (Finding S3).
 *
 * 1. Read / Rehydration:
 *    If disk contains a future schema version (e.g. 9999), return CURRENT_SEARCH_PROFILES_SCHEMA_VERSION
 *    to Zustand hydration logic. Zustand evaluates deserializedStorageValue.version === options.version (5)
 *    as true, bypassing migrate and not calling setItem() during hydration. Disk bytes remain
 *    100% byte-for-byte exact (beforeRaw === afterRaw).
 *
 * 2. Writes (saveProfile / updateProfile / deleteProfile):
 *    Directly inspects localStorage.getItem(name) at write time. If a future version is present
 *    on disk, refuses writes completely to prevent discarding future-version profiles, unknown fields,
 *    or sentinels.
 */
export const searchProfilesPersistStorage: PersistStorage<PersistedSearchProfiles> = {
  getItem: (name: string): StorageValue<PersistedSearchProfiles> | null => {
    if (typeof window === 'undefined') return null;
    let raw: string | null = null;
    try {
      raw = localStorage.getItem(name);
    } catch {
      return null;
    }
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') return null;
      const version = typeof parsed.version === 'number' ? parsed.version : 0;
      const state = (parsed.state && typeof parsed.state === 'object') ? parsed.state : {};
      const legacyTargetPctDropped = (state as Record<string, unknown>).legacyTargetPctDropped === true;

      if (version > CURRENT_SEARCH_PROFILES_SCHEMA_VERSION) {
        const profiles = sanitizeSearchProfiles((state as Record<string, unknown>).profiles);
        return {
          state: {
            profiles,
            legacyTargetPctDropped,
          },
          version: CURRENT_SEARCH_PROFILES_SCHEMA_VERSION,
        };
      }

      const rawProfiles = (state as Record<string, unknown>).profiles;
      const profiles = version >= CURRENT_SEARCH_PROFILES_SCHEMA_VERSION
        ? sanitizeSearchProfiles(rawProfiles)
        : (Array.isArray(rawProfiles) ? rawProfiles as SearchProfile[] : []);

      return {
        state: {
          profiles,
          legacyTargetPctDropped,
        },
        version,
      };
    } catch {
      return null;
    }
  },
  setItem: (name: string, value: StorageValue<PersistedSearchProfiles>): void => {
    if (typeof window === 'undefined') return;
    try {
      const currentRaw = localStorage.getItem(name);
      if (currentRaw) {
        try {
          const currentEnvelope = JSON.parse(currentRaw);
          if (
            typeof currentEnvelope?.version === 'number' &&
            currentEnvelope.version > CURRENT_SEARCH_PROFILES_SCHEMA_VERSION
          ) {
            console.warn(
              `[searchProfilesStore] Write barrier: refusing write to newer schema version ${currentEnvelope.version} (current: ${CURRENT_SEARCH_PROFILES_SCHEMA_VERSION})`,
            );
            return;
          }
        } catch {
          // malformed disk contents; proceed to standard write
        }
      }
      localStorage.setItem(name, JSON.stringify(value));
    } catch {
      // quota exceeded or storage disabled
    }
  },
  removeItem: (name: string): void => {
    if (typeof window === 'undefined') return;
    try {
      localStorage.removeItem(name);
    } catch {
      // ignore
    }
  },
};

interface SearchProfilesState {
  profiles: SearchProfile[];
  legacyTargetPctDropped: boolean;
  dismissLegacyTargetPctNotice: () => void;
  /** Schedule-entry ids whose automatic re-sync push (see resyncScheduleEntriesForProfile
   *  below) failed after retries — the Settings UI reads this to show a
   *  "may be out of date" badge per entry rather than failing silently. */
  staleScheduleEntryIds: string[];
  saveProfile:   (name: string, snapshot: SearchProfileSnapshot) => string;
  updateProfile: (id: string, snapshot: SearchProfileSnapshot) => void;
  renameProfile: (id: string, name: string) => void;
  deleteProfile: (id: string) => void;
  clearStaleScheduleEntry: (entryId: string) => void;
}

export const useSearchProfilesStore = create<SearchProfilesState>()(
  persist(
    (set, get) => ({
      profiles: [],
      legacyTargetPctDropped: false,
      dismissLegacyTargetPctNotice: () => set({ legacyTargetPctDropped: false }),
      staleScheduleEntryIds: [],
      saveProfile: (name, snapshot) => {
        if (snapshot.strategyParams) {
          assertStrategyScanOverrides({
            pullbackTolerancePct: snapshot.strategyParams.pullbackTolerancePct,
            maCrossoverLookback: snapshot.strategyParams.maCrossoverLookback,
            breakoutVolumeMult: snapshot.strategyParams.breakoutVolumeMult,
          });
        }
        const now = new Date().toISOString();
        const id = genId();
        set((s) => ({
          profiles: [...s.profiles, { ...snapshot, id, name, createdAt: now, updatedAt: now }],
        }));
        void resyncScheduleEntriesForProfile(id);
        return id;
      },
      updateProfile: (id, snapshot) => {
        if (snapshot.strategyParams) {
          assertStrategyScanOverrides({
            pullbackTolerancePct: snapshot.strategyParams.pullbackTolerancePct,
            maCrossoverLookback: snapshot.strategyParams.maCrossoverLookback,
            breakoutVolumeMult: snapshot.strategyParams.breakoutVolumeMult,
          });
        }
        set((s) => ({
          profiles: s.profiles.map((p) =>
            p.id === id ? { ...p, ...snapshot, updatedAt: new Date().toISOString() } : p),
        }));
        void resyncScheduleEntriesForProfile(id);
      },
      // Bumps updatedAt too, so a rename reorders the dropdown's
      // most-recently-touched-first sort the same way an edit would.
      renameProfile: (id, name) => set((s) => ({
        profiles: s.profiles.map((p) =>
          p.id === id ? { ...p, name, updatedAt: new Date().toISOString() } : p),
      })),
      deleteProfile: (id) => set((s) => ({
        profiles: s.profiles.filter((p) => p.id !== id),
      })),
      clearStaleScheduleEntry: (entryId) => set((s) => ({
        staleScheduleEntryIds: s.staleScheduleEntryIds.filter((id) => id !== entryId),
      })),
    }),
    {
      name: 'bamendjou:search-profiles',
      storage: searchProfilesPersistStorage,
      skipHydration: true,
      version: 5,
      migrate: (persistedState, version) => {
        const st = { ...((persistedState ?? {}) as Record<string, unknown>) };
        // ROUND 5 finding 3. `seedOverrides` was appended to the `version < 2`
        // branch AFTER v2 had already shipped (v2 landed with only the spreads
        // knob at 038aa2d1; the overrides half arrived at d1ea97c9), and zustand
        // calls migrate only when the stored version DIFFERS from the configured
        // one — so a store already stamped 2 never re-entered it, and the
        // user's `iv_rank_pass_max: 20` stayed inert on every chain without a
        // rank source. Same defect shape as scanStore's (finding 2). Bumped to
        // 3 so the seeding actually reaches those stores.
        //
        // Idempotent by construction: seedOverrides returns the input untouched
        // unless `iv_rank_pass_max` is a number AND `iv_abs_pass_max` is absent,
        // so running it at v2 and again at v3 cannot double-apply or overwrite a
        // value the user has since set.
        if (version < 3) {
          // PHASE-A-SPREAD-BASIS-2026-09-06 split the spread picker's single
          // sell-premium cut-off into a percentile knob and an absolute one.
          // settingsStore got a v23->v24 migration for the LIVE value; a profile
          // carries its OWN frozen copy of the same block
          // (searchProfileSnapshot.ts bakes in `spreads: { ...settings.spreads }`),
          // and that copy was left at the pre-split shape.
          //
          // Applying it matters because the profile's copy is what
          // resolveProfileToScanRequest re-resolves for a scheduled scan: with
          // `ivAbsThreshold` undefined the key is omitted from the request body
          // entirely, and on a Tradier-only chain that flips choose_primary from
          // bear_put (debit, long premium) to bear_call (credit, short premium,
          // assignment exposure). Round 1's finding (d), surviving in a store
          // that was not migrated with the other two.
          //
          // Seeded from THAT PROFILE's own ivRankThreshold, not the constant and
          // not the live setting, for the same reason settingsStore seeds from
          // the user's own: whoever moved the old single knob meant it for the
          // chains they actually see, which are the absolute ones. Reading the
          // live setting here would let a later, unrelated change to Settings
          // rewrite what a saved profile means.
          //
          // PHASE A MOVED TWO KNOBS, and a profile freezes BOTH. The second is
          // the Step-3 execution parameter `iv_rank_pass_max`, captured into
          // `scanOverrides` by searchProfileSnapshot.ts:23. Post-split the
          // scorer reads `iv_abs_pass_max` whenever the basis is not 'rank'
          // (stock_scorer._rule_vol), and the two keys deliberately do not leak
          // across bases — so a stored `iv_rank_pass_max` is simply INERT on
          // every chain without a rank source, i.e. most of them. That is round
          // 1's finding (c) surviving in stored form: the user's own ceiling of
          // 20 against a 30% absolute IV yields PASS 90 where they asked for
          // CAUTION 55, a 35-point swing on a weighted component.
          //
          // Same seeding rule as the spread knob below, for the same reason.
          const seedOverrides = (raw: unknown): unknown => {
            if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return raw;
            const ov = raw as Record<string, unknown>;
            if (typeof ov.iv_rank_pass_max !== 'number') return raw;
            if (ov.iv_abs_pass_max !== undefined) return raw;
            return { ...ov, iv_abs_pass_max: ov.iv_rank_pass_max };
          };

          const profiles = Array.isArray(st.profiles) ? st.profiles : [];
          st.profiles = profiles.map((profile) => {
            if (typeof profile !== 'object' || profile === null) return profile;
            const p = profile as Record<string, unknown>;

            // Applies to STOCKS profiles too — the Step-3 panel is shared, so
            // `scanOverrides` is frozen whatever the mode. Done before the
            // spreads block, which returns early on a profile without one.
            const overrides = seedOverrides(p.scanOverrides);
            const withOverrides = overrides === p.scanOverrides
              ? p
              : { ...p, scanOverrides: overrides };

            const scanSettings = withOverrides.scanSettings;
            if (typeof scanSettings !== 'object' || scanSettings === null) return withOverrides;
            const ss = scanSettings as Record<string, unknown>;
            const spreads = ss.spreads;
            // Stocks profiles carry no `spreads` block at all — leave them be
            // rather than inventing one.
            if (typeof spreads !== 'object' || spreads === null) return withOverrides;
            const sp = spreads as Record<string, unknown>;
            if (sp.ivAbsThreshold !== undefined) return withOverrides;
            return {
              ...withOverrides,
              scanSettings: {
                ...ss,
                spreads: {
                  ...sp,
                  ivAbsThreshold: typeof sp.ivRankThreshold === 'number'
                    ? sp.ivRankThreshold
                    : DEFAULT_SPREADS.ivAbsThreshold,
                },
              },
            };
          });
        }
        if (version < 4) {
          let dropped = st.legacyTargetPctDropped === true;
          st.profiles = (Array.isArray(st.profiles) ? st.profiles : []).map((raw) => {
            if (!raw || typeof raw !== 'object') return raw;
            const profile = raw as Record<string, unknown>;
            const original = profile.scanOverrides;
            if (!original || typeof original !== 'object' || Array.isArray(original)) return raw;
            const overrides = { ...(original as Record<string, unknown>) };
            for (const key of ['rr_bullish_target_pct', 'rr_bearish_target_pct']) {
              if (key in overrides) {
                if (overrides[key] !== 0.08) dropped = true;
                delete overrides[key];
              }
            }
            return { ...profile, scanOverrides: overrides };
          });
          st.legacyTargetPctDropped = dropped;
        }
        if (version < 5) {
          // STOCKS-HORIZON-T1 H5: a saved stocks profile's strategy fields
          // became overrides of the backend horizon profile. The stored values
          // were full copies of the old hardcoded defaults, so every override
          // resets to "follow the profile". Removed rather than written as
          // null: captureCurrentSnapshot stores only the overrides that are
          // set, so a migrated profile has the shape a fresh save would have
          // and does not read as modified. Other saved fields are kept.
          st.profiles = (Array.isArray(st.profiles) ? st.profiles : []).map((raw) => {
            if (!raw || typeof raw !== 'object') return raw;
            const profile = raw as Record<string, unknown>;
            const sp = profile.strategyParams;
            if (!sp || typeof sp !== 'object' || Array.isArray(sp)) return raw;
            const kept = { ...(sp as Record<string, unknown>) };
            for (const f of OVERRIDE_FIELDS) delete kept[f];
            return { ...profile, strategyParams: kept };
          });
        }
        return st as unknown as SearchProfilesState;
      },
      merge: (persistedState, currentState) => {
        const typed = persistedState as Partial<SearchProfilesState> | undefined;
        return {
          ...currentState,
          ...typed,
          profiles: sanitizeSearchProfiles(typed?.profiles ?? currentState.profiles),
        };
      },
      partialize: (state) => ({ profiles: state.profiles, legacyTargetPctDropped: state.legacyTargetPctDropped }),
    },
  ),
);

/**
 * Part 3, §3.4 — after a successful profile save, look up whether any
 * schedule entry references it, and if so, re-resolve that profile into a
 * fresh request body (the same client-side resolution manual Run Scan uses)
 * and PUT each such entry's `resolved_request` with it. This is the entire
 * mechanism behind "a schedule always reflects the profile's last explicit
 * save" — the backend never reads localStorage, it just receives pushes,
 * including this automatic one triggered by the save action itself.
 *
 * Retries a failed push a bounded number of times before surfacing a
 * visible "may be stale" indicator (staleScheduleEntryIds) rather than
 * failing silently — a network blip or backend restart mid-save must not
 * leave an entry silently running a stale resolved_request indefinitely.
 */
async function resyncScheduleEntriesForProfile(profileId: string): Promise<void> {
  let entries;
  try {
    entries = await api.getScanSchedule();
  } catch {
    return; // backend unreachable — nothing to re-sync; the local save already succeeded
  }
  const referencing = entries.filter((e) => e.profile_id === profileId);
  if (referencing.length === 0) return;

  const profile = useSearchProfilesStore.getState().profiles.find((p) => p.id === profileId);
  if (!profile) return;

  for (const entry of referencing) {
    let resolvedRequest;
    try {
      resolvedRequest = resolveProfileToScanRequest(profile);
    } catch {
      // Profile can't be resolved or has invalid parameters.
      // Mark the referencing entry stale instead of silently succeeding.
      useSearchProfilesStore.setState((s) => ({
        staleScheduleEntryIds: Array.from(new Set([...s.staleScheduleEntryIds, entry.id])),
      }));
      continue;
    }

    const ok = await pushResolvedRequestWithRetry(entry.id, entry, profile.name, resolvedRequest);
    if (ok) {
      useSearchProfilesStore.getState().clearStaleScheduleEntry(entry.id);
    } else {
      useSearchProfilesStore.setState((s) => ({
        staleScheduleEntryIds: Array.from(new Set([...s.staleScheduleEntryIds, entry.id])),
      }));
    }
  }
}

async function pushResolvedRequestWithRetry(
  entryId: string,
  entry: import('@/lib/api').ScanScheduleEntry,
  profileName: string,
  resolvedRequest: import('@/lib/resolveOptionsScanRequest').OptionsScanRequestBody
    | import('@/lib/resolveStockScanRequest').StockScanRequestBody,
  attempts = 3,
): Promise<boolean> {
  for (let i = 0; i < attempts; i++) {
    try {
      await api.updateScanScheduleEntry(entryId, {
        label: entry.label,
        mode: entry.mode,
        profile_id: entry.profile_id,
        profile_name: profileName,
        profile_synced_at: new Date().toISOString(),
        resolved_request: resolvedRequest,
        pattern: entry.pattern,
        enabled: entry.enabled,
        days_of_week: entry.days_of_week,
        fire_time: entry.fire_time,
        cadence_minutes: entry.cadence_minutes,
        window_start_hour: entry.window_start_hour,
        window_end_hour: entry.window_end_hour,
      });
      return true;
    } catch {
      if (i < attempts - 1) {
        await new Promise((resolve) => setTimeout(resolve, 300 * (i + 1)));
      }
    }
  }
  return false;
}
