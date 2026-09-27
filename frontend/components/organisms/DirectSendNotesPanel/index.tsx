'use client';

/*
 * STOCK-SENDS (plan §A3) — the direct-send notes where the STOCK sends happen
 * (Step 7 position card, Step 4 stocks). Same notes store, text and Remove
 * behaviour as Step 7 options' own rendering, which is unchanged: a note is a
 * fact about one rec_id, and its Remove deletes exactly that row after a confirm.
 */

import { Text } from '@/components/primitives';
import { useDirectSendNotesStore } from '@/lib/directSendNotesStore';
import { directSendNoteText } from '@/lib/directOrder';
import { removeNoteRow } from '@/lib/stockDirectSend';
import styles from './DirectSendNotesPanel.module.css';

export function DirectSendNotesPanel() {
  const notes = useDirectSendNotesStore((s) => s.notes);
  if (notes.length === 0) return null;
  return (
    <div className={styles.list}>
      {notes.map((n) => (
        <div key={n.recId} className={styles.note}>
          <Text size={12} tone="reject">{directSendNoteText(n)}</Text>
          <button
            type="button"
            className={styles.remove}
            onClick={() => { void removeNoteRow(n); }}
            disabled={n.removing}
          >
            {`Remove (${n.label})`}
          </button>
          {n.status && <Text size={11} tone="caution">{n.status}</Text>}
        </div>
      ))}
    </div>
  );
}
