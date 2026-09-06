import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { SearchProfile, SearchProfileSnapshot } from '@/types/searchProfile';
import { api } from '@/lib/api';
import { DEFAULT_SPREADS } from '@/lib/settingsStore';
import { resolveProfileToScanRequest } from '@/lib/scanScheduleResolve';

function genId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
}

interface SearchProfilesState {
  profiles: SearchProfile[];
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
      staleScheduleEntryIds: [],
      saveProfile: (name, snapshot) => {
        const now = new Date().toISOString();
        const id = genId();
        set((s) => ({
          profiles: [...s.profiles, { ...snapshot, id, name, createdAt: now, updatedAt: now }],
        }));
        void resyncScheduleEntriesForProfile(id);
        return id;
      },
      updateProfile: (id, snapshot) => {
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
      storage: createJSONStorage(() => {
        if (typeof window === 'undefined') return undefined as unknown as Storage;
        return localStorage;
      }),
      skipHydration: true,
      version: 2,
      migrate: (persistedState, version) => {
        const st = { ...((persistedState ?? {}) as Record<string, unknown>) };
        if (version < 2) {
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
          const profiles = Array.isArray(st.profiles) ? st.profiles : [];
          st.profiles = profiles.map((profile) => {
            if (typeof profile !== 'object' || profile === null) return profile;
            const p = profile as Record<string, unknown>;
            const scanSettings = p.scanSettings;
            if (typeof scanSettings !== 'object' || scanSettings === null) return profile;
            const ss = scanSettings as Record<string, unknown>;
            const spreads = ss.spreads;
            // Stocks profiles carry no `spreads` block at all — leave them be
            // rather than inventing one.
            if (typeof spreads !== 'object' || spreads === null) return profile;
            const sp = spreads as Record<string, unknown>;
            if (sp.ivAbsThreshold !== undefined) return profile;
            return {
              ...p,
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
        return st as unknown as SearchProfilesState;
      },
      partialize: (state) => ({ profiles: state.profiles }),
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
      // Profile can't be resolved yet (e.g. stocks-mode, Step 5 never
      // visited) — nothing valid to push; leave the entry as it is rather
      // than pushing a request that would fail backend validation anyway.
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
