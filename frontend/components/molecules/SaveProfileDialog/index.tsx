'use client';

import { useState } from 'react';
import { Text } from '@/components/primitives';
import styles from './SaveProfileDialog.module.css';

interface Props {
  mode: 'options' | 'stocks';
  onClose: () => void;
  onSave: (name: string) => void;
}

export function SaveProfileDialog({ mode, onClose, onSave }: Props) {
  const [name, setName] = useState('');

  function handleSave() {
    const trimmed = name.trim();
    if (trimmed) onSave(trimmed);
  }

  return (
    <div className={styles.overlay} onClick={onClose} role="dialog" aria-modal aria-labelledby="save-profile-title">
      <div className={styles.panel} onClick={(e) => e.stopPropagation()}>
        <Text size={14} weight={600}>Save search profile</Text>
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
          <button type="button" className={styles.saveBtn} disabled={!name.trim()} onClick={handleSave}>Save</button>
        </div>
      </div>
    </div>
  );
}
