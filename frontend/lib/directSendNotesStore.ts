/*
 * P1b-i — the persistent notes Step 7's direct sends leave behind when a
 * Portfolio row may have no order behind it, or an order's status is unknown.
 *
 * NO `persist()`, deliberately (decision P1B1-NOTE-IN-MEMORY-2026-09-25): the
 * notes survive Prev/Next, basket sends, new sends and leaving Step 7, and go
 * only on a full reload. A module-level store is what gives them that lifetime:
 * page `useState` would die on unmount. Each note carries its own rec_id, and
 * its Remove button deletes exactly that row (P1B1-MINIMAL-REMOVE-2026-09-25).
 * There is no dismiss: a note leaves only when its row is provably gone.
 */

import { create } from 'zustand';

export type DirectSendNoteKind = 'order-unknown' | 'save-unconfirmed' | 'not-removed';

export interface DirectSendNote {
  recId: string;
  kind: DirectSendNoteKind;
  label: string;
  brokerLabel: string;
  orderId: string | null;
  /** The Remove button's last outcome, shown under the note. */
  status: string | null;
  removing: boolean;
}

interface DirectSendNotesState {
  notes: DirectSendNote[];
  /** Dedup by recId: a later push for the same recId replaces it in place. */
  addNote: (n: Omit<DirectSendNote, 'status' | 'removing'>) => void;
  patchNote: (recId: string, partial: Partial<Pick<DirectSendNote, 'status' | 'removing'>>) => void;
  removeNote: (recId: string) => void;
}

export const useDirectSendNotesStore = create<DirectSendNotesState>()((set) => ({
  notes: [],
  addNote: (n) => set((s) => {
    const note: DirectSendNote = { ...n, status: null, removing: false };
    const i = s.notes.findIndex((x) => x.recId === n.recId);
    if (i < 0) return { notes: [...s.notes, note] };
    const notes = s.notes.slice();
    notes[i] = note;
    return { notes };
  }),
  patchNote: (recId, partial) => set((s) => ({
    notes: s.notes.map((x) => (x.recId === recId ? { ...x, ...partial } : x)),
  })),
  removeNote: (recId) => set((s) => ({ notes: s.notes.filter((x) => x.recId !== recId) })),
}));
