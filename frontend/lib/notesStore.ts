/*
 * Notes store — one overwritable free-text note per symbol, backend-synced
 * (not localStorage). Shared between the Chart sidebar, the Portfolio
 * EditDrawer, and the Portfolio page's own sidebar — all three read/write
 * the same record via this store, so an edit made in one place is visible
 * in the others without a page refresh.
 *
 * Edits are applied to local state immediately (so typing feels instant)
 * and persisted to the backend on a 600ms debounce, mirroring
 * portfolioStore.ts's scheduleRemotePositionPatch/flushPendingPositionPatches
 * pattern — a module-level Map of timers, not Zustand state, since timers
 * aren't serializable.
 */

import { create } from 'zustand';
import { api } from '@/lib/api';

export interface NoteEntry {
  body: string;
  /** True once this entry holds a confirmed value — either a successful GET,
   *  or a local edit the user has made since. SymbolNotes refuses to render
   *  an editable textarea until this is true, specifically so a failed GET
   *  can never be mistaken for "no note exists yet" and silently overwritten
   *  by a fresh (actually blank) edit. */
  loaded: boolean;
  saving: boolean;
  /** Most recent save attempt failed. */
  error: boolean;
  /** Most recent load attempt failed and no confirmed value is held yet. */
  loadError: boolean;
}

interface NotesState {
  notes: Record<string, NoteEntry>;
  fetchNote: (symbol: string) => Promise<void>;
  setNoteBody: (symbol: string, body: string) => void;
}

const NOTE_SAVE_DEBOUNCE_MS = 600;
const _pendingSaves = new Map<string, ReturnType<typeof setTimeout>>();
// Dedupes concurrent fetchNote calls for the same symbol (e.g. two surfaces
// mounting for the same symbol in the same tick) — without this, both would
// fire their own GET.
const _inFlightFetches = new Set<string>();
// Per-symbol edit counter. Each setNoteBody call bumps it and captures the
// resulting value as that edit's "generation" — the identity a save result
// is checked against, instead of comparing saved body text. Text equality
// alone misses the case where the user types away and back to the exact
// same content: two different edits with identical bodies would look like
// "the same edit" to a body comparison, so a stale failure for the first
// one could still stamp `error: true` onto the second one's already-saved,
// textually-identical content. A monotonic id has no such collision.
const _generations = new Map<string, number>();

function _save(symbol: string, body: string, gen: number): void {
  api.putSymbolNote(symbol, body)
    .then(() => {
      useNotesStore.setState((s) => {
        const cur = s.notes[symbol];
        // A newer edit landed while this PUT was in flight — don't clear
        // its `saving` flag, that edit's own debounced save owns it.
        if (!cur || _generations.get(symbol) !== gen) return s;
        return { notes: { ...s.notes, [symbol]: { ...cur, saving: false, error: false } } };
      });
    })
    .catch(() => {
      useNotesStore.setState((s) => {
        const cur = s.notes[symbol];
        // Same staleness check as the success path — if a newer edit already
        // landed (and its own save already succeeded or is in flight), this
        // stale failure must not stamp an `error` onto content that is, as
        // far as the user can tell, already saved.
        if (!cur || _generations.get(symbol) !== gen) return s;
        return { notes: { ...s.notes, [symbol]: { ...cur, saving: false, error: true } } };
      });
    });
}

export const useNotesStore = create<NotesState>()((set, get) => ({
  notes: {},

  fetchNote: async (symbolRaw) => {
    const symbol = symbolRaw.trim().toUpperCase();
    if (!symbol) return;
    // Already have a confirmed value (a prior successful GET, or the user
    // has since typed something) — nothing to fetch. Deliberately NOT keyed
    // on "does an entry exist at all": a failed load also leaves an entry
    // behind (loaded: false, loadError: true) precisely so this guard lets
    // a retry — the next mount, or an explicit re-call — go through instead
    // of permanently caching the failure.
    if (get().notes[symbol]?.loaded) return;
    if (_inFlightFetches.has(symbol)) return;
    _inFlightFetches.add(symbol);
    try {
      const res = await api.getSymbolNote(symbol);
      set((s) => {
        // The user may have already started typing (setNoteBody sets
        // loaded: true synchronously) while this fetch was in flight —
        // never let a late GET clobber a local edit.
        if (s.notes[symbol]?.loaded) return s;
        return { notes: { ...s.notes, [symbol]: { body: res.body, loaded: true, saving: false, error: false, loadError: false } } };
      });
    } catch {
      set((s) => {
        if (s.notes[symbol]?.loaded) return s;
        return { notes: { ...s.notes, [symbol]: { body: '', loaded: false, saving: false, error: false, loadError: true } } };
      });
    } finally {
      _inFlightFetches.delete(symbol);
    }
  },

  setNoteBody: (symbolRaw, body) => {
    const symbol = symbolRaw.trim().toUpperCase();
    if (!symbol) return;
    const gen = (_generations.get(symbol) ?? 0) + 1;
    _generations.set(symbol, gen);
    set((s) => ({
      notes: { ...s.notes, [symbol]: { body, loaded: true, saving: true, error: false, loadError: false } },
    }));
    const existing = _pendingSaves.get(symbol);
    if (existing) clearTimeout(existing);
    const timer = setTimeout(() => {
      _pendingSaves.delete(symbol);
      _save(symbol, body, gen);
    }, NOTE_SAVE_DEBOUNCE_MS);
    _pendingSaves.set(symbol, timer);
  },
}));

/** Sends a pending debounced note save immediately instead of waiting out
 *  the debounce window — call when a component holding the textarea is
 *  about to unmount (drawer close, page navigation), so a fast edit-then-
 *  leave is never silently dropped. */
export function flushPendingNoteSave(symbol: string): void {
  const sym = symbol.trim().toUpperCase();
  const timer = _pendingSaves.get(sym);
  if (!timer) return;
  clearTimeout(timer);
  _pendingSaves.delete(sym);
  const entry = useNotesStore.getState().notes[sym];
  // The pending timer's body is always this symbol's most recent edit, so
  // its generation is simply the current counter value — the same one
  // setNoteBody just stamped when it (re)armed this timer.
  if (entry) _save(sym, entry.body, _generations.get(sym) ?? 0);
}
