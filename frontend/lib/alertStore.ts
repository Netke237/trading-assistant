import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { ToastItem, AlertConfig } from '@/types/domain';

interface AlertStoreState {
  toasts: ToastItem[];
  unreadCount: number;
  config: AlertConfig;
  addToast: (item: Omit<ToastItem, 'id' | 'dismissed'>) => void;
  dismissToast: (id: string) => void;
  clearAll: () => void;
  setConfig: (c: AlertConfig) => void;
}

export const DEFAULT_CONFIG: AlertConfig = {
  dedupWindowMinutes: 15,
  enabledTypes: [
    'TP_HIT', 'STOP_REACHED', 'PREMIUM_STOP', 'TIME_STOP_APPROACHING',
    'EARNINGS_APPROACHING', 'EXPIRATION_APPROACHING',
  ],
  soundEnabled: false,
};

function makeDedupKey(item: Omit<ToastItem, 'id' | 'dismissed'>): string {
  return `${item.kind}:${item.symbol}:${item.reason}`;
}

export const useAlertStore = create<AlertStoreState>()(
  persist(
    (set, get) => ({
      toasts: [],
      unreadCount: 0,
      config: DEFAULT_CONFIG,
      addToast: (item) => {
        const { toasts, config } = get();
        const key = makeDedupKey(item);
        const windowMs = config.dedupWindowMinutes * 60_000;
        const now = Date.now();

        const duplicate = toasts.find((t) => {
          if (t.dismissed) return false;
          return makeDedupKey(t) === key && now - parseInt(t.id, 36) < windowMs;
        });

        if (duplicate) return;

        const id = now.toString(36) + Math.random().toString(36).slice(2, 6);
        const toast: ToastItem = { ...item, id, dismissed: false };
        set({
          toasts: [...toasts, toast],
          unreadCount: get().unreadCount + 1,
        });
      },
      dismissToast: (id) => {
        set((s) => ({
          toasts: s.toasts.map((t) => (t.id === id ? { ...t, dismissed: true } : t)),
        }));
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
