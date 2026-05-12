import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { ToastItem, AlertConfig, AlertType } from '@/types/domain';
import { useSettingsStore } from '@/lib/settingsStore';

interface AlertStoreState {
  toasts: ToastItem[];
  visibleToasts: ToastItem[];
  unreadCount: number;
  config: AlertConfig;
  firedAlerts: Record<string, number>;
  addToast: (item: Omit<ToastItem, 'id' | 'dismissed'>) => void;
  dismissToast: (id: string) => void;
  clearAll: () => void;
  setConfig: (c: AlertConfig) => void;
}

export const DEFAULT_CONFIG: AlertConfig = {
  dedupWindowMinutes: 15,
  enabledTypes: [
    'TP_HIT', 'STOP_REACHED', 'PREMIUM_STOP', 'TIME_STOP',
    'EVENT_RISK', 'REGIME_CHANGE', 'SCAN_COMPLETE',
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
      visibleToasts: [],
      unreadCount: 0,
      config: DEFAULT_CONFIG,
      firedAlerts: {},

      addToast: (item) => {
        const { toasts, config, firedAlerts } = get();
        const dedupHours = useSettingsStore.getState().alertDeduplicationHours;
        const now = Date.now();
        const windowMs = dedupHours * 3_600_000;

        const evicted: Record<string, number> = {};
        for (const [key, ts] of Object.entries(firedAlerts)) {
          if (now - ts <= windowMs) {
            evicted[key] = ts;
          }
        }

        const compositeKey = makeDedupKey(item.recId, item.alertType);
        if (compositeKey in evicted) return;

        evicted[compositeKey] = now;
        const id = now.toString(36) + Math.random().toString(36).slice(2, 6);
        const toast: ToastItem = { ...item, id, dismissed: false };
        const updatedToasts = [...toasts, toast];
        set({
          toasts: updatedToasts,
          visibleToasts: updatedToasts.filter((t) => !t.dismissed),
          unreadCount: get().unreadCount + 1,
          firedAlerts: evicted,
        });
      },

      dismissToast: (id) => {
        set((s) => {
          const updatedToasts = s.toasts.map((t) => (t.id === id ? { ...t, dismissed: true } : t));
          return {
            toasts: updatedToasts,
            visibleToasts: updatedToasts.filter((t) => !t.dismissed),
          };
        });
      },

      clearAll: () => {
        set({ unreadCount: 0 });
      },

      setConfig: (c) => {
        set({ config: c });
      },
    }),
    {
      name: 'bamendjou-alerts-v1',
      partialize: (state) => ({ config: state.config }),
      merge: (persistedState, currentState) => {
        const ps = persistedState as Partial<AlertStoreState> | undefined;
        return {
          ...currentState,
          config: ps?.config ?? currentState.config,
        };
      },
    }
  )
);