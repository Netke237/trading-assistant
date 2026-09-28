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

/** CHART-RULES-SYNC-CONCURRENCY C3 -- deleted rule ids ("tombstones").
 *  `deleteRule` adds its id here BEFORE sending the DELETE, and nothing ever
 *  removes one: no DELETE answer (2xx, 404, 5xx, network error, in any order)
 *  can bring a deleted rule back (G2), and a POST that was in flight when the
 *  rule was deleted is answered with another DELETE (C4, G3). Rule ids come
 *  from `makeId()` and are never reused, so a tombstone never hides a later
 *  rule.
 *
 *  Mirrored to localStorage under its OWN key (the colon-form
 *  `'bamendjou:alert-tombstones'`: a JSON array of ids, oldest first, the 500
 *  most recent), so a tombstone survives a reload and is shared by this
 *  browser's tabs. `'bamendjou:alerts'`, its `partialize` and `version` are
 *  untouched. Storage is only ever written by read-merge-write
 *  (`addTombstone`), never straight from this Set, so one tab cannot erase
 *  another tab's tombstone; and every check goes through `isTombstoned`,
 *  which re-reads storage first, so a tombstone another tab writes mid-run
 *  counts. Known limit: two tabs read-merge-writing within the same instant
 *  can lose one tombstone (localStorage is last-writer-wins per key). */
const TOMBSTONE_KEY = 'bamendjou:alert-tombstones';
const TOMBSTONE_LIMIT = 500;
const deletedIds = new Set<string>();

/** The stored tombstone array: `[]` when the key is missing, not JSON or not
 *  an array (non-string entries dropped); `null` when storage itself is
 *  unavailable (SSR, blocked storage) -- the Set alone then serves. */
function readStoredTombstones(): string[] | null {
  if (typeof window === 'undefined') return null;
  let raw: string | null;
  try { raw = window.localStorage.getItem(TOMBSTONE_KEY); } catch { return null; }
  if (raw === null) return [];
  let parsed: unknown;
  try { parsed = JSON.parse(raw); } catch { return []; }
  return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : [];
}

/** Merges storage into the Set (another tab's or a pre-reload tombstone). */
function refreshTombstones(): void {
  const stored = readStoredTombstones();
  if (stored) for (const id of stored) deletedIds.add(id);
}

function isTombstoned(id: string): boolean {
  refreshTombstones();
  return deletedIds.has(id);
}

function addTombstone(id: string): void {
  deletedIds.add(id);
  const stored = readStoredTombstones();
  if (stored === null) return;
  for (const s of stored) deletedIds.add(s);
  const next = [...new Set([...stored.filter((s) => s !== id), id])].slice(-TOMBSTONE_LIMIT);
  try { window.localStorage.setItem(TOMBSTONE_KEY, JSON.stringify(next)); } catch { /* the Set still holds it */ }
}

/** CHART-RULES-SYNC-CONCURRENCY C5 (G5) -- the longest a sync run waits on one
 *  fetch (the GET, or one re-POST). */
export const SYNC_FETCH_TIMEOUT_MS = 15_000;

const TIMED_OUT = Symbol('timed out');

/** Races `p` against a timer; the timer is always cleared. `p` is NOT
 *  aborted: a re-POST the server may still commit must keep running so its
 *  late answer can be acted on (C4/C5). */
async function raceDeadline<T>(p: Promise<T>, ms: number): Promise<T | typeof TIMED_OUT> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      p,
      new Promise<typeof TIMED_OUT>((resolve) => { timer = setTimeout(() => resolve(TIMED_OUT), ms); }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

/** Runs `work` with an abort signal, rejecting after `ms` (and aborting) even
 *  if the fetch ignores the signal. For the sync GET only (C5). */
async function withDeadline<T>(ms: number, work: (signal: AbortSignal) => Promise<T>): Promise<T> {
  const ctl = new AbortController();
  const out = await raceDeadline(work(ctl.signal), ms);
  if (out === TIMED_OUT) {
    ctl.abort();
    throw new Error('sync fetch timed out');
  }
  return out;
}

/** CHART-RULES-SYNC-CONCURRENCY C1 (G4) -- `syncRules` runs are serial. A call
 *  while a run is in flight waits for it, then runs once more (a second mount
 *  still gets a fresh GET); every call made during one run shares that single
 *  follow-up. `run` never rejects, and `running` is cleared in `finally`, so a
 *  throwing run cannot wedge the queue. */
let running: Promise<void> | null = null;
let queued: Promise<void> | null = null;
function requestSync(run: () => Promise<void>): Promise<void> {
  if (!running) {
    running = run().finally(() => { running = null; });
    return running;
  }
  if (!queued) {
    const next = () => { queued = null; return requestSync(run); };
    queued = running.then(next, next);
  }
  return queued;
}

/** Test-only: clears the in-memory module state (both generation maps, the
 *  tombstone Set, the sync queue). Never touches localStorage, so a test can
 *  simulate a reload; test files clear `'bamendjou:alert-tombstones'`
 *  themselves. */
export function __resetChartAlertSyncGenForTests(): void {
  syncGen.clear();
  okGen.clear();
  deletedIds.clear();
  running = null;
  queued = null;
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
            // C4 (G3): deleted while this POST was in flight -- an accepted
            // (or unconfirmed) POST may have created it on the server.
            if (outcome.kind !== 'refused' && isTombstoned(rule.id)) void deleteRuleFromAPI(rule.id);
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
        // C3: tombstone first, then the DELETE, then the local removal -- a
        // storage error in either write cannot skip the DELETE or the
        // in-memory tombstone.
        addTombstone(id);
        void deleteRuleFromAPI(id);
        set((s) => ({
          rules: s.rules.filter((r) => r.id !== id),
          history: s.history.filter((h) => h.rule_id !== id),
        }));
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

      /** CHART-RULES-SYNC-CONCURRENCY (piece B) -- a sync run GETs the
       *  server's rules, re-POSTs each local-only rule, then writes the merge.
       *  While it awaits, the user may add, delete or edit rules, and another
       *  mount may sync. The run therefore:
       *  - G4: runs serially (`requestSync`, C1), so every final write is the
       *    newest verdict;
       *  - G1/G6: writes functionally against the state at that moment (C2):
       *    a rule added mid-run is kept, a local-only rule keeps its edits;
       *  - G2: drops every tombstoned id (C3), re-read right before the write;
       *  - G3: skips re-POSTing a tombstoned rule, and re-DELETEs one the
       *    server lists or a POST may have created (C4);
       *  - G5: never waits more than SYNC_FETCH_TIMEOUT_MS on one fetch (C5). */
      syncRules: () => requestSync(async () => {
        const okAtStart = new Map(okGen);
        try {
          const serverRules = await withDeadline(SYNC_FETCH_TIMEOUT_MS, async (signal) => {
            const res = await fetch(`${BASE_URL}/alerts/rules`, { signal });
            if (!res.ok) return null;
            return (await res.json()) as AlertRule[];
          });
          if (!serverRules) return;
          const snapshot = get().rules;
          const snapshotIds = new Set(snapshot.map((r) => r.id));
          const serverIds = new Set(serverRules.map((r) => r.id));
          const localOnly = snapshot.filter((r) => !serverIds.has(r.id));

          // C4: the server lists a rule deleted here -- delete it again
          // (fire and forget). One storage read for the whole list.
          refreshTombstones();
          for (const id of serverIds) if (deletedIds.has(id)) void deleteRuleFromAPI(id);

          // A2 (Q1): a refused re-POST keeps the rule locally and says why;
          // an accepted one (201/409) clears any old mark; an offline one
          // keeps an existing mark verbatim (a refusal reason says more),
          // else marks OFFLINE_SAVE_REASON.
          const unsaved: Record<string, string> = {};
          for (const rule of localOnly) {
            if (isTombstoned(rule.id)) continue; // C4: deleted meanwhile -- never POST it
            const post = pushRuleToAPI(rule);
            const outcome = await raceDeadline(post, SYNC_FETCH_TIMEOUT_MS);
            if (outcome === TIMED_OUT) {
              // C5: treated as offline; the POST keeps running (not aborted)
              // and its late answer is acted on.
              unsaved[rule.id] = get().unsavedRules[rule.id] ?? OFFLINE_SAVE_REASON;
              void post.then((late) => {
                if (late.kind !== 'refused' && isTombstoned(rule.id)) void deleteRuleFromAPI(rule.id);
                if (late.kind !== 'ok') return;
                bump(okGen, rule.id);
                set((s) => {
                  if (!(rule.id in s.unsavedRules)) return s;
                  const { [rule.id]: _cleared, ...rest } = s.unsavedRules;
                  return { unsavedRules: rest };
                });
              });
              continue;
            }
            if (outcome.kind !== 'refused' && isTombstoned(rule.id)) void deleteRuleFromAPI(rule.id);
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

          // C2: computed against the state at the moment of writing.
          refreshTombstones();
          set((s) => {
            const currentById = new Map(s.rules.map((r) => [r.id, r]));
            const dropped = (id: string) =>
              deletedIds.has(id) || (snapshotIds.has(id) && !currentById.has(id));
            const rules: AlertRule[] = [];
            const seen = new Set<string>();
            const unsavedRules: Record<string, string> = {};
            // (1) the server's rules
            for (const r of serverRules) {
              if (seen.has(r.id) || dropped(r.id)) continue;
              seen.add(r.id);
              rules.push(r);
            }
            // (2) snapshot local-only rules, as their current object (G6)
            for (const r of localOnly) {
              const cur = currentById.get(r.id);
              if (!cur || seen.has(r.id) || dropped(r.id)) continue;
              seen.add(r.id);
              rules.push(cur);
              if (r.id in unsaved) unsavedRules[r.id] = unsaved[r.id]!;
            }
            // (3) rules added mid-run (G1), keeping their own addRule mark
            for (const r of s.rules) {
              if (seen.has(r.id) || snapshotIds.has(r.id) || serverIds.has(r.id) || dropped(r.id)) continue;
              seen.add(r.id);
              rules.push(r);
              if (r.id in s.unsavedRules) unsavedRules[r.id] = s.unsavedRules[r.id]!;
            }
            return { rules, migrated: true, unsavedRules };
          });
          for (const id of serverIds) bump(syncGen, id);
          for (const rule of localOnly) bump(syncGen, rule.id);
        } catch {}
      }),

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
