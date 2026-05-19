'use client';

import { useMemo } from 'react';
import { useAlertStore } from '@/lib/alertStore';
import { Toast } from '@/components/molecules/Toast';
import styles from './ToastContainer.module.css';

export function ToastContainer() {
  const visibleToasts = useAlertStore((s) => s.visibleToasts);
  const recentToasts = useMemo(() => visibleToasts.slice(-3), [visibleToasts]);
  const dismissToast = useAlertStore((s) => s.dismissToast);

  if (recentToasts.length === 0) return null;

  return (
    <div className={styles.container} role="region" aria-live="polite" aria-label="Notifications">
      {recentToasts.map((t) => (
        <Toast key={t.id} item={t} onDismiss={dismissToast} />
      ))}
    </div>
  );
}
