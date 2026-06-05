'use client';

import { useState, useRef, useEffect } from 'react';
import { Text } from '@/components/primitives';
import styles from './TextInputPopover.module.css';

interface Props {
  initial?: string;
  onSave: (text: string) => void;
  onCancel: () => void;
}

export default function TextInputPopover({ initial = '', onSave, onCancel }: Props) {
  const [value, setValue] = useState(initial);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSave = () => {
    const trimmed = value.trim();
    if (trimmed) {
      onSave(trimmed);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSave();
    } else if (e.key === 'Escape') {
      onCancel();
    }
  };

  return (
    <div className={styles.pop} role="dialog" aria-label="Enter text">
      <Text size={12} weight={500}>Add text</Text>
      <input
        ref={inputRef}
        autoFocus
        type="text"
        className={styles.input}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Type text..."
      />
      <div className={styles.actions}>
        <button type="button" onClick={onCancel}>Cancel</button>
        <button
          type="button"
          onClick={handleSave}
          disabled={!value.trim()}
          className={styles.btnPrimary}
        >
          Save
        </button>
      </div>
    </div>
  );
}
