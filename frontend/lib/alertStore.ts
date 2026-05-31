import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { ToastItem, AlertConfig, AlertType } from '@/types/domain';

interface AlertStoreState {
  toasts: ToastItem[];
  config: AlertConfig;
  firedAlerts: Record<string, number>;
  suppressedAlerts: Record<string, true>;  // permanent suppress after acknowledge

  addToast: (item: Omit<ToastItem, 'id' | 'dismissed' | 'acknowledged' | 'firedAt'>) => void;
  dismissToast: (id: string) => void;
  acknowledgeAlert: (id: string) => void;
  deleteAlert: (id: string) => void;
  clearOldAlerts: () => void;
  clearAll: () => void;
  setConfig: (c: AlertConfig) => void;

  // derived
  unacknowledgedCount: () => number;
}

export const DEFAULT_CONFIG: AlertConfig = {
  dedupWindowMinutes: 15,
  reminderIntervalHours: 4,
  keepAlertsDays: 30,
  retentionDays: 30,
  enabledTypes: [
    'TP_HIT', 'STOP_REACHED', 'PREMIUM_STOP', 'TIME_STOP',
    'EVENT_RISK', 'REGIME_CHANGE', 'SCAN_COMPLETE', 'SCAN_FAILED',
    'TIME_STOP_APPROACHING', 'EARNINGS_APPROACHING', 'EXPIRATION_APPROACHING',
  ],
  soundEnabled: false,
};

function makeDedupKey(recId: string, alertType: AlertType | string): string {
  return `${recId}-${alertType}`;
}

// Collapse un-acknowledged duplicates down to one row per (recId, alertType),
// keeping the most recent. Acknowledged rows are left untouched as history.
// Used on hydration to clean up any pre-existing pile-up.
function collapseToasts(toasts: ToastItem[]): ToastItem[] {
  const latestActive = new Map<string, ToastItem>();
  const acknowledged: ToastItem[] = [];
  for (const t of toasts) {
    if (t.acknowledged) {
      acknowledged.push(t);
      continue;
    }
    const key = makeDedupKey(t.recId, t.alertType);
    const existing = latestActive.get(key);
    if (!existing || new Date(t.firedAt).getTime() >= new Date(existing.firedAt).getTime()) {
      latestActive.set(key, t);
    }
  }
  return [...acknowledged, ...latestActive.values()];
}

// Portfolio alert types that should trigger an email/Telegram. Scan lifecycle
// types (SCAN_COMPLETE/SCAN_FAILED) are deliberately excluded.
const NOTIFIABLE_TYPES = new Set<string>([
  'TP_HIT', 'STOP_REACHED', 'PREMIUM_STOP', 'TIME_STOP', 'EVENT_RISK', 'REGIME_CHANGE',
]);

const NOTIFY_BASE_URL = () =>
  process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

// Fire-and-forget: tell the backend to deliver this alert. The backend enforces
// masterEnabled/enabledTypes and dedups (shared with the headless monitor), so
// the browser just reports every NEW alert it shows.
function notifyBackend(item: {
  symbol: string;
  alertType: string;
  reason: string;
  recId: string;
  firedAt: string;
}): void {
  if (typeof window === 'undefined') return;
  if (!NOTIFIABLE_TYPES.has(item.alertType)) return;
  try {
    void fetch(`${NOTIFY_BASE_URL()}/api/alerts/notify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        symbol: item.symbol,
        alertType: item.alertType,
        reason: item.reason,
        recId: item.recId,
        timestamp: item.firedAt,
      }),
    }).catch(() => {
      /* backend offline — in-app alert still shows */
    });
  } catch {
    /* network unavailable */
  }
}

export const useAlertStore = create<AlertStoreState>()(
  persist(
    (set, get) => ({
      toasts: [],
      config: DEFAULT_CONFIG,
      firedAlerts: {},
      suppressedAlerts: {},

      addToast: (item) => {
        const { toasts, config, firedAlerts, suppressedAlerts } = get();
        const now = Date.now();
        const nowIso = new Date(now).toISOString();

        const compositeKey = makeDedupKey(item.recId, item.alertType);

        // permanently suppressed after acknowledge
        if (suppressedAlerts[compositeKey]) return;

        // ── In-app: one row per active condition. A still-true condition that
        //    keeps re-checking updates its existing (un-acknowledged) row in
        //    place instead of spawning a new one — no pile-up.
        const existingIdx = toasts.findIndex(
          (t) => t.recId === item.recId && t.alertType === item.alertType && !t.acknowledged,
        );
        const isNewRow = existingIdx < 0;

        let nextToasts: ToastItem[];
        if (isNewRow) {
          const id = now.toString(36) + Math.random().toString(36).slice(2, 6);
          nextToasts = [...toasts, {
            ...item,
            id,
            dismissed: false,
            acknowledged: false,
            firedAt: nowIso,
          }];
        } else {
          // Still-true condition refreshing in place: keep the ORIGINAL firedAt
          // so the row (and the reminder notifications) reflect the first trigger.
          nextToasts = [...toasts];
          nextToasts[existingIdx] = {
            ...nextToasts[existingIdx]!,
            kind: item.kind,
            reason: item.reason,
          };
        }

        // ── Notification: throttle re-POSTs to once per dedupWindowMinutes so we
        //    don't hit the backend every 30s tick. The backend enforces the real
        //    reminder gap (reminderIntervalHours), so a short throttle here is
        //    enough — it just needs to re-POST soon after each reminder window
        //    opens. dedupWindowMinutes (15m) ≪ reminderIntervalHours (4h).
        const throttleMs = Math.max(config.dedupWindowMinutes, 1) * 60_000;
        const lastSent = firedAlerts[compositeKey];
        const shouldNotify = lastSent == null || now - lastSent >= throttleMs;
        const nextFired = { ...firedAlerts };
        if (shouldNotify) nextFired[compositeKey] = now;

        set({ toasts: nextToasts, firedAlerts: nextFired });

        if (shouldNotify) {
          notifyBackend({
            symbol: item.symbol,
            alertType: item.alertType,
            reason: item.reason,
            recId: item.recId,
            firedAt: nowIso,
          });
        }

        // Only chime on a genuinely new alert, not on silent in-place refreshes.
        if (isNewRow && config.soundEnabled && typeof window !== 'undefined') {
          const ctx = new (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
          const osc = ctx.createOscillator();
          osc.connect(ctx.destination);
          osc.frequency.value = 880;
          osc.start();
          osc.stop(ctx.currentTime + 0.1);
        }
      },

      dismissToast: (id) => {
        set((s) => ({
          toasts: s.toasts.map((t) => (t.id === id ? { ...t, dismissed: true } : t)),
        }));
      },

      acknowledgeAlert: (id) => {
        const toast = get().toasts.find((t) => t.id === id);
        if (!toast) return;
        const key = makeDedupKey(toast.recId, toast.alertType);
        set((s) => ({
          toasts: s.toasts.map((t) => (t.id === id ? { ...t, acknowledged: true } : t)),
          suppressedAlerts: { ...s.suppressedAlerts, [key]: true },
        }));
      },

      deleteAlert: (id) => {
        const toast = get().toasts.find((t) => t.id === id);
        if (!toast) return;
        const key = makeDedupKey(toast.recId, toast.alertType);
        set((s) => {
          const next = { ...s.suppressedAlerts };
          delete next[key];
          return {
            toasts: s.toasts.filter((t) => t.id !== id),
            suppressedAlerts: next,
          };
        });
      },

      clearOldAlerts: () => {
        const { toasts, config } = get();
        const cutoff = Date.now() - config.keepAlertsDays * 86_400_000;
        set({ toasts: toasts.filter((t) => new Date(t.firedAt).getTime() > cutoff) });
      },

      clearAll: () => {
        set({ toasts: [], suppressedAlerts: {}, firedAlerts: {} });
      },

      setConfig: (c) => {
        set({ config: c });
      },

      unacknowledgedCount: () => get().toasts.filter((t) => !t.acknowledged).length,
    }),
    {
      name: 'bamendjou-alerts-v2',
      partialize: (state) => ({
        toasts: state.toasts,
        config: state.config,
        suppressedAlerts: state.suppressedAlerts,
      }),
      merge: (persistedState, currentState) => {
        const ps = persistedState as Partial<AlertStoreState> | undefined;
        const merged = {
          ...currentState,
          toasts: ps?.toasts ?? [],
          config: { ...DEFAULT_CONFIG, ...(ps?.config ?? {}) },
          suppressedAlerts: ps?.suppressedAlerts ?? {},
        };
        // purge old alerts, then collapse any pre-existing duplicate pile-up
        const cutoff = Date.now() - merged.config.keepAlertsDays * 86_400_000;
        merged.toasts = collapseToasts(
          merged.toasts.filter((t) => new Date(t.firedAt).getTime() > cutoff),
        );
        return merged;
      },
    }
  )
);
