/*
 * SymbolNotes — inline, autosaving free-text note for a symbol. Shared
 * across the Chart sidebar, the Portfolio EditDrawer, and the Portfolio
 * page's own sidebar; all three read/write the same backend-synced record
 * via notesStore.
 *
 * `editable` gates whether the textarea renders at all — the note record
 * itself is independent of watchlist/portfolio membership (it's never
 * deleted when a symbol is unstarred or a position closed), but editing is
 * only offered while the symbol is watchlisted or held.
 */

'use client';

import { useEffect } from 'react';
import { Text } from '@/components/primitives';
import { useNotesStore, flushPendingNoteSave } from '@/lib/notesStore';
import styles from './SymbolNotes.module.css';

export function SymbolNotes({ symbol, editable }: { symbol: string; editable: boolean }) {
  const sym = symbol.trim().toUpperCase();
  const note = useNotesStore((s) => s.notes[sym]);
  const fetchNote = useNotesStore((s) => s.fetchNote);
  const setNoteBody = useNotesStore((s) => s.setNoteBody);

  // Gated on `editable` too — a not-editable symbol only ever shows the
  // gating placeholder, so fetching its note would be a wasted request. If
  // the symbol becomes editable later without remounting (e.g. the user
  // stars it while this component stays mounted), the dependency on
  // `editable` re-fires this effect and fetches it then.
  useEffect(() => {
    if (sym && editable) fetchNote(sym);
  }, [sym, editable, fetchNote]);

  // Flush a still-debounced edit on unmount (drawer close, page nav) so a
  // fast edit-then-leave is never silently dropped.
  useEffect(() => {
    return () => { if (sym) flushPendingNoteSave(sym); };
  }, [sym]);

  if (!editable) {
    return (
      <div className={styles.placeholder}>
        <Text size={11} tone="dim">Star this symbol or open a position to add a note.</Text>
      </div>
    );
  }

  // A failed load must never fall through to a blank, editable textarea —
  // that would look exactly like "no note exists yet" and a save while in
  // this state would silently overwrite whatever note actually exists on
  // the backend. Block editing until a load actually succeeds.
  if (note?.loadError && !note.loaded) {
    return (
      <div className={styles.placeholder}>
        <Text size={11} tone="reject">Couldn&apos;t load this note.</Text>
        <button type="button" className={styles.retryBtn} onClick={() => fetchNote(sym)}>
          <Text size={11} weight={500}>Retry</Text>
        </button>
      </div>
    );
  }

  return (
    <div className={styles.wrap}>
      <textarea
        className={styles.textarea}
        placeholder="Add a note…"
        value={note?.body ?? ''}
        onChange={(e) => setNoteBody(sym, e.target.value)}
        aria-label={`Note for ${sym}`}
      />
      <div className={styles.statusRow}>
        {note?.saving && <Text size={10} tone="dim">Saving…</Text>}
        {note?.error && <Text size={10} tone="reject">Couldn&apos;t save — will retry on next edit.</Text>}
      </div>
    </div>
  );
}
