'use client';

import { useEffect, useRef, useState } from 'react';
import { Text, Data } from '@/components/primitives';
import { useAlertStore } from '@/lib/alertStore';
import { useScanStore } from '@/lib/scanStore';
import styles from './index.module.css';

type Tab = 'alerts' | 'events';

interface BellPanelProps {
  open: boolean;
  onClose: () => void;
}

function AlertKindBadge({ kind }: { kind: string }) {
  return (
    <span
      className={`${styles.kindBadge} ${
        kind === 'Critical' ? styles.kindCritical :
        kind === 'Action'   ? styles.kindAction   :
                              styles.kindInfo
      }`}
    >
      {kind}
    </span>
  );
}

function AlertsTab() {
  const toasts = useAlertStore((s) => s.toasts);
  const dismissToast = useAlertStore((s) => s.dismissToast);
  const visible = toasts.filter((t) => !t.dismissed).reverse();

  if (visible.length === 0) {
    return (
      <div className={styles.empty}>
        <Text size={12} tone="dim">No alerts.</Text>
      </div>
    );
  }

  return (
    <ul className={styles.list}>
      {visible.map((t) => (
        <li key={t.id} className={styles.alertItem}>
          <div className={styles.alertTop}>
            <Data size={13} weight={500}>{t.symbol}</Data>
            <AlertKindBadge kind={t.kind} />
            <button
              type="button"
              className={styles.dismissBtn}
              aria-label="Dismiss"
              onClick={() => dismissToast(t.id)}
            >
              ×
            </button>
          </div>
          <Text size={12} tone="secondary">{t.reason}</Text>
        </li>
      ))}
    </ul>
  );
}

function EventsTab() {
  const candidates = useScanStore((s) => s.scanResult?.candidates ?? []);
  const events = candidates
    .filter((c) => c.nextEventDays != null)
    .sort((a, b) => (a.nextEventDays ?? 999) - (b.nextEventDays ?? 999));

  if (events.length === 0) {
    return (
      <div className={styles.empty}>
        <Text size={12} tone="dim">Run a scan to see upcoming events.</Text>
      </div>
    );
  }

  return (
    <ul className={styles.list}>
      {events.map((c) => (
        <li key={c.symbol} className={styles.eventItem}>
          <Data size={13} weight={500}>{c.symbol}</Data>
          <Text size={12} tone="secondary">{c.nextEventLabel}</Text>
          <Data size={12} tone={
            (c.nextEventDays ?? 99) <= 3  ? 'reject' :
            (c.nextEventDays ?? 99) <= 14 ? 'caution' : undefined
          }>
            {c.nextEventDays}d
          </Data>
        </li>
      ))}
    </ul>
  );
}

export function BellPanel({ open, onClose }: BellPanelProps) {
  const [tab, setTab] = useState<Tab>('alerts');
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        onClose();
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div ref={panelRef} className={styles.panel} role="dialog" aria-label="Notifications">
      <div className={styles.tabs}>
        <button
          type="button"
          className={`${styles.tab} ${tab === 'alerts' ? styles.tabActive : ''}`}
          onClick={() => setTab('alerts')}
        >
          Alerts
        </button>
        <button
          type="button"
          className={`${styles.tab} ${tab === 'events' ? styles.tabActive : ''}`}
          onClick={() => setTab('events')}
        >
          Upcoming Events
        </button>
      </div>
      <div className={styles.body}>
        {tab === 'alerts' ? <AlertsTab /> : <EventsTab />}
      </div>
    </div>
  );
}
