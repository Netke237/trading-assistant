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
fetches carry an abort signal (C5), a DELETE may be re-sent (C4), and a
re-POST of a rule deleted meanwhile is skipped (C4).

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

**C3. Deletions are tombstoned (G2).** A module-level
`deletedIds = new Set<string>()`. `deleteRule(id)` adds `id` before sending
its DELETE. Rule ids come from `makeId()` (`AlertRuleBuilder`) and are never
reused, so a tombstone never hides a later rule; it lives for the tab's life
(not persisted). In the final write, `dropped(id)` = `deletedIds.has(id)`, or
`id` is in `snapshot` but not in `current` (defensive: `deleteRule` is the
only path that removes a rule). No DELETE answer (2xx, 404, 5xx, network
error, in any order, for any number of DELETEs of that id) changes the
tombstone, so a 404 that raced an in-flight POST (r1 F1) or a failing older
DELETE (r1 F3) can never bring the rule back. A server rule not in `snapshot`,
not in `current` and not tombstoned (created elsewhere) is kept, as today.

**C4. A deleted rule is deleted again (G3).** A tombstoned id can still be
created on the server by a POST that was in flight (or that the server
committed after C5 aborted it). The store re-sends the DELETE (fire and
forget, never awaited, so it cannot hold a run) whenever it has reason to
think the server might hold a tombstoned id:
- `addRule`'s POST settles `ok` or `offline` and `rule.id` is tombstoned
  (an `offline` POST may still have committed; DELETE is idempotent, a 404
  is harmless). `refused` sends nothing.
- `runSync`: each GET that lists a tombstoned id sends a DELETE for it (the
  id is dropped by C3 either way). So while the tab lives, every later sync
  retries until the server stops listing it.
- `runSync`: before each re-POST, a snapshot rule that is tombstoned by then
  is **skipped** (no POST is sent, r1 F2); a re-POST that settles `ok` or
  `offline` for an id tombstoned meanwhile sends a DELETE.
If every re-DELETE fails, the rule stays on the server — the same state as an
offline `deleteRule` today (not in scope); after a reload the tombstone is
gone and a GET listing it restores it, unmarked (truthful: the server holds it).

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
- **Tombstones are per tab.** Another tab deleting a rule is seen through its
  absence from a later GET, as today.

## Tests (`frontend/lib/__tests__/p4aChartAlertStore.test.ts`, new describe)

- T1 (G1). `addRule(n1)` while a sync awaits a re-POST of r1: after the sync,
  n1 is in `rules`; with n1's POST offline → marked `OFFLINE_SAVE_REASON`;
  with n1's POST offline *after* the sync → marked; with 201 → unmarked.
- T2 (G2). Deleted while the sync awaits, for (i) a local-only snapshot rule,
  (ii) a server snapshot rule, (iii) a rule the GET listed that was deleted
  after it entered `rules`: none is in `rules`, none has a mark.
- T3 (G2, r1 F1/F3). `deleteRule(r1)`; its DELETE answers 404, fails, or
  never settles (and, separately, two DELETEs for r1 settle 2xx then network
  error); a later sync whose GET still lists r1: r1 not restored, no mark,
  and a DELETE for r1 is sent by that sync.
- T4 (G3). A local-only rule deleted while its `addRule` POST, or its sync
  re-POST, is pending; the POST then gets 201, 409 or offline → a DELETE for
  that id is sent after it; with `refused` → no extra DELETE.
- T4b (r1 F2). A snapshot rule deleted before the sync reaches its turn: no
  POST for it is sent.
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

- **Plan r1** (2026-09-28): 3 gate-level findings, all in the original C3/C4
  (a clock + pending-DELETE map), all fixed by replacing them with tombstones:
  F1 a 404 that raced an in-flight POST counted as "deleted on the server", so
  a GET listing the rule restored it and C4 saw it in `rules` and sent no
  DELETE; F2 a C5-aborted re-POST that the server still committed was
  `offline`, so C4 sent no DELETE and a later GET restored the rule; F3 a
  failing older DELETE removed the entry a later successful DELETE had set.
  C1, C2, okGen/syncGen traced clean.
