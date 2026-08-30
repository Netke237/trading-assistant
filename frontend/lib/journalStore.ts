/*
 * Journal store — Zustand, NO persist().
 *
 * Deliberately diverges from chartAlertStore.ts's persisted-array-with-merge
 * pattern (see the plan's Full-stack pattern section): journal data has no
 * local-only state to reconcile — the backend is the sole source of truth
 * from the first write — so there's no localStorage key and no merge-on-load.
 * What IS cloned from chartAlertStore is the array-of-records shape and the
 * mutation-action style (optimistic local update + API call).
 *
 * Error handling (this took several audit rounds — follow exactly):
 *  - syncEntries()'s OWN success path unconditionally clears `error` — a
 *    successful list load, from ANY caller (mount, filter-bar change, or a
 *    mutation's own recovery call below), is legitimate evidence that
 *    supersedes a stale error.
 *  - syncEntries()'s OWN failure path sets `error` — covers a filter-triggered
 *    fetch failing on its own, with no mutation involved.
 *  - A failed mutation (createEntry/updateEntry/deleteEntry) rolls back its
 *    optimistic local change, `await`s syncEntries() to reconcile with the
 *    real backend state, and ONLY THEN sets `error` to the mutation-failure
 *    message — after the await, not before. Since syncEntries() always clears
 *    `error` on its own success, setting `error` before awaiting syncEntries()
 *    would have the reconciling call immediately wipe the mutation-failure
 *    message right back out.
 *  - clearError() remains for an explicit user-dismiss of the error banner.
 */

import { create } from 'zustand';
import { api } from '@/lib/api';
import type { JournalEntry, JournalEntryInput, JournalEntryFilters } from '@/types/journal';

interface JournalState {
  entries: JournalEntry[];
  loading: boolean;
  error: string | null;
  /** The filters `syncEntries` was last called with — so a mutation's own
   *  recovery re-sync (see createEntry/updateEntry/deleteEntry) restores the
   *  same filtered view instead of silently resetting the table to the full
   *  unfiltered list at the exact moment an error banner appears. */
  lastFilters: JournalEntryFilters | undefined;

  syncEntries: (filters?: JournalEntryFilters) => Promise<void>;
  createEntry: (input: JournalEntryInput) => Promise<void>;
  /** `entry` is the COMPLETE entry — matches the backend's PUT-full-replace
   *  semantics, not a partial patch, despite the short name. */
  updateEntry: (id: string, entry: JournalEntryInput) => Promise<void>;
  deleteEntry: (id: string) => Promise<void>;
  clearError: () => void;
}

function tempId(): string {
  return 'tmp-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8);
}

function nowIso(): string {
  return new Date().toISOString();
}

function toOptimisticEntry(input: JournalEntryInput, id: string): JournalEntry {
  return {
    ...input,
    id,
    user_id: 'default',
    r_multiple: null,
    created_at: nowIso(),
    updated_at: nowIso(),
  };
}

function errorMessage(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

// Monotonic request counter — NOT store state (it doesn't need to trigger a
// re-render on its own). Two syncEntries() calls can be in flight at once
// (e.g. a slow mutation-recovery resync racing a faster filter-bar change);
// without this, whichever request happens to RESOLVE last wins and can
// silently overwrite fresher results with stale ones. Each call captures the
// id it was assigned before awaiting; only the call that's still the latest
// outstanding request when its promise settles is allowed to apply its
// result (entries or error) to the store.
let latestSyncRequestId = 0;

export const useJournalStore = create<JournalState>((set, get) => ({
  entries: [],
  loading: false,
  error: null,
  lastFilters: undefined,

  syncEntries: async (filters) => {
    const requestId = ++latestSyncRequestId;
    set({ loading: true, lastFilters: filters });
    try {
      const entries = await api.getJournalEntries(filters);
      if (requestId !== latestSyncRequestId) return; // superseded by a newer call
      set({ entries, loading: false, error: null });
    } catch (e) {
      if (requestId !== latestSyncRequestId) return; // superseded by a newer call
      set({ loading: false, error: errorMessage(e, 'Failed to load journal entries') });
    }
  },

  createEntry: async (input) => {
    const id = tempId();
    const optimistic = toOptimisticEntry(input, id);
    set((s) => ({ entries: [optimistic, ...s.entries] }));

    try {
      const created = await api.createJournalEntry(input);
      set((s) => ({ entries: s.entries.map((x) => (x.id === id ? created : x)) }));
    } catch (e) {
      set((s) => ({ entries: s.entries.filter((x) => x.id !== id) }));
      await get().syncEntries(get().lastFilters);
      set({ error: errorMessage(e, 'Failed to create journal entry') });
    }
  },

  updateEntry: async (id, entry) => {
    const prev = get().entries.find((x) => x.id === id);
    const optimistic: JournalEntry = prev
      ? { ...prev, ...entry, id, updated_at: nowIso() }
      : toOptimisticEntry(entry, id);
    set((s) => ({ entries: s.entries.map((x) => (x.id === id ? optimistic : x)) }));

    try {
      const updated = await api.updateJournalEntry(id, entry);
      set((s) => ({ entries: s.entries.map((x) => (x.id === id ? updated : x)) }));
    } catch (e) {
      set((s) => ({ entries: s.entries.map((x) => (x.id === id ? (prev ?? x) : x)) }));
      await get().syncEntries(get().lastFilters);
      set({ error: errorMessage(e, 'Failed to update journal entry') });
    }
  },

  deleteEntry: async (id) => {
    const prev = get().entries.find((x) => x.id === id);
    set((s) => ({ entries: s.entries.filter((x) => x.id !== id) }));

    try {
      await api.deleteJournalEntry(id);
    } catch (e) {
      set((s) => (prev ? { entries: [...s.entries, prev] } : s));
      await get().syncEntries(get().lastFilters);
      set({ error: errorMessage(e, 'Failed to delete journal entry') });
    }
  },

  clearError: () => set({ error: null }),
}));
