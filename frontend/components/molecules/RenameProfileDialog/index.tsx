'use client';

import { useState } from 'react';
import { Text } from '@/components/primitives';
import styles from './RenameProfileDialog.module.css';

interface Props {
  currentName: string;
  onClose: () => void;
  onSave: (name: string) => void;
}

export function RenameProfileDialog({ currentName, onClose, onSave }: Props) {
  const [name, setName] = useState(currentName);

  function handleSave() {
    const trimmed = name.trim();
    if (trimmed) onSave(trimmed);
  }

  return (
    <div className={styles.overlay} onClick={onClose} role="dialog" aria-modal aria-labelledby="rename-profile-title">
      <div className={styles.panel} onClick={(e) => e.stopPropagation()}>
        <Text size={14} weight={600}>Rename profile</Text>
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
          <button type="button" className={styles.saveBtn} disabled={!name.trim()} onClick={handleSave}>Save</button>
        </div>
      </div>
    </div>
  );
}
