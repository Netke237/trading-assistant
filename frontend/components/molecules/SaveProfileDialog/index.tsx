'use client';

import { useState, useRef } from 'react';
import { Text } from '@/components/primitives';
import styles from './SaveProfileDialog.module.css';

interface Props {
  mode: 'options' | 'stocks';
  onClose: () => void;
  onSave: (name: string) => void;
}

export function SaveProfileDialog({ mode, onClose, onSave }: Props) {
  const [name, setName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  // Tracks whether the mousedown that led to this click also started on the
  // overlay itself — without this, a mousedown inside the input (e.g. to
  // select the text just typed) that drags out and releases over the
  // backdrop would still fire a bubbled click on the overlay and silently
  // discard the in-progress name.
  const mouseDownOnOverlay = useRef(false);

  function handleSave() {
    if (submitting) return;
    const trimmed = name.trim();
    if (!trimmed) return;
    setSubmitting(true);
    onSave(trimmed);
  }

  return (
    <div
      className={styles.overlay}
      onMouseDown={(e) => { mouseDownOnOverlay.current = e.target === e.currentTarget; }}
      onClick={(e) => { if (mouseDownOnOverlay.current && e.target === e.currentTarget) onClose(); }}
      role="dialog"
      aria-modal
      aria-labelledby="save-profile-title"
    >
      <div className={styles.panel}>
        <Text as="div" size={14} weight={600}>
          <span id="save-profile-title">Save search profile</span>
        </Text>
        <Text size={11} tone="dim">
          Universe, filters, direction, horizon, execution parameters, and scan settings.
          {mode === 'stocks' && ' Includes the current strategy + tuning params, if a strategy has been picked this session.'}
        </Text>
        <input
          className={styles.input}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleSave();
            else if (e.key === 'Escape') onClose();
          }}
          placeholder="Profile name"
          autoFocus
        />
        <div className={styles.actions}>
          <button type="button" className={styles.cancelBtn} onClick={onClose}>Cancel</button>
          <button type="button" className={styles.saveBtn} disabled={!name.trim() || submitting} onClick={handleSave}>Save</button>
        </div>
      </div>
    </div>
  );
}
