'use client';

import { useCallback } from 'react';
import Link from 'next/link';
import { Title, Text, Data } from '@/components/primitives';
import { useAlertStore, DEFAULT_CONFIG } from '@/lib/alertStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useScanStore } from '@/lib/scanStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import type { AlertType, ToastItem } from '@/types/domain';
import styles from './page.module.css';

/* ─── helpers ─── */

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60_000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

const ALERT_TYPE_LABELS: Record<AlertType, string> = {
  TP_HIT:                 'Target reached',
  STOP_REACHED:           'Stop-loss breach',
  PREMIUM_STOP:           'Premium stop (–40%)',
  TIME_STOP_APPROACHING:  'Time stop approaching',
  TIME_STOP:              'Time stop (≤3 DTE)',
  EARNINGS_APPROACHING:   'Earnings within 3 days',
  EVENT_RISK:             'Event risk (≤3 days)',
  EXPIRATION_APPROACHING: 'Expiration within 3 days',
  REGIME_CHANGE:          'Regime flip',
  SCAN_COMPLETE:          'Scan complete',
  SCAN_FAILED:            'Scan failed',
};

/* ─── Alert row ─── */

function AlertRow({ toast }: { toast: ToastItem }) {
  const { acknowledgeAlert, deleteAlert } = useAlertStore();
  return (
    <div className={[styles.alertRow, toast.acknowledged ? styles.alertRowAck : ''].join(' ')}>
      <div className={styles.alertMeta}>
        <Data size={12} weight={500}>{toast.symbol}</Data>
        <span className={styles.alertKind} data-kind={toast.kind}>{toast.kind}</span>
        <Text size={11} tone="secondary">{ALERT_TYPE_LABELS[toast.alertType] ?? toast.alertType}</Text>
      </div>
      <Text size={12}>{toast.reason}</Text>
      <div className={styles.alertFooter}>
        <span title={fmtDate(toast.firedAt)}><Text size={11} tone="dim">{timeAgo(toast.firedAt)}</Text></span>
        {toast.acknowledged ? (
          <span className={styles.ackBadge}>Acknowledged</span>
        ) : (
          <button
            type="button"
            className={styles.btnAck}
            onClick={() => acknowledgeAlert(toast.id)}
          >
            Acknowledge
          </button>
        )}
        <button
          type="button"
          className={styles.btnDelete}
          onClick={() => deleteAlert(toast.id)}
          aria-label="Delete alert"
        >
          ×
        </button>
      </div>
    </div>
  );
}

/* ─── Toggle helper ─── */

function Toggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      className={[styles.toggle, on ? styles.toggleOn : ''].join(' ')}
      onClick={() => onChange(!on)}
    />
  );
}

/* ─── Main page ─── */

export default function AlertsPage() {
  const { toasts, config, setConfig, clearAll, clearOldAlerts, acknowledgeAlert } = useAlertStore();
  const { ivPassThreshold, ivCautionThreshold, setIvPassThreshold, setIvCautionThreshold } = useSettingsStore();

  const candidates = useScanStore((s) => s.scanResult?.candidates) ?? [];
  const portfolioPositions = usePortfolioStore((s) => s.positions);
  const watchlistSymbols = useWatchlistStore((s) => s.added);

  const mySymbols = new Set([...portfolioPositions.map((p) => p.symbol), ...watchlistSymbols]);
  const upcomingEvents = candidates
    .filter((c) => mySymbols.has(c.symbol) && c.nextEventDays != null && (c.nextEventDays ?? 999) <= 30)
    .sort((a, b) => (a.nextEventDays ?? 999) - (b.nextEventDays ?? 999));

  const sorted = [...toasts].sort(
    (a, b) => new Date(b.firedAt).getTime() - new Date(a.firedAt).getTime(),
  );
  const unacknowledgedCount = toasts.filter((t) => !t.acknowledged).length;

  const toggleType = useCallback((type: AlertType, on: boolean) => {
    const next = on
      ? [...config.enabledTypes, type]
      : config.enabledTypes.filter((t) => t !== type);
    setConfig({ ...config, enabledTypes: next });
  }, [config, setConfig]);

  function ackAll() {
    toasts.filter((t) => !t.acknowledged).forEach((t) => acknowledgeAlert(t.id));
  }

  return (
    <div className={styles.page}>
      {/* ── Header ── */}
      <div className={styles.pageHeader}>
        <Title as="h1" size={24}>Alerts</Title>
        {unacknowledgedCount > 0 && (
          <Text size={12} tone="secondary">{unacknowledgedCount} unacknowledged</Text>
        )}
        <div className={styles.headerActions}>
          {unacknowledgedCount > 0 && (
            <button type="button" className={styles.btnSecondary} onClick={ackAll}>
              Acknowledge all
            </button>
          )}
          {toasts.length > 0 && (
            <button type="button" className={styles.btnSecondary} onClick={clearAll}>
              Clear all
            </button>
          )}
        </div>
      </div>

      {/* ── Alert history ── */}
      <section className={styles.section}>
        <Text size={11} tone="secondary" weight={600}>Alert History</Text>
        {sorted.length === 0 ? (
          <div className={styles.empty}>
            <Text size={13} tone="secondary">No alerts yet.</Text>
          </div>
        ) : (
          <div className={styles.alertList}>
            {sorted.map((t) => <AlertRow key={t.id} toast={t} />)}
          </div>
        )}
      </section>

      {/* ── Upcoming Events ── */}
      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <Text size={11} tone="secondary" weight={600}>Upcoming Events</Text>
          <Text size={11} tone="dim">Portfolio + watchlist · ≤ 30d · beyond 30d shown in{' '}
            <Link href="/calendar" className={styles.link}>Calendar</Link>
          </Text>
        </div>
        {upcomingEvents.length === 0 ? (
          <div className={styles.empty}>
            <Text size={13} tone="secondary">
              {candidates.length === 0
                ? 'Run a scan to see upcoming events.'
                : 'No events within 30 days for your portfolio + watchlist.'}
            </Text>
          </div>
        ) : (
          <div className={styles.eventList}>
            {upcomingEvents.map((c) => (
              <div key={c.symbol} className={styles.eventRow}>
                <Data size={12} weight={500}>{c.symbol}</Data>
                <Text size={12}>{c.nextEventLabel ?? 'Earnings'}</Text>
                <Data
                  size={12}
                  tone={
                    (c.nextEventDays ?? 999) <= 3 ? 'reject'
                    : (c.nextEventDays ?? 999) <= 14 ? 'caution'
                    : undefined
                  }
                >
                  {c.nextEventDays}d
                </Data>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── Alert Settings ── */}
      <section className={styles.section}>
        <Text size={11} tone="secondary" weight={600}>Alert Settings</Text>
        <Text size={12} tone="secondary">In-app alerts only. Email / push arrive in Phase 8.</Text>

        <div className={styles.settingsGrid}>
          <SettingsRow label="Keep alerts for (days)" hint="Alerts older than this are auto-purged." defaultValue="10">
            <input
              type="number"
              className={styles.input}
              min={1}
              max={365}
              value={config.keepAlertsDays}
              onChange={(e) => {
                const val = Number(e.target.value);
                if (val >= 1 && val <= 365) {
                  setConfig({ ...config, keepAlertsDays: val });
                  clearOldAlerts();
                }
              }}
            />
          </SettingsRow>
          <SettingsRow label="Deduplication window (min)" hint="Minutes before the same alert can fire again." defaultValue="15">
            <input
              type="number"
              className={styles.input}
              min={1}
              max={120}
              value={config.dedupWindowMinutes}
              onChange={(e) => {
                const val = Number(e.target.value);
                if (val >= 1 && val <= 120) setConfig({ ...config, dedupWindowMinutes: val });
              }}
            />
          </SettingsRow>
          <SettingsRow label="Sound" hint="Play a short tone when a new alert fires." defaultValue="Off">
            <Toggle on={config.soundEnabled} onChange={(on) => setConfig({ ...config, soundEnabled: on })} />
          </SettingsRow>
          <SettingsRow label="IV Pass Threshold" hint="IV rank above this is considered PASS." defaultValue="34">
            <input
              type="number"
              className={styles.input}
              min={1}
              max={100}
              value={ivPassThreshold}
              onChange={(e) => {
                const val = Number(e.target.value);
                if (val >= 1 && val <= 100) setIvPassThreshold(val);
              }}
            />
          </SettingsRow>
          <SettingsRow label="IV Caution Threshold" hint="IV rank above this (but below Pass) is CAUTION." defaultValue="55">
            <input
              type="number"
              className={styles.input}
              min={1}
              max={100}
              value={ivCautionThreshold}
              onChange={(e) => {
                const val = Number(e.target.value);
                if (val >= 1 && val <= 100) setIvCautionThreshold(val);
              }}
            />
          </SettingsRow>

          <div className={styles.divider} />
          <Text size={12} tone="secondary">Alert types</Text>
          {(Object.keys(ALERT_TYPE_LABELS) as AlertType[]).map((type) => (
            <SettingsRow
              key={type}
              label={ALERT_TYPE_LABELS[type]}
              defaultValue={DEFAULT_CONFIG.enabledTypes.includes(type) ? 'On' : 'Off'}
            >
              <Toggle
                on={config.enabledTypes.includes(type)}
                onChange={(on) => toggleType(type, on)}
              />
            </SettingsRow>
          ))}
        </div>
      </section>
    </div>
  );
}

function SettingsRow({
  label, hint, defaultValue, children,
}: {
  label: string;
  hint?: string;
  defaultValue?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={styles.settingsRow}>
      <div className={styles.settingsLabel}>
        <Text size={13} weight={400}>{label}</Text>
        {hint && <Text size={11} tone="secondary">{hint}</Text>}
        {defaultValue !== undefined && (
          <span className={styles.defaultTag}>Default: {defaultValue}</span>
        )}
      </div>
      <div className={styles.settingsControl}>{children}</div>
    </div>
  );
}
