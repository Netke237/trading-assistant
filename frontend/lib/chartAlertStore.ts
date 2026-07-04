import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { AlertRule, AlertHistory, Condition } from '@/types/alerts';

export const HISTORY_LIMIT = 200;

/** Compares condition arrays for the purpose of duplicate-rule detection,
 * ignoring each condition's `id` — two conditions with identical fields but
 * different (freshly generated) ids are still the same condition. */
export function conditionsEqual(a: Condition[], b: Condition[]): boolean {
  const stripDeep = (v: unknown): unknown => {
    if (Array.isArray(v)) return v.map(stripDeep);
    if (v && typeof v === 'object') {
      const out: Record<string, unknown> = {};
      for (const [k, val] of Object.entries(v as Record<string, unknown>)) {
        if (k === 'id') continue;
        out[k] = stripDeep(val);
      }
      return out;
    }
    return v;
  };
  return JSON.stringify(stripDeep(a)) === JSON.stringify(stripDeep(b));
}
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
  /**
   * Add an alert history entry to the store.
   * @param skipApiSync - set true when the entry comes from a backend
   *   `alert_triggered` WebSocket message (backend already saved it to DB and
   *   sent notifications; pushing again would create duplicates).
   */
  addHistory: (entry: AlertHistory, skipApiSync?: boolean) => void;
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
  // A composite rule's `group` is only ever the backend's display placeholder
  // {logic:'AND', conditions:[]} — never the real trigger definition (see
  // _rule_to_dict on the backend). Sending that placeholder here would overwrite
  // the rule's real composite_def with an empty group, silently corrupting it into
  // a dead standard rule. Composite rules must PUT rule_type/composite_def instead.
  const body = rule.rule_type === 'composite'
    ? {
        name: rule.name, symbol: rule.symbol, interval: rule.interval,
        enabled: rule.enabled, rule_type: 'composite', composite_def: rule.composite_def,
        cooldown_minutes: rule.cooldown_minutes, expiry_date: rule.expiry_date,
      }
    : {
        name: rule.name, symbol: rule.symbol, interval: rule.interval,
        enabled: rule.enabled, group: rule.group,
        cooldown_minutes: rule.cooldown_minutes, expiry_date: rule.expiry_date,
      };
  try {
    await fetch(`${BASE_URL}/alerts/rules/${encodeURIComponent(rule.id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
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
              conditionsEqual(r.group.conditions, rule.group.conditions),
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

      addHistory: (entry, skipApiSync = false) => {
        let added = false;
        set((s) => {
          // Dedup: skip if exact same id already present (cooldown handled by alert engine)
          const isDupe = s.history.some((h) => h.id === entry.id);
          if (isDupe) return s;
          added = true;
          return {
            history: [entry, ...s.history].slice(0, HISTORY_LIMIT),
            newSinceView: s.newSinceView + 1,
          };
        });
        // Only push to API for locally-originated entries. Entries from the
        // backend `alert_triggered` WebSocket message are already persisted and
        // notified server-side — pushing again would create duplicate DB rows
        // and fire duplicate email/telegram notifications.
        if (added && !skipApiSync) pushHistoryToAPI(entry);
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
