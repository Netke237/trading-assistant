'use client';
import { useEffect } from 'react';
import { useChartAlertStore } from '@/lib/chartAlertStore';
import { Text } from '@/components/primitives';
import styles from './AlertToast.module.css';

export default function AlertToast() {
  const toasts = useChartAlertStore((s) => s.toasts);
  const dismissToast = useChartAlertStore((s) => s.dismissToast);

  return (
    <div className={styles.container} aria-live="polite" aria-label="Notifications">
      {toasts.map((t) => (
        <ToastItem
          key={t.id}
          id={t.id}
          message={t.message}
          timestamp={t.timestamp}
          onDismiss={dismissToast}
        />
      ))}
    </div>
  );
}

function ToastItem({
  id,
  message,
  timestamp,
  onDismiss,
}: {
  id: string;
  message: string;
  timestamp: number;
  onDismiss: (id: string) => void;
}) {
  useEffect(() => {
    const timer = setTimeout(() => onDismiss(id), 5000);
    return () => clearTimeout(timer);
  }, [id, onDismiss]);

  return (
    <div className={styles.toast}>
      <div className={styles.toastText}>
        <Text size={12} tone="primary">{message}</Text>
        <Text size={10} tone="dim">{new Date(timestamp).toLocaleTimeString()}</Text>
      </div>
      <button type="button" className={styles.toastClose} onClick={() => onDismiss(id)} aria-label="Dismiss notification">&times;</button>
    </div>
  );
}
