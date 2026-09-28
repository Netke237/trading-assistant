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

  /** P4a A2 (decision Q1) -- rules the server does not hold as far as the
   *  last POST knows, id -> reason: the server's reason on a refusal, or
   *  OFFLINE_SAVE_REASON when the POST got a network error or a 5xx
   *  (CHART-RULE-OFFLINE-SAVE-MARK). NOT persisted (absent from `partialize`),
   *  so a mark cannot outlive the POST it describes; every `syncRules` and
   *  `addRule` POST rebuilds or clears it. */
  unsavedRules: Record<string, string>;
  /** P4a A3 -- the Alerts-page toggle. Sets `enabled` locally and PATCHes
   *  `{enabled}` only, so a stale local interval / composite_def is never
   *  re-sent (a full PUT could be refused, losing the toggle, or overwrite
   *  the server). */
  setRuleEnabled: (id: string, enabled: boolean) => void;
  /** P4a A4 -- records a trigger time. `persist: true` PATCHes
   *  `{last_triggered_at}` with the stamp UNCHANGED (the client's
   *  `toISOString()`; the server's cooldown check normalises an aware stamp,
   *  alert_evaluator.is_cooldown_passed). `persist: false` when the backend
   *  already wrote it (the WebSocket `alert_triggered` message). */
  stampRuleTriggered: (id: string, at: string, opts: { persist: boolean }) => void;
}

/** P4a A1 (decision Q1) -- ONE body for POST and PUT.
 *
 *  A composite rule's `group` is only ever the backend's display placeholder
 *  {logic:'AND', conditions:[]} -- never the real trigger definition (see
 *  _rule_to_dict on the backend). Sending that placeholder would create or
 *  overwrite the rule as an empty STANDARD rule: a dead alert under the user's
 *  name. The POST used to do exactly that for a local-only composite that
 *  `syncRules` re-sent; composite rules send rule_type/composite_def instead. */
export function ruleBodyForApi(rule: AlertRule): Record<string, unknown> {
  const shared = {
    name: rule.name, symbol: rule.symbol, interval: rule.interval,
    enabled: rule.enabled,
    cooldown_minutes: rule.cooldown_minutes, expiry_date: rule.expiry_date,
  };
  return rule.rule_type === 'composite'
    ? { ...shared, rule_type: 'composite', composite_def: rule.composite_def }
    : { ...shared, group: rule.group };
}

/** How a POST ended. 'ok' includes 409 (the server already has this id).
 *  'refused' carries the server's reason as TEXT: a pydantic 422 `detail` is
 *  an array of objects, an HTTPException's a string. 'offline' is a network
 *  error or a 5xx -- the server did not confirm the save, so the rule is
 *  marked OFFLINE_SAVE_REASON (a 1D/1W rule is judged by the server only). */
export type PostOutcome = { kind: 'ok' } | { kind: 'refused'; detail: string } | { kind: 'offline' };

/** CHART-RULE-OFFLINE-SAVE-MARK C1 -- the mark for an 'offline' POST.
 *  `syncRules` runs when the Alerts page or a chart mounts, hence the text. */
export const OFFLINE_SAVE_REASON =
  'could not reach the server; retried when the Alerts page or a chart next opens';

/** CHART-RULE-OFFLINE-SAVE-MARK C2/C3-ok -- per-id generation counters that
 *  order an `addRule` POST against a `syncRules` run. Module-level, not store
 *  state (never persisted or rendered).
 *  - syncGen: bumped by `syncRules` right after its final write, for every id
 *    it ruled on. A late 'offline'/'refused' answer to an `addRule` POST that
 *    started before that bump is dropped: the sync's verdict is newer.
 *  - okGen: bumped by `addRule` on a 201/409. A `syncRules` run that saw it
 *    move since the run started drops its mark for that id: the server holds
 *    the rule, whatever the run's own re-POST answered. */
const syncGen = new Map<string, number>();
const okGen = new Map<string, number>();
const bump = (m: Map<string, number>, id: string) => m.set(id, (m.get(id) ?? 0) + 1);

/** Test-only: clears both generation maps. */
export function __resetChartAlertSyncGenForTests(): void {
  syncGen.clear();
  okGen.clear();
}

async function pushRuleToAPI(rule: AlertRule): Promise<PostOutcome> {
  try {
    const res = await fetch(`${BASE_URL}/alerts/rules`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // `id`: send the client id so the server preserves it.
      body: JSON.stringify({ id: rule.id, ...ruleBodyForApi(rule) }),
    });
    if (res.ok || res.status === 409) return { kind: 'ok' };
    if (res.status >= 400 && res.status < 500) {
      let detail: string = `HTTP ${res.status}`;
      try {
        const body = await res.json();
        const d = (body as { detail?: unknown })?.detail;
        if (typeof d === 'string') detail = d;
        else if (d !== undefined) detail = JSON.stringify(d);
      } catch { /* keep the status */ }
      return { kind: 'refused', detail };
    }
    return { kind: 'offline' };
  } catch {
    return { kind: 'offline' };
  }
}

async function patchRuleToAPI(id: string, body: { enabled?: boolean; last_triggered_at?: string }): Promise<void> {
  // A 404 (the rule is local-only) needs nothing more: the next syncRules
  // re-POSTs the rule with its current fields.
  try {
    await fetch(`${BASE_URL}/alerts/rules/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {}
}

async function putRuleToAPI(rule: AlertRule): Promise<void> {
  const body = ruleBodyForApi(rule);
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
        checklist: entry.checklist,
      }),
    });
  } catch {}
}

export function migrateChartAlerts(persistedState: unknown, version: number): ChartAlertState {
  const prev = (persistedState as Partial<ChartAlertState> | null) ?? {};
  if (version < 2) {
    const oldRules: AlertRule[] = Array.isArray(prev.rules) ? prev.rules : [];
    const oldHistory: AlertHistory[] = Array.isArray(prev.history) ? prev.history.slice(0, HISTORY_LIMIT) : [];
    return { rules: oldRules, history: oldHistory, toasts: [], newSinceView: 0, migrated: false } as unknown as ChartAlertState;
  }
  return prev as ChartAlertState;
}

export const useChartAlertStore = create<ChartAlertState>()(
  persist(
    (set, get) => ({
      rules: [],
      history: [],
      toasts: [],
      newSinceView: 0,
      migrated: false,
      unsavedRules: {},

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
        if (added) {
          const gen = syncGen.get(rule.id) ?? 0;
          void pushRuleToAPI(rule).then((outcome) => {
            if (outcome.kind === 'ok') {
              // The server holds the rule, so no mark is right whatever the
              // ordering: a sync that ran during this POST may have marked it.
              bump(okGen, rule.id);
              set((s) => {
                if (!(rule.id in s.unsavedRules)) return s;
                const { [rule.id]: _cleared, ...rest } = s.unsavedRules;
                return { unsavedRules: rest };
              });
              return;
            }
            const reason = outcome.kind === 'refused' ? outcome.detail : OFFLINE_SAVE_REASON;
            set((s) => {
              // Deleted meanwhile, or a sync has ruled on this id since the
              // POST started (its verdict is newer): write nothing.
              if (!s.rules.some((r) => r.id === rule.id)) return s;
              if ((syncGen.get(rule.id) ?? 0) !== gen) return s;
              return { unsavedRules: { ...s.unsavedRules, [rule.id]: reason } };
            });
          });
        }
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
        const okAtStart = new Map(okGen);
        try {
          const res = await fetch(`${BASE_URL}/alerts/rules`);
          if (!res.ok) return;
          const serverRules: AlertRule[] = await res.json();
          const localRules = get().rules;
          const serverIds = new Set(serverRules.map((r) => r.id));
          const localOnly = localRules.filter((r) => !serverIds.has(r.id));

          // A2 (Q1): a refused re-POST keeps the rule locally and says why;
          // an accepted one (201/409) clears any old mark; an offline one
          // keeps an existing mark verbatim (a refusal reason says more),
          // else marks OFFLINE_SAVE_REASON.
          const unsaved: Record<string, string> = {};
          for (const rule of localOnly) {
            const outcome = await pushRuleToAPI(rule);
            if (outcome.kind === 'refused') unsaved[rule.id] = outcome.detail;
            else if (outcome.kind === 'offline') {
              unsaved[rule.id] = get().unsavedRules[rule.id] ?? OFFLINE_SAVE_REASON;
            }
          }
          // C3-ok: an addRule POST that got 201/409 during this run proves
          // the server holds the rule (this run's re-POST may have raced it).
          for (const id of Object.keys(unsaved)) {
            if ((okGen.get(id) ?? 0) !== (okAtStart.get(id) ?? 0)) delete unsaved[id];
          }

          const merged = [...serverRules];
          for (const rule of localOnly) {
            if (!merged.find((r) => r.id === rule.id)) merged.push(rule);
          }

          set({ rules: merged, migrated: true, unsavedRules: unsaved });
          for (const id of serverIds) bump(syncGen, id);
          for (const rule of localOnly) bump(syncGen, rule.id);
        } catch {}
      },

      setMigrated: () => set({ migrated: true }),

      setRuleEnabled: (id, enabled) => {
        set((s) => ({ rules: s.rules.map((r) => (r.id === id ? { ...r, enabled } : r)) }));
        void patchRuleToAPI(id, { enabled });
      },

      stampRuleTriggered: (id, at, { persist }) => {
        set((s) => ({ rules: s.rules.map((r) => (r.id === id ? { ...r, last_triggered_at: at } : r)) }));
        if (persist) void patchRuleToAPI(id, { last_triggered_at: at });
      },
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
      migrate: migrateChartAlerts,
    },
  ),
);
