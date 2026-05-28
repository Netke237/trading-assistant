import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { AlertRule, AlertHistory } from '@/types/alerts';

export const HISTORY_LIMIT = 200;
const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

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
  migrated: boolean;

  addRule: (rule: AlertRule) => boolean;
  updateRule: (id: string, patch: Partial<AlertRule>) => void;
  deleteRule: (id: string) => void;
  addHistory: (entry: AlertHistory) => void;
  clearHistory: () => void;
  dismissHistory: (id: string) => void;
  pushToast: (toast: ChartToast) => void;
  dismissToast: (id: string) => void;
  markViewed: () => void;

  syncRules: () => Promise<void>;
  setMigrated: () => void;
}

async function pushRuleToAPI(rule: AlertRule): Promise<void> {
  try {
    await fetch(`${BASE_URL}/alerts/rules`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: rule.id,              // send client id so server preserves it
        name: rule.name, symbol: rule.symbol, interval: rule.interval,
        enabled: rule.enabled, group: rule.group,
        cooldown_minutes: rule.cooldown_minutes, expiry_date: rule.expiry_date,
      }),
    });
  } catch { /* fire-and-forget */ }
}

async function putRuleToAPI(rule: AlertRule): Promise<void> {
  try {
    await fetch(`${BASE_URL}/alerts/rules/${encodeURIComponent(rule.id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: rule.name, symbol: rule.symbol, interval: rule.interval,
        enabled: rule.enabled, group: rule.group,
        cooldown_minutes: rule.cooldown_minutes, expiry_date: rule.expiry_date,
      }),
    });
  } catch {}
}

async function deleteRuleFromAPI(id: string): Promise<void> {
  try { await fetch(`${BASE_URL}/alerts/rules/${encodeURIComponent(id)}`, { method: 'DELETE' }); } catch {}
}

async function deleteHistoryFromAPI(id: string): Promise<void> {
  try { await fetch(`${BASE_URL}/alerts/history/${encodeURIComponent(id)}`, { method: 'DELETE' }); } catch {}
}

async function pushHistoryToAPI(entry: AlertHistory): Promise<void> {
  try {
    await fetch(`${BASE_URL}/alerts/history`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        rule_id: entry.rule_id, symbol: entry.symbol, interval: entry.interval,
        triggered_at: entry.triggered_at, candle: entry.candle,
        trigger_values: entry.trigger_values, reason: entry.reason,
      }),
    });
  } catch {}
}

export const useChartAlertStore = create<ChartAlertState>()(
  persist(
    (set, get) => ({
      rules: [],
      history: [],
      toasts: [],
      newSinceView: 0,
      migrated: false,

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
        if (added) pushRuleToAPI(rule);
        return added;
      },

      updateRule: (id, patch) => {
        set((s) => ({
          rules: s.rules.map((r) => (r.id === id ? { ...r, ...patch } : r)),
        }));
        const updated = get().rules.find((r) => r.id === id);
        if (updated) putRuleToAPI(updated);
      },

      deleteRule: (id) => {
        set((s) => ({
          rules: s.rules.filter((r) => r.id !== id),
          history: s.history.filter((h) => h.rule_id !== id),
        }));
        deleteRuleFromAPI(id);
      },

      addHistory: (entry) => {
        let added = false;
        set((s) => {
          // Dedup: skip if same rule triggered within the same candle period (60s window)
          const isDupe = s.history.some(
            (h) =>
              h.rule_id === entry.rule_id &&
              Math.abs(
                new Date(h.triggered_at).getTime() - new Date(entry.triggered_at).getTime(),
              ) < 60_000,
          );
          if (isDupe) return s;
          added = true;
          return {
            history: [entry, ...s.history].slice(0, HISTORY_LIMIT),
            newSinceView: s.newSinceView + 1,
          };
        });
        if (added) pushHistoryToAPI(entry);
      },

      clearHistory: () => set({ history: [] }),

      dismissHistory: (id) => {
        set((s) => ({
          history: s.history.filter((h) => h.id !== id),
        }));
        deleteHistoryFromAPI(id);
      },

      pushToast: (toast) =>
        set((s) => ({ toasts: [...s.toasts, toast] })),

      dismissToast: (id) =>
        set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),

      markViewed: () => set({ newSinceView: 0 }),

      syncRules: async () => {
        try {
          const res = await fetch(`${BASE_URL}/alerts/rules`);
          if (!res.ok) return;
          const serverRules: AlertRule[] = await res.json();
          const localRules = get().rules;
          const serverIds = new Set(serverRules.map((r) => r.id));
          const localOnly = localRules.filter((r) => !serverIds.has(r.id));

          for (const rule of localOnly) await pushRuleToAPI(rule);

          const merged = [...serverRules];
          for (const rule of localOnly) {
            if (!merged.find((r) => r.id === rule.id)) merged.push(rule);
          }

          set({ rules: merged, migrated: true });
        } catch {}
      },

      setMigrated: () => set({ migrated: true }),
    }),
    {
      name: 'bamendjou:alerts',
      storage: createJSONStorage(() => {
        if (typeof window === 'undefined') return undefined as unknown as Storage;
        return localStorage;
      }),
      skipHydration: true,
      partialize: (state) => ({
        rules: state.rules,
        history: state.history,
      }),
      version: 2,
      migrate: (persistedState: unknown, version: number) => {
        const prev = (persistedState as Partial<ChartAlertState> | null) ?? {};
        if (version < 2) {
          const oldRules: AlertRule[] = Array.isArray(prev.rules) ? prev.rules : [];
          const oldHistory: AlertHistory[] = Array.isArray(prev.history) ? prev.history.slice(0, HISTORY_LIMIT) : [];
          return { rules: oldRules, history: oldHistory, toasts: [], newSinceView: 0, migrated: false } as unknown as ChartAlertState;
        }
        return prev as ChartAlertState;
      },
    },
  ),
);
