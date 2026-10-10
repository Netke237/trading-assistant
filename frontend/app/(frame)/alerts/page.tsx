'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { Title, Text, Data } from '@/components/primitives';
import { useAlertStore, DEFAULT_CONFIG } from '@/lib/alertStore';
import { useScanStore } from '@/lib/scanStore';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useWatchlistStore } from '@/lib/watchlistStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { useChartAlertStore } from '@/lib/chartAlertStore';
import AlertRuleBuilder from '@/components/organisms/AlertRuleBuilder';
import { api, type CompositeWatch } from '@/lib/api';
import { compositeWatchSummary } from '@/lib/compositeWatchSummary';
import { resolvePremiumStopPct, premiumStopPctLabel } from '@/lib/premiumStop';
import type { AlertType, ToastItem } from '@/types/domain';
import type { AlertRule, Condition } from '@/types/alerts';
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
  STRUCTURAL_STOP_BREACHED: 'Structural stop breach',
  // Names the TYPE, which covers options and both stock sides
  // (STOP-SEMANTICS-2026-10-02); a fired row is labelled by its stamped side.
  PREMIUM_STOP:           'Premium / stock stop',
  TIME_STOP_APPROACHING:  'Time stop approaching',
  TIME_STOP:              'Time stop (≤3 DTE / hold reached)',
  EARNINGS_APPROACHING:   'Earnings within 3 days',
  EVENT_RISK:             'Event risk (≤3 days)',
  EXPIRATION_APPROACHING: 'Expiration within 3 days',
  REGIME_CHANGE:          'Regime flip',
  SCAN_COMPLETE:          'Scan complete',
  SCAN_FAILED:            'Scan failed',
};

// PREMIUM_STOP's percentage is user-configurable (settingsStore.premiumStopPct) — never
// hardcode it in the static label map above, or it will drift out of sync with the real value.
//
// Since piece 4 the global is not the whole answer either: a position can carry
// its own premium_stop_pct, and this label is the ONLY percentage on screen for
// a fired alert — neither `reason` string carries a threshold
// (alertEngine.ts, alert_generator.py). A row printing "Premium stop (–60%)"
// for a position pinned at 30% is the drift this comment warns about, one level
// down. Callers pass the percentage RESOLVED FOR THAT POSITION AS IT STANDS
// NOW; the settings list below passes the global, because that row IS the
// global.
//
// "as it stands now" WAS the defect, and is now only the FALLBACK
// (ALERT-THRESHOLD-STAMP-2026-09-05). The threshold is stamped on the toast at
// fire time, so a row reports the fraction that actually fired and editing a
// position's stop afterwards no longer relabels its history. Live resolution
// survives for rows persisted before the field existed: they carry no stamp,
// and what the position resolves to now is the best answer available for a row
// that was never stamped.
//
// Trimmed to two decimals via the shared helper, NOT Math.round -- see
// premiumStopPctLabel.
//
// `side` (STOP-SEMANTICS-2026-10-02) is the row's STAMPED `stopSide`: a short
// stock's stop fires on a RISE, so it reads "+X%". An UNSTAMPED row -- every
// row from before the stamp, which fired under the old fall-side rule, shorts
// included -- keeps the legacy "Premium stop (–X%)": that wording is what
// actually happened. It never falls back to the position's current contract
// or direction. 'type' is the Alert-types toggle list, which names the type
// for every side at once.
function alertTypeLabel(
  type: AlertType,
  premiumStopPct: number,
  side: ToastItem['stopSide'] | 'type',
): string {
  if (type === 'PREMIUM_STOP') {
    const pct = premiumStopPctLabel(premiumStopPct);
    if (side === 'type') return `Premium / stock stop (±${pct})`;
    if (side === 'short-stock') return `Stock stop (+${pct})`;
    if (side === 'long-stock') return `Stock stop (–${pct})`;
    return `Premium stop (–${pct})`;
  }
  return ALERT_TYPE_LABELS[type] ?? type;
}

/** The fraction to LABEL a fired alert with: the one it fired at when the row
 *  carries a stamp, otherwise the position's current resolution.
 *
 *  `!= null` (loose), not `??` on a falsy test and not truthiness: 0 is not a
 *  reachable stamp today (PREMIUM_STOP_MIN_PCT is 0.10, and the engine only
 *  fires on `currentPrice > 0`) but it is a real fraction, and a label that
 *  silently fell back to the live value for it would be the same class of
 *  misreport this stamp exists to end. */
function labelPremiumStopPct(
  stamped: number | null | undefined,
  liveResolved: number,
): number {
  return stamped != null ? stamped : liveResolved;
}

/* ─── Alert row ─── */

function AlertRow({ toast }: { toast: ToastItem }) {
  const { acknowledgeAlert, deleteAlert } = useAlertStore();
  const globalPremiumStopPct = useSettingsStore((s) => s.premiumStopPct);
  // Resolved for THIS position, through the same helper the alert engine and
  // the backend generator use. A position that no longer exists (closed, or
  // an alert older than the portfolio) resolves to the global, which is what
  // it would have inherited anyway.
  const position = usePortfolioStore((s) => s.positions.find((p) => p.recId === toast.recId));
  const premiumStopPct = labelPremiumStopPct(
    toast.premiumStopPct,
    resolvePremiumStopPct(position?.premiumStopPct, globalPremiumStopPct),
  );
  return (
    <div className={[styles.alertRow, toast.acknowledged ? styles.alertRowAck : ''].join(' ')}>
      <div className={styles.alertMeta}>
        <Data size={12} weight={500}>{toast.symbol}</Data>
        <span className={styles.alertKind} data-kind={toast.kind}>{toast.kind}</span>
        <Text size={11} tone="secondary">{alertTypeLabel(toast.alertType, premiumStopPct, toast.stopSide)}</Text>
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

/* ─── conditions summary ─── */

function conditionText(cond: Condition): string {
  if (cond.kind === 'price') return `Price ${cond.operator} ${cond.value}`;
  if (cond.kind === 'indicator') return `${cond.indicator} ${cond.operator} ${cond.value}`;
  if (cond.kind === 'regime') {
    const modelPart = cond.model === 'any' ? '' : `${cond.model} `;
    const convPart = cond.min_conviction != null ? ` (conv≥${cond.min_conviction}%)` : '';
    return `Regime ${modelPart}state = ${cond.state}${convPart}`.trim();
  }
  // structure
  let text = cond.signal_kind;
  if (cond.direction) text += ` ${cond.direction}`;
  if (cond.min_confidence != null) text += ` (${cond.min_confidence}%)`;
  return text;
}

function conditionsSummary(rule: AlertRule): string {
  if (rule.rule_type === 'composite' && rule.composite_def) {
    return `Composite — ${compositeWatchSummary(rule.composite_def)}`;
  }
  return rule.group.conditions.map(conditionText).join(` ${rule.group.logic} `);
}

/* ─── Main page ─── */

export default function AlertsPage() {
  const { toasts, config, setConfig, clearAll, clearOldAlerts, acknowledgeAlert, testSound } = useAlertStore();
  const { rules, setRuleEnabled, deleteRule, unsavedRules } = useChartAlertStore();
  const premiumStopPct = useSettingsStore((s) => s.premiumStopPct);

  const [tab, setTab] = useState<'alerts' | 'rules' | 'watches'>('alerts');
  const [showRuleBuilder, setShowRuleBuilder] = useState(false);
  const [editingRule, setEditingRule] = useState<AlertRule | null>(null);
  const [duplicatingRule, setDuplicatingRule] = useState<AlertRule | null>(null);
  const [watches, setWatches] = useState<CompositeWatch[]>([]);
  const [watchesLoaded, setWatchesLoaded] = useState(false);

  const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
  const deliverySyncTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const deliveryLoaded = useRef(false);

  // Load delivery prefs from backend on mount and merge into store
  useEffect(() => {
    fetch(`${BASE_URL}/settings/alert-delivery`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data) {
          setConfig({
            ...config,
            enabledTypes: data.enabledTypes ?? config.enabledTypes,
            dedupWindowMinutes: data.dedupWindowMinutes ?? config.dedupWindowMinutes,
            reminderIntervalHours: data.reminderIntervalHours ?? config.reminderIntervalHours,
            checkIntervalSeconds: data.checkIntervalSeconds ?? config.checkIntervalSeconds,
            retentionDays: data.retentionDays ?? config.retentionDays,
            // No UI control yet (deferred) — still round-tripped so this page's
            // save effect doesn't clobber a value set through another path.
            positionSustainMinutes: data.positionSustainMinutes ?? config.positionSustainMinutes,
            positionAlertRetentionDays: data.positionAlertRetentionDays ?? config.positionAlertRetentionDays,
          });
        }
        deliveryLoaded.current = true;
      })
      .catch(() => { deliveryLoaded.current = true; });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [BASE_URL]);

  // Debounced save of delivery-relevant prefs to backend
  useEffect(() => {
    if (!deliveryLoaded.current) return;
    if (deliverySyncTimer.current) clearTimeout(deliverySyncTimer.current);
    deliverySyncTimer.current = setTimeout(() => {
      fetch(`${BASE_URL}/settings/alert-delivery`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          masterEnabled: true,
          enabledTypes: config.enabledTypes,
          dedupWindowMinutes: config.dedupWindowMinutes,
          reminderIntervalHours: config.reminderIntervalHours,
          checkIntervalSeconds: config.checkIntervalSeconds,
          retentionDays: config.retentionDays,
          positionSustainMinutes: config.positionSustainMinutes,
          positionAlertRetentionDays: config.positionAlertRetentionDays,
        }),
      }).catch(() => {});
    }, 800);
    return () => {
      if (deliverySyncTimer.current) clearTimeout(deliverySyncTimer.current);
    };
  }, [BASE_URL, config.enabledTypes, config.dedupWindowMinutes, config.reminderIntervalHours, config.checkIntervalSeconds, config.retentionDays, config.positionSustainMinutes, config.positionAlertRetentionDays]);

  const loadWatches = useCallback(() => {
    api.listCompositeWatches()
      .then((w) => { setWatches(w); setWatchesLoaded(true); })
      .catch(() => setWatchesLoaded(true));
  }, []);

  // A4f-rules: this table reads the persisted (localStorage) rules. Refresh from the
  // backend on mount so a rule the backend migrated (e.g. '1D' -> '5m') is not shown
  // stale. (P4a A3: a toggle PATCHes {enabled} only, so a toggle made before the sync
  // returns no longer re-sends the old interval and is no longer refused.)
  useEffect(() => {
    useChartAlertStore.getState().syncRules();
  }, []);

  useEffect(() => {
    if (tab === 'watches' && !watchesLoaded) loadWatches();
  }, [tab, watchesLoaded, loadWatches]);

  function toggleWatch(id: string, on: boolean) {
    setWatches((prev) => prev.map((w) => (w.id === id ? { ...w, enabled: on } : w)));
    api.setCompositeWatchEnabled(id, on).catch(() => loadWatches());
  }

  function deleteWatch(id: string) {
    setWatches((prev) => prev.filter((w) => w.id !== id));
    api.removeCompositeWatch(id).catch(() => loadWatches());
  }

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
  const cutoff = Date.now() - 30 * 24 * 60 * 60 * 1000;
  const recent = sorted.filter((t) => new Date(t.firedAt).getTime() >= cutoff);
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

  function handleCreate() {
    setEditingRule(null);
    setDuplicatingRule(null);
    setShowRuleBuilder(true);
  }

  function handleEdit(rule: AlertRule) {
    setEditingRule(rule);
    setDuplicatingRule(null);
    setShowRuleBuilder(true);
  }

  function handleDuplicate(rule: AlertRule) {
    setEditingRule(null);
    setDuplicatingRule({ ...rule, name: `${rule.name} (copy)` });
    setShowRuleBuilder(true);
  }

  function handleCloseBuilder() {
    setShowRuleBuilder(false);
    setEditingRule(null);
    setDuplicatingRule(null);
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

      {/* ── Tab strip ── */}
      <div className={styles.pageTabStrip}>
        <button
          type="button"
          className={[styles.pageTab, tab === 'alerts' ? styles.pageTabActive : ''].join(' ')}
          onClick={() => setTab('alerts')}
        >
          Alerts
        </button>
        <button
          type="button"
          className={[styles.pageTab, tab === 'rules' ? styles.pageTabActive : ''].join(' ')}
          onClick={() => setTab('rules')}
        >
          Rules
        </button>
        <button
          type="button"
          className={[styles.pageTab, tab === 'watches' ? styles.pageTabActive : ''].join(' ')}
          onClick={() => setTab('watches')}
        >
          Watches
        </button>
      </div>

      {tab === 'alerts' && (
      <div className={styles.layout}>
        {/* ── Left: Alert Settings ── */}
        <aside className={styles.colLeft}>
          <section className={styles.section}>
            <Text size={11} tone="secondary" weight={600}>Alert Settings</Text>
            <Text size={12} tone="secondary">Toggles control both in-app and Telegram / email delivery.</Text>

            <div className={styles.settingsGrid}>
              <SettingsRow label="Keep alerts for (days)" hint="Alerts older than this are auto-purged." defaultValue="30">
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
              <SettingsRow label="Background check frequency (sec)" hint="How often the server re-checks price/portfolio/chart-rule alerts, even with the app closed. Lower = faster detection, more API calls." defaultValue="60">
                <input
                  type="number"
                  className={styles.input}
                  min={15}
                  max={900}
                  value={config.checkIntervalSeconds}
                  onChange={(e) => {
                    const val = Number(e.target.value);
                    if (val >= 15 && val <= 900) setConfig({ ...config, checkIntervalSeconds: val });
                  }}
                />
              </SettingsRow>
              <SettingsRow label="Reminder interval (hours)" hint="While a condition stays true, how often email / Telegram reminds you." defaultValue="4">
                <input
                  type="number"
                  className={styles.input}
                  min={1}
                  max={168}
                  value={config.reminderIntervalHours}
                  onChange={(e) => {
                    const val = Number(e.target.value);
                    if (val >= 1 && val <= 168) setConfig({ ...config, reminderIntervalHours: val });
                  }}
                />
              </SettingsRow>
              <SettingsRow label="Keep sent-message log for (days)" hint="Delivered email / Telegram records older than this are auto-purged." defaultValue="30">
                <input
                  type="number"
                  className={styles.input}
                  min={1}
                  max={365}
                  value={config.retentionDays}
                  onChange={(e) => {
                    const val = Number(e.target.value);
                    if (val >= 1 && val <= 365) setConfig({ ...config, retentionDays: val });
                  }}
                />
              </SettingsRow>
              <SettingsRow label="Sound" hint="Play a short tone when a new alert fires." defaultValue="Off">
                <div className={styles.soundControl}>
                  <button type="button" className={styles.btnSecondary} onClick={testSound}>
                    Test
                  </button>
                  <Toggle on={config.soundEnabled} onChange={(on) => setConfig({ ...config, soundEnabled: on })} />
                </div>
              </SettingsRow>

              <div className={styles.divider} />
              <Text size={12} tone="secondary">Alert types</Text>
              {(Object.keys(ALERT_TYPE_LABELS) as AlertType[]).map((type) => (
                <SettingsRow
                  key={type}
                  label={alertTypeLabel(type, premiumStopPct, 'type')}
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
        </aside>

        {/* ── Middle: Alert History (30d) ── */}
        <main className={styles.colMiddle}>
          <section className={styles.section}>
            <Text size={11} tone="secondary" weight={600}>Alert History (30d)</Text>
            <Text size={11} tone="dim">Showing alerts from the last 30 days.</Text>
            {recent.length === 0 ? (
              <div className={styles.empty}>
                <Text size={13} tone="secondary">No alerts in the last 30 days.</Text>
              </div>
            ) : (
              <div className={styles.alertList}>
                {recent.map((t) => <AlertRow key={t.id} toast={t} />)}
              </div>
            )}
          </section>
        </main>

        {/* ── Right: Upcoming Events ── */}
        <aside className={styles.colRight}>
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
                      title={`Next: ${c.nextEventLabel ?? 'event'} in ${c.nextEventDays}d`}
                    >
                      {c.nextEventDays}d
                    </Data>
                  </div>
                ))}
              </div>
            )}
          </section>
        </aside>
      </div>
      )}

      {tab === 'rules' && (
        <section className={styles.section}>
          <div className={styles.rulesHeader}>
            <Text size={11} tone="secondary" weight={600}>Chart Alert Rules</Text>
            <button type="button" className={styles.btnPrimary} onClick={handleCreate}>
              Create Alert
            </button>
          </div>
          {rules.length === 0 ? (
            <div className={styles.empty}>
              <Text size={13} tone="secondary">No chart alert rules defined yet.</Text>
            </div>
          ) : (
            <div className={styles.rulesTable}>
              <div className={[styles.rulesTableRow, styles.rulesTableHeader].join(' ')}>
                <Text size={11} tone="dim" weight={600}>Name</Text>
                <Text size={11} tone="dim" weight={600}>Symbol</Text>
                <Text size={11} tone="dim" weight={600}>Interval</Text>
                <Text size={11} tone="dim" weight={600}>Conditions</Text>
                <Text size={11} tone="dim" weight={600}>Status</Text>
                <Text size={11} tone="dim" weight={600}>Last Triggered</Text>
                <Text size={11} tone="dim" weight={600}>Actions</Text>
              </div>
              {rules.map((rule) => (
                <div key={rule.id} className={styles.rulesTableRow}>
                  <div>
                    <Text size={13}>{rule.name}</Text>
                    {/* P4a A2 (decision Q1): the server refused this rule's
                        last POST, so it exists only in this browser. */}
                    {unsavedRules[rule.id] && (
                      <div>
                        <Text size={11} tone="caution">{`Not saved to server: ${unsavedRules[rule.id]}`}</Text>
                      </div>
                    )}
                  </div>
                  <Data size={12} weight={500}>{rule.symbol}</Data>
                  <Text size={12}>{rule.interval}</Text>
                  <Text size={12}>{conditionsSummary(rule)}</Text>
                  <Toggle
                    on={rule.enabled}
                    // P4a A3: PATCH {enabled} only -- never re-PUT the local rule.
                    onChange={(on) => setRuleEnabled(rule.id, on)}
                  />
                  <Text size={12} tone="dim">
                    {rule.last_triggered_at ? timeAgo(rule.last_triggered_at) : 'never'}
                  </Text>
                  <div className={styles.rulesActions}>
                    {/* AlertRuleBuilder has no composite-def editor -- it only builds flat
                        price/indicator/structure/regime conditions. Opening Edit or Duplicate
                        on a composite rule would save a fresh empty-condition group over it
                        (or under a new id), corrupting or misrepresenting the rule. Composite
                        rows can still be enabled/disabled and deleted. */}
                    {rule.rule_type !== 'composite' && (
                      <>
                        <button
                          type="button"
                          className={styles.btnSecondary}
                          onClick={() => handleEdit(rule)}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className={styles.btnSecondary}
                          onClick={() => handleDuplicate(rule)}
                        >
                          Duplicate
                        </button>
                      </>
                    )}
                    <button
                      type="button"
                      className={styles.btnDanger}
                      onClick={() => deleteRule(rule.id)}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {tab === 'watches' && (
        <section className={styles.section}>
          <div className={styles.rulesHeader}>
            <Text size={11} tone="secondary" weight={600}>Composite Watches</Text>
            <Text size={11} tone="dim">
              Background checks by the scheduler — active even when no chart tab is open.
            </Text>
          </div>
          {!watchesLoaded ? (
            <div className={styles.empty}><Text size={13} tone="secondary">Loading…</Text></div>
          ) : watches.length === 0 ? (
            <div className={styles.empty}>
              <Text size={13} tone="secondary">
                No composite watches yet. Create one from a chart&apos;s Composite Alert dialog.
              </Text>
            </div>
          ) : (
            <div className={styles.rulesTable}>
              <div className={[styles.watchesTableRow, styles.rulesTableHeader].join(' ')}>
                <Text size={11} tone="dim" weight={600}>Symbol</Text>
                <Text size={11} tone="dim" weight={600}>Direction</Text>
                <Text size={11} tone="dim" weight={600}>Interval</Text>
                <Text size={11} tone="dim" weight={600}>Trigger</Text>
                <Text size={11} tone="dim" weight={600}>Enabled</Text>
                <Text size={11} tone="dim" weight={600}>Actions</Text>
              </div>
              {watches.map((w) => (
                <div key={w.id} className={styles.watchesTableRow}>
                  <Data size={12} weight={500}>{w.symbol}</Data>
                  <Text size={12}>{w.direction}</Text>
                  <Text size={12}>{w.interval}</Text>
                  <Text size={12}>{compositeWatchSummary(w.trigger_def)}</Text>
                  <Toggle
                    on={w.enabled}
                    onChange={(on) => toggleWatch(w.id, on)}
                  />
                  <div className={styles.rulesActions}>
                    <button
                      type="button"
                      className={styles.btnDanger}
                      onClick={() => deleteWatch(w.id)}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {showRuleBuilder && (
        <AlertRuleBuilder
          onClose={handleCloseBuilder}
          editRule={editingRule}
          duplicateFrom={duplicatingRule}
        />
      )}
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
