import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { SearchProfile, SearchProfileSnapshot } from '@/types/searchProfile';
import { api } from '@/lib/api';
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
      version: 1,
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
