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
  keepAlertsDays: 10,
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
        const windowMs = config.dedupWindowMinutes * 60_000;

        const compositeKey = makeDedupKey(item.recId, item.alertType);

        // permanently suppressed after acknowledge
        if (suppressedAlerts[compositeKey]) return;

        // time-window dedup
        const evicted: Record<string, number> = {};
        for (const [key, ts] of Object.entries(firedAlerts)) {
          if (now - ts <= windowMs) evicted[key] = ts;
        }
        if (compositeKey in evicted) return;

        evicted[compositeKey] = now;
        const id = now.toString(36) + Math.random().toString(36).slice(2, 6);
        const toast: ToastItem = {
          ...item,
          id,
          dismissed: false,
          acknowledged: false,
          firedAt: new Date(now).toISOString(),
        };
        set({ toasts: [...toasts, toast], firedAlerts: evicted });

        if (config.soundEnabled && typeof window !== 'undefined') {
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
        // purge old alerts on hydration
        const cutoff = Date.now() - merged.config.keepAlertsDays * 86_400_000;
        merged.toasts = merged.toasts.filter((t) => new Date(t.firedAt).getTime() > cutoff);
        return merged;
      },
    }
  )
);
