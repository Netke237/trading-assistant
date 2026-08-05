'use client';

import { useState, useRef } from 'react';
import { Text } from '@/components/primitives';
import styles from './RenameProfileDialog.module.css';

interface Props {
  currentName: string;
  onClose: () => void;
  onSave: (name: string) => void;
}

export function RenameProfileDialog({ currentName, onClose, onSave }: Props) {
  const [name, setName] = useState(currentName);
  const [submitting, setSubmitting] = useState(false);
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
      aria-labelledby="rename-profile-title"
    >
      <div className={styles.panel}>
        <Text as="div" size={14} weight={600}>
          <span id="rename-profile-title">Rename profile</span>
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
