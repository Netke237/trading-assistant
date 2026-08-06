'use client';

import { useRef } from 'react';
import { Text } from '@/components/primitives';
import styles from './ConfirmDialog.module.css';

interface Props {
  title: string;
  body?: string;
  confirmLabel?: string;
  onCancel: () => void;
  onConfirm: () => void;
}

export function ConfirmDialog({ title, body, confirmLabel = 'Confirm', onCancel, onConfirm }: Props) {
  const mouseDownOnOverlay = useRef(false);

  return (
    <div
      className={styles.overlay}
      onMouseDown={(e) => { mouseDownOnOverlay.current = e.target === e.currentTarget; }}
      onClick={(e) => { if (mouseDownOnOverlay.current && e.target === e.currentTarget) onCancel(); }}
      role="dialog"
      aria-modal
      aria-labelledby="confirm-dialog-title"
    >
      <div className={styles.dialog}>
        <Text as="div" size={14} weight={600}>
          <span id="confirm-dialog-title">{title}</span>
        </Text>
        {body && <Text size={13} tone="secondary">{body}</Text>}
        <div className={styles.actions}>
          <button type="button" className={styles.cancelBtn} onClick={onCancel}>Cancel</button>
          <button type="button" className={styles.confirmBtn} onClick={onConfirm}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}
