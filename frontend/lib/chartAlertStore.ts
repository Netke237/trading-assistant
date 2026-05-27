import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { AlertRule, AlertHistory } from '@/types/alerts';

export const HISTORY_LIMIT = 200;

export interface ChartToast {
  id: string;
  message: string;
  timestamp: number;
}

interface ChartAlertState {
  rules: AlertRule[];
  history: AlertHistory[];
  toasts: ChartToast[];
  newSinceView: number;
  addRule: (rule: AlertRule) => boolean;
  updateRule: (id: string, patch: Partial<AlertRule>) => void;
  deleteRule: (id: string) => void;
  addHistory: (entry: AlertHistory) => void;
  clearHistory: () => void;
  dismissHistory: (id: string) => void;
  pushToast: (toast: ChartToast) => void;
  dismissToast: (id: string) => void;
  markViewed: () => void;
}

export const useChartAlertStore = create<ChartAlertState>()(
  persist(
    (set) => ({
      rules: [],
      history: [],
      toasts: [],
      newSinceView: 0,

      addRule: (rule) => {
        let added = false;
        set((s) => {
          const duplicate = s.rules.some(
            (r) =>
              r.symbol === rule.symbol &&
              r.interval === rule.interval &&
              JSON.stringify(r.group.conditions) === JSON.stringify(rule.group.conditions),
          );
          if (duplicate) return s;
          added = true;
          return { rules: [...s.rules, rule] };
        });
        return added;
      },

      updateRule: (id, patch) =>
        set((s) => ({
          rules: s.rules.map((r) => (r.id === id ? { ...r, ...patch } : r)),
        })),

      deleteRule: (id) =>
        set((s) => ({
          rules: s.rules.filter((r) => r.id !== id),
          history: s.history.filter((h) => h.rule_id !== id),
        })),

      addHistory: (entry) =>
        set((s) => ({
          history: [entry, ...s.history].slice(0, HISTORY_LIMIT),
          newSinceView: s.newSinceView + 1,
        })),

      clearHistory: () => set({ history: [] }),

      dismissHistory: (id) =>
        set((s) => ({
          history: s.history.filter((h) => h.id !== id),
        })),

      pushToast: (toast) =>
        set((s) => ({ toasts: [...s.toasts, toast] })),

      dismissToast: (id) =>
        set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),

      markViewed: () => set({ newSinceView: 0 }),
    }),
    {
      name: 'bamendjou:alerts',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        rules: state.rules,
        history: state.history,
      }),
      version: 1,
      migrate: (persistedState, version) => {
        const prev = (persistedState as Partial<ChartAlertState> | null) ?? {};
        if (version < 1) {
          return {
            rules: Array.isArray(prev.rules) ? prev.rules : [],
            history: Array.isArray(prev.history) ? prev.history.slice(0, HISTORY_LIMIT) : [],
            toasts: [],
            newSinceView: 0,
          } as unknown as ChartAlertState;
        }
        return prev as ChartAlertState;
      },
    },
  ),
);
