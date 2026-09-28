# CHART-RULES-SYNC-CONCURRENCY (piece B) — plan

- Phase: `CHART-RULES-SYNC-CONCURRENCY` (PROJECT_STATE.json), piece B of the split
  `CHART-RULE-OFFLINE-SAVE-MARK-SPLIT-2026-09-28`
- Depends on: `CHART-RULE-OFFLINE-SAVE-MARK` (piece A, merged 7d7159b)
- Branch: `claude/sleepy-gates-4084r7`, off main `e5b96d1`
- Source: `docs/superpowers/plans/2026-09-28-chart-rule-offline-save-mark-plan.md`
  (the capped r1–r3 plan: C2 generation counter, C3 functional final set,
  C3-deleted, C3-serial, C3-bound; tests T5, T5b, T7, T8, T9) and its audit
  record. This plan is fresh; its rounds restart at 0.

## The gaps (all in `frontend/lib/chartAlertStore.ts`, all pre-existing)

`syncRules` GETs the server's rules, re-POSTs each local-only rule one at a
time, then writes `set({ rules: merged, unsavedRules: unsaved })` built from a
snapshot taken after the GET. While it awaits:

- **G1 — add dropped.** A rule the user adds (`addRule`) is not in the
  snapshot, so the final write drops it from `rules`, and so from localStorage.
  If its POST failed, the rule is lost silently; if it succeeded, it comes back
  on the next sync.
- **G2 — delete undone.** A rule the user deletes (`deleteRule`) is in the
  snapshot (or in the GET, whose answer may predate the DELETE), so the final
  write brings it back, unmarked, though the server no longer holds it (or is
  about to drop it). The same holds for a GET that is merely *answered* before
  a DELETE issued just before the sync lands.
- **G3 — deleted, then created.** A local-only rule deleted while the sync (or
  its own `addRule`) is POSTing it: the DELETE can reach the server first
  (404), then the POST creates the rule. The server now holds, judges and
  notifies on a rule the user deleted; nothing locally shows it.
- **G4 — overlapping runs.** Two `syncRules` runs at once (Alerts page and a
  chart both mount) interleave; the older run's final write, carrying an older
  verdict, can overwrite a newer run's (e.g. re-mark a rule the newer run
  proved saved).
- **G5 — unbounded.** A GET or re-POST that never settles holds the run
  forever. Harmless today; fatal once runs are serial (G4's fix), since every
  later sync would queue behind it for the life of the tab.
- **G6 — edit reverted.** A local-only rule edited (`updateRule`,
  `setRuleEnabled`, `stampRuleTriggered`) while the sync awaits is reverted to
  the snapshot copy by the final write, and persisted so.

## Severity gate (PROJECT_STATE.json `audit_rule`, clause 1, verbatim)

> (1) THE GATE IS THE ONLY THING THAT COUNTS, AND THE REVIEWER IS TOLD SO. A
> finding blocks only if it can put a WRONG NUMBER in front of a user or on a
> broker order, or CORRUPT PERSISTED DATA. Everything else -- wording,
> comments, test hygiene, dead code, stale records, latent defects with no
> reachable path -- is not a finding for this purpose, and the audit brief
> must instruct the reviewer NOT TO REPORT IT AT ALL.

For this phase, gate-level means, after any interleaving of `addRule`,
`deleteRule`, `updateRule`/`setRuleEnabled`/`stampRuleTriggered` and one or
more `syncRules` calls, and any settle order of their fetches:
- `rules` (persisted) loses a rule the user did not delete, keeps or restores a
  rule the user deleted, or reverts a local-only rule's local edit; or
- a rule the server does not hold carries no `unsavedRules` mark, or a rule
  the server was proved to hold keeps one; or
- a rule the user deleted is left created on the server by this code (G3); or
- a `syncRules` call can wait forever.

**Not a finding (unchanged, logged elsewhere):** L3-a (an offline PUT leaves
the server's older version), L3-b (after a reload with the server wholly down
no mark shows), a server rule's local edit being replaced by the server's copy
in a sync (its PUT/PATCH still lands; the next sync shows it), an offline
DELETE leaving the rule on the server (see C4), anything in `history`.

Caps: plan stage ≤ 3 rounds, code stage ≤ 3 rounds (AUDIT-CAP-PER-STAGE-2026-09-25).

## Scope

Frontend only: `frontend/lib/chartAlertStore.ts` and
`frontend/lib/__tests__/p4aChartAlertStore.test.ts` (plus a new test file if
cleaner). No backend, page or persisted-shape change (`partialize` and
`version` untouched). What is sent over the wire is unchanged except: syncRules
fetches carry an abort signal (C5) and a DELETE may be re-sent (C4).

## Changes

All new module-level state sits beside `syncGen`/`okGen` (never persisted or
rendered); `__resetChartAlertSyncGenForTests` also resets it.

**C1. Serial runs (G4).** `syncRules` becomes a thin wrapper over
`runSync()` (today's body, changed as below):

```ts
let running: Promise<void> | null = null;
let queued: Promise<void> | null = null;
function requestSync(): Promise<void> {
  if (!running) {
    running = runSync().finally(() => { running = null; });
    return running;
  }
  if (!queued) {
    queued = running.then(() => { queued = null; return requestSync(); });
  }
  return queued;
}
```

A call while a run is in flight waits for it, then runs once more (a mount
that comes second still gets a fresh GET); every call made during one run
shares that single follow-up. `runSync` never rejects (its body is inside
`try/catch`), and `running` is cleared in `finally`, so a throwing run (e.g. a
localStorage quota error in the final `set`) cannot wedge the queue. With runs
serial, every final write is the newest verdict, and `syncGen` only has to
order `addRule` against a sync.

**C2. Functional final write (G1, G6).** The final write becomes
`set((s) => …)`, computed against the state at that moment. With `snapshot` =
the rules read after the GET, `serverIds` = the GET's ids, `current` =
`s.rules`, `currentById` = `current` by id, and `dropped(id)` = C3:

- **rules**, in this order:
  1. each server rule, unless `dropped(id)`;
  2. each snapshot `localOnly` rule still in `current`, **as its current
     object** (`currentById.get(id)`, G6), unless `dropped(id)`;
  3. each rule in `current` whose id is in neither `snapshot` nor `serverIds`
     (added mid-sync), in `current` order.
- **unsavedRules** = this run's verdicts for the ids in (2) (after the existing
  okGen filter), plus, for each rule in (3), `s.unsavedRules[id]` if present
  (its own `addRule` answer may already have marked it). Server ids carry no
  mark.
- `syncGen` is bumped, right after the write, for the ids in (1) and (2) only
  — the ids this run ruled on. A rule in (3) was not ruled on, so its
  `addRule` answer still marks it (the `syncGen` guard of piece A lets it
  through).

**C3. Deletions are recorded (G2).** A module-level
`pendingDeletes = new Map<string, number | null>()` and a monotonically
increasing `clock` counter:

- `deleteRule(id)` (and C4's re-DELETE) sets `pendingDeletes[id] = null`
  (in flight) before sending the DELETE.
- When that DELETE settles with 2xx or 404, `pendingDeletes[id] = ++clock`
  (confirmed at). With a network error, timeout or other status, the entry is
  removed: the server still holds the rule, so a later GET listing it restores
  it — truthfully, and it is not marked (it is saved).
- Each run records `getAt = ++clock` just before sending its GET.
- `dropped(id)` at the final write = `id` is in `snapshot` but not in
  `current` (deleted mid-sync), **or** `pendingDeletes` has `id` with value
  `null` or `> getAt` (a DELETE not confirmed before the GET was sent, so the
  GET may still list it).
- A server rule not in `snapshot`, not in `current` and not in
  `pendingDeletes` (created elsewhere) is kept, as today.

`pendingDeletes` entries are never read once `confirmed < getAt` for every
later run; they stay (one small entry per deleted id per tab session).

**C4. Deleted, then created (G3).** When a POST is accepted (201/409) for a
rule no longer in `rules`, the store sends the DELETE again through the same
tracked path as `deleteRule` (so C3 sees it as in flight):
- in `addRule`'s `ok` branch, if `rule.id` is not in `get().rules`;
- in `runSync` after each re-POST whose outcome is `ok`, if the id is not in
  `get().rules`.
A 409 counts: the server holds the rule either way. An offline/refused POST
sends nothing. If the re-DELETE itself fails, the rule stays on the server and
a later GET restores it locally (C3), unmarked — the same truthful state as an
offline `deleteRule` today (not in scope).

**C5. Bounded fetches (G5).** `runSync`'s GET (including `res.json()`) and
each re-POST (including reading a refusal body) run under a 15 s deadline:
`withDeadline(ms, (signal) => …)` passes an `AbortController` signal to
`fetch`, and races the work against a timer that aborts and rejects, so the
bound holds even if a `fetch` ignores the signal; the timer is cleared in
`finally`. A timed-out GET returns early (as a failed GET does today); a
timed-out re-POST is `offline` (marked `OFFLINE_SAVE_REASON`, or its prior
mark kept). `pushRuleToAPI` takes an optional `signal`; `addRule`'s POST is not
bounded (it never blocks a sync). `SYNC_FETCH_TIMEOUT_MS = 15_000` is exported
for tests.

**C6. Doc comments** on `syncRules` / module state naming G1–G6 and this phase.

## Checked, not changed

- **A rule added mid-sync whose id is in `serverIds`** (only if the server
  already held that id): kept once, as the server's copy, unmarked; its late
  `addRule` offline answer is dropped because the run bumped its `syncGen`.
- **`okGen` filter** keeps working for the ids in (2); ids in (3) keep their
  own `addRule` mark lifecycle.
- **`addRule`'s own `refused`/`offline` mark on a rule deleted meanwhile** —
  already dropped by piece A's check (i).
- **A DELETE issued before the run's GET and confirmed before it**: not
  pending at `getAt`, the GET cannot list it, nothing to drop.

## Tests (`frontend/lib/__tests__/p4aChartAlertStore.test.ts`, new describe)

- T1 (G1). `addRule(n1)` while a sync awaits a re-POST of r1: after the sync,
  n1 is in `rules`; with n1's POST offline → marked `OFFLINE_SAVE_REASON`;
  with n1's POST offline *after* the sync → marked; with 201 → unmarked.
- T2 (G2). Deleted while the sync awaits, for (i) a local-only snapshot rule,
  (ii) a server snapshot rule, (iii) a rule the GET listed that was deleted
  after it entered `rules`: none is in `rules`, none has a mark.
- T3 (G2). `deleteRule(r1)` with the DELETE pending, then a sync whose GET
  still lists r1: r1 not restored; once the DELETE is confirmed, a later sync
  whose GET does not list r1 keeps it gone; if the DELETE fails, a later sync
  whose GET lists r1 restores it unmarked.
- T4 (G3). A local-only rule deleted while its sync re-POST (and, separately,
  its `addRule` POST) is pending; the POST then gets 201 → a second DELETE for
  that id is sent. With `refused`/`offline` → no second DELETE.
- T5 (G4). Two `syncRules` calls back to back: the second GET is not sent
  until the first run's final write; a third call during the first run shares
  the follow-up (exactly two GETs); all three promises resolve.
- T6 (G4). First run's re-POST of n1 offline while a second call is queued;
  the queued run's re-POST gets 201 → n1 ends unmarked.
- T7 (G5). With fake timers: the first run's GET never resolves → after
  `SYNC_FETCH_TIMEOUT_MS` the call resolves and the queued call sends its own
  GET; a re-POST that never resolves → after the timeout the rule is marked
  `OFFLINE_SAVE_REASON`; a run whose final `set` throws does not block the
  next call.
- T8 (G6). `updateRule`/`setRuleEnabled` on a local-only rule while the sync
  awaits its re-POST: the edit survives the final write.
- Existing piece A tests (T1–T6, T5c/d/e) keep passing unchanged.

## Verification

`cd frontend && npx tsc --noEmit && npx jest --silent` clean. Backend untouched.
`python3 scripts/state.py` exit 0 after the phase probe is re-pointed to
`present` on `CHART-RULES-SYNC-CONCURRENCY` in `chartAlertStore.ts` (C6's doc
comment names the phase next to `requestSync`).

## Audit record

(none yet)
