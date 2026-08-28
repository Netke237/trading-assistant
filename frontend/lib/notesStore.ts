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
  loaded: boolean;
  saving: boolean;
  error: boolean;
}

interface NotesState {
  notes: Record<string, NoteEntry>;
  fetchNote: (symbol: string) => Promise<void>;
  setNoteBody: (symbol: string, body: string) => void;
}

const NOTE_SAVE_DEBOUNCE_MS = 600;
const _pendingSaves = new Map<string, ReturnType<typeof setTimeout>>();

function _save(symbol: string, body: string): void {
  api.putSymbolNote(symbol, body)
    .then(() => {
      useNotesStore.setState((s) => {
        const cur = s.notes[symbol];
        // A newer edit landed while this PUT was in flight — don't clear
        // its `saving` flag, that edit's own debounced save owns it.
        if (!cur || cur.body !== body) return s;
        return { notes: { ...s.notes, [symbol]: { ...cur, saving: false, error: false } } };
      });
    })
    .catch(() => {
      useNotesStore.setState((s) => {
        const cur = s.notes[symbol];
        if (!cur) return s;
        return { notes: { ...s.notes, [symbol]: { ...cur, saving: false, error: true } } };
      });
    });
}

export const useNotesStore = create<NotesState>()((set, get) => ({
  notes: {},

  fetchNote: async (symbolRaw) => {
    const symbol = symbolRaw.trim().toUpperCase();
    if (!symbol || get().notes[symbol]) return;
    try {
      const res = await api.getSymbolNote(symbol);
      set((s) => {
        // The user may have already started typing (setNoteBody creates an
        // entry synchronously) while this fetch was in flight — never let a
        // late GET clobber a local edit.
        if (s.notes[symbol]) return s;
        return { notes: { ...s.notes, [symbol]: { body: res.body, loaded: true, saving: false, error: false } } };
      });
    } catch {
      set((s) => {
        if (s.notes[symbol]) return s;
        return { notes: { ...s.notes, [symbol]: { body: '', loaded: true, saving: false, error: true } } };
      });
    }
  },

  setNoteBody: (symbolRaw, body) => {
    const symbol = symbolRaw.trim().toUpperCase();
    if (!symbol) return;
    set((s) => ({
      notes: { ...s.notes, [symbol]: { body, loaded: true, saving: true, error: false } },
    }));
    const existing = _pendingSaves.get(symbol);
    if (existing) clearTimeout(existing);
    const timer = setTimeout(() => {
      _pendingSaves.delete(symbol);
      _save(symbol, body);
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
  if (entry) _save(sym, entry.body);
}
