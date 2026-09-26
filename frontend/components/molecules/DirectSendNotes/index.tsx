'use client';

/*
 * The persistent notes every save-first broker send leaves behind when a
 * Portfolio row may have no order, or an order's status is unknown (P1b-i;
 * shared with the stock sends by STOCK-SENDS-SAVE-FIRST-THEN-REAL-SHARES).
 * Reads the module-level store itself, so every surface that renders it shows
 * every note -- each carries its own label and rec_id.
 *
 * Remove (P1B1-MINIMAL-REMOVE-2026-09-25): confirm, then hard-DELETE exactly
 * that note's rec_id -- never "the ${label} position".
 */

import { Text } from '@/components/primitives';
import { useDirectSendNotesStore, type DirectSendNote } from '@/lib/directSendNotesStore';
import {
  directSendNoteText, isNotFound, removeConfirmText, removeTrackedRow, whyOf,
} from '@/lib/directOrder';
import styles from './DirectSendNotes.module.css';

async function removeNoteRow(note: DirectSendNote): Promise<void> {
  if (note.removing) return;
  if (!window.confirm(removeConfirmText(note))) return;
  const { patchNote, removeNote } = useDirectSendNotesStore.getState();
  patchNote(note.recId, { removing: true, status: null });
  try {
    // A 404 is final only when the server had already answered this send's
    // save before the note existed (ORDER-UNKNOWN, NOT-REMOVED). On
    // SAVE-UNCONFIRMED the create may still be in flight, so it is not.
    await removeTrackedRow(note.recId, note.kind !== 'save-unconfirmed');
    removeNote(note.recId);
  } catch (e) {
    patchNote(note.recId, {
      removing: false,
      status: note.kind === 'save-unconfirmed' && isNotFound(e)
        ? 'Not found yet — the save may still be finishing. Press Remove again in a few seconds.'
        : `Remove failed: ${whyOf(e)}. Try again.`,
    });
  }
}

export function DirectSendNotes() {
  const notes = useDirectSendNotesStore((s) => s.notes);
  if (notes.length === 0) return null;
  return (
    <>
      {notes.map((n) => (
        <div key={`direct:${n.recId}`} className={styles.directNote}>
          <Text size={12} tone="reject">{directSendNoteText(n)}</Text>
          <button
            type="button"
            className={styles.directNoteRemove}
            onClick={() => { void removeNoteRow(n); }}
            disabled={n.removing}
          >
            {`Remove (${n.label})`}
          </button>
          {n.status && <Text size={11} tone="caution">{n.status}</Text>}
        </div>
      ))}
    </>
  );
}
